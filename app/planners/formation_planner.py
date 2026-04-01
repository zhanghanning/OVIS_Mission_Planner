from typing import Dict, List


def build_formation_plan(robots: List[Dict], constraints: Dict) -> Dict:
    if not constraints.get("formation_required"):
        return {
            "formation_required": False,
            "formation_type": None,
            "leader_robot_id": None,
            "members": [],
            "spacing_m": None,
        }

    if not robots:
        return {
            "formation_required": True,
            "formation_type": constraints.get("formation_type", "line"),
            "leader_robot_id": None,
            "members": [],
            "spacing_m": constraints.get("spacing_m", 2.0),
        }

    leader = robots[0]["robot_id"]
    members = []
    spacing = float(constraints.get("spacing_m", 2.0))
    for index, robot in enumerate(robots):
        members.append(
            {
                "robot_id": robot["robot_id"],
                "role": "leader" if index == 0 else "wing",
                "offset": {"x": 0.0 if index == 0 else index * spacing, "y": 0.0},
            }
        )

    return {
        "formation_required": True,
        "formation_type": constraints.get("formation_type", "line"),
        "leader_robot_id": leader,
        "members": members,
        "spacing_m": spacing,
    }
