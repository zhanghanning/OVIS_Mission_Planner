from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

from app.models.schemas import ManualPlanCreate, PolygonPlanCreate, SemanticPlanCreate
from app.services.interactive_plan_service import (
    create_manual_plan,
    create_polygon_plan,
    create_semantic_plan,
    get_console_payload,
    get_plan,
)
from app.services.semantic_llm_service import semantic_llm_provider_status


router = APIRouter(prefix="/api/planner/interactive", tags=["planner-interactive"])

CONSOLE_HTML_PATH = Path(__file__).resolve().parent.parent / "static" / "planning_console.html"


@router.get("/assets")
def interactive_assets():
    return get_console_payload()


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
            mission_label=payload.mission_label or "",
            notes=payload.notes or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/plans/polygon")
def create_polygon_interactive_plan(payload: PolygonPlanCreate):
    try:
        vertices = [vertex.model_dump(exclude_none=True) for vertex in payload.vertices]
        return create_polygon_plan(
            vertices=vertices,
            coordinate_mode=payload.coordinate_mode,
            mission_label=payload.mission_label or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/plans/semantic")
def create_semantic_interactive_plan(payload: SemanticPlanCreate):
    try:
        return create_semantic_plan(query=payload.query, use_llm=payload.use_llm)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/plans/{plan_id}")
def get_interactive_plan(plan_id: str):
    try:
        return get_plan(plan_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="interactive plan not found") from exc


@router.get("/plans/{plan_id}/viewer")
def get_interactive_plan_viewer(plan_id: str):
    return RedirectResponse(url=f"/api/planner/interactive/console?plan_id={plan_id}", status_code=307)
