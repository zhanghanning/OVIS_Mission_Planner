from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from app.planners.native_formal_multi_robot import solve_multi_robot_routes_native


EPSILON = 1e-9
CONSTRUCTION_MODES = ("regret", "constrained", "best_global")
MAX_IMPROVEMENT_PASSES = 8


def _resolve_targets_from_template(template_id: str, mission_templates: Dict, target_sets: Dict) -> Tuple[Dict, List[str]]:
    template_map = {item["template_id"]: item for item in mission_templates["templates"]}
    target_set_map = {item["target_set_id"]: item for item in target_sets["target_sets"]}
    template = template_map[template_id]
    nav_ids: List[str] = []
    for target_set_id in template["target_set_ids"]:
        nav_ids.extend(target_set_map[target_set_id]["nav_point_ids"])
    return template, sorted(set(nav_ids))


def _route_metrics(
    robot_id: str,
    route: Sequence[str],
    start_costs: Dict,
    home_costs: Dict,
    nav_pair_costs: Dict,
) -> Dict:
    if not route:
        return {
            "reachable": True,
            "distance_m": 0.0,
            "estimated_time_s": 0.0,
            "legs": [],
        }

    legs: List[Dict] = []
    first = start_costs[robot_id]["costs"][route[0]]
    if not first["reachable"]:
        return {"reachable": False}

    total_distance = float(first["distance_m"])
    total_time = float(first["estimated_time_s"])
    legs.append(
        {
            "type": "start_to_nav",
            "from": "start",
            "to": route[0],
            "distance_m": round(float(first["distance_m"]), 3),
            "estimated_time_s": round(float(first["estimated_time_s"]), 3),
            "graph_distance_m": round(float(first.get("graph_distance_m", 0.0)), 3),
            "graph_time_s": round(float(first.get("graph_time_s", 0.0)), 3),
            "source_access_distance_m": round(float(first.get("source_access_distance_m", 0.0)), 3),
            "target_access_distance_m": round(float(first.get("target_access_distance_m", 0.0)), 3),
            "path_node_ids": list(first.get("path_node_ids", [])),
            "path_edge_ids": list(first.get("path_edge_ids", [])),
        }
    )

    for source_nav_id, target_nav_id in zip(route, route[1:]):
        leg = nav_pair_costs[source_nav_id][target_nav_id]
        if not leg["reachable"]:
            return {"reachable": False}
        total_distance += float(leg["distance_m"])
        total_time += float(leg["estimated_time_s"])
        legs.append(
            {
                "type": "nav_to_nav",
                "from": source_nav_id,
                "to": target_nav_id,
                "distance_m": round(float(leg["distance_m"]), 3),
                "estimated_time_s": round(float(leg["estimated_time_s"]), 3),
                "graph_distance_m": round(float(leg.get("graph_distance_m", 0.0)), 3),
                "graph_time_s": round(float(leg.get("graph_time_s", 0.0)), 3),
                "source_access_distance_m": round(float(leg.get("source_access_distance_m", 0.0)), 3),
                "target_access_distance_m": round(float(leg.get("target_access_distance_m", 0.0)), 3),
                "path_node_ids": list(leg.get("path_node_ids", [])),
                "path_edge_ids": list(leg.get("path_edge_ids", [])),
            }
        )

    last = home_costs[robot_id]["costs"][route[-1]]
    if not last["reachable"]:
        return {"reachable": False}
    total_distance += float(last["distance_m"])
    total_time += float(last["estimated_time_s"])
    legs.append(
        {
            "type": "nav_to_home",
            "from": route[-1],
            "to": "home",
            "distance_m": round(float(last["distance_m"]), 3),
            "estimated_time_s": round(float(last["estimated_time_s"]), 3),
            "graph_distance_m": round(float(last.get("graph_distance_m", 0.0)), 3),
            "graph_time_s": round(float(last.get("graph_time_s", 0.0)), 3),
            "source_access_distance_m": round(float(last.get("source_access_distance_m", 0.0)), 3),
            "target_access_distance_m": round(float(last.get("target_access_distance_m", 0.0)), 3),
            "path_node_ids": list(last.get("path_node_ids", [])),
            "path_edge_ids": list(last.get("path_edge_ids", [])),
        }
    )

    return {
        "reachable": True,
        "distance_m": round(total_distance, 3),
        "estimated_time_s": round(total_time, 3),
        "legs": legs,
    }


def _empty_metrics() -> Dict:
    return {
        "reachable": True,
        "distance_m": 0.0,
        "estimated_time_s": 0.0,
        "legs": [],
    }


