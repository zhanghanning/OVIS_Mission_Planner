from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from app.services.local_asset_service import (
    load_mission_templates,
    load_semantic_catalog,
    load_target_sets,
    nav_point_index,
)
from app.services.semantic_llm_service import resolve_semantic_selection_with_llm


logger = logging.getLogger(__name__)


CATEGORY_KEYWORDS = {
    "teaching_building": ["教学楼", "教楼", "教学设施", "教学"],
    "dormitory": ["宿舍楼", "宿舍", "宿舍区"],
    "dining": ["食堂", "餐厅", "餐饮"],
    "sports_facility": ["体育", "球场", "运动场", "运动设施"],
    "service_building": ["服务中心", "服务楼", "快递站", "后勤"],
    "general_building": ["综合楼", "综合建筑", "公共建筑"],
}

CHINESE_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}

BUILDING_CATEGORY_PREFIX = {
    "teaching_building": "教",
    "dormitory": "学",
}


def _parse_chinese_number(token: str) -> Optional[int]:
    if not token:
        return None
    if token.isdigit():
        return int(token)
    if token == "十":
        return 10
    if "百" in token:
        hundreds_text, rest_text = token.split("百", 1)
        hundreds = CHINESE_DIGITS.get(hundreds_text)
        if hundreds is None:
            return None
        rest = _parse_chinese_number(rest_text) if rest_text else 0
        if rest is None:
            return None
        return hundreds * 100 + rest
    if "十" in token:
        tens_text, ones_text = token.split("十", 1)
        tens = CHINESE_DIGITS.get(tens_text) if tens_text else 1
        if tens is None:
            return None
        if ones_text:
            ones = CHINESE_DIGITS.get(ones_text)
            if ones is None:
                return None
        else:
            ones = 0
        return tens * 10 + ones
    if len(token) == 1:
        return CHINESE_DIGITS.get(token)
    return None


def _replace_chinese_numerals(value: str) -> str:
    def repl(match: re.Match[str]) -> str:
        token = match.group(0)
        parsed = _parse_chinese_number(token)
        return str(parsed) if parsed is not None else token

    return re.sub(r"[零一二两三四五六七八九十百]+", repl, value)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", _replace_chinese_numerals(value or "")).lower()


def _infer_allowed_categories(normalized_query: str) -> Optional[set[str]]:
    has_teaching = any(_normalize_text(keyword) in normalized_query for keyword in CATEGORY_KEYWORDS["teaching_building"])
    has_dormitory = any(_normalize_text(keyword) in normalized_query for keyword in CATEGORY_KEYWORDS["dormitory"])
    if has_teaching and not has_dormitory:
        return {"teaching_building"}
    if has_dormitory and not has_teaching:
        return {"dormitory"}
    return None


def _local_template_match(query: str, mission_templates: Dict) -> Optional[Dict]:
    normalized_query = _normalize_text(query)
    for template in mission_templates["templates"]:
        if _normalize_text(template["template_id"]) in normalized_query:
            return {
                "resolution_mode": "template_id",
                "resolved_target_set_ids": list(template["target_set_ids"]),
                "resolved_nav_point_ids": list(template["candidate_nav_point_ids"]),
                "matched_building_ids": [],
                "matched_building_names": [],
                "matched_nav_point_ids": list(template["candidate_nav_point_ids"]),
                "natural_language_match": template["natural_language"],
                "notes": f"Matched template id {template['template_id']}",
            }
        if _normalize_text(template["natural_language"]) in normalized_query:
            return {
                "resolution_mode": "template_text",
                "resolved_target_set_ids": list(template["target_set_ids"]),
                "resolved_nav_point_ids": list(template["candidate_nav_point_ids"]),
                "matched_building_ids": [],
                "matched_building_names": [],
                "matched_nav_point_ids": list(template["candidate_nav_point_ids"]),
                "natural_language_match": template["natural_language"],
                "notes": f"Matched template text {template['natural_language']}",
            }
    return None


