from __future__ import annotations

import gc
import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from app.core.config import get_settings
from app.services.local_asset_service import nav_point_index


logger = logging.getLogger(__name__)

SUPPORTED_PROVIDERS = {"disabled", "deepseek", "openai_compatible", "local_transformers"}


SYSTEM_PROMPT = (
    "You are a mission-selection assistant. Select relevant target_set_ids and nav point ids "
    "for an inspection task in the current scene. Return JSON only with keys "
    "selected_target_set_ids, selected_nav_point_ids, reason."
)


def build_semantic_catalog_prompt(target_sets: Dict, semantic_catalog: Dict, scene_name: str | None = None) -> str:
    candidate_target_sets = [
        {
            "target_set_id": item["target_set_id"],
            "display_name": item["display_name"],
            "selector_type": item["selector_type"],
            "nav_point_count": item["nav_point_count"],
        }
        for item in target_sets["target_sets"]
    ]
    candidate_nav_points = [
        {
            "id": item["id"],
            "name": item["name"],
            "semantic_type": item.get("semantic_type", ""),
            "building_name": item.get("building_name", ""),
            "building_category": item.get("building_category", ""),
            "power_asset_name": item.get("power_asset_name", ""),
            "power_asset_category": item.get("power_asset_category", ""),
        }
        for item in nav_point_index(scene_name).values()
    ]
    return json.dumps(
        {
            "target_sets": candidate_target_sets,
            "nav_points": candidate_nav_points,
        },
        ensure_ascii=False,
        indent=2,
    )


def build_semantic_user_prompt(query: str, target_sets: Dict, semantic_catalog: Dict, scene_name: str | None = None) -> str:
    return (
        "Mission query:\n"
        f"{query}\n\n"
        "Available catalog:\n"
        f"{build_semantic_catalog_prompt(target_sets, semantic_catalog, scene_name)}"
    )


def strip_markdown_fence(content: str) -> str:
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


def _torch_dtype_from_setting(torch_module, dtype_name: str):
    if dtype_name in {"auto", ""}:
        return None
    mapping = {
        "float16": getattr(torch_module, "float16", None),
        "bfloat16": getattr(torch_module, "bfloat16", None),
        "float32": getattr(torch_module, "float32", None),
    }
    return mapping.get(dtype_name)


def _json_from_text(content: str) -> Dict:
    text = strip_markdown_fence(content)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise


@lru_cache(maxsize=1)
def _load_local_transformers_stack(model_path_str: str, adapter_path_str: str | None, device: str, dtype_name: str, trust_remote_code: bool, load_in_4bit: bool, bnb_compute_dtype_name: str):
    try:
        import torch  # type: ignore
        import transformers  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "local_transformers provider requires optional dependencies 'torch' and 'transformers'."
        ) from exc

    model_path = Path(model_path_str)
    if not model_path.exists():
        raise RuntimeError(f"local model path does not exist: {model_path}")

    processor = None
    tokenizer = None
    if hasattr(transformers, "AutoProcessor"):
        try:
            processor = transformers.AutoProcessor.from_pretrained(
                str(model_path),
                trust_remote_code=trust_remote_code,
            )
        except Exception as exc:  # pragma: no cover - optional runtime backend
            logger.warning("failed to load AutoProcessor from %s: %s", model_path, exc)
    if hasattr(transformers, "AutoTokenizer"):
        tokenizer = transformers.AutoTokenizer.from_pretrained(
            str(model_path),
            trust_remote_code=trust_remote_code,
        )

    model = None
    last_error = None
    model_kwargs = {
        "trust_remote_code": trust_remote_code,
        "low_cpu_mem_usage": True,
    }
    torch_dtype = _torch_dtype_from_setting(torch, dtype_name)
    if torch_dtype is not None:
        model_kwargs["torch_dtype"] = torch_dtype
    if device == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("SEMANTIC_LLM_LOCAL_DEVICE=cuda but torch.cuda.is_available() is false")
        model_kwargs["device_map"] = {"": 0}
        model_kwargs["attn_implementation"] = "sdpa"
    elif device == "auto":
        model_kwargs["device_map"] = "auto"

    if load_in_4bit:
        if device != "cuda":
            raise RuntimeError("SEMANTIC_LLM_LOCAL_LOAD_IN_4BIT=true requires SEMANTIC_LLM_LOCAL_DEVICE=cuda")
        bnb_config_class = getattr(transformers, "BitsAndBytesConfig", None)
        if bnb_config_class is None:
            raise RuntimeError("bitsandbytes support is unavailable in the installed transformers package")
        bnb_compute_dtype = _torch_dtype_from_setting(torch, bnb_compute_dtype_name) or getattr(torch, "float16")
        model_kwargs["quantization_config"] = bnb_config_class(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=bnb_compute_dtype,
            bnb_4bit_use_double_quant=True,
        )
        model_kwargs.pop("torch_dtype", None)

    for class_name in (
        "Qwen3VLForConditionalGeneration",
        "AutoModelForVision2Seq",
        "AutoModelForImageTextToText",
        "AutoModelForCausalLM",
    ):
        model_class = getattr(transformers, class_name, None)
        if model_class is None:
            continue
        try:
            model = model_class.from_pretrained(str(model_path), **model_kwargs)
            break
        except Exception as exc:  # pragma: no cover - optional runtime backend
            last_error = exc
            logger.warning("failed to load %s from %s: %s", class_name, model_path, exc)
            gc.collect()
            if device == "cuda" and torch.cuda.is_available():
                torch.cuda.empty_cache()

    if model is None:
        raise RuntimeError(
            f"unable to load local transformers model from {model_path}: {last_error}"
        )

    if device == "cuda":
        hf_device_map = getattr(model, "hf_device_map", None)
        if hf_device_map:
            normalized_devices = {str(value).lower() for value in hf_device_map.values()}
            if any(not (value.startswith("cuda") or value.isdigit()) for value in normalized_devices):
                raise RuntimeError(
                    f"local transformers model spilled outside CUDA devices: {sorted(normalized_devices)}"
                )
        elif getattr(getattr(model, "device", None), "type", "") != "cuda":
            raise RuntimeError("local transformers model was not placed on CUDA")

    if device == "cpu" and hasattr(model, "to"):
        model = model.to("cpu")

    adapter_path = Path(adapter_path_str).expanduser() if adapter_path_str else None
    if adapter_path is not None:
        if not adapter_path.exists():
            raise RuntimeError(f"local adapter path does not exist: {adapter_path}")
        try:
            from peft import PeftModel  # type: ignore
        except ImportError as exc:
            raise RuntimeError("adapter loading requires optional dependency 'peft'.") from exc
        model = PeftModel.from_pretrained(model, str(adapter_path), is_trainable=False)

    return {"torch": torch, "transformers": transformers, "processor": processor, "tokenizer": tokenizer, "model": model}


def _build_local_chat_prompt(processor, tokenizer, system_prompt: str, user_prompt: str) -> str:
    multimodal_messages = [
        {"role": "system", "content": [{"type": "text", "text": system_prompt}]},
        {"role": "user", "content": [{"type": "text", "text": user_prompt}]},
    ]
    text_messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    for candidate in (processor, tokenizer):
        if candidate is None or not hasattr(candidate, "apply_chat_template"):
            continue
        for messages in (multimodal_messages, text_messages):
            try:
                return candidate.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            except Exception:
                continue

    return f"{system_prompt}\n\n{user_prompt}\n"