def _build_state(planner_problem: Dict) -> Dict:
    state = {}
    for robot in planner_problem["robots"]:
        range_budget = float(robot["planner_limits"]["planning_range_budget_m"])
        soc = float(robot["planner_limits"]["initial_battery_soc_percent"]) / 100.0
        effective_range_budget = round(range_budget * soc, 3)
        state[robot["planning_slot_id"]] = {
            "robot": robot,
            "budget_m": effective_range_budget,
            "route": [],
            "metrics": _empty_metrics(),
        }
    return state


def _float_less(a: float, b: float) -> bool:
    return a + EPSILON < b


def _float_greater(a: float, b: float) -> bool:
    return b + EPSILON < a


def _compare_time_vectors(left: Tuple[float, ...], right: Tuple[float, ...]) -> int:
    for left_value, right_value in zip(left, right):
        if _float_less(left_value, right_value):
            return -1
        if _float_greater(left_value, right_value):
            return 1
    return 0


def _score_from_metric_pairs(metric_pairs: Sequence[Tuple[float, float]]) -> Tuple[Tuple[float, ...], float]:
    route_times = tuple(sorted((float(time_s) for time_s, _ in metric_pairs), reverse=True))
    total_distance = sum(float(distance_m) for _, distance_m in metric_pairs)
    return route_times, total_distance


def _score_better(
    candidate: Tuple[Tuple[float, ...], float],
    incumbent: Optional[Tuple[Tuple[float, ...], float]],
) -> bool:
    if incumbent is None:
        return True
    vector_cmp = _compare_time_vectors(candidate[0], incumbent[0])
    if vector_cmp != 0:
        return vector_cmp < 0
    if _float_less(candidate[1], incumbent[1]):
        return True
    return False


def _state_score(state: Dict, robot_ids: Sequence[str]) -> Tuple[Tuple[float, ...], float]:
    return _score_from_metric_pairs(
        [
            (
                state[robot_id]["metrics"]["estimated_time_s"],
                state[robot_id]["metrics"]["distance_m"],
            )
            for robot_id in robot_ids
        ]
    )


def _final_solution_better(
    candidate_assigned_count: int,
    candidate_score: Tuple[Tuple[float, ...], float],
    incumbent_assigned_count: int,
    incumbent_score: Optional[Tuple[Tuple[float, ...], float]],
) -> bool:
    if candidate_assigned_count != incumbent_assigned_count:
        return candidate_assigned_count > incumbent_assigned_count
    return _score_better(candidate_score, incumbent_score)


def _route_sort_key(metrics: Dict, route: Sequence[str], position: int, candidate: str) -> Tuple:
    return (
        float(metrics["estimated_time_s"]),
        float(metrics["distance_m"]),
        len(route),
        position,
        candidate,
    )


def _best_insertion_for_candidate(
    robot_id: str,
    route: Sequence[str],
    candidate: str,
    budget_m: float,
    start_costs: Dict,
    home_costs: Dict,
    nav_pair_costs: Dict,
) -> Optional[Dict]:
    best = None
    for position in range(len(route) + 1):
        new_route = list(route[:position]) + [candidate] + list(route[position:])
        metrics = _route_metrics(robot_id, new_route, start_costs, home_costs, nav_pair_costs)
        if not metrics["reachable"] or _float_greater(metrics["distance_m"], budget_m):
            continue
        sort_key = _route_sort_key(metrics, new_route, position, candidate)
        if best is None or sort_key < best["sort_key"]:
            best = {
                "sort_key": sort_key,
                "route": new_route,
                "metrics": metrics,
                "position": position,
            }
    return best


def _two_opt_improve(
    robot_id: str,
    route: List[str],
    budget_m: float,
    start_costs: Dict,
    home_costs: Dict,
    nav_pair_costs: Dict,
) -> Tuple[List[str], Dict]:
    best_route = route[:]
    best_metrics = _route_metrics(robot_id, best_route, start_costs, home_costs, nav_pair_costs)
    if len(route) < 4 or not best_metrics["reachable"]:
        return best_route, best_metrics

    improved = True
    while improved:
        improved = False
        for left in range(len(best_route) - 2):
            for right in range(left + 2, len(best_route) + 1):
                candidate_route = best_route[:left] + list(reversed(best_route[left:right])) + best_route[right:]
                candidate_metrics = _route_metrics(robot_id, candidate_route, start_costs, home_costs, nav_pair_costs)
                if not candidate_metrics["reachable"] or _float_greater(candidate_metrics["distance_m"], budget_m):
                    continue
                if (
                    _float_less(candidate_metrics["estimated_time_s"], best_metrics["estimated_time_s"])
                    or (
                        not _float_greater(candidate_metrics["estimated_time_s"], best_metrics["estimated_time_s"])
                        and _float_less(candidate_metrics["distance_m"], best_metrics["distance_m"])
                    )
                ):
                    best_route = candidate_route
                    best_metrics = candidate_metrics
                    improved = True
                    break
            if improved:
                break
    return best_route, best_metrics


