from __future__ import annotations

import ctypes
import os
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional, Sequence


_NATIVE_LIB_ENV = "MISSION_PLANNER_NATIVE_LIB_PATH"
_DISABLE_NATIVE_ENV = "MISSION_PLANNER_DISABLE_NATIVE_PLANNER"
_DEFAULT_NATIVE_LIB_PATHS = (
    Path("/tmp/mission_planner_native/libmission_planner_native.so"),
    Path("/usr/local/lib/libmission_planner_native.so"),
)


class _NativePlannerInput(ctypes.Structure):
    _fields_ = [
        ("robot_count", ctypes.c_int32),
        ("target_count", ctypes.c_int32),
        ("budgets_m", ctypes.POINTER(ctypes.c_double)),
        ("start_reachable", ctypes.POINTER(ctypes.c_uint8)),
        ("start_distance_m", ctypes.POINTER(ctypes.c_double)),
        ("start_time_s", ctypes.POINTER(ctypes.c_double)),
        ("home_reachable", ctypes.POINTER(ctypes.c_uint8)),
        ("home_distance_m", ctypes.POINTER(ctypes.c_double)),
        ("home_time_s", ctypes.POINTER(ctypes.c_double)),
        ("pair_reachable", ctypes.POINTER(ctypes.c_uint8)),
        ("pair_distance_m", ctypes.POINTER(ctypes.c_double)),
        ("pair_time_s", ctypes.POINTER(ctypes.c_double)),
        ("max_improvement_passes", ctypes.c_int32),
    ]


class _NativePlannerOutput(ctypes.Structure):
    _fields_ = [
        ("route_lengths", ctypes.POINTER(ctypes.c_int32)),
        ("routes_flat", ctypes.POINTER(ctypes.c_int32)),
        ("unassigned_mask", ctypes.POINTER(ctypes.c_uint8)),
    ]


