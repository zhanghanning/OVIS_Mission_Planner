from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

from app.core.config import get_settings
from app.planners.formal_multi_robot import plan_multi_robot_routes
from app.services.local_asset_service import (
    get_console_assets,
    load_mission_templates,
    load_nav_to_nav_costs,
    load_planner_problem,
    load_robot_to_nav_costs,
    nav_point_index,
    route_node_index,
)
from app.services.result_service import write_json
from app.services.semantic_service import resolve_semantic_targets, validate_nav_point_ids


ROBOT_COLORS = {
    "slot_01": "#d94841",
    "slot_02": "#2674f2",
    "slot_03": "#1a936f",
}


def _settings():
    return get_settings()


def _plan_root(plan_id: str) -> Path:
    return _settings().local_plan_dir / plan_id


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


def _select_nav_points_in_polygon(vertices: Sequence[Dict], coordinate_mode: str) -> List[str]:
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
    for nav_point in nav_point_index().values():
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


def _selected_nav_point_payload(nav_ids: Iterable[str]) -> List[Dict]:
    nav_index = nav_point_index()
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


def _build_plan_artifacts(raw_result: Dict, selection_payload: Dict, polygon_payload: List[Dict] | None = None) -> Dict:
    planner_problem = load_planner_problem()
    robot_problem_index = {robot["planning_slot_id"]: robot for robot in planner_problem["robots"]}
    nav_index = nav_point_index()
    node_index = route_node_index()
    console_assets = get_console_assets()

    for robot in raw_result["robots"]:
        robot_problem = robot_problem_index[robot["planning_slot_id"]]
        leg_payloads = []
        for leg in robot["legs"]:
            polyline = _build_leg_polyline(leg, robot_problem, nav_index, node_index)
            leg_payload = dict(leg)
            leg_payload["polyline_local_m"] = polyline
            leg_payloads.append(leg_payload)
        robot["legs"] = leg_payloads
        robot["route_nav_points"] = _selected_nav_point_payload(robot["route_nav_point_ids"])
        robot["display_route_local_m"] = _merge_route_polylines(leg_payloads)
        robot["start_pose"] = robot_problem["start_pose"]
        robot["home_pose"] = robot_problem["home_pose"]
        robot["color"] = ROBOT_COLORS.get(robot["planning_slot_id"], "#444444")

    raw_result["selection"] = selection_payload
    raw_result["selected_nav_points"] = _selected_nav_point_payload(raw_result["target_nav_point_ids"])
    raw_result["unassigned_nav_points"] = _selected_nav_point_payload(raw_result["unassigned_nav_point_ids"])
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
    plan_root = _plan_root(plan_id)
    write_json(plan_root / "request.json", request_payload)
    write_json(plan_root / "plan_result.json", result_payload)


def _base_request_envelope(mode: str, payload: Dict) -> Dict:
    return {
        "plan_id": payload["plan_id"],
        "mode": mode,
        "created_at": payload["created_at"],
        "request": payload["request"],
    }


def _execute_plan(
    mode: str,
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

    planner_problem = load_planner_problem()
    robot_to_nav = load_robot_to_nav_costs()
    nav_to_nav = load_nav_to_nav_costs()

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

    result_payload = _build_plan_artifacts(raw_result, selection_payload, polygon_payload=polygon_payload)
    _save_plan_files(
        plan_id,
        _base_request_envelope(
            mode,
            {
                "plan_id": plan_id,
                "created_at": created_at,
                "request": request_payload,
            },
        ),
        result_payload,
    )
    return result_payload


def create_manual_plan(nav_point_ids: List[str], mission_label: str = "", notes: str = "") -> Dict:
    selected_nav_ids = sorted(set(validate_nav_point_ids(nav_point_ids)))
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
        selected_nav_ids=selected_nav_ids,
        mission_label=mission_label or "manual_selected_targets",
        natural_language=mission_label or "手动选择任务点",
        selection_payload=selection_payload,
        request_payload={
            "nav_point_ids": selected_nav_ids,
            "mission_label": mission_label,
            "notes": notes,
        },
    )


def create_polygon_plan(vertices: List[Dict], coordinate_mode: str = "local", mission_label: str = "") -> Dict:
    selected_nav_ids = _select_nav_points_in_polygon(vertices, coordinate_mode=coordinate_mode)
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
        selected_nav_ids=selected_nav_ids,
        mission_label=mission_label or "polygon_selected_targets",
        natural_language=mission_label or "圈选区域内任务点",
        selection_payload=selection_payload,
        request_payload={
            "vertices": vertices,
            "coordinate_mode": coordinate_mode,
            "mission_label": mission_label,
        },
        polygon_payload=vertices,
    )


def create_semantic_plan(query: str, use_llm: bool = True) -> Dict:
    resolution = resolve_semantic_targets(query, use_llm=use_llm)
    selected_nav_ids = sorted(set(validate_nav_point_ids(resolution["resolved_nav_point_ids"])))
    resolution["resolved_nav_point_ids"] = selected_nav_ids
    resolution["matched_nav_point_ids"] = selected_nav_ids
    if not selected_nav_ids:
        raise ValueError(f"semantic query did not resolve any nav points: {query}")
    return _execute_plan(
        mode="semantic",
        selected_nav_ids=selected_nav_ids,
        mission_label="semantic_selected_targets",
        natural_language=query,
        selection_payload=resolution,
        request_payload={
            "query": query,
            "use_llm": use_llm,
        },
    )


def get_plan(plan_id: str) -> Dict:
    result_path = _plan_root(plan_id) / "plan_result.json"
    if not result_path.exists():
        raise FileNotFoundError(plan_id)
    return json.loads(result_path.read_text(encoding="utf-8"))


def get_console_payload() -> Dict:
    payload = get_console_assets()
    mission_templates = load_mission_templates()
    payload["available_templates"] = mission_templates["templates"]
    payload["semantic_examples"] = [item["natural_language"] for item in mission_templates["templates"]]
    payload["plan_api"] = {
        "manual": "/api/planner/interactive/plans/manual",
        "polygon": "/api/planner/interactive/plans/polygon",
        "semantic": "/api/planner/interactive/plans/semantic",
    }
    return payload