def _optimize_specific_routes(
    state: Dict,
    robot_ids: Iterable[str],
    start_costs: Dict,
    home_costs: Dict,
    nav_pair_costs: Dict,
) -> None:
    for robot_id in sorted(set(robot_ids)):
        route, metrics = _two_opt_improve(
            robot_id,
            list(state[robot_id]["route"]),
            state[robot_id]["budget_m"],
            start_costs,
            home_costs,
            nav_pair_costs,
        )
        state[robot_id]["route"] = route
        state[robot_id]["metrics"] = metrics


def _singleton_target_difficulty(
    target_nav_id: str,
    state: Dict,
    start_costs: Dict,
    home_costs: Dict,
    nav_pair_costs: Dict,
) -> Tuple[float, int]:
    best_time = math.inf
    feasible_robot_count = 0
    for robot_id, robot_state in state.items():
        metrics = _route_metrics(robot_id, [target_nav_id], start_costs, home_costs, nav_pair_costs)
        if not metrics["reachable"] or _float_greater(metrics["distance_m"], robot_state["budget_m"]):
            continue
        feasible_robot_count += 1
        best_time = min(best_time, float(metrics["estimated_time_s"]))
    return best_time, feasible_robot_count


def _option_sort_key(option: Dict) -> Tuple:
    time_vector, total_distance = option["score"]
    return time_vector + (
        total_distance,
        option["metrics"]["estimated_time_s"],
        option["metrics"]["distance_m"],
        option["robot_id"],
    )


def _evaluate_target_options(
    state: Dict,
    robot_ids: Sequence[str],
    target_nav_id: str,
    start_costs: Dict,
    home_costs: Dict,
    nav_pair_costs: Dict,
) -> List[Dict]:
    current_metric_pairs = {
        robot_id: (
            state[robot_id]["metrics"]["estimated_time_s"],
            state[robot_id]["metrics"]["distance_m"],
        )
        for robot_id in robot_ids
    }
    options: List[Dict] = []

    for robot_id in robot_ids:
        insertion = _best_insertion_for_candidate(
            robot_id,
            state[robot_id]["route"],
            target_nav_id,
            state[robot_id]["budget_m"],
            start_costs,
            home_costs,
            nav_pair_costs,
        )
        if insertion is None:
            continue

        metric_pairs_after = []
        for current_robot_id in robot_ids:
            if current_robot_id == robot_id:
                metric_pairs_after.append(
                    (
                        insertion["metrics"]["estimated_time_s"],
                        insertion["metrics"]["distance_m"],
                    )
                )
            else:
                metric_pairs_after.append(current_metric_pairs[current_robot_id])

        option = {
            "robot_id": robot_id,
            "route": insertion["route"],
            "metrics": insertion["metrics"],
            "score": _score_from_metric_pairs(metric_pairs_after),
            "added_time_s": insertion["metrics"]["estimated_time_s"] - state[robot_id]["metrics"]["estimated_time_s"],
            "added_distance_m": insertion["metrics"]["distance_m"] - state[robot_id]["metrics"]["distance_m"],
        }
        option["sort_key"] = _option_sort_key(option)
        options.append(option)

    options.sort(key=lambda item: item["sort_key"])
    return options


def _select_next_assignment(
    state: Dict,
    unassigned: Set[str],
    robot_ids: Sequence[str],
    difficulty_by_target: Dict[str, float],
    start_costs: Dict,
    home_costs: Dict,
    nav_pair_costs: Dict,
    mode: str,
) -> Optional[Dict]:
    best_choice = None
    for target_nav_id in sorted(unassigned):
        options = _evaluate_target_options(
            state,
            robot_ids,
            target_nav_id,
            start_costs,
            home_costs,
            nav_pair_costs,
        )
        if not options:
            continue

        best_option = options[0]
        second_option = options[1] if len(options) > 1 else None
        best_makespan = best_option["score"][0][0] if best_option["score"][0] else 0.0
        second_makespan = second_option["score"][0][0] if second_option and second_option["score"][0] else math.inf
        regret = second_makespan - best_makespan if second_option is not None else math.inf
        difficulty = difficulty_by_target[target_nav_id]

        if mode == "regret":
            choice_key = (
                len(options),
                -regret,
                -difficulty,
                best_option["sort_key"],
                target_nav_id,
            )
        elif mode == "constrained":
            choice_key = (
                len(options),
                -difficulty,
                best_option["sort_key"],
                target_nav_id,
            )
        else:
            choice_key = (
                best_option["sort_key"],
                len(options),
                -difficulty,
                target_nav_id,
            )

        if best_choice is None or choice_key < best_choice["choice_key"]:
            best_choice = {
                "choice_key": choice_key,
                "target_nav_id": target_nav_id,
                "option": best_option,
            }
    return best_choice