def _native_disabled() -> bool:
    raw = os.getenv(_DISABLE_NATIVE_ENV, "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _native_library_candidates() -> list[Path]:
    candidates: list[Path] = []
    env_path = os.getenv(_NATIVE_LIB_ENV, "").strip()
    if env_path:
        candidates.append(Path(env_path))
    candidates.extend(_DEFAULT_NATIVE_LIB_PATHS)
    return candidates


@lru_cache(maxsize=1)
def _load_native_library():
    if _native_disabled():
        return None

    for path in _native_library_candidates():
        if not path.exists():
            continue
        try:
            library = ctypes.CDLL(str(path))
        except OSError:
            continue

        library.solve_multi_robot_routes.argtypes = [
            ctypes.POINTER(_NativePlannerInput),
            ctypes.POINTER(_NativePlannerOutput),
        ]
        library.solve_multi_robot_routes.restype = ctypes.c_int
        library.planner_last_error.argtypes = []
        library.planner_last_error.restype = ctypes.c_char_p
        return library

    return None


def reset_native_planner_cache() -> None:
    _load_native_library.cache_clear()


def native_planner_available() -> bool:
    return _load_native_library() is not None


def _robot_ids_in_default_order(planner_problem: Dict) -> list[str]:
    return sorted(str(robot["planning_slot_id"]) for robot in planner_problem["robots"])


def _robot_budget_map(planner_problem: Dict) -> dict[str, float]:
    budget_map: dict[str, float] = {}
    for robot in planner_problem["robots"]:
        robot_id = str(robot["planning_slot_id"])
        range_budget = float(robot["planner_limits"]["planning_range_budget_m"])
        soc = float(robot["planner_limits"]["initial_battery_soc_percent"]) / 100.0
        budget_map[robot_id] = round(range_budget * soc, 3)
    return budget_map


def _cost_components(cost_entry: Optional[Dict]) -> tuple[int, float, float]:
    if not cost_entry or not bool(cost_entry.get("reachable")):
        return 0, 0.0, 0.0
    return 1, float(cost_entry.get("distance_m", 0.0)), float(cost_entry.get("estimated_time_s", 0.0))


def solve_multi_robot_routes_native(
    planner_problem: Dict,
    start_costs: Dict,
    home_costs: Dict,
    pair_costs: Dict,
    target_nav_ids: Sequence[str],
    *,
    max_improvement_passes: int,
) -> Optional[Dict]:
    library = _load_native_library()
    if library is None:
        return None

    robot_ids = _robot_ids_in_default_order(planner_problem)
    target_ids = list(target_nav_ids)
    robot_count = len(robot_ids)
    target_count = len(target_ids)

    if robot_count < 1:
        return None

    if target_count == 0:
        return {
            "routes_by_robot": {robot_id: [] for robot_id in robot_ids},
            "unassigned_nav_point_ids": [],
        }

    budget_map = _robot_budget_map(planner_problem)

    budgets = [budget_map[robot_id] for robot_id in robot_ids]
    start_reachable: list[int] = []
    start_distance_m: list[float] = []
    start_time_s: list[float] = []
    home_reachable: list[int] = []
    home_distance_m: list[float] = []
    home_time_s: list[float] = []

    for robot_id in robot_ids:
        start_cost_map = start_costs.get(robot_id, {}).get("costs", {})
        home_cost_map = home_costs.get(robot_id, {}).get("costs", {})
        for target_id in target_ids:
            reachable, distance_m, time_s = _cost_components(start_cost_map.get(target_id))
            start_reachable.append(reachable)
            start_distance_m.append(distance_m)
            start_time_s.append(time_s)

            reachable, distance_m, time_s = _cost_components(home_cost_map.get(target_id))
            home_reachable.append(reachable)
            home_distance_m.append(distance_m)
            home_time_s.append(time_s)

    pair_reachable: list[int] = []
    pair_distance_m: list[float] = []
    pair_time_s: list[float] = []
    for source_target_id in target_ids:
        pair_cost_map = pair_costs.get(source_target_id, {})
        for target_id in target_ids:
            reachable, distance_m, time_s = _cost_components(pair_cost_map.get(target_id))
            pair_reachable.append(reachable)
            pair_distance_m.append(distance_m)
            pair_time_s.append(time_s)

    budgets_buffer = (ctypes.c_double * robot_count)(*budgets)
    start_reachable_buffer = (ctypes.c_uint8 * len(start_reachable))(*start_reachable)
    start_distance_buffer = (ctypes.c_double * len(start_distance_m))(*start_distance_m)
    start_time_buffer = (ctypes.c_double * len(start_time_s))(*start_time_s)
    home_reachable_buffer = (ctypes.c_uint8 * len(home_reachable))(*home_reachable)
    home_distance_buffer = (ctypes.c_double * len(home_distance_m))(*home_distance_m)
    home_time_buffer = (ctypes.c_double * len(home_time_s))(*home_time_s)
    pair_reachable_buffer = (ctypes.c_uint8 * len(pair_reachable))(*pair_reachable)
    pair_distance_buffer = (ctypes.c_double * len(pair_distance_m))(*pair_distance_m)
    pair_time_buffer = (ctypes.c_double * len(pair_time_s))(*pair_time_s)

    route_lengths_buffer = (ctypes.c_int32 * robot_count)()
    routes_flat_buffer = (ctypes.c_int32 * (robot_count * target_count))()
    unassigned_mask_buffer = (ctypes.c_uint8 * target_count)()

    native_input = _NativePlannerInput(
        robot_count=robot_count,
        target_count=target_count,
        budgets_m=budgets_buffer,
        start_reachable=start_reachable_buffer,
        start_distance_m=start_distance_buffer,
        start_time_s=start_time_buffer,
        home_reachable=home_reachable_buffer,
        home_distance_m=home_distance_buffer,
        home_time_s=home_time_buffer,
        pair_reachable=pair_reachable_buffer,
        pair_distance_m=pair_distance_buffer,
        pair_time_s=pair_time_buffer,
        max_improvement_passes=int(max_improvement_passes),
    )
    native_output = _NativePlannerOutput(
        route_lengths=route_lengths_buffer,
        routes_flat=routes_flat_buffer,
        unassigned_mask=unassigned_mask_buffer,
    )

    status = library.solve_multi_robot_routes(ctypes.byref(native_input), ctypes.byref(native_output))
    if status != 0:
        return None

    routes_by_robot: dict[str, list[str]] = {}
    for robot_index, robot_id in enumerate(robot_ids):
        route_length = int(route_lengths_buffer[robot_index])
        route: list[str] = []
        base_index = robot_index * target_count
        for item_index in range(route_length):
            target_index = int(routes_flat_buffer[base_index + item_index])
            if target_index < 0 or target_index >= target_count:
                return None
            route.append(target_ids[target_index])
        routes_by_robot[robot_id] = route

    unassigned_nav_point_ids = [
        target_ids[target_index]
        for target_index in range(target_count)
        if int(unassigned_mask_buffer[target_index]) != 0
    ]

    return {
        "routes_by_robot": routes_by_robot,
        "unassigned_nav_point_ids": unassigned_nav_point_ids,
    }
