#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


PI = math.pi
GCJ_A = 6378245.0
GCJ_EE = 0.00669342162296594323


def out_of_china(lat: float, lon: float) -> bool:
    return not (72.004 <= lon <= 137.8347 and 0.8293 <= lat <= 55.8271)


def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * PI) + 20.0 * math.sin(2.0 * x * PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * PI) + 40.0 * math.sin(y / 3.0 * PI)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * PI) + 320 * math.sin(y * PI / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lon(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * PI) + 20.0 * math.sin(2.0 * x * PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * PI) + 40.0 * math.sin(x / 3.0 * PI)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * PI) + 300.0 * math.sin(x / 30.0 * PI)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lat: float, lon: float) -> Tuple[float, float]:
    if out_of_china(lat, lon):
        return lat, lon
    dlat = _transform_lat(lon - 105.0, lat - 35.0)
    dlon = _transform_lon(lon - 105.0, lat - 35.0)
    radlat = lat / 180.0 * PI
    magic = math.sin(radlat)
    magic = 1 - GCJ_EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((GCJ_A * (1 - GCJ_EE)) / (magic * sqrtmagic) * PI)
    dlon = (dlon * 180.0) / (GCJ_A / sqrtmagic * math.cos(radlat) * PI)
    return lat + dlat, lon + dlon


def gcj02_to_wgs84(lat: float, lon: float) -> Tuple[float, float]:
    # Iterative inverse is more stable than the common one-step approximation.
    wgs_lat = lat
    wgs_lon = lon
    for _ in range(8):
        gcj_lat, gcj_lon = wgs84_to_gcj02(wgs_lat, wgs_lon)
        wgs_lat -= gcj_lat - lat
        wgs_lon -= gcj_lon - lon
    return wgs_lat, wgs_lon


def meter_delta(from_lat: float, from_lon: float, to_lat: float, to_lon: float) -> Tuple[float, float, float]:
    lat_mid = math.radians((from_lat + to_lat) / 2.0)
    east_m = (to_lon - from_lon) * 111320.0 * math.cos(lat_mid)
    north_m = (to_lat - from_lat) * 110540.0
    return east_m, north_m, math.hypot(east_m, north_m)


def _stats(values: Sequence[float]) -> Dict[str, Optional[float]]:
    if not values:
        return {"min": None, "max": None, "mean": None}
    return {
        "min": round(min(values), 6),
        "max": round(max(values), 6),
        "mean": round(sum(values) / len(values), 6),
    }


def _solve_3x3(matrix: List[List[float]], vector: List[float]) -> Optional[List[float]]:
    augmented = [row[:] + [value] for row, value in zip(matrix, vector)]
    size = 3
    for col in range(size):
        pivot = max(range(col, size), key=lambda row: abs(augmented[row][col]))
        if abs(augmented[pivot][col]) < 1e-12:
            return None
        augmented[col], augmented[pivot] = augmented[pivot], augmented[col]
        pivot_value = augmented[col][col]
        for item in range(col, size + 1):
            augmented[col][item] /= pivot_value
        for row in range(size):
            if row == col:
                continue
            factor = augmented[row][col]
            for item in range(col, size + 1):
                augmented[row][item] -= factor * augmented[col][item]
    return [augmented[row][size] for row in range(size)]


def _fit_affine(points: Sequence[Tuple[float, float, float, float]]) -> Dict[str, object]:
    # Fit local_x/local_z from lon/lat. This checks internal consistency only.
    if len(points) < 3:
        return {
            "point_count": len(points),
            "available": False,
            "reason": "at least three points are required",
        }
    normal = [[0.0 for _ in range(3)] for _ in range(3)]
    rhs_x = [0.0, 0.0, 0.0]
    rhs_z = [0.0, 0.0, 0.0]
    for lon, lat, local_x, local_z in points:
        row = [lon, lat, 1.0]
        for i in range(3):
            rhs_x[i] += row[i] * local_x
            rhs_z[i] += row[i] * local_z
            for j in range(3):
                normal[i][j] += row[i] * row[j]
    coeff_x = _solve_3x3(normal, rhs_x)
    coeff_z = _solve_3x3(normal, rhs_z)
    if coeff_x is None or coeff_z is None:
        return {
            "point_count": len(points),
            "available": False,
            "reason": "affine solve failed",
        }
    residuals = []
    for lon, lat, local_x, local_z in points:
        row = [lon, lat, 1.0]
        predicted_x = sum(row[i] * coeff_x[i] for i in range(3))
        predicted_z = sum(row[i] * coeff_z[i] for i in range(3))
        residuals.append(math.hypot(local_x - predicted_x, local_z - predicted_z))
    return {
        "point_count": len(points),
        "available": True,
        "residual_m": _stats(residuals),
        "coefficients": {
            "local_x_from_lon_lat_1": [round(value, 9) for value in coeff_x],
            "local_z_from_lon_lat_1": [round(value, 9) for value in coeff_z],
        },
    }


