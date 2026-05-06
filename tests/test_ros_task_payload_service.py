from __future__ import annotations

import json
from pathlib import Path

from app.services.interactive_plan_service import create_manual_plan
from app.services.ros_task_payload_service import build_ros_task_payloads


def test_build_ros_task_payloads_from_saved_plan_result():
    plan_path = Path(__file__).resolve().parents[1] / "data" / "outputs" / "interactive_plan_1859b62319" / "plan_result.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))

    payloads = build_ros_task_payloads(plan, scene_name=plan["scene_name"])

    assert payloads
    first = payloads[0]
    assert first["schema_version"] == "1.2.0"
    assert first["task_type"] == "mission_planner_route"
    assert first["coordinate_system"]["geo"]["type"] == "WGS84"
    assert first["coordinate_system"]["geo"]["alt_unit"] == "m"
    assert first["coordinate_system"]["local"]["projection_origin"]["lat"]
    assert first["coordinate_system"]["local"]["y_axis"] == "up"
    assert first["coordinate_system"]["ros_map"]["z_from"] == "local.y"
    assert first["route"]["points"]

    route_points = first["route"]["points"]
    assert [point["seq"] for point in route_points] == list(range(len(route_points)))
    assert route_points[0]["kind"] == "start"
    assert route_points[-1]["kind"] == "home"
    assert any(point["kind"] in {"calibration", "inspection"} and point["required"] for point in route_points)

    for point in route_points:
        assert "local" in point
        assert "map" in point
        assert point["map"]["x"] == point["local"]["x"]
        assert point["map"]["y"] == point["local"]["z"]
        assert point["map"]["z"] == point["local"]["y"]
        assert "geo" in point
        assert "alt" in point["geo"]

    task_params_json = json.dumps(first, ensure_ascii=False, separators=(",", ":"))
    dispatch_payload = json.loads(task_params_json)
    assert dispatch_payload["task_id"] == first["task_id"]
    assert dispatch_payload["route"]["points"][0]["map"]["frame_id"] == "map"
    assert "uran_dispatch" not in dispatch_payload
    assert "backend_dispatch" not in dispatch_payload


def test_interactive_plan_result_contains_only_non_empty_ros_task_payloads():
    result = create_manual_plan(["NP_015"], scene_name="NCEPU", mission_label="ros payload test")

    payloads = result["ros_task_payloads"]
    assert payloads
    assert all(payload["route"]["points"] for payload in payloads)

    assigned_robot_ids = {
        robot["hardware_id"]
        for robot in result["robots"]
        if robot.get("route_nav_point_ids")
    }
    payload_robot_ids = {
        payload["robot"]["hardware_id"]
        for payload in payloads
    }
    assert payload_robot_ids == assigned_robot_ids
    assert "backend_dispatch" not in result