def _local_category_match(query: str, target_sets: Dict) -> Optional[Dict]:
    normalized_query = _normalize_text(query)
    target_set_map = {item["target_set_id"]: item for item in target_sets["target_sets"]}
    matched_target_set_ids: List[str] = []
    matched_nav_ids: List[str] = []
    for category, keywords in CATEGORY_KEYWORDS.items():
        if not any(_normalize_text(keyword) in normalized_query for keyword in keywords):
            continue
        target_set_id = f"category::{category}"
        target_set = target_set_map.get(target_set_id)
        if target_set is None:
            continue
        matched_target_set_ids.append(target_set_id)
        matched_nav_ids.extend(target_set["nav_point_ids"])

    if not matched_target_set_ids:
        return None

    return {
        "resolution_mode": "category",
        "resolved_target_set_ids": sorted(set(matched_target_set_ids)),
        "resolved_nav_point_ids": sorted(set(matched_nav_ids)),
        "matched_building_ids": [],
        "matched_building_names": [],
        "matched_nav_point_ids": sorted(set(matched_nav_ids)),
        "notes": "Matched category keywords from semantic query.",
    }


def _extract_building_number(building: Dict) -> Optional[str]:
    texts = [building.get("name", "")]
    texts.extend(building.get("aliases", []))
    for text in texts:
        match = re.search(r"(\d+)", _normalize_text(text))
        if match:
            return match.group(1)
    return None


def _resolve_building_prefix(explicit_prefix: Optional[str], suffix: str, allowed_categories: Optional[set[str]]) -> Optional[str]:
    if explicit_prefix in {"教", "学"}:
        return explicit_prefix
    normalized_suffix = _normalize_text(suffix)
    if "教学" in normalized_suffix:
        return "教"
    if "宿舍" in normalized_suffix or normalized_suffix == "舍":
        return "学"
    if allowed_categories == {"teaching_building"}:
        return "教"
    if allowed_categories == {"dormitory"}:
        return "学"
    return None


def _build_number_reference_map(semantic_catalog: Dict) -> Dict[tuple[str, str], Dict]:
    reference_map: Dict[tuple[str, str], Dict] = {}
    for building in semantic_catalog["buildings"]:
        category = building.get("category", "")
        prefix = BUILDING_CATEGORY_PREFIX.get(category)
        number = _extract_building_number(building)
        if prefix and number:
            reference_map[(prefix, number)] = building
    return reference_map


def _building_matches_by_number_reference(query: str, semantic_catalog: Dict) -> Optional[Dict]:
    normalized_query = _normalize_text(query)
    allowed_categories = _infer_allowed_categories(normalized_query)
    building_map = _build_number_reference_map(semantic_catalog)
    matched_buildings: List[Dict] = []

    def add_match(prefix: Optional[str], number: str):
        if prefix is None:
            return
        building = building_map.get((prefix, number))
        if building and building not in matched_buildings:
            matched_buildings.append(building)

    range_pattern = re.compile(
        r"(教|学)?(\d+)(?:号)?(?:教学楼|宿舍楼|楼|舍|座)?(?:到|至|-|~|—)(教|学)?(\d+)(?:号)?(教学楼|宿舍楼|楼|舍|座)?"
    )
    match = range_pattern.search(normalized_query)
    if match:
        start_prefix = _resolve_building_prefix(match.group(1), match.group(5) or "", allowed_categories)
        end_prefix = _resolve_building_prefix(match.group(3), match.group(5) or "", allowed_categories) or start_prefix
        if start_prefix == end_prefix and start_prefix is not None:
            low = min(int(match.group(2)), int(match.group(4)))
            high = max(int(match.group(2)), int(match.group(4)))
            for number in range(low, high + 1):
                add_match(start_prefix, str(number))

    explicit_pattern = re.compile(r"(教|学)(\d+)(?:号)?(?:教学楼|宿舍楼|楼|舍|座)?")
    for match in explicit_pattern.finditer(normalized_query):
        add_match(match.group(1), match.group(2))

    implicit_pattern = re.compile(r"(\d+)(?:号)?(教学楼|宿舍楼|宿舍|楼|舍|座)")
    for match in implicit_pattern.finditer(normalized_query):
        prefix = _resolve_building_prefix(None, match.group(2), allowed_categories)
        add_match(prefix, match.group(1))

    if not matched_buildings:
        return None

    nav_ids = sorted({nav_id for building in matched_buildings for nav_id in building.get("nav_point_ids", [])})
    return {
        "resolution_mode": "building_number",
        "resolved_target_set_ids": [],
        "resolved_nav_point_ids": nav_ids,
        "matched_building_ids": [building["building_id"] for building in matched_buildings],
        "matched_building_names": [building["name"] for building in matched_buildings],
        "matched_nav_point_ids": nav_ids,
        "notes": "Matched numbered building references from semantic query.",
    }


