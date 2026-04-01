from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, HttpUrl


class PlannerJobCreate(BaseModel):
    mission_id: str
    package_url: HttpUrl
    callback_url: Optional[HttpUrl] = None
    planner_type: str = "multi_robot_global"
    package_sha256: Optional[str] = None
    auth_token: Optional[str] = None


class PlannerJobStatus(BaseModel):
    planner_job_id: str
    mission_id: str
    status: str
    progress: int = 0
    message: str = ""
    result_url: Optional[str] = None


class PlannerCallbackPayload(BaseModel):
    planner_job_id: str
    mission_id: str
    status: str
    result_url: Optional[str] = None
    message: str = ""


class GoalSequence(BaseModel):
    robot_id: str
    task_sequence: List[str]


class Waypoint(BaseModel):
    x: float
    y: float
    z: float = 0.0
    yaw: Optional[float] = None


class PathResult(BaseModel):
    robot_id: str
    path_type: str
    goal_id: Optional[str] = None
    estimated_length_m: float = 0.0
    estimated_duration_s: float = 0.0
    waypoints: List[Waypoint] = Field(default_factory=list)


JsonDict = Dict[str, Any]


class ManualPlanCreate(BaseModel):
    nav_point_ids: List[str]
    mission_label: Optional[str] = None
    notes: Optional[str] = None
    scene: Optional[str] = None


class PolygonVertex(BaseModel):
    x: Optional[float] = None
    z: Optional[float] = None
    lat: Optional[float] = None
    lon: Optional[float] = None


class PolygonPlanCreate(BaseModel):
    vertices: List[PolygonVertex]
    coordinate_mode: str = "local"
    mission_label: Optional[str] = None
    scene: Optional[str] = None


class SemanticPlanCreate(BaseModel):
    query: str
    use_llm: bool = True
    scene: Optional[str] = None


class RuntimeRobotConfigEntry(BaseModel):
    anchor_nav_point_id: Optional[str] = None


class RuntimeRobotConfigUpdate(BaseModel):
    robot_count: int = Field(ge=1, le=32)
    robots: List[RuntimeRobotConfigEntry] = Field(default_factory=list)
    scene: Optional[str] = None