def _assign_remaining_targets(
    state: Dict,
    unassigned: Set[str],
    robot_ids: Sequence[str],
    difficulty_by_target: Dict[str, float],
    start_costs: Dict,
    home_costs: Dict,
    nav_pair_costs: Dict,
    mode: str,
) -> bool:
    progress = False
    while unassigned:
        choice = _select_next_assignment(
            state,
            unassigned,
            robot_ids,
            difficulty_by_target,
            start_costs,
            home_costs,
            nav_pair_costs,
            mode,
        )
        if choice is None:
            break
        option = choice["option"]
        robot_id = option["robot_id"]
        state[robot_id]["route"] = list(option["route"])
        state[robot_id]["metrics"] = option["metrics"]
        unassigned.remove(choice["target_nav_id"])
        progress = True
    return progress


def _repair_unassigned_by_relocation(
    state: Dict,
    unassigned: Set[str],
    robot_ids: Sequence[str],
    difficulty_by_target: Dict[str, float],
    start_costs: Dict,
    home_costs: Dict,
    nav_pair_costs: Dict,
) -> bool:
    improved = False
    while unassigned:
        best_move = None

        for target_nav_id in sorted(unassigned, key=lambda item: (-difficulty_by_target[item], item)):
            for source_robot_id in robot_ids:
                source_route = state[source_robot_id]["route"]
                for source_index, displaced_target in enumerate(source_route):
                    reduced_source_route = source_route[:source_index] + source_route[source_index + 1 :]
                    reduced_source_metrics = _route_metrics(
                        source_robot_id,
                        reduced_source_route,
                        start_costs,
                        home_costs,
                        nav_pair_costs,
                    )
                    if (
                        not reduced_source_metrics["reachable"]
                        or _float_greater(reduced_source_metrics["distance_m"], state[source_robot_id]["budget_m"])
                    ):
                        continue

                    target_insertion = _best_insertion_for_candidate(
                        source_robot_id,
                        reduced_source_route,
                        target_nav_id,
                        state[source_robot_id]["budget_m"],
                        start_costs,
                        home_costs,
                        nav_pair_costs,
                    )
                    if target_insertion is None:
                        continue

                    for target_robot_id in robot_ids:
                        if target_robot_id == source_robot_id:
                            continue
                        displaced_insertion = _best_insertion_for_candidate(
                            target_robot_id,
                            state[target_robot_id]["route"],
                            displaced_target,
                            state[target_robot_id]["budget_m"],
                            start_costs,
                            home_costs,
                            nav_pair_costs,
                        )
                        if displaced_insertion is None:
                            continue

                        metric_pairs_after = []
                        for robot_id in robot_ids:
                            if robot_id == source_robot_id:
                                metric_pairs_after.append(
                                    (
                                        target_insertion["metrics"]["estimated_time_s"],
                                        target_insertion["metrics"]["distance_m"],
                                    )
                                )
                            elif robot_id == target_robot_id:
                                metric_pairs_after.append(
                                    (
                                        displaced_insertion["metrics"]["estimated_time_s"],
                                        displaced_insertion["metrics"]["distance_m"],
                                    )
                                )
                            else:
                                metric_pairs_after.append(
                                    (
                                        state[robot_id]["metrics"]["estimated_time_s"],
                                        state[robot_id]["metrics"]["distance_m"],
                                    )
                                )

                        candidate_score = _score_from_metric_pairs(metric_pairs_after)
                        move_key = (
                            candidate_score[0],
                            candidate_score[1],
                            -difficulty_by_target[target_nav_id],
                            target_nav_id,
                            source_robot_id,
                            target_robot_id,
                            displaced_target,
                        )
                        if best_move is None or move_key < best_move["move_key"]:
                            best_move = {
                                "move_key": move_key,
                                "target_nav_id": target_nav_id,
                                "source_robot_id": source_robot_id,
                                "target_robot_id": target_robot_id,
                                "source_route": target_insertion["route"],
                                "target_route": displaced_insertion["route"],
                                "source_metrics": target_insertion["metrics"],
                                "target_metrics": displaced_insertion["metrics"],
                            }

        if best_move is None:
            break

        source_robot_id = best_move["source_robot_id"]
        target_robot_id = best_move["target_robot_id"]
        state[source_robot_id]["route"] = best_move["source_route"]
        state[source_robot_id]["metrics"] = best_move["source_metrics"]
        state[target_robot_id]["route"] = best_move["target_route"]
        state[target_robot_id]["metrics"] = best_move["target_metrics"]
        _optimize_specific_routes(
            state,
            [source_robot_id, target_robot_id],
            start_costs,
            home_costs,
            nav_pair_costs,
        )
        unassigned.remove(best_move["target_nav_id"])
        improved = True

    return improved


