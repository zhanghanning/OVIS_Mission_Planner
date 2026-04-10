from __future__ import annotations

import copy
import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Dict, Iterable, List, Sequence

from app.core.config import get_settings
from app.planners.formal_multi_robot import plan_multi_robot_routes
from app.services.local_asset_service import (
    get_console_assets,
    list_available_scenes,
    load_mission_templates,
    load_nav_to_nav_costs,
    nav_point_index,
    resolve_scene_name,
    route_node_index,
)
from app.services.result_service import write_json
from app.services.runtime_robot_service import (
    build_runtime_planner_problem,
    build_runtime_robot_assets,
    build_runtime_robot_to_nav_costs,
    get_runtime_robot_config,
)
from app.services.semantic_service import resolve_semantic_targets, validate_nav_point_ids

_PLAN_CACHE_LOCK = Lock()
_PENDING_PLAN_CACHE: Dict[str, Dict[str, Dict]] = {}


def _settings():
    return get_settings()


def _plan_root(plan_id: str) -> Path:
    return _settings().local_plan_dir / plan_id


def _output_root_relative(plan_id: str) -> Path:
    return Path("data") / "outputs" / plan_id


def _output_root(plan_id: str) -> Path:
    return _settings().base_dir / _output_root_relative(plan_id)


def _output_base_dir() -> Path:
    return _settings().base_dir / "data" / "outputs"


def _dedupe_polyline(points: Sequence[Dict]) -> List[Dict]:
    deduped: List[Dict] = []
    for point in points:
        if not deduped:
            deduped.append({"x": float(point["x"]), "z": float(point["z"])})
            continue
        previous = deduped[-1]
        if math.isclose(previous["x"], float(point["x"]), abs_tol=1e-6) and math.isclose(
            previous["z"], float(point["z"]), abs_tol=1e-6
        ):
            continue
        deduped.append({"x": float(point["x"]), "z": float(point["z"])})
    return deduped