def _decode_local_generation(processor, tokenizer, generated_ids, input_ids):
    new_tokens = generated_ids[:, input_ids.shape[-1]:] if input_ids is not None else generated_ids
    for candidate in (processor, tokenizer):
        if candidate is None:
            continue
        if hasattr(candidate, "batch_decode"):
            return candidate.batch_decode(new_tokens, skip_special_tokens=True)[0]
        if hasattr(candidate, "decode"):
            return candidate.decode(new_tokens[0], skip_special_tokens=True)
    raise RuntimeError("no decoder available for local transformers provider")


def _invoke_chat_completion(
    *,
    base_url: str,
    api_key: str,
    model: str,
    timeout_sec: int,
    system_prompt: str,
    user_prompt: str,
    extra_payload: Optional[Dict[str, Any]] = None,
) -> Dict:
    if not base_url or not model:
        raise RuntimeError("chat completion provider requires base_url and model")

    url = base_url
    if not url.endswith("/chat/completions"):
        url = url.rstrip("/") + "/chat/completions"

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "stream": False,
    }
    if extra_payload:
        payload.update(extra_payload)

    response = requests.post(url, headers=headers, json=payload, timeout=timeout_sec)
    response.raise_for_status()
    raw = response.json()
    content = raw["choices"][0]["message"]["content"]
    return _json_from_text(content)


def _invoke_local_transformers(system_prompt: str, user_prompt: str) -> Dict:
    settings = get_settings()
    model_path = settings.semantic_llm_local_model_path
    if model_path is None:
        raise RuntimeError("SEMANTIC_LLM_LOCAL_MODEL_PATH is not configured")

    stack = _load_local_transformers_stack(
        str(model_path),
        str(settings.semantic_llm_local_adapter_path) if settings.semantic_llm_local_adapter_path else None,
        settings.semantic_llm_local_device,
        settings.semantic_llm_local_dtype,
        settings.semantic_llm_local_trust_remote_code,
        settings.semantic_llm_local_load_in_4bit,
        settings.semantic_llm_local_bnb_compute_dtype,
    )
    processor = stack["processor"]
    tokenizer = stack["tokenizer"]
    model = stack["model"]

    prompt = _build_local_chat_prompt(processor, tokenizer, system_prompt, user_prompt)

    if processor is not None:
        try:
            inputs = processor(text=[prompt], images=None, videos=None, return_tensors="pt")
        except TypeError:
            inputs = processor([prompt], return_tensors="pt")
    elif tokenizer is not None:
        inputs = tokenizer([prompt], return_tensors="pt")
    else:
        raise RuntimeError("local transformers provider could not build tokenizer or processor")

    model_device = getattr(model, "device", None)
    prepared_inputs = {}
    for key, value in inputs.items():
        if hasattr(value, "to") and model_device is not None:
            prepared_inputs[key] = value.to(model_device)
        else:
            prepared_inputs[key] = value

    generated_ids = model.generate(
        **prepared_inputs,
        max_new_tokens=settings.semantic_llm_local_max_new_tokens,
        do_sample=False,
    )
    input_ids = prepared_inputs.get("input_ids")
    content = _decode_local_generation(processor, tokenizer, generated_ids, input_ids)
    return _json_from_text(content)


def _invoke_openai_compatible(system_prompt: str, user_prompt: str) -> Dict:
    settings = get_settings()
    if not settings.semantic_llm_base_url or not settings.semantic_llm_model:
        raise RuntimeError("openai_compatible provider requires SEMANTIC_LLM_BASE_URL and SEMANTIC_LLM_MODEL")
    return _invoke_chat_completion(
        base_url=settings.semantic_llm_base_url,
        api_key=settings.semantic_llm_api_key,
        model=settings.semantic_llm_model,
        timeout_sec=settings.semantic_llm_timeout_sec,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )


def _invoke_deepseek(system_prompt: str, user_prompt: str) -> Dict:
    settings = get_settings()
    if not settings.deepseek_api_key and not settings.semantic_llm_api_key:
        raise RuntimeError("deepseek provider requires DEEPSEEK_API_KEY or SEMANTIC_LLM_API_KEY")
    return _invoke_chat_completion(
        base_url=settings.semantic_llm_base_url or settings.deepseek_api_base_url,
        api_key=settings.semantic_llm_api_key or settings.deepseek_api_key,
        model=settings.semantic_llm_model or settings.deepseek_api_model,
        timeout_sec=settings.semantic_llm_timeout_sec,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        extra_payload={
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
        },
    )


def resolve_semantic_selection_with_llm(
    query: str,
    target_sets: Dict,
    semantic_catalog: Dict,
    scene_name: str | None = None,
) -> Optional[Dict]:
    settings = get_settings()
    if not settings.semantic_llm_enabled:
        return None

    provider = settings.semantic_llm_provider
    if provider == "disabled":
        return None

    user_prompt = build_semantic_user_prompt(query, target_sets, semantic_catalog, scene_name)
    if provider == "deepseek":
        return _invoke_deepseek(SYSTEM_PROMPT, user_prompt)
    if provider == "openai_compatible":
        return _invoke_openai_compatible(SYSTEM_PROMPT, user_prompt)
    if provider == "local_transformers":
        return _invoke_local_transformers(SYSTEM_PROMPT, user_prompt)
    raise RuntimeError(f"unsupported semantic llm provider: {provider}")


def semantic_llm_provider_status() -> Dict:
    settings = get_settings()
    local_model_path = settings.semantic_llm_local_model_path
    local_adapter_path = settings.semantic_llm_local_adapter_path
    dependency_status = {}
    torch_module = None
    for module_name in ("torch", "transformers", "accelerate", "sentencepiece", "bitsandbytes", "peft", "datasets"):
        try:
            imported = __import__(module_name)
            if module_name == "torch":
                torch_module = imported
            dependency_status[module_name] = True
        except ImportError:
            dependency_status[module_name] = False
    return {
        "enabled": settings.semantic_llm_enabled,
        "provider": settings.semantic_llm_provider,
        "supported_providers": sorted(SUPPORTED_PROVIDERS),
        "project_root": str(settings.project_root),
        "dependency_status": dependency_status,
        "deepseek": {
            "configured": bool(settings.deepseek_api_key),
            "enabled_by_current_provider": settings.semantic_llm_provider == "deepseek" and settings.semantic_llm_enabled,
            "base_url": settings.deepseek_api_base_url,
            "model": settings.deepseek_api_model,
            "api_key_present": bool(settings.deepseek_api_key),
        },
        "openai_compatible": {
            "configured": bool(settings.semantic_llm_base_url and settings.semantic_llm_model),
            "enabled_by_current_provider": settings.semantic_llm_provider in {"deepseek", "openai_compatible"} and settings.semantic_llm_enabled,
            "base_url": settings.semantic_llm_base_url,
            "model": settings.semantic_llm_model,
            "api_key_present": bool(settings.semantic_llm_api_key),
        },
        "local_transformers": {
            "configured": local_model_path is not None,
            "model_path": str(local_model_path) if local_model_path is not None else "",
            "adapter_path": str(local_adapter_path) if local_adapter_path is not None else "",
            "adapter_path_exists": bool(local_adapter_path and local_adapter_path.exists()),
            "model_path_exists": bool(local_model_path and local_model_path.exists()),
            "model_path_real": str(local_model_path.resolve()) if local_model_path and local_model_path.exists() else "",
            "device": settings.semantic_llm_local_device,
            "dtype": settings.semantic_llm_local_dtype,
            "load_in_4bit": settings.semantic_llm_local_load_in_4bit,
            "bnb_compute_dtype": settings.semantic_llm_local_bnb_compute_dtype,
            "max_new_tokens": settings.semantic_llm_local_max_new_tokens,
            "cuda_available": bool(torch_module and torch_module.cuda.is_available()),
            "cuda_device_count": int(torch_module.cuda.device_count()) if torch_module else 0,
        },
    }
