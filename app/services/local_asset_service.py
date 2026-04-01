from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.core.config import get_settings


def _settings():
    return get_settings()


def _asset_root() -> Path:
    return _settings().asset_root_dir


def _read_json(path: Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _mission_path(name: str) -> Path:
    return _asset_root() / "mission" / name


def _world_path(name: str) -> Path:
    return _asset_root() / "world" / name


def _fleet_path(name: str) -> Path:
    return _asset_root() / "fleet" / name


def _planning_asset_path(name: str) -> Path:
    return _asset_root() / "planning" / "assets" / name


@lru_cache(maxsize=1)
def load_world_manifest() -> Dict:
    return _read_json(_world_path("manifest.json"))


@lru_cache(maxsize=1)
def load_world_map_data() -> Dict:
    return _read_json(_world_path("map_data.json"))


@lru_cache(maxsize=1)
def load_nav_points_geojson() -> Dict:
    return _read_json(_mission_path("nav_points_enriched.geojson"))


@lru_cache(maxsize=1)
def load_route_graph() -> Dict:
    return _read_json(_mission_path("route_graph.json"))


@lru_cache(maxsize=1)
def load_nav_point_bindings() -> Dict:
    return _read_json(_mission_path("nav_point_bindings.json"))


@lru_cache(maxsize=1)
def load_semantic_catalog() -> Dict:
    return _read_json(_mission_path("semantic_catalog.json"))


@lru_cache(maxsize=1)
def load_robot_registry() -> Dict:
    return _read_json(_fleet_path("robot_registry.json"))


@lru_cache(maxsize=1)
def load_planner_problem() -> Dict:
    return _read_json(_planning_asset_path("planner_problem.json"))


@lru_cache(maxsize=1)
def load_planning_manifest() -> Dict:
    return _read_json(_planning_asset_path("planning_input_manifest.json"))


@lru_cache(maxsize=1)
def load_target_sets() -> Dict:
    return _read_json(_planning_asset_path("semantic_target_sets.json"))


@lru_cache(maxsize=1)
def load_mission_templates() -> Dict:
    return _read_json(_planning_asset_path("mission_request_templates.json"))


@lru_cache(maxsize=1)
def load_robot_to_nav_costs() -> Dict:
    return _read_json(_planning_asset_path("robot_to_nav_costs.json"))


@lru_cache(maxsize=1)
def load_nav_to_nav_costs() -> Dict:
    return _read_json(_planning_asset_path("nav_to_nav_shortest_paths.json"))


@lru_cache(maxsize=1)
def world_boundary() -> Dict[str, float]:
    boundary = load_world_map_data().get("boundary", {})
    return {
        "min_x": float(boundary.get("min_x", 0.0)),
        "max_x": float(boundary.get("max_x", 0.0)),
        "min_z": float(boundary.get("min_z", 0.0)),
        "max_z": float(boundary.get("max_z", 0.0)),
    }


def _classify_area_style(tags: Dict) -> Tuple[Optional[str], Optional[str]]:
    if "building" in tags:
        return "building", "building"

    landuse = tags.get("landuse")
    if landuse in {"forest", "orchard", "meadow", "grass", "residential"}:
        return "landuse", f"landuse:{landuse}"

    leisure = tags.get("leisure")
    if leisure in {"pitch", "park"}:
        return "landuse", f"leisure:{leisure}"

    natural = tags.get("natural")
    if natural in {"grassland", "wood"}:
        return "landuse", f"natural:{natural}"

    amenity = tags.get("amenity")
    if amenity:
        return "landuse", f"amenity:{amenity}"

    return None, None


@lru_cache(maxsize=1)
def nav_point_index() -> Dict[str, Dict]:
    index = {}
    for feature in load_nav_points_geojson()["features"]:
        props = feature["properties"]
        index[props["id"]] = {
            "id": props["id"],
            "name": props.get("name", props["id"]),
            "lat": float(props["lat"]),
            "lon": float(props["lon"]),
            "local_x": float(props["local_x"]),
            "local_z": float(props["local_z"]),
            "category": props.get("category", ""),
            "semantic_type": props.get("semantic_type", ""),
            "building_ref": props.get("building_ref", ""),
            "building_name": props.get("building_name", ""),
            "building_category": props.get("building_category", ""),
            "robot_types": list(props.get("robot_types", [])),
            "yaw": float(props.get("yaw", 0.0)),
            "action": props.get("action", ""),
            "note": props.get("note", ""),
        }
    return index


@lru_cache(maxsize=1)
def route_node_index() -> Dict[str, Dict]:
    index = {}
    for node in load_route_graph()["nodes"]:
        index[node["node_id"]] = {
            "node_id": node["node_id"],
            "x": float(node["local_x"]),
            "z": float(node["local_z"]),
        }
    return index


@lru_cache(maxsize=1)
def map_area_layers() -> List[Dict]:
    areas = []
    boundary = world_boundary()
    for area in load_world_map_data().get("areas", []):
        layer_type, style_key = _classify_area_style(area.get("tags", {}))
        polygon = area.get("polygon_xz", {})
        outer = polygon.get("outer", [])
        if layer_type is None or len(outer) < 3:
            continue

        bbox = area.get("bbox", {})
        if (
            float(bbox.get("max_x", -1e12)) < boundary["min_x"]
            or float(bbox.get("min_x", 1e12)) > boundary["max_x"]
            or float(bbox.get("max_z", -1e12)) < boundary["min_z"]
            or float(bbox.get("min_z", 1e12)) > boundary["max_z"]
        ):
            continue

        areas.append(
            {
                "area_id": area["element_id"],
                "layer_type": layer_type,
                "style_key": style_key,
                "name": area.get("tags", {}).get("name", ""),
                "tags": area.get("tags", {}),
                "outer": [
                    {"x": float(point["x"]), "z": float(point["z"])}
                    for point in outer
                ],
                "holes": [
                    [
                        {"x": float(point["x"]), "z": float(point["z"])}
                        for point in hole
                    ]
                    for hole in polygon.get("holes", [])
                ],
            }
        )
    return sorted(areas, key=lambda item: (item["layer_type"] != "landuse", item["area_id"]))


def _clip_segment_to_boundary(start: Dict[str, float], end: Dict[str, float], boundary: Dict[str, float]) -> Optional[List[Dict]]:
    x0 = float(start["x"])
    z0 = float(start["z"])
    x1 = float(end["x"])
    z1 = float(end["z"])
    dx = x1 - x0
    dz = z1 - z0

    min_x = float(boundary["min_x"])
    max_x = float(boundary["max_x"])
    min_z = float(boundary["min_z"])
    max_z = float(boundary["max_z"])

    u1 = 0.0
    u2 = 1.0
    p = (-dx, dx, -dz, dz)
    q = (x0 - min_x, max_x - x0, z0 - min_z, max_z - z0)

    for pi, qi in zip(p, q):
        if abs(pi) <= 1e-12:
            if qi < 0:
                return None
            continue
        t = qi / pi
        if pi < 0:
            if t > u2:
                return None
            u1 = max(u1, t)
        else:
            if t < u1:
                return None
            u2 = min(u2, t)

    clipped_start = {"x": round(x0 + u1 * dx, 3), "z": round(z0 + u1 * dz, 3)}
    clipped_end = {"x": round(x0 + u2 * dx, 3), "z": round(z0 + u2 * dz, 3)}
    return [clipped_start, clipped_end]


@lru_cache(maxsize=1)
def route_edge_segments() -> List[Dict]:
    boundary = world_boundary()
    segments = []
    for edge in load_route_graph()["edges"]:
        source = {
            "x": float(edge["from_local_xz"]["x"]),
            "z": float(edge["from_local_xz"]["z"]),
        }
        target = {
            "x": float(edge["to_local_xz"]["x"]),
            "z": float(edge["to_local_xz"]["z"]),
        }
        clipped_points = _clip_segment_to_boundary(source, target, boundary)
        if clipped_points is None:
            continue
        segments.append(
            {
                "edge_id": edge["edge_id"],
                "from": edge["from_node_id"],
                "to": edge["to_node_id"],
                "length_m": float(edge.get("length_m", 0.0)),
                "road_type": edge.get("highway", ""),
                "bidirectional": bool(edge.get("bidirectional", False)),
                "points": clipped_points,
            }
        )
    return segments


def get_console_assets() -> Dict:
    manifest = load_planning_manifest()
    nav_points = sorted(nav_point_index().values(), key=lambda item: item["id"])
    robots = []
    for robot in load_planner_problem()["robots"]:
        robots.append(
            {
                "planning_slot_id": robot["planning_slot_id"],
                "hardware_id": robot["hardware_id"],
                "start_nav_point_id": robot["start_nav_point_id"],
                "home_nav_point_id": robot["home_nav_point_id"],
                "start_pose": robot["start_pose"],
                "home_pose": robot["home_pose"],
                "planner_limits": robot["planner_limits"],
            }
        )
    return {
        "package_id": manifest["package_id"],
        "counts": manifest["counts"],
        "projection_origin": load_world_manifest().get("projection_origin", {}),
        "world_boundary": world_boundary(),
        "map_areas": map_area_layers(),
        "nav_points": nav_points,
        "route_segments": route_edge_segments(),
        "robots": robots,
    }


def clear_asset_caches() -> None:
    load_world_manifest.cache_clear()
    load_world_map_data.cache_clear()
    load_nav_points_geojson.cache_clear()
    load_route_graph.cache_clear()
    load_nav_point_bindings.cache_clear()
    load_semantic_catalog.cache_clear()
    load_robot_registry.cache_clear()
    load_planner_problem.cache_clear()
    load_planning_manifest.cache_clear()
    load_target_sets.cache_clear()
    load_mission_templates.cache_clear()
    load_robot_to_nav_costs.cache_clear()
    load_nav_to_nav_costs.cache_clear()
    world_boundary.cache_clear()
    map_area_layers.cache_clear()
    nav_point_index.cache_clear()
    route_node_index.cache_clear()
    route_edge_segments.cache_clear()