def _relocate_improve(
    state: Dict,
    robot_ids: Sequence[str],
    start_costs: Dict,
    home_costs: Dict,
    nav_pair_costs: Dict,
) -> bool:
    improved = False
    while True:
        current_score = _state_score(state, robot_ids)
        best_move = None
        best_score = current_score

        for source_robot_id in robot_ids:
            source_route = state[source_robot_id]["route"]
            for source_index, target_nav_id in enumerate(source_route):
                reduced_source_route = source_route[:source_index] + source_route[source_index + 1 :]
                reduced_source_metrics = _route_metrics(
                    source_robot_id,
                    reduced_source_route,
                    start_costs,
                    home_costs,
                    nav_pair_costs,
                )
                if (
                    not reduced_source_metrics["reachable"]
                    or _float_greater(reduced_source_metrics["distance_m"], state[source_robot_id]["budget_m"])
                ):
                    continue

                for target_robot_id in robot_ids:
                    if target_robot_id == source_robot_id:
                        continue

                    insertion = _best_insertion_for_candidate(
                        target_robot_id,
                        state[target_robot_id]["route"],
                        target_nav_id,
                        state[target_robot_id]["budget_m"],
                        start_costs,
                        home_costs,
                        nav_pair_costs,
                    )
                    if insertion is None:
                        continue

                    candidate_score = _score_from_metric_pairs(
                        [
                            (
                                reduced_source_metrics["estimated_time_s"],
                                reduced_source_metrics["distance_m"],
                            )
                            if robot_id == source_robot_id
                            else (
                                insertion["metrics"]["estimated_time_s"],
                                insertion["metrics"]["distance_m"],
                            )
                            if robot_id == target_robot_id
                            else (
                                state[robot_id]["metrics"]["estimated_time_s"],
                                state[robot_id]["metrics"]["distance_m"],
                            )
                            for robot_id in robot_ids
                        ]
                    )
                    if not _score_better(candidate_score, best_score):
                        continue

                    best_score = candidate_score
                    best_move = {
                        "source_robot_id": source_robot_id,
                        "target_robot_id": target_robot_id,
                        "source_route": reduced_source_route,
                        "target_route": insertion["route"],
                        "source_metrics": reduced_source_metrics,
                        "target_metrics": insertion["metrics"],
                    }

        if best_move is None:
            break

        source_robot_id = best_move["source_robot_id"]
        target_robot_id = best_move["target_robot_id"]
        state[source_robot_id]["route"] = best_move["source_route"]
        state[source_robot_id]["metrics"] = best_move["source_metrics"]
        state[target_robot_id]["route"] = best_move["target_route"]
        state[target_robot_id]["metrics"] = best_move["target_metrics"]
        _optimize_specific_routes(
            state,
            [source_robot_id, target_robot_id],
            start_costs,
            home_costs,
            nav_pair_costs,
        )
        improved = True

    return improved


