from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class Settings:
    project_root: Path
    base_dir: Path
    job_dir: Path
    package_dir: Path
    result_dir: Path
    local_plan_dir: Path
    asset_root_dir: Path
    public_base_url: str
    cors_allow_origins: list[str]
    cors_allow_origin_regex: str
    cors_allow_credentials: bool
    semantic_llm_enabled: bool
    semantic_llm_provider: str
    semantic_llm_base_url: str
    semantic_llm_api_key: str
    semantic_llm_model: str
    semantic_llm_timeout_sec: int
    semantic_llm_local_model_path: Optional[Path]
    semantic_llm_local_adapter_path: Optional[Path]
    semantic_llm_local_device: str
    semantic_llm_local_dtype: str
    semantic_llm_local_load_in_4bit: bool
    semantic_llm_local_bnb_compute_dtype: str
    semantic_llm_local_max_new_tokens: int
    semantic_llm_local_trust_remote_code: bool


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_path(raw_value: Optional[str], default_value: Path, anchor_dir: Path) -> Path:
    if not raw_value:
        return default_value
    path = Path(raw_value).expanduser()
    if path.is_absolute():
        return path
    return (anchor_dir / path).resolve()


def _resolve_optional_path(raw_value: Optional[str], anchor_dir: Path) -> Optional[Path]:
    if not raw_value:
        return None
    path = Path(raw_value).expanduser()
    if path.is_absolute():
        return path
    return (anchor_dir / path).resolve()


def _parse_csv_list(raw_value: Optional[str]) -> list[str]:
    if not raw_value:
        return []
    return [item.strip() for item in raw_value.split(',') if item.strip()]


def get_settings() -> Settings:
    project_root = _project_root()
    base_dir = _resolve_path(os.getenv('MISSION_PLANNER_BASE_DIR'), project_root, project_root)
    job_dir = _resolve_path(os.getenv('JOB_DIR'), base_dir / 'data' / 'jobs', base_dir)
    package_dir = _resolve_path(os.getenv('PACKAGE_DIR'), base_dir / 'data' / 'packages', base_dir)
    result_dir = _resolve_path(os.getenv('RESULT_DIR'), base_dir / 'data' / 'results', base_dir)
    local_plan_dir = _resolve_path(os.getenv('LOCAL_PLAN_DIR'), base_dir / 'data' / 'local_plans', base_dir)
    asset_root_dir = _resolve_path(
        os.getenv('MISSION_ASSET_ROOT_DIR'),
        base_dir / 'data' / 'assets' / 'ncepu',
        base_dir,
    )
    public_base_url = os.getenv('PUBLIC_BASE_URL', 'http://127.0.0.1:8081').rstrip('/')
    cors_allow_origins = _parse_csv_list(os.getenv('BACKEND_CORS_ALLOW_ORIGINS', ''))
    cors_allow_origin_regex = os.getenv('BACKEND_CORS_ALLOW_ORIGIN_REGEX', '').strip()
    cors_allow_credentials = os.getenv('BACKEND_CORS_ALLOW_CREDENTIALS', 'false').lower() in {'1', 'true', 'yes', 'on'}
    semantic_llm_enabled = os.getenv('SEMANTIC_LLM_ENABLED', 'false').lower() in {'1', 'true', 'yes', 'on'}
    semantic_llm_provider = os.getenv('SEMANTIC_LLM_PROVIDER', '').strip().lower()
    if not semantic_llm_provider:
        if os.getenv('SEMANTIC_LLM_LOCAL_MODEL_PATH'):
            semantic_llm_provider = 'local_transformers'
        elif os.getenv('SEMANTIC_LLM_BASE_URL'):
            semantic_llm_provider = 'openai_compatible'
        else:
            semantic_llm_provider = 'disabled'
    semantic_llm_base_url = os.getenv('SEMANTIC_LLM_BASE_URL', '').rstrip('/')
    semantic_llm_api_key = os.getenv('SEMANTIC_LLM_API_KEY', '')
    semantic_llm_model = os.getenv('SEMANTIC_LLM_MODEL', '')
    semantic_llm_timeout_sec = int(os.getenv('SEMANTIC_LLM_TIMEOUT_SEC', '30'))
    semantic_llm_local_model_path = _resolve_optional_path(
        os.getenv('SEMANTIC_LLM_LOCAL_MODEL_PATH'),
        base_dir,
    )
    semantic_llm_local_adapter_path = _resolve_optional_path(
        os.getenv('SEMANTIC_LLM_LOCAL_ADAPTER_PATH'),
        base_dir,
    )
    semantic_llm_local_device = os.getenv('SEMANTIC_LLM_LOCAL_DEVICE', 'auto').strip().lower()
    semantic_llm_local_dtype = os.getenv('SEMANTIC_LLM_LOCAL_DTYPE', 'auto').strip().lower()
    semantic_llm_local_load_in_4bit = os.getenv('SEMANTIC_LLM_LOCAL_LOAD_IN_4BIT', 'false').lower() in {'1', 'true', 'yes', 'on'}
    semantic_llm_local_bnb_compute_dtype = os.getenv('SEMANTIC_LLM_LOCAL_BNB_COMPUTE_DTYPE', 'float16').strip().lower()
    semantic_llm_local_max_new_tokens = int(os.getenv('SEMANTIC_LLM_LOCAL_MAX_NEW_TOKENS', '512'))
    semantic_llm_local_trust_remote_code = os.getenv(
        'SEMANTIC_LLM_LOCAL_TRUST_REMOTE_CODE',
        'true',
    ).lower() in {'1', 'true', 'yes', 'on'}
    return Settings(
        project_root=project_root,
        base_dir=base_dir,
        job_dir=job_dir,
        package_dir=package_dir,
        result_dir=result_dir,
        local_plan_dir=local_plan_dir,
        asset_root_dir=asset_root_dir,
        public_base_url=public_base_url,
        cors_allow_origins=cors_allow_origins,
        cors_allow_origin_regex=cors_allow_origin_regex,
        cors_allow_credentials=cors_allow_credentials,
        semantic_llm_enabled=semantic_llm_enabled,
        semantic_llm_provider=semantic_llm_provider,
        semantic_llm_base_url=semantic_llm_base_url,
        semantic_llm_api_key=semantic_llm_api_key,
        semantic_llm_model=semantic_llm_model,
        semantic_llm_timeout_sec=semantic_llm_timeout_sec,
        semantic_llm_local_model_path=semantic_llm_local_model_path,
        semantic_llm_local_adapter_path=semantic_llm_local_adapter_path,
        semantic_llm_local_device=semantic_llm_local_device,
        semantic_llm_local_dtype=semantic_llm_local_dtype,
        semantic_llm_local_load_in_4bit=semantic_llm_local_load_in_4bit,
        semantic_llm_local_bnb_compute_dtype=semantic_llm_local_bnb_compute_dtype,
        semantic_llm_local_max_new_tokens=semantic_llm_local_max_new_tokens,
        semantic_llm_local_trust_remote_code=semantic_llm_local_trust_remote_code,
    )