def _point_in_polygon(point_x: float, point_y: float, polygon: Sequence[Dict]) -> bool:
    inside = False
    if len(polygon) < 3:
        return False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi = float(polygon[i]["x"])
        yi = float(polygon[i]["y"])
        xj = float(polygon[j]["x"])
        yj = float(polygon[j]["y"])
        intersects = ((yi > point_y) != (yj > point_y)) and (
            point_x < (xj - xi) * (point_y - yi) / ((yj - yi) or 1e-12) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def _select_nav_points_in_polygon(vertices: Sequence[Dict], coordinate_mode: str, scene_name: str) -> List[str]:
    if coordinate_mode not in {"local", "latlon"}:
        raise ValueError("coordinate_mode must be 'local' or 'latlon'")
    if len(vertices) < 3:
        raise ValueError("polygon requires at least three vertices")

    polygon = []
    for vertex in vertices:
        if coordinate_mode == "latlon":
            if "lat" not in vertex or "lon" not in vertex:
                raise ValueError("latlon polygon vertices must provide lat and lon")
            polygon.append({"x": float(vertex["lon"]), "y": float(vertex["lat"])})
        else:
            if "x" not in vertex or "z" not in vertex:
                raise ValueError("local polygon vertices must provide x and z")
            polygon.append({"x": float(vertex["x"]), "y": float(vertex["z"])})

    selected_ids = []
    for nav_point in nav_point_index(scene_name).values():
        point_x = nav_point["lon"] if coordinate_mode == "latlon" else nav_point["local_x"]
        point_y = nav_point["lat"] if coordinate_mode == "latlon" else nav_point["local_z"]
        if _point_in_polygon(point_x, point_y, polygon):
            selected_ids.append(nav_point["id"])
    return sorted(selected_ids)


def _build_leg_polyline(leg: Dict, robot_problem: Dict, nav_index: Dict, node_index: Dict) -> List[Dict]:
    path_node_ids = list(leg.get("path_node_ids", []))
    if leg["type"] == "start_to_nav":
        start_point = robot_problem["start_pose"]["resolved_local_position_m"]
        end_nav = nav_index[leg["to"]]
        end_point = {"x": end_nav["local_x"], "z": end_nav["local_z"]}
    elif leg["type"] == "nav_to_home":
        start_nav = nav_index[leg["from"]]
        start_point = {"x": start_nav["local_x"], "z": start_nav["local_z"]}
        end_point = robot_problem["home_pose"]["resolved_local_position_m"]
        path_node_ids = list(reversed(path_node_ids))
    else:
        start_nav = nav_index[leg["from"]]
        end_nav = nav_index[leg["to"]]
        start_point = {"x": start_nav["local_x"], "z": start_nav["local_z"]}
        end_point = {"x": end_nav["local_x"], "z": end_nav["local_z"]}

    points = [{"x": float(start_point["x"]), "z": float(start_point["z"])}]
    for node_id in path_node_ids:
        node = node_index.get(node_id)
        if node is not None:
            points.append({"x": float(node["x"]), "z": float(node["z"])})
    points.append({"x": float(end_point["x"]), "z": float(end_point["z"])})
    return _dedupe_polyline(points)


def _merge_route_polylines(robot_legs: Sequence[Dict]) -> List[Dict]:
    merged: List[Dict] = []
    for leg in robot_legs:
        for point in leg["polyline_local_m"]:
            if not merged:
                merged.append(point)
                continue
            previous = merged[-1]
            if math.isclose(previous["x"], point["x"], abs_tol=1e-6) and math.isclose(
                previous["z"], point["z"], abs_tol=1e-6
            ):
                continue
            merged.append(point)
    return merged


def _selected_nav_point_payload(nav_ids: Iterable[str], scene_name: str) -> List[Dict]:
    nav_index = nav_point_index(scene_name)
    payload = []
    for nav_id in nav_ids:
        if nav_id not in nav_index:
            continue
        payload.append(nav_index[nav_id])
    return payload


def _visualization_bounds(console_assets: Dict) -> Dict:
    xs: List[float] = []
    zs: List[float] = []
    for nav_point in console_assets["nav_points"]:
        xs.append(float(nav_point["local_x"]))
        zs.append(float(nav_point["local_z"]))
    for segment in console_assets["route_segments"]:
        for point in segment["points"]:
            xs.append(float(point["x"]))
            zs.append(float(point["z"]))
    return {
        "min_x": min(xs),
        "max_x": max(xs),
        "min_z": min(zs),
        "max_z": max(zs),
    }


def _build_plan_artifacts(
    raw_result: Dict,
    selection_payload: Dict,
    scene_name: str,
    polygon_payload: List[Dict] | None = None,
) -> Dict:
    planner_problem = build_runtime_planner_problem(scene_name, require_all_placed=True)
    robot_problem_index = {robot["planning_slot_id"]: robot for robot in planner_problem["robots"]}
    nav_index = nav_point_index(scene_name)
    node_index = route_node_index(scene_name)
    console_assets = get_console_assets(scene_name)

    for robot in raw_result["robots"]:
        robot_problem = robot_problem_index[robot["planning_slot_id"]]
        leg_payloads = []
        for leg in robot["legs"]:
            polyline = _build_leg_polyline(leg, robot_problem, nav_index, node_index)
            leg_payload = dict(leg)
            leg_payload["polyline_local_m"] = polyline
            leg_payloads.append(leg_payload)
        robot["legs"] = leg_payloads
        robot["route_nav_points"] = _selected_nav_point_payload(robot["route_nav_point_ids"], scene_name)
        robot["display_route_local_m"] = _merge_route_polylines(leg_payloads)
        robot["start_pose"] = robot_problem["start_pose"]
        robot["home_pose"] = robot_problem["home_pose"]
        robot["color"] = robot_problem.get("color", "#444444")
        robot["display_name"] = robot_problem.get("display_name", robot["planning_slot_id"])

    raw_result["selection"] = selection_payload
    raw_result["scene_name"] = scene_name
    raw_result["selected_nav_points"] = _selected_nav_point_payload(raw_result["target_nav_point_ids"], scene_name)
    raw_result["unassigned_nav_points"] = _selected_nav_point_payload(raw_result["unassigned_nav_point_ids"], scene_name)
    raw_result["visualization"] = {
        "bounds_local_m": _visualization_bounds(console_assets),
        "selected_polygon": polygon_payload or [],
        "nav_points": console_assets["nav_points"],
        "robots": [
            {
                "planning_slot_id": robot["planning_slot_id"],
                "color": robot["color"],
                "display_route_local_m": robot["display_route_local_m"],
                "route_nav_point_ids": robot["route_nav_point_ids"],
            }
            for robot in raw_result["robots"]
        ],
    }
    return raw_result


def _save_plan_files(plan_id: str, request_payload: Dict, result_payload: Dict) -> None:
    plan_root = _output_root(plan_id)
    write_json(plan_root / "request.json", request_payload)
    write_json(plan_root / "plan_result.json", result_payload)


def _cache_plan_preview(plan_id: str, request_payload: Dict, result_payload: Dict) -> None:
    with _PLAN_CACHE_LOCK:
        _PENDING_PLAN_CACHE[plan_id] = {
            "request": copy.deepcopy(request_payload),
            "result": copy.deepcopy(result_payload),
        }


def _get_cached_plan_preview(plan_id: str) -> Dict[str, Dict] | None:
    with _PLAN_CACHE_LOCK:
        payload = _PENDING_PLAN_CACHE.get(plan_id)
        if payload is None:
            return None
        return copy.deepcopy(payload)


def _relative_output_paths(plan_id: str) -> Dict[str, str]:
    root = _output_root_relative(plan_id)
    return {
        "output_dir": root.as_posix(),
        "request_path": (root / "request.json").as_posix(),
        "result_path": (root / "plan_result.json").as_posix(),
    }


def _apply_persistence_metadata(result_payload: Dict, plan_id: str, saved_at: str | None = None) -> Dict:
    payload = copy.deepcopy(result_payload)
    payload["persistence"] = {
        **_relative_output_paths(plan_id),
        "saved": saved_at is not None,
        "saved_at": saved_at,
    }
    return payload


def _base_request_envelope(mode: str, payload: Dict) -> Dict:
    return {
        "plan_id": payload["plan_id"],
        "mode": mode,
        "created_at": payload["created_at"],
        "request": payload["request"],
    }


def _execute_plan(
    mode: str,
    scene_name: str,
    selected_nav_ids: List[str],
    mission_label: str,
    natural_language: str,
    selection_payload: Dict,
    request_payload: Dict,
    polygon_payload: List[Dict] | None = None,
) -> Dict:
    if not selected_nav_ids:
        raise ValueError("no nav points selected for planning")

    plan_id = f"interactive_plan_{uuid.uuid4().hex[:10]}"
    created_at = datetime.now(timezone.utc).isoformat()

    planner_problem = build_runtime_planner_problem(scene_name, require_all_placed=True)
    robot_to_nav = build_runtime_robot_to_nav_costs(scene_name, require_all_placed=True)
    nav_to_nav = load_nav_to_nav_costs(scene_name)
    runtime_robot_config = get_runtime_robot_config(scene_name)

    raw_result = plan_multi_robot_routes(
        planner_problem=planner_problem,
        robot_to_nav_costs=robot_to_nav,
        nav_to_nav_costs=nav_to_nav,
        target_nav_ids=selected_nav_ids,
        mission_context={
            "mission_mode": mode,
            "mission_label": mission_label,
            "natural_language": natural_language,
            "target_set_ids": selection_payload.get("resolved_target_set_ids", []),
        },
    )
    raw_result["plan_id"] = plan_id
    raw_result["created_at"] = created_at

    result_payload = _apply_persistence_metadata(
        _build_plan_artifacts(raw_result, selection_payload, scene_name, polygon_payload=polygon_payload),
        plan_id,
    )
    request_envelope = _base_request_envelope(
        mode,
        {
            "plan_id": plan_id,
            "created_at": created_at,
            "request": {
                **request_payload,
                "scene": scene_name,
                "runtime_robot_config": runtime_robot_config,
            },
        },
    )
    _cache_plan_preview(plan_id, request_envelope, result_payload)
    return result_payload


def create_manual_plan(
    nav_point_ids: List[str],
    mission_label: str = "",
    notes: str = "",
    scene_name: str | None = None,
) -> Dict:
    scene = resolve_scene_name(scene_name)
    selected_nav_ids = sorted(set(validate_nav_point_ids(nav_point_ids, scene)))
    selection_payload = {
        "resolution_mode": "manual_selection",
        "resolved_target_set_ids": [],
        "resolved_nav_point_ids": selected_nav_ids,
        "matched_building_ids": [],
        "matched_building_names": [],
        "matched_nav_point_ids": selected_nav_ids,
        "notes": notes,
    }
    return _execute_plan(
        mode="manual",
        scene_name=scene,
        selected_nav_ids=selected_nav_ids,
        mission_label=mission_label or "manual_selected_targets",
        natural_language=mission_label or "手动选择任务点",
        selection_payload=selection_payload,
        request_payload={
            "nav_point_ids": selected_nav_ids,
            "mission_label": mission_label,
            "notes": notes,
            "scene": scene,
        },
    )


def create_polygon_plan(
    vertices: List[Dict],
    coordinate_mode: str = "local",
    mission_label: str = "",
    scene_name: str | None = None,
) -> Dict:
    scene = resolve_scene_name(scene_name)
    selected_nav_ids = _select_nav_points_in_polygon(vertices, coordinate_mode=coordinate_mode, scene_name=scene)
    if not selected_nav_ids:
        raise ValueError("polygon contains no selectable nav points")
    selection_payload = {
        "resolution_mode": "polygon_selection",
        "resolved_target_set_ids": [],
        "resolved_nav_point_ids": selected_nav_ids,
        "matched_building_ids": [],
        "matched_building_names": [],
        "matched_nav_point_ids": selected_nav_ids,
        "notes": f"Selected all nav points inside a {coordinate_mode} polygon.",
    }
    return _execute_plan(
        mode="polygon",
        scene_name=scene,
        selected_nav_ids=selected_nav_ids,
        mission_label=mission_label or "polygon_selected_targets",
        natural_language=mission_label or "圈选区域内任务点",
        selection_payload=selection_payload,
        request_payload={
            "vertices": vertices,
            "coordinate_mode": coordinate_mode,
            "mission_label": mission_label,
            "scene": scene,
        },
        polygon_payload=vertices,
    )


def create_semantic_plan(query: str, use_llm: bool = True, scene_name: str | None = None) -> Dict:
    scene = resolve_scene_name(scene_name)
    resolution = resolve_semantic_targets(query, use_llm=use_llm, scene_name=scene)
    selected_nav_ids = sorted(set(validate_nav_point_ids(resolution["resolved_nav_point_ids"], scene)))
    resolution["resolved_nav_point_ids"] = selected_nav_ids
    resolution["matched_nav_point_ids"] = selected_nav_ids
    if not selected_nav_ids:
        raise ValueError(f"semantic query did not resolve any nav points: {query}")
    return _execute_plan(
        mode="semantic",
        scene_name=scene,
        selected_nav_ids=selected_nav_ids,
        mission_label="semantic_selected_targets",
        natural_language=query,
        selection_payload=resolution,
        request_payload={
            "query": query,
            "use_llm": use_llm,
            "scene": scene,
        },
    )


def get_plan(plan_id: str) -> Dict:
    cached = _get_cached_plan_preview(plan_id)
    if cached is not None:
        return cached["result"]

    for root in (_output_root(plan_id), _plan_root(plan_id)):
        result_path = root / "plan_result.json"
        if result_path.exists():
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            if "persistence" not in payload:
                payload = _apply_persistence_metadata(payload, plan_id, saved_at=None)
            return payload
    raise FileNotFoundError(plan_id)


def list_saved_plan_ids() -> Dict:
    output_base_dir = _output_base_dir()
    if not output_base_dir.exists():
        return {
            "plan_ids": [],
            "count": 0,
        }

    plan_dirs = []
    for child in output_base_dir.iterdir():
        if not child.is_dir():
            continue
        if not child.name.startswith("interactive_plan_"):
            continue
        if not (child / "plan_result.json").exists():
            continue
        plan_dirs.append(child)

    plan_dirs.sort(key=lambda item: (item.stat().st_mtime, item.name), reverse=True)
    return {
        "plan_ids": [item.name for item in plan_dirs],
        "count": len(plan_dirs),
    }


def execute_plan(plan_id: str) -> Dict:
    cached = _get_cached_plan_preview(plan_id)
    if cached is None:
        saved_result_path = _output_root(plan_id) / "plan_result.json"
        if saved_result_path.exists():
            return json.loads(saved_result_path.read_text(encoding="utf-8"))
        raise FileNotFoundError(plan_id)

    request_payload = cached["request"]
    result_payload = cached["result"]
    if result_payload.get("persistence", {}).get("saved"):
        return result_payload

    saved_at = datetime.now(timezone.utc).isoformat()
    result_payload = _apply_persistence_metadata(result_payload, plan_id, saved_at=saved_at)
    request_payload = copy.deepcopy(request_payload)
    request_payload["executed_at"] = saved_at

    _save_plan_files(plan_id, request_payload, result_payload)
    _cache_plan_preview(plan_id, request_payload, result_payload)
    return result_payload


def get_console_payload(scene_name: str | None = None) -> Dict:
    scene = resolve_scene_name(scene_name)
    payload = get_console_assets(scene)
    mission_templates = load_mission_templates(scene)
    runtime_robot_config = get_runtime_robot_config(scene)
    payload["robots"] = build_runtime_robot_assets(scene)
    if isinstance(payload.get("counts"), dict):
        payload["counts"] = {
            **payload["counts"],
            "robots": runtime_robot_config["robot_count"],
        }
    payload["robot_config"] = runtime_robot_config
    payload["current_scene"] = scene
    payload["available_scenes"] = list_available_scenes()
    payload["available_templates"] = mission_templates["templates"]
    payload["semantic_examples"] = [item["natural_language"] for item in mission_templates["templates"]]
    payload["plan_api"] = {
        "assets": "/api/planner/interactive/assets",
        "robot_config": "/api/planner/interactive/robots/config",
        "list_saved": "/api/planner/interactive/plans",
        "manual": "/api/planner/interactive/plans/manual",
        "polygon": "/api/planner/interactive/plans/polygon",
        "semantic": "/api/planner/interactive/plans/semantic",
        "execute_template": "/api/planner/interactive/plans/{plan_id}/execute",
    }
    return payload
