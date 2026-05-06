from __future__ import annotations

import copy
import math
import re
from typing import Dict, List, Optional, Sequence

from app.services.local_asset_service import load_route_graph, load_world_manifest, nav_point_index


SCHEMA_VERSION = "1.2.0"
TASK_TYPE = "mission_planner_route"
DEFAULT_FRAME_ID = "map"
DEFAULT_POSITION_TOLERANCE_M = 10.0
DEFAULT_GPS_JUMP_REJECT_M = 15.0
EARTH_RADIUS_M = 6378137.0


def build_ros_task_payloads(plan_result: Dict, scene_name: Optional[str] = None) -> List[Dict]:
    """
    Build one URAN/CyberDog task payload for each robot route.

    The planner result remains the source of truth for web display. This
    function only adds a machine-facing route description so the backend can
    forward it to uran_autotask through task_params_json.
    """

    scene = scene_name or str(plan_result.get("scene_name") or "")
    if not scene:
        raise ValueError("scene_name is required to build ROS task payloads")

    nav_index = nav_point_index(scene)
    node_index = _route_node_index_with_geo(scene)
    projection_origin = _projection_origin(scene)

    payloads = []
    for robot in plan_result.get("robots") or []:
        if not isinstance(robot, dict):
            continue
        payload = _build_robot_payload(
            plan_result=plan_result,
            robot=robot,
            scene_name=scene,
            nav_index=nav_index,
            node_index=node_index,
            projection_origin=projection_origin,
        )
        if not payload.get("route", {}).get("points"):
            continue
        payloads.append(payload)
    return payloads


def _build_robot_payload(
    *,
    plan_result: Dict,
    robot: Dict,
    scene_name: str,
    nav_index: Dict[str, Dict],
    node_index: Dict[str, Dict],
    projection_origin: Dict[str, float],
) -> Dict:
    robot_id = str(robot.get("hardware_id") or robot.get("planning_slot_id") or "robot")
    planner_result_id = str(plan_result.get("plan_id") or "")
    task_id = _safe_task_id(f"mp_{planner_result_id}_{robot_id}") if planner_result_id else _safe_task_id(f"mp_{robot_id}")
    route_points = _build_route_points(
        robot=robot,
        nav_index=nav_index,
        node_index=node_index,
        projection_origin=projection_origin,
    )

    payload = {
        "schema_version": SCHEMA_VERSION,
        "task_type": TASK_TYPE,
        "task_id": task_id,
        "planner_result_id": planner_result_id,
        "scene_name": scene_name,
        "created_at": plan_result.get("created_at"),
        "robot": {
            "planning_slot_id": str(robot.get("planning_slot_id") or ""),
            "hardware_id": str(robot.get("hardware_id") or ""),
            "display_name": str(robot.get("display_name") or robot_id),
        },
        "coordinate_system": _coordinate_system(projection_origin),
        "execution": {
            "position_tolerance_m": DEFAULT_POSITION_TOLERANCE_M,
            "altitude_tolerance_m": 5.0,
            "min_gps_fix_type": 2,
            "gps_jump_reject_m": DEFAULT_GPS_JUMP_REJECT_M,
            "gps_vo_blend_window_s": 3.0,
            "stable_offset_required_count": 2,
            "calibrate_at_required_points": True,
            "calibrate_at_nav_points": True,
        },
        "route": {
            "route_nav_point_ids": [str(item) for item in robot.get("route_nav_point_ids") or []],
            "route_nav_points": copy.deepcopy(robot.get("route_nav_points") or []),
            "points": route_points,
        },
        "planner_summary": {
            "planning_slot_id": str(robot.get("planning_slot_id") or ""),
            "hardware_id": str(robot.get("hardware_id") or ""),
            "total_distance_with_home_m": float(robot.get("total_distance_with_home_m") or 0.0),
            "estimated_time_with_home_s": float(robot.get("estimated_time_with_home_s") or 0.0),
            "leg_count": len(robot.get("legs") or []),
        },
    }
    return payload