def _nav_points(nav_geojson: Dict) -> List[Tuple[float, float, float, float]]:
    points = []
    for feature in nav_geojson.get("features", []):
        props = feature.get("properties", {})
        try:
            points.append((
                float(props["lon"]),
                float(props["lat"]),
                float(props["local_x"]),
                float(props["local_z"]),
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return points


def _route_nodes(route_graph: Dict) -> List[Tuple[float, float, float, float]]:
    points = []
    nodes = route_graph.get("nodes", [])
    if isinstance(nodes, dict):
        iterable: Iterable = nodes.values()
    else:
        iterable = nodes
    for node in iterable:
        try:
            points.append((
                float(node["lon"]),
                float(node["lat"]),
                float(node["local_x"]),
                float(node["local_z"]),
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return points


def _gcj_shift_summary(lat_lon_points: Sequence[Tuple[float, float]]) -> Dict[str, object]:
    forward_east = []
    forward_north = []
    forward_dist = []
    correction_east = []
    correction_north = []
    correction_dist = []
    for lat, lon in lat_lon_points:
        gcj_lat, gcj_lon = wgs84_to_gcj02(lat, lon)
        east, north, dist = meter_delta(lat, lon, gcj_lat, gcj_lon)
        forward_east.append(east)
        forward_north.append(north)
        forward_dist.append(dist)

        wgs_lat, wgs_lon = gcj02_to_wgs84(lat, lon)
        east, north, dist = meter_delta(lat, lon, wgs_lat, wgs_lon)
        correction_east.append(east)
        correction_north.append(north)
        correction_dist.append(dist)
    return {
        "wgs84_to_gcj02_offset_m": {
            "east": _stats(forward_east),
            "north": _stats(forward_north),
            "distance": _stats(forward_dist),
        },
        "gcj02_like_to_wgs84_correction_m": {
            "east": _stats(correction_east),
            "north": _stats(correction_north),
            "distance": _stats(correction_dist),
        },
    }


def _correct_lat_lon_pair(lat: float, lon: float) -> Tuple[float, float]:
    return gcj02_to_wgs84(lat, lon)


def _correct_lat_lon_fields(value):
    if isinstance(value, dict):
        result = {}
        has_lat_lon = (
            "lat" in value
            and "lon" in value
            and isinstance(value.get("lat"), (int, float))
            and isinstance(value.get("lon"), (int, float))
        )
        corrected_lat_lon: Optional[Tuple[float, float]] = None
        if has_lat_lon:
            corrected_lat_lon = _correct_lat_lon_pair(float(value["lat"]), float(value["lon"]))
        for key, item in value.items():
            if corrected_lat_lon and key == "lat":
                result[key] = corrected_lat_lon[0]
            elif corrected_lat_lon and key == "lon":
                result[key] = corrected_lat_lon[1]
            else:
                result[key] = _correct_lat_lon_fields(item)
        return result
    if isinstance(value, list):
        return [_correct_lat_lon_fields(item) for item in value]
    return value


def _correct_geojson_points(nav_geojson: Dict) -> Dict:
    corrected = _correct_lat_lon_fields(copy.deepcopy(nav_geojson))
    for feature in corrected.get("features", []):
        geometry = feature.get("geometry", {})
        if geometry.get("type") != "Point":
            continue
        coordinates = geometry.get("coordinates", [])
        if not isinstance(coordinates, list) or len(coordinates) < 2:
            continue
        lon = coordinates[0]
        lat = coordinates[1]
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            continue
        wgs_lat, wgs_lon = _correct_lat_lon_pair(float(lat), float(lon))
        geometry["coordinates"][0] = wgs_lon
        geometry["coordinates"][1] = wgs_lat
    metadata = corrected.setdefault("metadata", {})
    metadata["georef_correction"] = {
        "source_assumption": "coordinates_are_gcj02_like",
        "target": "wgs84_for_gnss",
        "local_x_local_z": "unchanged",
    }
    return corrected


def audit_scene(asset_root: Path, output_root: Path, scene: str, write_corrected: bool) -> Dict[str, object]:
    scene_root = asset_root / scene
    manifest = json.loads((scene_root / "world" / "manifest.json").read_text(encoding="utf-8"))
    nav_points = json.loads((scene_root / "mission" / "nav_points.geojson").read_text(encoding="utf-8"))
    nav_points_enriched_path = scene_root / "mission" / "nav_points_enriched.geojson"
    nav_points_enriched = (
        json.loads(nav_points_enriched_path.read_text(encoding="utf-8"))
        if nav_points_enriched_path.exists()
        else None
    )
    route_graph = json.loads((scene_root / "mission" / "route_graph.json").read_text(encoding="utf-8"))

    origin = manifest.get("projection_origin", {})
    origin_lat = float(origin["lat"])
    origin_lon = float(origin["lon"])
    origin_gcj_lat, origin_gcj_lon = wgs84_to_gcj02(origin_lat, origin_lon)
    origin_forward = meter_delta(origin_lat, origin_lon, origin_gcj_lat, origin_gcj_lon)
    origin_corrected_lat, origin_corrected_lon = gcj02_to_wgs84(origin_lat, origin_lon)
    origin_correction = meter_delta(origin_lat, origin_lon, origin_corrected_lat, origin_corrected_lon)

    nav_fit = _fit_affine(_nav_points(nav_points))
    route_fit = _fit_affine(_route_nodes(route_graph))
    nav_lat_lon = [
        (float(feature["properties"]["lat"]), float(feature["properties"]["lon"]))
        for feature in nav_points.get("features", [])
        if "properties" in feature and "lat" in feature["properties"] and "lon" in feature["properties"]
    ]
    gcj_summary = _gcj_shift_summary(nav_lat_lon)

    report = {
        "scene": scene,
        "source_files": {
            "manifest": str((scene_root / "world" / "manifest.json").relative_to(asset_root.parent.parent)),
            "nav_points": str((scene_root / "mission" / "nav_points.geojson").relative_to(asset_root.parent.parent)),
            "route_graph": str((scene_root / "mission" / "route_graph.json").relative_to(asset_root.parent.parent)),
        },
        "important_limit": (
            "This audit can check internal coordinate consistency and the GCJ-02 correction scenario. "
            "It cannot prove the true satellite-to-GNSS offset without independent WGS84 control points."
        ),
        "projection_origin": {
            "current": {"lat": origin_lat, "lon": origin_lon},
            "wgs84_to_gcj02_offset_m": {
                "east": round(origin_forward[0], 3),
                "north": round(origin_forward[1], 3),
                "distance": round(origin_forward[2], 3),
            },
            "gcj02_like_to_wgs84_candidate": {
                "lat": origin_corrected_lat,
                "lon": origin_corrected_lon,
                "correction_m": {
                    "east": round(origin_correction[0], 3),
                    "north": round(origin_correction[1], 3),
                    "distance": round(origin_correction[2], 3),
                },
            },
        },
        "local_projection_self_consistency": {
            "nav_points_affine_fit": nav_fit,
            "route_nodes_affine_fit": route_fit,
        },
        "gcj02_scenario_from_nav_points": gcj_summary,
        "correction_policy": {
            "safe_default": "do_not_overwrite_scene_assets",
            "candidate_use": (
                "Use corrected copies only if the original scene coordinates were drawn on a GCJ-02-like "
                "or otherwise China-offset imagery layer while robot GNSS reports WGS84."
            ),
            "local_frame": "local_x/local_z are kept unchanged; only lat/lon fields are corrected in candidate files.",
        },
    }

    scene_output = output_root / scene
    scene_output.mkdir(parents=True, exist_ok=True)
    (scene_output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if write_corrected:
        corrected_nav = _correct_geojson_points(nav_points)
        (scene_output / "nav_points.wgs84_from_gcj.geojson").write_text(
            json.dumps(corrected_nav, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if nav_points_enriched is not None:
            corrected_enriched = _correct_geojson_points(nav_points_enriched)
            (scene_output / "nav_points_enriched.wgs84_from_gcj.geojson").write_text(
                json.dumps(corrected_enriched, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        corrected_route = _correct_lat_lon_fields(route_graph)
        corrected_route.setdefault("metadata", {})["georef_correction"] = {
            "source_assumption": "coordinates_are_gcj02_like",
            "target": "wgs84_for_gnss",
            "local_x_local_z": "unchanged",
        }
        (scene_output / "route_graph.wgs84_from_gcj.json").write_text(
            json.dumps(corrected_route, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    return report


def _available_scenes(asset_root: Path) -> List[str]:
    return sorted(
        path.name
        for path in asset_root.iterdir()
        if path.is_dir() and (path / "world" / "manifest.json").exists()
    )


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Audit mission planner scene georeference offsets.")
    parser.add_argument("--asset-root", default=str(project_root / "data" / "assets"))
    parser.add_argument("--output-root", default=str(project_root / "data" / "outputs" / "georef_audit"))
    parser.add_argument("--scenes", nargs="*", default=None)
    parser.add_argument("--no-write-corrected", action="store_true")
    args = parser.parse_args()

    asset_root = Path(args.asset_root).resolve()
    output_root = Path(args.output_root).resolve()
    scenes = args.scenes or _available_scenes(asset_root)
    if not scenes:
        raise SystemExit(f"no scenes found under {asset_root}")

    reports = []
    for scene in scenes:
        reports.append(audit_scene(asset_root, output_root, scene, write_corrected=not args.no_write_corrected))

    index = {
        "asset_root": str(asset_root),
        "output_root": str(output_root),
        "scenes": [
            {
                "scene": report["scene"],
                "report": str((output_root / report["scene"] / "report.json").resolve()),
                "candidate_nav_points": str((output_root / report["scene"] / "nav_points.wgs84_from_gcj.geojson").resolve()),
                "candidate_route_graph": str((output_root / report["scene"] / "route_graph.wgs84_from_gcj.json").resolve()),
                "origin_correction_m": report["projection_origin"]["gcj02_like_to_wgs84_candidate"]["correction_m"],
            }
            for report in reports
        ],
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for item in index["scenes"]:
        correction = item["origin_correction_m"]
        print(
            f"{item['scene']}: candidate GCJ-like -> WGS84 correction "
            f"east={correction['east']}m north={correction['north']}m distance={correction['distance']}m"
        )
        print(f"  report: {item['report']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
