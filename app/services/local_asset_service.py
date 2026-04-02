from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.core.config import get_settings


def _settings():
    return get_settings()


def _asset_base_dir() -> Path:
    asset_root = _settings().asset_root_dir
    return asset_root.parent


def default_scene_name() -> str:
    return _settings().asset_root_dir.name


@lru_cache(maxsize=1)
def list_available_scenes() -> List[str]:
    base_dir = _asset_base_dir()
    if not base_dir.exists():
        return []
    return sorted(
        child.name
        for child in base_dir.iterdir()
        if child.is_dir() and not child.name.startswith(".")
    )


def resolve_scene_name(scene_name: Optional[str] = None) -> str:
    available = list_available_scenes()
    if not available:
        raise FileNotFoundError(f"no scene directories found under {_asset_base_dir()}")

    if scene_name:
        normalized = scene_name.strip()
        if normalized in available:
            return normalized
        raise ValueError(f"unknown scene: {scene_name}")

    default_name = default_scene_name()
    if default_name in available:
        return default_name
    return available[0]


def _asset_root(scene_name: Optional[str] = None) -> Path:
    return _asset_base_dir() / resolve_scene_name(scene_name)


def _read_json(path: Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _mission_path(name: str, scene_name: Optional[str] = None) -> Path:
    return _asset_root(scene_name) / "mission" / name


def _world_path(name: str, scene_name: Optional[str] = None) -> Path:
    return _asset_root(scene_name) / "world" / name


def _fleet_path(name: str, scene_name: Optional[str] = None) -> Path:
    return _asset_root(scene_name) / "fleet" / name


def _planning_asset_path(name: str, scene_name: Optional[str] = None) -> Path:
    return _asset_root(scene_name) / "planning" / "assets" / name


@lru_cache(maxsize=32)
def load_world_manifest(scene_name: Optional[str] = None) -> Dict:
    scene = resolve_scene_name(scene_name)
    return _read_json(_world_path("manifest.json", scene))


@lru_cache(maxsize=32)
def load_world_map_data(scene_name: Optional[str] = None) -> Dict:
    scene = resolve_scene_name(scene_name)
    return _read_json(_world_path("map_data.json", scene))


@lru_cache(maxsize=32)
def load_nav_points_geojson(scene_name: Optional[str] = None) -> Dict:
    scene = resolve_scene_name(scene_name)
    return _read_json(_mission_path("nav_points_enriched.geojson", scene))


@lru_cache(maxsize=32)
def load_route_graph(scene_name: Optional[str] = None) -> Dict:
    scene = resolve_scene_name(scene_name)
    return _read_json(_mission_path("route_graph.json", scene))


@lru_cache(maxsize=32)
def load_nav_point_bindings(scene_name: Optional[str] = None) -> Dict:
    scene = resolve_scene_name(scene_name)
    return _read_json(_mission_path("nav_point_bindings.json", scene))


@lru_cache(maxsize=32)
def load_semantic_catalog(scene_name: Optional[str] = None) -> Dict:
    scene = resolve_scene_name(scene_name)
    return _read_json(_mission_path("semantic_catalog.json", scene))


@lru_cache(maxsize=32)
def load_robot_registry(scene_name: Optional[str] = None) -> Dict:
    scene = resolve_scene_name(scene_name)
    return _read_json(_fleet_path("robot_registry.json", scene))


@lru_cache(maxsize=32)
def load_planner_problem(scene_name: Optional[str] = None) -> Dict:
    scene = resolve_scene_name(scene_name)
    return _read_json(_planning_asset_path("planner_problem.json", scene))


@lru_cache(maxsize=32)
def load_planning_manifest(scene_name: Optional[str] = None) -> Dict:
    scene = resolve_scene_name(scene_name)
    return _read_json(_planning_asset_path("planning_input_manifest.json", scene))


@lru_cache(maxsize=32)
def load_target_sets(scene_name: Optional[str] = None) -> Dict:
    scene = resolve_scene_name(scene_name)
    return _read_json(_planning_asset_path("semantic_target_sets.json", scene))


@lru_cache(maxsize=32)
def load_mission_templates(scene_name: Optional[str] = None) -> Dict:
    scene = resolve_scene_name(scene_name)
    return _read_json(_planning_asset_path("mission_request_templates.json", scene))


@lru_cache(maxsize=32)
def load_robot_to_nav_costs(scene_name: Optional[str] = None) -> Dict:
    scene = resolve_scene_name(scene_name)
    return _read_json(_planning_asset_path("robot_to_nav_costs.json", scene))


@lru_cache(maxsize=32)
def load_nav_to_nav_costs(scene_name: Optional[str] = None) -> Dict:
    scene = resolve_scene_name(scene_name)
    return _read_json(_planning_asset_path("nav_to_nav_shortest_paths.json", scene))


@lru_cache(maxsize=32)
def world_boundary(scene_name: Optional[str] = None) -> Dict[str, float]:
    boundary = load_world_map_data(scene_name).get("boundary", {})
    return {
        "min_x": float(boundary.get("min_x", 0.0)),
        "max_x": float(boundary.get("max_x", 0.0)),
        "min_z": float(boundary.get("min_z", 0.0)),
        "max_z": float(boundary.get("max_z", 0.0)),
    }


def _classify_area_style(tags: Dict) -> Tuple[Optional[str], Optional[str]]:
    if "building" in tags:
        return "building", "building"

    power = tags.get("power")
    if power == "substation":
        return "power", "power:substation"

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


@lru_cache(maxsize=32)
def nav_point_index(scene_name: Optional[str] = None) -> Dict[str, Dict]:
    index = {}
    for feature in load_nav_points_geojson(scene_name)["features"]:
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
            "power_asset_ref": props.get("power_asset_ref", ""),
            "power_asset_name": props.get("power_asset_name", ""),
            "power_asset_category": props.get("power_asset_category", ""),
            "robot_types": list(props.get("robot_types", [])),
            "yaw": float(props.get("yaw", 0.0)),
            "action": props.get("action", ""),
            "note": props.get("note", ""),
        }
    return index