def _swap_improve(
    state: Dict,
    robot_ids: Sequence[str],
    start_costs: Dict,
    home_costs: Dict,
    nav_pair_costs: Dict,
) -> bool:
    improved = False
    while True:
        current_score = _state_score(state, robot_ids)
        best_move = None
        best_score = current_score

        for left_index, left_robot_id in enumerate(robot_ids):
            left_route = state[left_robot_id]["route"]
            if not left_route:
                continue
            for right_robot_id in robot_ids[left_index + 1 :]:
                right_route = state[right_robot_id]["route"]
                if not right_route:
                    continue

                for left_task_index, left_target in enumerate(left_route):
                    reduced_left_route = left_route[:left_task_index] + left_route[left_task_index + 1 :]
                    for right_task_index, right_target in enumerate(right_route):
                        reduced_right_route = right_route[:right_task_index] + right_route[right_task_index + 1 :]

                        left_insertion = _best_insertion_for_candidate(
                            left_robot_id,
                            reduced_left_route,
                            right_target,
                            state[left_robot_id]["budget_m"],
                            start_costs,
                            home_costs,
                            nav_pair_costs,
                        )
                        if left_insertion is None:
                            continue

                        right_insertion = _best_insertion_for_candidate(
                            right_robot_id,
                            reduced_right_route,
                            left_target,
                            state[right_robot_id]["budget_m"],
                            start_costs,
                            home_costs,
                            nav_pair_costs,
                        )
                        if right_insertion is None:
                            continue

                        candidate_score = _score_from_metric_pairs(
                            [
                                (
                                    left_insertion["metrics"]["estimated_time_s"],
                                    left_insertion["metrics"]["distance_m"],
                                )
                                if robot_id == left_robot_id
                                else (
                                    right_insertion["metrics"]["estimated_time_s"],
                                    right_insertion["metrics"]["distance_m"],
                                )
                                if robot_id == right_robot_id
                                else (
                                    state[robot_id]["metrics"]["estimated_time_s"],
                                    state[robot_id]["metrics"]["distance_m"],
                                )
                                for robot_id in robot_ids
                            ]
                        )
                        if not _score_better(candidate_score, best_score):
                            continue

                        best_score = candidate_score
                        best_move = {
                            "left_robot_id": left_robot_id,
                            "right_robot_id": right_robot_id,
                            "left_route": left_insertion["route"],
                            "right_route": right_insertion["route"],
                            "left_metrics": left_insertion["metrics"],
                            "right_metrics": right_insertion["metrics"],
                        }

        if best_move is None:
            break

        left_robot_id = best_move["left_robot_id"]
        right_robot_id = best_move["right_robot_id"]
        state[left_robot_id]["route"] = best_move["left_route"]
        state[left_robot_id]["metrics"] = best_move["left_metrics"]
        state[right_robot_id]["route"] = best_move["right_route"]
        state[right_robot_id]["metrics"] = best_move["right_metrics"]
        _optimize_specific_routes(
            state,
            [left_robot_id, right_robot_id],
            start_costs,
            home_costs,
            nav_pair_costs,
        )
        improved = True

    return improved


def _run_heuristic_search(
    planner_problem: Dict,
    start_costs: Dict,
    home_costs: Dict,
    nav_pair_costs: Dict,
    target_nav_ids: Sequence[str],
    mode: str,
    robot_ids: Sequence[str],
) -> Tuple[Dict, Set[str]]:
    state = _build_state(planner_problem)
    unassigned = set(target_nav_ids)

    difficulty_by_target = {}
    for target_nav_id in target_nav_ids:
        difficulty, _ = _singleton_target_difficulty(
            target_nav_id,
            state,
            start_costs,
            home_costs,
            nav_pair_costs,
        )
        difficulty_by_target[target_nav_id] = difficulty

    _assign_remaining_targets(
        state,
        unassigned,
        robot_ids,
        difficulty_by_target,
        start_costs,
        home_costs,
        nav_pair_costs,
        mode,
    )
    _optimize_specific_routes(state, robot_ids, start_costs, home_costs, nav_pair_costs)
    _assign_remaining_targets(
        state,
        unassigned,
        robot_ids,
        difficulty_by_target,
        start_costs,
        home_costs,
        nav_pair_costs,
        mode,
    )
    _optimize_specific_routes(state, robot_ids, start_costs, home_costs, nav_pair_costs)

    for _ in range(MAX_IMPROVEMENT_PASSES):
        progress = False

        if _repair_unassigned_by_relocation(
            state,
            unassigned,
            robot_ids,
            difficulty_by_target,
            start_costs,
            home_costs,
            nav_pair_costs,
        ):
            progress = True

        if _assign_remaining_targets(
            state,
            unassigned,
            robot_ids,
            difficulty_by_target,
            start_costs,
            home_costs,
            nav_pair_costs,
            mode,
        ):
            progress = True

        if _relocate_improve(state, robot_ids, start_costs, home_costs, nav_pair_costs):
            progress = True

        if _swap_improve(state, robot_ids, start_costs, home_costs, nav_pair_costs):
            progress = True

        if progress:
            _optimize_specific_routes(state, robot_ids, start_costs, home_costs, nav_pair_costs)
        else:
            break

    return state, unassigned