def _build_route_points(
    *,
    robot: Dict,
    nav_index: Dict[str, Dict],
    node_index: Dict[str, Dict],
    projection_origin: Dict[str, float],
) -> List[Dict]:
    points: List[Dict] = []
    for leg_index, leg in enumerate(robot.get("legs") or []):
        if not isinstance(leg, dict):
            continue
        for point in _leg_points(
            leg=leg,
            leg_index=leg_index,
            robot=robot,
            nav_index=nav_index,
            node_index=node_index,
            projection_origin=projection_origin,
        ):
            _append_deduped(points, point)

    for seq, point in enumerate(points):
        point["seq"] = seq
    return points


def _leg_points(
    *,
    leg: Dict,
    leg_index: int,
    robot: Dict,
    nav_index: Dict[str, Dict],
    node_index: Dict[str, Dict],
    projection_origin: Dict[str, float],
) -> List[Dict]:
    leg_type = str(leg.get("type") or "")
    path_node_ids = [str(item) for item in leg.get("path_node_ids") or []]

    if leg_type == "start_to_nav":
        start = _pose_point(
            pose=robot.get("start_pose") or {},
            kind="start",
            source_type="robot_start",
            point_id=f"start_{robot.get('planning_slot_id') or 'robot'}",
            nav_index=nav_index,
            projection_origin=projection_origin,
            leg_index=leg_index,
        )
        end = _nav_point(
            nav_id=str(leg.get("to") or ""),
            nav_index=nav_index,
            leg_index=leg_index,
        )
        ordered_node_ids = path_node_ids
    elif leg_type == "nav_to_home":
        start = _nav_point(
            nav_id=str(leg.get("from") or ""),
            nav_index=nav_index,
            leg_index=leg_index,
        )
        end = _pose_point(
            pose=robot.get("home_pose") or {},
            kind="home",
            source_type="robot_home",
            point_id=f"home_{robot.get('planning_slot_id') or 'robot'}",
            nav_index=nav_index,
            projection_origin=projection_origin,
            leg_index=leg_index,
        )
        ordered_node_ids = list(reversed(path_node_ids))
    else:
        start = _nav_point(
            nav_id=str(leg.get("from") or ""),
            nav_index=nav_index,
            leg_index=leg_index,
        )
        end = _nav_point(
            nav_id=str(leg.get("to") or ""),
            nav_index=nav_index,
            leg_index=leg_index,
        )
        ordered_node_ids = path_node_ids

    points = []
    if start is not None:
        points.append(start)
    for node_id in ordered_node_ids:
        node_point = _route_node_point(
            node_id=node_id,
            node_index=node_index,
            projection_origin=projection_origin,
            leg_index=leg_index,
        )
        if node_point is not None:
            points.append(node_point)
    if end is not None:
        points.append(end)
    return points


def _nav_point(*, nav_id: str, nav_index: Dict[str, Dict], leg_index: int) -> Optional[Dict]:
    nav = nav_index.get(nav_id)
    if nav is None:
        return None
    action = str(nav.get("action") or "").strip()
    kind = "inspection" if action else "calibration"
    return _route_point(
        point_id=nav_id,
        kind=kind,
        local_x=float(nav["local_x"]),
        local_y=_optional_float(nav.get("local_y"), 0.0),
        local_z=float(nav["local_z"]),
        lat=float(nav["lat"]),
        lon=float(nav["lon"]),
        alt=_optional_float(nav.get("alt"), _optional_float(nav.get("altitude_m"), 0.0)),
        yaw_deg=None if nav.get("yaw") in (None, "") else float(nav.get("yaw")),
        name=str(nav.get("name") or nav_id),
        source={"type": "nav_point", "id": nav_id, "leg_index": leg_index},
        required=True,
        allow_skip=False,
        actions=[action] if action else [],
        tolerance_m=DEFAULT_POSITION_TOLERANCE_M,
        geo_source="nav_point",
    )


