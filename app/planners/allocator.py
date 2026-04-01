from typing import Dict, List


def _squared_distance(a: Dict, b: Dict) -> float:
    dx = float(a["x"]) - float(b["x"])
    dy = float(a["y"]) - float(b["y"])
    return dx * dx + dy * dy


def greedy_allocate(robots: List[Dict], goals: List[Dict]) -> Dict:
    remaining = goals[:]
    assignments = []

    for robot in robots:
        current = robot["start"]
        task_sequence = []

        while remaining:
            remaining.sort(key=lambda goal: _squared_distance(current, goal["position"]))
            nearest_goal = remaining.pop(0)
            task_sequence.append(nearest_goal["goal_id"])
            current = nearest_goal["position"]

            # Minimal version: one robot takes one nearest goal at a time,
            # then move to the next robot so tasks distribute naturally.
            break

        assignments.append(
            {
                "robot_id": robot["robot_id"],
                "task_sequence": task_sequence,
            }
        )

    while remaining and assignments:
        for assignment in assignments:
            if not remaining:
                break
            assignment["task_sequence"].append(remaining.pop(0)["goal_id"])

    return {"assignments": assignments}