def _building_matches_by_range(query: str, semantic_catalog: Dict) -> Optional[Dict]:
    normalized_query = _normalize_text(query)
    buildings = semantic_catalog["buildings"]
    matched_buildings: List[Dict] = []
    allowed_categories = _infer_allowed_categories(normalized_query)

    range_patterns = [
        re.compile(r"(教|学)\s*(\d+)(?:楼|舍|座)?(?:到|至|-|~|—)(教|学)?\s*(\d+)", re.IGNORECASE),
    ]

    for pattern in range_patterns:
        match = pattern.search(normalized_query)
        if not match:
            continue
        prefix_start = match.group(1)
        start_num = int(match.group(2))
        prefix_end = match.group(3) or prefix_start
        end_num = int(match.group(4))
        if prefix_start != prefix_end:
            continue
        low = min(start_num, end_num)
        high = max(start_num, end_num)
        for building in buildings:
            if allowed_categories and building.get("category") not in allowed_categories:
                continue
            aliases = [_normalize_text(alias) for alias in building.get("aliases", [])]
            aliases.append(_normalize_text(building.get("name", "")))
            for number in range(low, high + 1):
                token = _normalize_text(f"{prefix_start}{number}")
                if any(token in alias for alias in aliases):
                    matched_buildings.append(building)
                    break
        break

    if not matched_buildings:
        return None

    nav_ids = sorted({nav_id for building in matched_buildings for nav_id in building.get("nav_point_ids", [])})
    return {
        "resolution_mode": "building_range",
        "resolved_target_set_ids": [],
        "resolved_nav_point_ids": nav_ids,
        "matched_building_ids": [building["building_id"] for building in matched_buildings],
        "matched_building_names": [building["name"] for building in matched_buildings],
        "matched_nav_point_ids": nav_ids,
        "notes": "Matched building range expression from semantic query.",
    }


def _building_matches_by_name(query: str, semantic_catalog: Dict) -> Optional[Dict]:
    normalized_query = _normalize_text(query)
    matched_buildings: List[Dict] = []
    allowed_categories = _infer_allowed_categories(normalized_query)
    for building in semantic_catalog["buildings"]:
        if allowed_categories and building.get("category") not in allowed_categories:
            continue
        names = [_normalize_text(building.get("name", ""))]
        names.extend(_normalize_text(alias) for alias in building.get("aliases", []))
        if any(name and name in normalized_query for name in names):
            matched_buildings.append(building)

    if not matched_buildings:
        return None

    nav_ids = sorted({nav_id for building in matched_buildings for nav_id in building.get("nav_point_ids", [])})
    return {
        "resolution_mode": "building_name",
        "resolved_target_set_ids": [],
        "resolved_nav_point_ids": nav_ids,
        "matched_building_ids": [building["building_id"] for building in matched_buildings],
        "matched_building_names": [building["name"] for building in matched_buildings],
        "matched_nav_point_ids": nav_ids,
        "notes": "Matched building aliases from semantic query.",
    }


def _standalone_nav_match(query: str, semantic_catalog: Dict) -> Optional[Dict]:
    normalized_query = _normalize_text(query)
    matched_nav_ids: List[str] = []
    for nav_point in semantic_catalog.get("standalone_nav_points", []):
        if _normalize_text(nav_point["name"]) in normalized_query:
            matched_nav_ids.append(nav_point["id"])

    if not matched_nav_ids:
        return None

    return {
        "resolution_mode": "standalone_nav_name",
        "resolved_target_set_ids": [],
        "resolved_nav_point_ids": sorted(set(matched_nav_ids)),
        "matched_building_ids": [],
        "matched_building_names": [],
        "matched_nav_point_ids": sorted(set(matched_nav_ids)),
        "notes": "Matched standalone nav point names from semantic query.",
    }