def _route_node_point(
    *,
    node_id: str,
    node_index: Dict[str, Dict],
    projection_origin: Dict[str, float],
    leg_index: int,
) -> Optional[Dict]:
    node = node_index.get(node_id)
    if node is None:
        return None
    lat = node.get("lat")
    lon = node.get("lon")
    geo_source = "route_graph_node"
    if lat is None or lon is None:
        lat, lon = _local_to_geo(float(node["x"]), float(node["z"]), projection_origin)
        geo_source = "approx_local_projection"
    return _route_point(
        point_id=node_id,
        kind="transit",
        local_x=float(node["x"]),
        local_y=_optional_float(node.get("y"), 0.0),
        local_z=float(node["z"]),
        lat=lat,
        lon=lon,
        alt=_optional_float(node.get("alt"), _optional_float(node.get("altitude_m"), 0.0)),
        yaw_deg=None,
        name=node_id,
        source={"type": "route_graph_node", "id": node_id, "leg_index": leg_index},
        required=False,
        allow_skip=True,
        actions=[],
        tolerance_m=DEFAULT_POSITION_TOLERANCE_M,
        geo_source=geo_source,
    )


def _pose_point(
    *,
    pose: Dict,
    kind: str,
    source_type: str,
    point_id: str,
    nav_index: Dict[str, Dict],
    projection_origin: Dict[str, float],
    leg_index: int,
) -> Optional[Dict]:
    local = pose.get("resolved_local_position_m") or {}
    if "x" not in local or "z" not in local:
        return None

    local_x = float(local["x"])
    local_y = _optional_float(local.get("y"), _optional_float(local.get("up"), 0.0))
    local_z = float(local["z"])
    anchor_id = str(pose.get("anchor_nav_point_id") or "")
    anchor = nav_index.get(anchor_id)
    if anchor is not None:
        lat, lon = _geo_from_anchor_offset(pose, anchor, projection_origin)
        geo_source = "anchor_nav_point"
    else:
        lat, lon = _local_to_geo(local_x, local_z, projection_origin)
        geo_source = "approx_local_projection"

    heading_rad = pose.get("heading_rad")
    yaw_deg = None if heading_rad in (None, "") else math.degrees(float(heading_rad))
    return _route_point(
        point_id=point_id,
        kind=kind,
        local_x=local_x,
        local_y=local_y,
        local_z=local_z,
        lat=lat,
        lon=lon,
        alt=_optional_float(pose.get("alt"), _optional_float(pose.get("altitude_m"), local_y)),
        yaw_deg=yaw_deg,
        name=str(pose.get("anchor_name") or point_id),
        source={
            "type": source_type,
            "id": point_id,
            "anchor_nav_point_id": anchor_id,
            "leg_index": leg_index,
        },
        required=False,
        allow_skip=True,
        actions=[],
        tolerance_m=DEFAULT_POSITION_TOLERANCE_M,
        geo_source=geo_source,
    )


def _route_point(
    *,
    point_id: str,
    kind: str,
    local_x: float,
    local_y: float,
    local_z: float,
    lat: Optional[float],
    lon: Optional[float],
    alt: Optional[float],
    yaw_deg: Optional[float],
    name: str,
    source: Dict,
    required: bool,
    allow_skip: bool,
    actions: Sequence[str],
    tolerance_m: float,
    geo_source: str,
) -> Dict:
    point = {
        "seq": -1,
        "point_id": str(point_id),
        "kind": str(kind),
        "source": copy.deepcopy(source),
        "local": {"x": float(local_x), "y": float(local_y), "z": float(local_z)},
        "map": {"frame_id": DEFAULT_FRAME_ID, "x": float(local_x), "y": float(local_z), "z": float(local_y)},
        "yaw_deg": yaw_deg,
        "tolerance_m": float(tolerance_m),
        "required": bool(required),
        "allow_skip": bool(allow_skip),
        "actions": [item for item in actions if item],
        "name": str(name),
    }
    if lat is not None and lon is not None:
        point["geo"] = {
            "lat": float(lat),
            "lon": float(lon),
            "alt": 0.0 if alt is None else float(alt),
            "source": geo_source,
        }
    return point


