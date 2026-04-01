from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from app.core.config import get_settings
from app.services.local_asset_service import (
    load_nav_to_nav_costs,
    load_planner_problem,
    nav_point_index,
    resolve_scene_name,
)
from app.services.result_service import write_json


ROBOT_COLOR_PALETTE = [
    "#d94841",
    "#2674f2",
    "#1a936f",
    "#d97706",
    "#7c3aed",
    "#0f766e",
    "#c026d3",
    "#2563eb",
    "#be123c",
    "#4f46e5",
    "#0ea5e9",
    "#65a30d",
]


def _settings():
    return get_settings()


def _config_dir() -> Path:
    return _settings().base_dir / "data" / "configs" / "robot_initialization"


def _config_path(scene_name: str) -> Path:
    return _config_dir() / f"{scene_name}.json"


def _relative_config_path(scene_name: str) -> str:
    return (Path("data") / "configs" / "robot_initialization" / f"{scene_name}.json").as_posix()


def _slot_id(index: int) -> str:
    return f"slot_{index:02d}"


def _hardware_id(index: int) -> str:
    return f"cyberdog2_{index:02d}"


def _display_name(index: int) -> str:
    return f"机器狗 {index}"


def _color_for_index(index: int) -> str:
    if index <= len(ROBOT_COLOR_PALETTE):
        return ROBOT_COLOR_PALETTE[index - 1]
    hue = (index * 137.508) % 360
    saturation = 66
    lightness = 46
    return _hsl_to_hex(hue, saturation, lightness)


def _hsl_to_hex(hue: float, saturation: float, lightness: float) -> str:
    h = hue / 360.0
    s = saturation / 100.0
    l = lightness / 100.0
    if s == 0:
        value = int(round(l * 255))
        return f"#{value:02x}{value:02x}{value:02x}"

    def hue_to_rgb(p: float, q: float, t: float) -> float:
        if t < 0:
            t += 1
        if t > 1:
            t -= 1
        if t < 1 / 6:
            return p + (q - p) * 6 * t
        if t < 1 / 2:
            return q
        if t < 2 / 3:
            return p + (q - p) * (2 / 3 - t) * 6
        return p

    q = l * (1 + s) if l < 0.5 else l + s - l * s
    p = 2 * l - q
    r = hue_to_rgb(p, q, h + 1 / 3)
    g = hue_to_rgb(p, q, h)
    b = hue_to_rgb(p, q, h - 1 / 3)
    return f"#{int(round(r * 255)):02x}{int(round(g * 255)):02x}{int(round(b * 255)):02x}"


def _template_robot_for_index(template_robots: List[Dict], index: int) -> Dict:
    if not template_robots:
        raise ValueError("planner problem contains no robot templates")
    return copy.deepcopy(template_robots[(index - 1) % len(template_robots)])


def _build_runtime_pose(anchor_nav_point: Dict) -> Dict:
    resolved = {
        "x": float(anchor_nav_point["local_x"]),
        "z": float(anchor_nav_point["local_z"]),
    }
    return {
        "anchor_nav_point_id": anchor_nav_point["id"],
        "anchor_name": anchor_nav_point["name"],
        "anchor_local_m": copy.deepcopy(resolved),
        "offset_from_anchor_local_m": {"x": 0.0, "z": 0.0},
        "resolved_local_position_m": copy.deepcopy(resolved),
        "heading_rad": float(anchor_nav_point.get("yaw", 0.0)),
        "note": "Runtime-selected robot anchor aligned directly to an existing nav point.",
    }


def _validate_robot_count(robot_count: int) -> int:
    count = int(robot_count)
    if count < 1:
        raise ValueError("robot_count must be at least 1")
    if count > 32:
        raise ValueError("robot_count must not exceed 32")
    return count


def _build_robot_entry(index: int, anchor_nav_point_id: Optional[str], scene_name: str) -> Dict:
    nav_index = nav_point_index(scene_name)
    anchor = nav_index.get(anchor_nav_point_id) if anchor_nav_point_id else None
    pose = _build_runtime_pose(anchor) if anchor is not None else None
    return {
        "index": index,
        "planning_slot_id": _slot_id(index),
        "hardware_id": _hardware_id(index),
        "display_name": _display_name(index),
        "color": _color_for_index(index),
        "placed": anchor is not None,
        "anchor_nav_point_id": anchor["id"] if anchor is not None else None,
        "anchor_nav_point_name": anchor["name"] if anchor is not None else "",
        "start_nav_point_id": anchor["id"] if anchor is not None else None,
        "home_nav_point_id": anchor["id"] if anchor is not None else None,
        "start_pose": copy.deepcopy(pose),
        "home_pose": copy.deepcopy(pose),
    }