def _build_plan_result_payload(
    planner_problem: Dict,
    best_state: Dict,
    best_unassigned: Set[str],
    best_score: Tuple[Tuple[float, ...], float],
    unique_target_ids: Sequence[str],
    default_robot_ids: Sequence[str],
    mission_context: Dict,
) -> Dict:
    robots_output = []
    for robot_id in default_robot_ids:
        robot = best_state[robot_id]["robot"]
        metrics = best_state[robot_id]["metrics"]
        robots_output.append(
            {
                "planning_slot_id": robot_id,
                "hardware_id": robot["hardware_id"],
                "route_nav_point_ids": list(best_state[robot_id]["route"]),
                "total_distance_with_home_m": round(metrics["distance_m"], 3),
                "estimated_time_with_home_s": round(metrics["estimated_time_s"], 3),
                "effective_range_budget_m": best_state[robot_id]["budget_m"],
                "feasible_with_budget": metrics["distance_m"] <= best_state[robot_id]["budget_m"] + EPSILON,
                "legs": metrics["legs"],
            }
        )

    assigned_count = len(unique_target_ids) - len(best_unassigned)
    balanced_route_times = [round(value, 3) for value in best_score[0]]
    active_robot_count = sum(1 for robot in robots_output if robot["route_nav_point_ids"])

    return {
        "schema_version": "1.0.0",
        "planner_name": "heuristic_makespan_planner",
        "planner_note": (
            "Heuristic multi-robot planner for full mission coverage: uses constrained target insertion, route repair, "
            "2-opt refinement, and inter-robot relocate/swap search to minimize the overall mission completion time, "
            "then improve total travel distance under explicit range budgets."
        ),
        "mission_mode": mission_context.get("mission_mode", "unspecified"),
        "mission_label": mission_context.get("mission_label", ""),
        "mission_template_id": mission_context.get("mission_template_id"),
        "natural_language": mission_context.get("natural_language", ""),
        "target_set_ids": list(mission_context.get("target_set_ids", [])),
        "target_nav_point_ids": list(unique_target_ids),
        "robots": robots_output,
        "unassigned_nav_point_ids": sorted(best_unassigned),
        "summary": {
            "target_count": len(unique_target_ids),
            "assigned_count": assigned_count,
            "unassigned_count": len(best_unassigned),
            "full_coverage_achieved": len(best_unassigned) == 0,
            "robot_count": len(robots_output),
            "active_robot_count": active_robot_count,
            "max_route_time_s": round(best_score[0][0] if best_score[0] else 0.0, 3),
            "balanced_route_times_desc_s": balanced_route_times,
            "total_estimated_time_s": round(sum(robot["estimated_time_with_home_s"] for robot in robots_output), 3),
            "total_distance_m": round(sum(robot["total_distance_with_home_m"] for robot in robots_output), 3),
        },
        "request_context": mission_context,
    }


def _plan_multi_robot_routes_python(
    planner_problem: Dict,
    robot_to_nav_costs: Dict,
    nav_to_nav_costs: Dict,
    target_nav_ids: Iterable[str],
    mission_context: Optional[Dict] = None,
) -> Dict:
    mission_context = mission_context or {}
    unique_target_ids = sorted(set(target_nav_ids))

    start_costs = robot_to_nav_costs["start_to_nav_costs"]
    home_costs = robot_to_nav_costs["nav_to_home_costs"]
    pair_costs = nav_to_nav_costs["pairs"]
    default_robot_ids = sorted(robot["planning_slot_id"] for robot in planner_problem["robots"])

    best_state = None
    best_unassigned = None
    best_assigned_count = -1
    best_score = None

    robot_order_variants = [default_robot_ids, list(reversed(default_robot_ids))]
    for mode in CONSTRUCTION_MODES:
        for robot_ids in robot_order_variants:
            candidate_state, candidate_unassigned = _run_heuristic_search(
                planner_problem=planner_problem,
                start_costs=start_costs,
                home_costs=home_costs,
                nav_pair_costs=pair_costs,
                target_nav_ids=unique_target_ids,
                mode=mode,
                robot_ids=robot_ids,
            )
            candidate_assigned_count = len(unique_target_ids) - len(candidate_unassigned)
            candidate_score = _state_score(candidate_state, default_robot_ids)
            if _final_solution_better(
                candidate_assigned_count,
                candidate_score,
                best_assigned_count,
                best_score,
            ):
                best_state = candidate_state
                best_unassigned = candidate_unassigned
                best_assigned_count = candidate_assigned_count
                best_score = candidate_score

    if best_state is None or best_unassigned is None or best_score is None:
        best_state = _build_state(planner_problem)
        best_unassigned = set(unique_target_ids)
        best_score = _state_score(best_state, default_robot_ids)

    return _build_plan_result_payload(
        planner_problem=planner_problem,
        best_state=best_state,
        best_unassigned=best_unassigned,
        best_score=best_score,
        unique_target_ids=unique_target_ids,
        default_robot_ids=default_robot_ids,
        mission_context=mission_context,
    )


