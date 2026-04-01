from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.interactive_planner_api import router as interactive_planner_router
from app.api.planner_api import router as planner_router
from app.core.config import get_settings
from app.core.logging import configure_logging


configure_logging()
settings = get_settings()

app = FastAPI(title="Mission Planner", version="1.0.0")

if settings.cors_allow_origins or settings.cors_allow_origin_regex:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_origin_regex=settings.cors_allow_origin_regex or None,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(planner_router)
app.include_router(interactive_planner_router)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "deployment_mode": "backend_service",
        "frontend_mode": "separate_vite_vue3",
        "cors_allow_origins": settings.cors_allow_origins,
        "cors_allow_origin_regex": settings.cors_allow_origin_regex,
    }