def _normalize_robot_entries(scene_name: str, robot_count: int, raw_robots: Optional[List[Dict]] = None) -> List[Dict]:
    count = _validate_robot_count(robot_count)
    nav_index = nav_point_index(scene_name)
    raw_robots = raw_robots or []
    robots: List[Dict] = []
    for index in range(1, count + 1):
        raw = raw_robots[index - 1] if index - 1 < len(raw_robots) else {}
        anchor_nav_point_id = raw.get("anchor_nav_point_id")
        if anchor_nav_point_id is not None:
            anchor_nav_point_id = str(anchor_nav_point_id).strip() or None
        if anchor_nav_point_id is not None and anchor_nav_point_id not in nav_index:
            raise ValueError(f"unknown robot anchor nav point: {anchor_nav_point_id}")
        robots.append(_build_robot_entry(index, anchor_nav_point_id, scene_name))
    return robots


def _build_config_payload(
    scene_name: str,
    robots: List[Dict],
    *,
    updated_at: Optional[str],
    source: str,
) -> Dict:
    placed_robot_ids = [robot["planning_slot_id"] for robot in robots if robot["placed"]]
    unplaced_robot_ids = [robot["planning_slot_id"] for robot in robots if not robot["placed"]]
    return {
        "schema_version": "1.0.0",
        "scene_name": scene_name,
        "robot_count": len(robots),
        "all_robots_placed": not unplaced_robot_ids,
        "placed_robot_ids": placed_robot_ids,
        "unplaced_robot_ids": unplaced_robot_ids,
        "config_path": _relative_config_path(scene_name),
        "source": source,
        "updated_at": updated_at,
        "robots": robots,
    }


def _persist_config(scene_name: str, robots: List[Dict], source: str = "file") -> Dict:
    updated_at = datetime.now(timezone.utc).isoformat()
    payload = _build_config_payload(scene_name, robots, updated_at=updated_at, source=source)
    file_payload = {
        "schema_version": payload["schema_version"],
        "scene_name": payload["scene_name"],
        "robot_count": payload["robot_count"],
        "updated_at": payload["updated_at"],
        "robots": [
            {
                "index": robot["index"],
                "planning_slot_id": robot["planning_slot_id"],
                "hardware_id": robot["hardware_id"],
                "display_name": robot["display_name"],
                "color": robot["color"],
                "anchor_nav_point_id": robot["anchor_nav_point_id"],
            }
            for robot in robots
        ],
    }
    write_json(_config_path(scene_name), file_payload)
    return payload


def _default_config(scene_name: str) -> Dict:
    planner_problem = load_planner_problem(scene_name)
    robots = []
    for index, template_robot in enumerate(planner_problem["robots"], start=1):
        robots.append(_build_robot_entry(index, template_robot.get("start_nav_point_id"), scene_name))
    return _persist_config(scene_name, robots, source="generated_default")


def get_runtime_robot_config(scene_name: str | None = None) -> Dict:
    scene = resolve_scene_name(scene_name)
    path = _config_path(scene)
    if not path.exists():
        return _default_config(scene)
    payload = json.loads(path.read_text(encoding="utf-8"))
    robot_count = payload.get("robot_count", len(payload.get("robots", [])))
    normalized = _normalize_robot_entries(scene, robot_count, payload.get("robots", []))
    return _build_config_payload(
        scene,
        normalized,
        updated_at=payload.get("updated_at"),
        source="file",
    )


def save_runtime_robot_config(
    scene_name: str | None,
    robot_count: int,
    robots: Optional[List[Dict]] = None,
) -> Dict:
    scene = resolve_scene_name(scene_name)
    normalized = _normalize_robot_entries(scene, robot_count, robots)
    return _persist_config(scene, normalized, source="file")