def _try_native_plan_result(
    planner_problem: Dict,
    start_costs: Dict,
    home_costs: Dict,
    pair_costs: Dict,
    unique_target_ids: Sequence[str],
    default_robot_ids: Sequence[str],
) -> Optional[Tuple[Dict, Set[str], Tuple[Tuple[float, ...], float]]]:
    native_solution = solve_multi_robot_routes_native(
        planner_problem=planner_problem,
        start_costs=start_costs,
        home_costs=home_costs,
        pair_costs=pair_costs,
        target_nav_ids=unique_target_ids,
        max_improvement_passes=MAX_IMPROVEMENT_PASSES,
    )
    if native_solution is None:
        return None

    state = _build_state(planner_problem)
    assigned_targets: Set[str] = set()

    for robot_id in default_robot_ids:
        route = list(native_solution["routes_by_robot"].get(robot_id, []))
        if len(route) != len(set(route)):
            return None
        if assigned_targets.intersection(route):
            return None

        metrics = _route_metrics(robot_id, route, start_costs, home_costs, pair_costs)
        if not metrics["reachable"] or _float_greater(metrics["distance_m"], state[robot_id]["budget_m"]):
            return None

        state[robot_id]["route"] = route
        state[robot_id]["metrics"] = metrics
        assigned_targets.update(route)

    unassigned_targets = set(native_solution.get("unassigned_nav_point_ids", []))
    expected_targets = set(unique_target_ids)
    if assigned_targets.intersection(unassigned_targets):
        return None
    if assigned_targets.union(unassigned_targets) != expected_targets:
        return None

    return state, unassigned_targets, _state_score(state, default_robot_ids)


def plan_multi_robot_routes(
    planner_problem: Dict,
    robot_to_nav_costs: Dict,
    nav_to_nav_costs: Dict,
    target_nav_ids: Iterable[str],
    mission_context: Optional[Dict] = None,
) -> Dict:
    mission_context = mission_context or {}
    unique_target_ids = sorted(set(target_nav_ids))
    start_costs = robot_to_nav_costs["start_to_nav_costs"]
    home_costs = robot_to_nav_costs["nav_to_home_costs"]
    pair_costs = nav_to_nav_costs["pairs"]
    default_robot_ids = sorted(robot["planning_slot_id"] for robot in planner_problem["robots"])

    native_result = _try_native_plan_result(
        planner_problem=planner_problem,
        start_costs=start_costs,
        home_costs=home_costs,
        pair_costs=pair_costs,
        unique_target_ids=unique_target_ids,
        default_robot_ids=default_robot_ids,
    )
    if native_result is not None:
        best_state, best_unassigned, best_score = native_result
        return _build_plan_result_payload(
            planner_problem=planner_problem,
            best_state=best_state,
            best_unassigned=best_unassigned,
            best_score=best_score,
            unique_target_ids=unique_target_ids,
            default_robot_ids=default_robot_ids,
            mission_context=mission_context,
        )

    return _plan_multi_robot_routes_python(
        planner_problem=planner_problem,
        robot_to_nav_costs=robot_to_nav_costs,
        nav_to_nav_costs=nav_to_nav_costs,
        target_nav_ids=unique_target_ids,
        mission_context=mission_context,
    )


def plan_from_template_id(
    template_id: str,
    planner_problem: Dict,
    robot_to_nav_costs: Dict,
    nav_to_nav_costs: Dict,
    mission_templates: Dict,
    target_sets: Dict,
) -> Dict:
    template, target_nav_ids = _resolve_targets_from_template(template_id, mission_templates, target_sets)
    return plan_multi_robot_routes(
        planner_problem=planner_problem,
        robot_to_nav_costs=robot_to_nav_costs,
        nav_to_nav_costs=nav_to_nav_costs,
        target_nav_ids=target_nav_ids,
        mission_context={
            "mission_mode": "template",
            "mission_label": template["template_id"],
            "mission_template_id": template["template_id"],
            "natural_language": template["natural_language"],
            "target_set_ids": template["target_set_ids"],
        },
    )