@lru_cache(maxsize=32)
def route_node_index(scene_name: Optional[str] = None) -> Dict[str, Dict]:
    index = {}
    for node in load_route_graph(scene_name)["nodes"]:
        index[node["node_id"]] = {
            "node_id": node["node_id"],
            "x": float(node["local_x"]),
            "z": float(node["local_z"]),
        }
    return index


@lru_cache(maxsize=32)
def map_area_layers(scene_name: Optional[str] = None) -> List[Dict]:
    areas = []
    boundary = world_boundary(scene_name)
    map_data = load_world_map_data(scene_name)

    def bbox_intersects_boundary(bbox: Dict) -> bool:
        return not (
            float(bbox.get("max_x", -1e12)) < boundary["min_x"]
            or float(bbox.get("min_x", 1e12)) > boundary["max_x"]
            or float(bbox.get("max_z", -1e12)) < boundary["min_z"]
            or float(bbox.get("min_z", 1e12)) > boundary["max_z"]
        )

    def append_area_layer(
        *,
        area_id: str,
        tags: Dict,
        outer: List[Dict],
        holes: List[List[Dict]],
        bbox: Dict,
    ) -> None:
        layer_type, style_key = _classify_area_style(tags)
        if layer_type is None or len(outer) < 3 or not bbox_intersects_boundary(bbox):
            return

        areas.append(
            {
                "area_id": area_id,
                "layer_type": layer_type,
                "style_key": style_key,
                "name": tags.get("name", ""),
                "tags": tags,
                "outer": [
                    {"x": float(point["x"]), "z": float(point["z"])}
                    for point in outer
                ],
                "holes": [
                    [
                        {"x": float(point["x"]), "z": float(point["z"])}
                        for point in hole
                    ]
                    for hole in holes
                ],
            }
        )

    for area in map_data.get("areas", []):
        polygon = area.get("polygon_xz", {})
        append_area_layer(
            area_id=area["element_id"],
            tags=area.get("tags", {}),
            outer=polygon.get("outer", []),
            holes=polygon.get("holes", []),
            bbox=area.get("bbox", {}),
        )

    for way in map_data.get("ways", []):
        polyline = way.get("polyline_xz", [])
        if len(polyline) < 4 or polyline[0] != polyline[-1]:
            continue
        append_area_layer(
            area_id=way["element_id"],
            tags=way.get("tags", {}),
            outer=polyline[:-1],
            holes=[],
            bbox=way.get("bbox", {}),
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


@lru_cache(maxsize=32)
def route_edge_segments(scene_name: Optional[str] = None) -> List[Dict]:
    boundary = world_boundary(scene_name)
    segments = []
    for edge in load_route_graph(scene_name)["edges"]:
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


def get_console_assets(scene_name: Optional[str] = None) -> Dict:
    scene = resolve_scene_name(scene_name)
    manifest = load_planning_manifest(scene)
    nav_points = sorted(nav_point_index(scene).values(), key=lambda item: item["id"])
    robots = []
    for robot in load_planner_problem(scene)["robots"]:
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
        "scene_name": scene,
        "package_id": manifest["package_id"],
        "counts": manifest["counts"],
        "projection_origin": load_world_manifest(scene).get("projection_origin", {}),
        "world_boundary": world_boundary(scene),
        "map_areas": map_area_layers(scene),
        "nav_points": nav_points,
        "route_segments": route_edge_segments(scene),
        "robots": robots,
    }


def clear_asset_caches() -> None:
    list_available_scenes.cache_clear()
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