def _append_deduped(points: List[Dict], point: Dict) -> None:
    if not points:
        points.append(point)
        return
    previous = points[-1]
    distance_m = math.hypot(
        float(previous["local"]["x"]) - float(point["local"]["x"]),
        float(previous["local"]["z"]) - float(point["local"]["z"]),
    )
    if distance_m > 1e-5:
        points.append(point)
        return
    if point.get("required") and not previous.get("required"):
        points[-1] = point
        return
    previous.setdefault("merged_sources", []).append(point.get("source", {}))


def _route_node_index_with_geo(scene_name: str) -> Dict[str, Dict]:
    index = {}
    for node in load_route_graph(scene_name).get("nodes") or []:
        node_id = str(node.get("node_id") or "")
        if not node_id:
            continue
        index[node_id] = {
            "node_id": node_id,
            "x": float(node["local_x"]),
            "y": _optional_float(node.get("local_y"), 0.0),
            "z": float(node["local_z"]),
            "lat": None if node.get("lat") in (None, "") else float(node.get("lat")),
            "lon": None if node.get("lon") in (None, "") else float(node.get("lon")),
            "alt": _optional_float(node.get("alt"), _optional_float(node.get("altitude_m"), 0.0)),
        }
    return index


def _projection_origin(scene_name: str) -> Dict[str, float]:
    manifest = load_world_manifest(scene_name)
    origin = manifest.get("projection_origin") or {}
    if "lat" not in origin or "lon" not in origin:
        return {}
    return {"lat": float(origin["lat"]), "lon": float(origin["lon"])}


def _coordinate_system(projection_origin: Dict[str, float]) -> Dict:
    return {
        "geo": {
            "type": "WGS84",
            "lat_unit": "deg",
            "lon_unit": "deg",
            "alt_unit": "m",
            "alt_reference": "scene_or_device_default",
        },
        "local": {
            "frame_id": "mission_planner_local_xzy",
            "unit": "m",
            "x_axis": "east",
            "y_axis": "up",
            "z_axis": "north",
            "projection_origin": copy.deepcopy(projection_origin),
        },
        "ros_map": {
            "frame_id": DEFAULT_FRAME_ID,
            "unit": "m",
            "x_from": "local.x",
            "y_from": "local.z",
            "z_from": "local.y",
            "yaw_deg": 0.0,
            "scale": 1.0,
        },
        "note": "No field calibration offset is applied here; uran_autotask should close the loop with GPS and visual odometry.",
    }


def _geo_from_anchor_offset(pose: Dict, anchor: Dict, projection_origin: Dict[str, float]) -> tuple[float, float]:
    offset = pose.get("offset_from_anchor_local_m") or {}
    dx = float(offset.get("x") or 0.0)
    dz = float(offset.get("z") or 0.0)
    if math.isclose(dx, 0.0, abs_tol=1e-6) and math.isclose(dz, 0.0, abs_tol=1e-6):
        return float(anchor["lat"]), float(anchor["lon"])
    return _offset_geo(float(anchor["lat"]), float(anchor["lon"]), dx, dz)


def _local_to_geo(local_x: float, local_z: float, projection_origin: Dict[str, float]) -> tuple[Optional[float], Optional[float]]:
    if "lat" not in projection_origin or "lon" not in projection_origin:
        return None, None
    return _offset_geo(float(projection_origin["lat"]), float(projection_origin["lon"]), local_x, local_z)


def _offset_geo(origin_lat: float, origin_lon: float, east_m: float, north_m: float) -> tuple[float, float]:
    lat_rad = math.radians(origin_lat)
    lat = origin_lat + math.degrees(float(north_m) / EARTH_RADIUS_M)
    lon = origin_lon + math.degrees(float(east_m) / (EARTH_RADIUS_M * max(math.cos(lat_rad), 1e-9)))
    return lat, lon


def _safe_task_id(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return normalized.strip("_") or "mission_planner_route"


def _optional_float(value, default: Optional[float] = None) -> Optional[float]:
    if value in (None, ""):
        return default
    return float(value)