def _resolve_with_llm(query: str, scene_name: str | None = None) -> Optional[Dict]:
    target_sets = load_target_sets(scene_name)
    semantic_catalog = load_semantic_catalog(scene_name)
    parsed = resolve_semantic_selection_with_llm(query, target_sets, semantic_catalog, scene_name)
    if not parsed:
        return None

    target_set_map = {item["target_set_id"]: item for item in target_sets["target_sets"]}
    standalone_ids = {item["id"] for item in semantic_catalog.get("standalone_nav_points", [])}

    selected_target_set_ids = [
        target_set_id
        for target_set_id in parsed.get("selected_target_set_ids", [])
        if target_set_id in target_set_map
    ]
    selected_nav_ids: List[str] = []
    for target_set_id in selected_target_set_ids:
        selected_nav_ids.extend(target_set_map[target_set_id]["nav_point_ids"])
    for nav_id in parsed.get("selected_nav_point_ids", []):
        if nav_id in standalone_ids:
            selected_nav_ids.append(nav_id)

    selected_nav_ids = sorted(set(selected_nav_ids))
    if not selected_nav_ids:
        return None

    return {
        "resolution_mode": "llm",
        "resolved_target_set_ids": selected_target_set_ids,
        "resolved_nav_point_ids": selected_nav_ids,
        "matched_building_ids": [],
        "matched_building_names": [],
        "matched_nav_point_ids": selected_nav_ids,
        "notes": parsed.get("reason", "Resolved by LLM selection."),
    }


def resolve_semantic_targets(query: str, use_llm: bool = True, scene_name: str | None = None) -> Dict:
    query = (query or "").strip()
    if not query:
        return {
            "resolution_mode": "empty_query",
            "resolved_target_set_ids": [],
            "resolved_nav_point_ids": [],
            "matched_building_ids": [],
            "matched_building_names": [],
            "matched_nav_point_ids": [],
            "notes": "Query is empty.",
            "llm_attempted": False,
        }

    mission_templates = load_mission_templates(scene_name)
    semantic_catalog = load_semantic_catalog(scene_name)
    target_sets = load_target_sets(scene_name)

    for resolver in (
        lambda: _local_template_match(query, mission_templates),
        lambda: _building_matches_by_number_reference(query, semantic_catalog),
        lambda: _building_matches_by_range(query, semantic_catalog),
        lambda: _building_matches_by_name(query, semantic_catalog),
        lambda: _local_category_match(query, target_sets),
        lambda: _standalone_nav_match(query, semantic_catalog),
    ):
        resolution = resolver()
        if resolution and resolution["resolved_nav_point_ids"]:
            resolution["query"] = query
            resolution["llm_attempted"] = False
            return resolution

    if use_llm:
        try:
            resolution = _resolve_with_llm(query, scene_name)
            if resolution and resolution["resolved_nav_point_ids"]:
                resolution["query"] = query
                resolution["llm_attempted"] = True
                return resolution
        except Exception as exc:
            logger.warning("semantic llm resolution failed: %s", exc)

    return {
        "resolution_mode": "no_match",
        "resolved_target_set_ids": [],
        "resolved_nav_point_ids": [],
        "matched_building_ids": [],
        "matched_building_names": [],
        "matched_nav_point_ids": [],
        "notes": "No semantic target matched the query.",
        "query": query,
        "llm_attempted": use_llm,
    }


def expand_target_set_ids(target_set_ids: List[str], scene_name: str | None = None) -> List[str]:
    target_set_map = {item["target_set_id"]: item for item in load_target_sets(scene_name)["target_sets"]}
    nav_ids: List[str] = []
    for target_set_id in target_set_ids:
        target_set = target_set_map.get(target_set_id)
        if target_set is not None:
            nav_ids.extend(target_set["nav_point_ids"])
    return sorted(set(nav_ids))


def validate_nav_point_ids(nav_point_ids: List[str], scene_name: str | None = None) -> List[str]:
    valid_ids = set(nav_point_index(scene_name))
    return [nav_id for nav_id in nav_point_ids if nav_id in valid_ids]
