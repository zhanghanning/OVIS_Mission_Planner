from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from app.planners.formal_multi_robot import _plan_multi_robot_routes_python, plan_multi_robot_routes
from app.planners.native_formal_multi_robot import (
    native_planner_available,
    reset_native_planner_cache,
    solve_multi_robot_routes_native,
)
from app.services.local_asset_service import load_nav_to_nav_costs, nav_point_index, resolve_scene_name
from app.services.runtime_robot_service import build_runtime_planner_problem, build_runtime_robot_to_nav_costs


class FormalMultiRobotNativeParityTest(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        project_root = Path(__file__).resolve().parents[1]
        build_script = project_root / "scripts" / "build_planner_native.sh"

        try:
            subprocess.run([str(build_script)], check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise unittest.SkipTest(f"native build tool unavailable: {exc}") from exc
        except subprocess.CalledProcessError as exc:
            raise unittest.SkipTest(f"native planner build failed: {exc.stderr or exc.stdout}") from exc

        reset_native_planner_cache()
        if not native_planner_available():
            raise unittest.SkipTest("native planner library is not available after build")

        cls.scene_name = resolve_scene_name("NCEPU")
        cls.robot_config = {
            "robot_count": 3,
            "robots": [
                {"anchor_nav_point_id": "NP_001"},
                {"anchor_nav_point_id": "NP_049"},
                {"anchor_nav_point_id": "NP_058"},
            ],
        }
        cls.planner_problem = build_runtime_planner_problem(cls.robot_config, cls.scene_name)
        cls.robot_to_nav_costs = build_runtime_robot_to_nav_costs(
            cls.robot_config,
            cls.scene_name,
            planner_problem=cls.planner_problem,
        )
        cls.nav_to_nav_costs = load_nav_to_nav_costs(cls.scene_name)
        cls.target_nav_ids = sorted(nav_point_index(cls.scene_name).keys())[:12]
        if not cls.target_nav_ids:
            raise unittest.SkipTest("scene contains no nav points to validate")

    def test_native_kernel_returns_complete_partition(self) -> None:
        native_solution = solve_multi_robot_routes_native(
            planner_problem=self.planner_problem,
            start_costs=self.robot_to_nav_costs["start_to_nav_costs"],
            home_costs=self.robot_to_nav_costs["nav_to_home_costs"],
            pair_costs=self.nav_to_nav_costs["pairs"],
            target_nav_ids=self.target_nav_ids,
            max_improvement_passes=8,
        )
        self.assertIsNotNone(native_solution)

        assigned = set()
        for route in native_solution["routes_by_robot"].values():
            assigned.update(route)
        unassigned = set(native_solution["unassigned_nav_point_ids"])

        self.assertFalse(assigned.intersection(unassigned))
        self.assertEqual(assigned.union(unassigned), set(self.target_nav_ids))

    def test_public_planner_matches_python_fallback(self) -> None:
        mission_context = {
            "mission_mode": "native_parity_test",
            "mission_label": "native_parity_test",
        }

        python_result = _plan_multi_robot_routes_python(
            planner_problem=self.planner_problem,
            robot_to_nav_costs=self.robot_to_nav_costs,
            nav_to_nav_costs=self.nav_to_nav_costs,
            target_nav_ids=self.target_nav_ids,
            mission_context=mission_context,
        )
        public_result = plan_multi_robot_routes(
            planner_problem=self.planner_problem,
            robot_to_nav_costs=self.robot_to_nav_costs,
            nav_to_nav_costs=self.nav_to_nav_costs,
            target_nav_ids=self.target_nav_ids,
            mission_context=mission_context,
        )

        self.assertEqual(public_result, python_result)


if __name__ == "__main__":
    unittest.main()
