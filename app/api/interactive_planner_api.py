from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.models.schemas import (
    ManualPlanCreate,
    PolygonPlanCreate,
    SemanticPlanCreate,
)
from app.services.interactive_plan_service import (
    create_manual_plan,
    create_polygon_plan,
    create_semantic_plan,
    get_console_payload,
)
from app.services.semantic_llm_service import semantic_llm_provider_status


router = APIRouter(prefix="/api/planner/interactive", tags=["planner-interactive"])

CONSOLE_HTML_PATH = Path(__file__).resolve().parent.parent / "static" / "planning_console.html"


@router.get("/assets")
def interactive_assets(scene: str | None = None):
    try:
        return get_console_payload(scene)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="scene not found") from exc


@router.get("/semantic/provider-status")
def interactive_semantic_provider_status():
    return semantic_llm_provider_status()


@router.get("/console")
def interactive_console():
    return FileResponse(CONSOLE_HTML_PATH, media_type="text/html")


@router.post("/plans/manual")
def create_manual_interactive_plan(payload: ManualPlanCreate):
    try:
        return create_manual_plan(
            nav_point_ids=payload.nav_point_ids,
            robot_config=payload.robot_config.model_dump(exclude_none=True),
            mission_label=payload.mission_label or "",
            notes=payload.notes or "",
            scene_name=payload.scene,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/plans/polygon")
def create_polygon_interactive_plan(payload: PolygonPlanCreate):
    try:
        vertices = [vertex.model_dump(exclude_none=True) for vertex in payload.vertices]
        return create_polygon_plan(
            vertices=vertices,
            robot_config=payload.robot_config.model_dump(exclude_none=True),
            coordinate_mode=payload.coordinate_mode,
            mission_label=payload.mission_label or "",
            scene_name=payload.scene,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/plans/semantic")
def create_semantic_interactive_plan(payload: SemanticPlanCreate):
    try:
        return create_semantic_plan(
            query=payload.query,
            robot_config=payload.robot_config.model_dump(exclude_none=True),
            use_llm=payload.use_llm,
            scene_name=payload.scene,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
