import json
import logging
import uuid
from pathlib import Path
from typing import Dict, List

import requests

from app.core.config import get_settings
from app.planners.allocator import greedy_allocate
from app.planners.formation_planner import build_formation_plan
from app.planners.graph_planner import load_route_graph, shortest_path
from app.services.package_service import (
    download_package,
    load_json,
    unzip_package,
    validate_package,
    verify_sha256,
)
from app.services.result_service import pack_result_dir, write_json


logger = logging.getLogger(__name__)
settings = get_settings()


def _job_path(job_id: str) -> Path:
    return settings.job_dir / job_id


def _result_path(job_id: str) -> Path:
    return settings.result_dir / job_id


def _status_file(job_id: str) -> Path:
    return _job_path(job_id) / "status.json"


def _read_status(job_id: str) -> Dict:
    return json.loads(_status_file(job_id).read_text(encoding="utf-8"))


def create_job_record(payload: Dict) -> str:
    settings.job_dir.mkdir(parents=True, exist_ok=True)
    settings.result_dir.mkdir(parents=True, exist_ok=True)

    job_id = f"planner_job_{uuid.uuid4().hex[:8]}"
    job_dir = _job_path(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        _status_file(job_id),
        {
            "planner_job_id": job_id,
            "mission_id": payload["mission_id"],
            "status": "accepted",
            "progress": 0,
            "message": "job accepted",
            "result_url": None,
        },
    )
    return job_id


def get_job_status(job_id: str) -> Dict:
    return _read_status(job_id)


def update_job_status(job_id: str, **kwargs) -> None:
    status = _read_status(job_id)
    status.update(kwargs)
    write_json(_status_file(job_id), status)


def _find_goal(goals: List[Dict], goal_id: str) -> Dict:
    for goal in goals:
        if goal["goal_id"] == goal_id:
            return goal
    raise KeyError(f"goal not found: {goal_id}")


def _find_robot(robots: List[Dict], robot_id: str) -> Dict:
    for robot in robots:
        if robot["robot_id"] == robot_id:
            return robot
    raise KeyError(f"robot not found: {robot_id}")


def _build_paths(assignments: List[Dict], graph, goals: List[Dict], robots: List[Dict]) -> List[Dict]:
    paths = []
    for assignment in assignments:
        robot = _find_robot(robots, assignment["robot_id"])
        current_position = robot["start"]
        speed = float(robot.get("max_speed_mps", 1.0)) or 1.0

        for goal_id in assignment["task_sequence"]:
            goal = _find_goal(goals, goal_id)
            planned = shortest_path(
                graph,
                (float(current_position["x"]), float(current_position["y"])),
                (float(goal["position"]["x"]), float(goal["position"]["y"])),
            )
            paths.append(
                {
                    "robot_id": robot["robot_id"],
                    "goal_id": goal_id,
                    "path_type": "ground_graph",
                    "estimated_length_m": planned["length_m"],
                    "estimated_duration_s": planned["length_m"] / speed,
                    "waypoints": planned["waypoints"],
                }
            )
            current_position = goal["position"]
    return paths


def _post_callback(callback_url: str, payload: Dict) -> None:
    if not callback_url:
        return
    response = requests.post(callback_url, json=payload, timeout=30)
    response.raise_for_status()


def run_job(job_id: str, payload: Dict) -> None:
    logger.info("start job %s for mission %s", job_id, payload["mission_id"])
    job_dir = _job_path(job_id)
    result_dir = _result_path(job_id)
    result_dir.mkdir(parents=True, exist_ok=True)
    package_zip = job_dir / "mission_package.zip"
    package_extract_dir = job_dir / "mission_package"

    try:
        update_job_status(job_id, status="running", progress=5, message="downloading package")
        download_package(str(payload["package_url"]), package_zip, payload.get("auth_token"))
        verify_sha256(package_zip, payload.get("package_sha256"))

        update_job_status(job_id, progress=20, message="unzipping package")
        package_dir = unzip_package(package_zip, package_extract_dir)
        validate_package(package_dir)

        update_job_status(job_id, progress=40, message="loading inputs")
        route_graph = load_json(package_dir / "route_graph.json")
        goals = load_json(package_dir / "goals.json").get("goals", [])
        robots = load_json(package_dir / "robots.json").get("robots", [])
        constraints = load_json(package_dir / "constraints.json")
        graph = load_route_graph(route_graph)

        update_job_status(job_id, progress=60, message="planning routes and assignments")
        allocation = greedy_allocate(robots, goals)
        paths = _build_paths(allocation["assignments"], graph, goals, robots)
        formation = build_formation_plan(robots, constraints)

        update_job_status(job_id, progress=80, message="writing result package")
        write_json(
            result_dir / "planner_manifest.json",
            {
                "planner_job_id": job_id,
                "mission_id": payload["mission_id"],
                "status": "success",
                "files": {
                    "task_assignment": "task_assignment.json",
                    "global_paths": "global_paths.json",
                    "planner_summary": "planner_summary.json",
                    "formation_plan": "formation_plan.json",
                    "ros_dispatch": "ros_dispatch.json",
                },
            },
        )
        write_json(
            result_dir / "task_assignment.json",
            {
                "mission_id": payload["mission_id"],
                "assignments": allocation["assignments"],
            },
        )
        write_json(
            result_dir / "global_paths.json",
            {
                "mission_id": payload["mission_id"],
                "paths": paths,
            },
        )
        write_json(
            result_dir / "planner_summary.json",
            {
                "status": "success",
                "message": "ok",
                "reachable_goals": len(paths),
                "unreachable_goals": max(0, len(goals) - len(paths)),
                "warnings": [],
            },
        )
        write_json(result_dir / "formation_plan.json", formation)
        write_json(
            result_dir / "ros_dispatch.json",
            {
                "dispatches": [
                    {
                        "robot_id": robot["robot_id"],
                        "namespace": f"/{robot['robot_id']}",
                        "controller_mode": "follow_path",
                        "path_file": "global_paths.json",
                        "task_file": "task_assignment.json",
                    }
                    for robot in robots
                ]
            },
        )

        result_zip = result_dir / "planner_result.zip"
        pack_result_dir(result_dir, result_zip)

        result_url = f"{settings.public_base_url}/api/planner/jobs/{job_id}/result"
        update_job_status(
            job_id,
            status="success",
            progress=100,
            message="planner finished",
            result_url=result_url,
        )

        if payload.get("callback_url"):
            _post_callback(
                str(payload["callback_url"]),
                {
                    "planner_job_id": job_id,
                    "mission_id": payload["mission_id"],
                    "status": "success",
                    "result_url": result_url,
                    "message": "planner finished",
                },
            )
    except Exception as exc:
        logger.exception("job %s failed", job_id)
        update_job_status(
            job_id,
            status="failed",
            progress=100,
            message=str(exc),
        )
        if payload.get("callback_url"):
            try:
                _post_callback(
                    str(payload["callback_url"]),
                    {
                        "planner_job_id": job_id,
                        "mission_id": payload["mission_id"],
                        "status": "failed",
                        "result_url": None,
                        "message": str(exc),
                    },
                )
            except Exception:
                logger.exception("callback for failed job %s also failed", job_id)
