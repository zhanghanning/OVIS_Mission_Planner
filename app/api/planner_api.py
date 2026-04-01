from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse

from app.core.config import get_settings
from app.models.schemas import PlannerJobCreate
from app.services.job_service import create_job_record, get_job_status, run_job


router = APIRouter(prefix="/api/planner", tags=["planner"])
settings = get_settings()


@router.post("/jobs")
def create_job(payload: PlannerJobCreate, background_tasks: BackgroundTasks):
    body = payload.model_dump()
    job_id = create_job_record(body)
    background_tasks.add_task(run_job, job_id, body)
    return {
        "planner_job_id": job_id,
        "mission_id": payload.mission_id,
        "status": "accepted",
    }


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    try:
        return get_job_status(job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc


@router.get("/jobs/{job_id}/result")
def download_result(job_id: str):
    zip_path = settings.result_dir / job_id / "planner_result.zip"
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail="result not found")
    return FileResponse(zip_path, filename="planner_result.zip")