def build_runtime_robot_assets(scene_name: str | None = None) -> List[Dict]:
    scene = resolve_scene_name(scene_name)
    config = get_runtime_robot_config(scene)
    planner_problem = load_planner_problem(scene)
    template_robots = planner_problem["robots"]
    assets: List[Dict] = []
    for robot_config in config["robots"]:
        template_robot = _template_robot_for_index(template_robots, robot_config["index"])
        template_robot["index"] = robot_config["index"]
        template_robot["planning_slot_id"] = robot_config["planning_slot_id"]
        template_robot["hardware_id"] = robot_config["hardware_id"]
        template_robot["display_name"] = robot_config["display_name"]
        template_robot["color"] = robot_config["color"]
        template_robot["start_nav_point_id"] = robot_config["start_nav_point_id"]
        template_robot["home_nav_point_id"] = robot_config["home_nav_point_id"]
        template_robot["start_pose"] = copy.deepcopy(robot_config["start_pose"])
        template_robot["home_pose"] = copy.deepcopy(robot_config["home_pose"])
        template_robot["placed"] = robot_config["placed"]
        template_robot["anchor_nav_point_id"] = robot_config["anchor_nav_point_id"]
        template_robot["anchor_nav_point_name"] = robot_config["anchor_nav_point_name"]
        template_robot["ros_namespace"] = f"../../../{robot_config['hardware_id']}"
        template_robot["gazebo_entity_name"] = robot_config["hardware_id"]
        assets.append(template_robot)
    return assets


def build_runtime_planner_problem(scene_name: str | None = None, *, require_all_placed: bool = False) -> Dict:
    scene = resolve_scene_name(scene_name)
    config = get_runtime_robot_config(scene)
    if require_all_placed and not config["all_robots_placed"]:
        raise ValueError(
            f"robot initialization incomplete for scene {scene}: place {', '.join(config['unplaced_robot_ids'])} first"
        )

    base_problem = copy.deepcopy(load_planner_problem(scene))
    base_problem["problem_id"] = f"{scene}_runtime_multi_dog_planner_problem"
    base_problem["fleet"]["robot_count"] = config["robot_count"]
    base_problem["fleet"]["planning_note"] = "Runtime robot initialization config determines active robot slots and anchors."
    base_problem["robots"] = build_runtime_robot_assets(scene)
    base_problem["refs"]["runtime_robot_config"] = _relative_config_path(scene)
    return base_problem


def build_runtime_robot_to_nav_costs(scene_name: str | None = None, *, require_all_placed: bool = False) -> Dict:
    scene = resolve_scene_name(scene_name)
    planner_problem = build_runtime_planner_problem(scene, require_all_placed=require_all_placed)
    nav_to_nav_costs = load_nav_to_nav_costs(scene)
    nav_pair_costs = nav_to_nav_costs["pairs"]
    nav_anchor_nodes = nav_to_nav_costs["nav_anchor_nodes"]
    payload = {
        "schema_version": "1.0.0",
        "metadata": {
            "route_graph_ref": nav_to_nav_costs["metadata"].get("route_graph_ref", ""),
            "nav_points_ref": nav_to_nav_costs["metadata"].get("nav_points_ref", ""),
            "nav_bindings_ref": nav_to_nav_costs["metadata"].get("nav_bindings_ref", ""),
            "access_model": "runtime_anchor_nav_point_plus_precomputed_nav_pairs",
            "runtime_robot_config": _relative_config_path(scene),
        },
        "start_to_nav_costs": {},
        "nav_to_home_costs": {},
    }

    for robot in planner_problem["robots"]:
        anchor_nav_point_id = robot.get("start_nav_point_id")
        if not anchor_nav_point_id:
            continue
        anchor_node = nav_anchor_nodes[anchor_nav_point_id]
        robot_meta = {
            "planning_slot_id": robot["planning_slot_id"],
            "hardware_id": robot["hardware_id"],
            "anchor_nav_point_id": anchor_nav_point_id,
            "anchor_nav_point_name": anchor_node["nav_point_name"],
            "graph_node_id": anchor_node["graph_node_id"],
            "resolved_local_position_m": copy.deepcopy(robot["start_pose"]["resolved_local_position_m"]),
            "heading_rad": float(robot["start_pose"].get("heading_rad", 0.0)),
            "access_distance_m": float(anchor_node.get("access_distance_m", 0.0)),
            "cruise_speed_mps": float(robot["planner_limits"]["max_cruise_speed_mps"]),
            "yaw_rate_rad_per_s": float(robot["planner_limits"]["max_yaw_rate_rad_per_s"]),
        }
        forward_costs = copy.deepcopy(nav_pair_costs[anchor_nav_point_id])
        payload["start_to_nav_costs"][robot["planning_slot_id"]] = {
            "robot": copy.deepcopy(robot_meta),
            "costs": forward_costs,
        }
        payload["nav_to_home_costs"][robot["planning_slot_id"]] = {
            "robot": copy.deepcopy(robot_meta),
            "costs": copy.deepcopy(nav_pair_costs[anchor_nav_point_id]),
        }
    return payload
