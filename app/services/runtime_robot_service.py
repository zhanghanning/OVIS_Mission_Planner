from __future__ import annotations

import copy
from typing import Dict, List, Optional

from app.services.local_asset_service import (
    load_nav_to_nav_costs,
    load_planner_problem,
    nav_point_index,
    resolve_scene_name,
)


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
        "note": "Request-selected robot anchor aligned directly to an existing nav point.",
    }


def _validate_robot_count(robot_count: int) -> int:
    try:
        count = int(robot_count)
    except (TypeError, ValueError) as exc:
        raise ValueError("robot_count is required and must be an integer") from exc
    if count < 1:
        raise ValueError("robot_count must be at least 1")
    if count > 32:
        raise ValueError("robot_count must not exceed 32")
    return count


def _clean_optional_string(value: object) -> Optional[str]:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _build_robot_entry(index: int, raw: Dict, scene_name: str) -> Dict:
    nav_index = nav_point_index(scene_name)
    anchor_nav_point_id = _clean_optional_string(raw.get("anchor_nav_point_id"))
    if anchor_nav_point_id is None:
        raise ValueError(f"robot_config.robots[{index - 1}].anchor_nav_point_id is required")
    if anchor_nav_point_id not in nav_index:
        raise ValueError(f"unknown robot anchor nav point: {anchor_nav_point_id}")

    anchor = nav_index[anchor_nav_point_id]
    pose = _build_runtime_pose(anchor)
    return {
        "index": index,
        "planning_slot_id": _clean_optional_string(raw.get("planning_slot_id")) or _slot_id(index),
        "hardware_id": _clean_optional_string(raw.get("hardware_id")) or _hardware_id(index),
        "display_name": _clean_optional_string(raw.get("display_name")) or _display_name(index),
        "color": _clean_optional_string(raw.get("color")) or _color_for_index(index),
        "placed": True,
        "anchor_nav_point_id": anchor["id"],
        "anchor_nav_point_name": anchor["name"],
        "start_nav_point_id": anchor["id"],
        "home_nav_point_id": anchor["id"],
        "start_pose": copy.deepcopy(pose),
        "home_pose": copy.deepcopy(pose),
    }


def normalize_robot_config(robot_config: Dict, scene_name: str | None = None) -> Dict:
    scene = resolve_scene_name(scene_name)
    if not isinstance(robot_config, dict):
        raise ValueError("robot_config must be an object")

    count = _validate_robot_count(robot_config.get("robot_count"))
    raw_robots = robot_config.get("robots") or []
    if not isinstance(raw_robots, list):
        raise ValueError("robot_config.robots must be a list")
    if len(raw_robots) < count:
        raise ValueError("robot_config.robots must contain one entry per robot_count")

    robots: List[Dict] = []
    planning_slot_ids: set[str] = set()
    hardware_ids: set[str] = set()
    for index in range(1, count + 1):
        raw = raw_robots[index - 1] or {}
        if not isinstance(raw, dict):
            raise ValueError(f"robot_config.robots[{index - 1}] must be an object")
        robot = _build_robot_entry(index, raw, scene)
        if robot["planning_slot_id"] in planning_slot_ids:
            raise ValueError(f"duplicate planning_slot_id: {robot['planning_slot_id']}")
        if robot["hardware_id"] in hardware_ids:
            raise ValueError(f"duplicate hardware_id: {robot['hardware_id']}")
        planning_slot_ids.add(robot["planning_slot_id"])
        hardware_ids.add(robot["hardware_id"])
        robots.append(robot)

    return {
        "schema_version": "1.0.0",
        "scene_name": scene,
        "robot_count": count,
        "all_robots_placed": True,
        "placed_robot_ids": [robot["planning_slot_id"] for robot in robots],
        "unplaced_robot_ids": [],
        "source": "request",
        "robots": robots,
    }


def build_runtime_robot_assets(robot_config: Dict, scene_name: str | None = None) -> List[Dict]:
    scene = resolve_scene_name(scene_name)
    config = normalize_robot_config(robot_config, scene)
    planner_problem = load_planner_problem(scene)
    template_robots = planner_problem["robots"]
    assets: List[Dict] = []
    for robot_config_entry in config["robots"]:
        template_robot = _template_robot_for_index(template_robots, robot_config_entry["index"])
        template_robot["index"] = robot_config_entry["index"]
        template_robot["planning_slot_id"] = robot_config_entry["planning_slot_id"]
        template_robot["hardware_id"] = robot_config_entry["hardware_id"]
        template_robot["display_name"] = robot_config_entry["display_name"]
        template_robot["color"] = robot_config_entry["color"]
        template_robot["start_nav_point_id"] = robot_config_entry["start_nav_point_id"]
        template_robot["home_nav_point_id"] = robot_config_entry["home_nav_point_id"]
        template_robot["start_pose"] = copy.deepcopy(robot_config_entry["start_pose"])
        template_robot["home_pose"] = copy.deepcopy(robot_config_entry["home_pose"])
        template_robot["placed"] = robot_config_entry["placed"]
        template_robot["anchor_nav_point_id"] = robot_config_entry["anchor_nav_point_id"]
        template_robot["anchor_nav_point_name"] = robot_config_entry["anchor_nav_point_name"]
        template_robot["ros_namespace"] = f"../../../{robot_config_entry['hardware_id']}"
        template_robot["gazebo_entity_name"] = robot_config_entry["hardware_id"]
        assets.append(template_robot)
    return assets


def build_runtime_planner_problem(robot_config: Dict, scene_name: str | None = None) -> Dict:
    scene = resolve_scene_name(scene_name)
    config = normalize_robot_config(robot_config, scene)

    base_problem = copy.deepcopy(load_planner_problem(scene))
    base_problem["problem_id"] = f"{scene}_request_multi_dog_planner_problem"
    base_problem["fleet"]["robot_count"] = config["robot_count"]
    base_problem["fleet"]["planning_note"] = "Request robot_config determines active robot slots and anchors."
    base_problem["robots"] = build_runtime_robot_assets(config, scene)
    base_problem["refs"].pop("runtime_robot_config", None)
    return base_problem


def build_runtime_robot_to_nav_costs(
    robot_config: Dict,
    scene_name: str | None = None,
    planner_problem: Dict | None = None,
) -> Dict:
    scene = resolve_scene_name(scene_name)
    if planner_problem is None:
        planner_problem = build_runtime_planner_problem(robot_config, scene)
    nav_to_nav_costs = load_nav_to_nav_costs(scene)
    nav_pair_costs = nav_to_nav_costs["pairs"]
    nav_anchor_nodes = nav_to_nav_costs["nav_anchor_nodes"]
    payload = {
        "schema_version": "1.0.0",
        "metadata": {
            "route_graph_ref": nav_to_nav_costs["metadata"].get("route_graph_ref", ""),
            "nav_points_ref": nav_to_nav_costs["metadata"].get("nav_points_ref", ""),
            "nav_bindings_ref": nav_to_nav_costs["metadata"].get("nav_bindings_ref", ""),
            "access_model": "request_anchor_nav_point_plus_precomputed_nav_pairs",
            "robot_config_source": "request",
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
