#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Dict, Iterable, List

SYSTEM_PROMPT = (
    "You are a mission-selection assistant. Select relevant target_set_ids and nav point ids "
    "for a campus inspection task. Return JSON only with keys "
    "selected_target_set_ids, selected_nav_point_ids, reason."
)

CATEGORY_QUERY_TEMPLATES = {
    "teaching_building": [
        "巡检所有教学楼",
        "检查全部教学区",
        "把所有教室楼都巡一遍",
        "巡检所有教学设施",
    ],
    "dormitory": [
        "巡检所有宿舍楼",
        "巡检寝室区",
        "检查全部学生公寓",
        "把住宿区都巡一遍",
    ],
    "dining": [
        "巡检所有食堂",
        "检查全部餐厅",
        "把餐饮楼都巡一遍",
        "巡检所有饭堂",
    ],
    "sports_facility": [
        "巡检所有运动场地",
        "检查全部体育场地",
        "把所有球场和体育中心都巡一遍",
        "巡检校园里的运动区域",
    ],
}

NEARBY_QUERY_TEMPLATES = [
    "巡检{anchor}附近的巡检点",
    "检查{anchor}周边的目标点",
    "把{anchor}一圈的点都巡一遍",
    "巡检{anchor}附近的运动场地",
    "检查{anchor}周边的教学楼",
    "巡检{anchor}附近的宿舍楼",
]

BUILDING_QUERY_TEMPLATES = [
    "巡检{name}",
    "检查{name}",
    "把{name}的点位都巡一遍",
    "查看{name}附近的出入口",
]

DINING_QUERY_TEMPLATES = [
    "巡检{alias}",
    "检查{alias}",
    "把{alias}都看一遍",
]

SPORTS_TARGET_SET_IDS = {"category::sports_facility", "standalone::sports_checkpoint"}
DEFAULT_NEARBY_RADIUS_M = 320.0
MAX_NEARBY_RADIUS_M = 420.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate synthetic SFT data for mission semantic resolution.")
    project_root = Path(__file__).resolve().parents[1]
    parser.add_argument(
        "--asset-root",
        type=Path,
        default=project_root / "data" / "assets" / "ncepu",
        help="Asset root containing mission/world/planning/fleet folders.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=project_root / "data" / "training" / "semantic_sft",
        help="Directory to write train/eval jsonl files.",
    )
    return parser.parse_args()


def read_json(path: Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize(value: str) -> str:
    value = value or ""
    digits = {
        "零": "0",
        "一": "1",
        "二": "2",
        "两": "2",
        "三": "3",
        "四": "4",
        "五": "5",
        "六": "6",
        "七": "7",
        "八": "8",
        "九": "9",
        "十": "10",
    }
    for src, dst in digits.items():
        value = value.replace(src, dst)
    return re.sub(r"\s+", "", value).lower()


def semantic_catalog_prompt(target_sets: Dict, nav_points: Dict) -> str:
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
            "id": feat["properties"]["id"],
            "name": feat["properties"]["name"],
            "semantic_type": feat["properties"].get("semantic_type", ""),
            "building_name": feat["properties"].get("building_name", ""),
            "building_category": feat["properties"].get("building_category", ""),
        }
        for feat in nav_points["features"]
    ]
    return json.dumps({"target_sets": candidate_target_sets, "nav_points": candidate_nav_points}, ensure_ascii=False, indent=2)


def build_example(query: str, target_set_ids: Iterable[str], nav_point_ids: Iterable[str], reason: str, catalog_prompt: str, tag: str) -> Dict:
    response = {
        "selected_target_set_ids": sorted(set(target_set_ids)),
        "selected_nav_point_ids": sorted(set(nav_point_ids)),
        "reason": reason,
    }
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Mission query:\n{query}\n\nAvailable catalog:\n{catalog_prompt}",
            },
            {"role": "assistant", "content": json.dumps(response, ensure_ascii=False)},
        ],
        "query": query,
        "response": response,
        "tag": tag,
    }


def building_number(building: Dict) -> str | None:
    texts = [building.get("name", "")] + list(building.get("aliases", []))
    for text in texts:
        match = re.search(r"(\d+)", normalize(text))
        if match:
            return match.group(1)
    return None


def dining_aliases(number: str) -> List[str]:
    return [
        f"{number}号餐厅",
        f"{number}号食堂",
        f"第{number}餐厅",
        f"第{number}食堂",
        f"{number}餐",
        f"{number}餐厅",
        f"{number}食堂",
    ]


def building_aliases(building: Dict) -> List[str]:
    aliases = {building.get("name", "")}
    aliases.update(building.get("aliases", []))
    number = building_number(building)
    category = building.get("category", "")
    if number and category == "dining":
        aliases.update(dining_aliases(number))
    if number and category == "dormitory":
        aliases.update(
            {
                f"{number}号宿舍楼",
                f"{number}号寝室楼",
                f"{number}号学生公寓",
                f"寝室{number}",
                f"公寓{number}",
            }
        )
    if number and category == "teaching_building":
        aliases.update({f"{number}号教学楼", f"教学楼{number}", f"教{number}楼"})
    return sorted(alias for alias in aliases if alias)


def nav_index(nav_points_geojson: Dict) -> Dict[str, Dict]:
    result = {}
    for feature in nav_points_geojson["features"]:
        props = feature["properties"]
        result[props["id"]] = props
    return result


def nearby_nav_ids(anchor_id: str, nav_points_by_id: Dict[str, Dict], radius_m: float, category: str | None = None) -> List[str]:
    anchor = nav_points_by_id[anchor_id]
    selected = []
    for nav_id, props in nav_points_by_id.items():
        dx = float(props["local_x"]) - float(anchor["local_x"])
        dz = float(props["local_z"]) - float(anchor["local_z"])
        distance = math.hypot(dx, dz)
        if distance > radius_m:
            continue
        if category == "sports_facility":
            if props.get("building_category") == "sports_facility" or str(props.get("semantic_type", "")).startswith("sports_"):
                selected.append(nav_id)
            continue
        if category == "teaching_building":
            if props.get("building_category") == "teaching_building" or str(props.get("semantic_type", "")).startswith("teaching_building"):
                selected.append(nav_id)
            continue
        if category == "dormitory":
            if props.get("building_category") == "dormitory" or props.get("semantic_type") == "dormitory_checkpoint":
                selected.append(nav_id)
            continue
        selected.append(nav_id)
    return sorted(set(selected))


def stable_split(examples: List[Dict]) -> tuple[List[Dict], List[Dict]]:
    train, eval_set = [], []
    for idx, example in enumerate(sorted(examples, key=lambda item: (item["tag"], item["query"]))):
        if idx % 10 == 0:
            eval_set.append(example)
        else:
            train.append(example)
    return train, eval_set


def main() -> None:
    args = parse_args()
    asset_root = args.asset_root.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    semantic_catalog = read_json(asset_root / "mission" / "semantic_catalog.json")
    target_sets = read_json(asset_root / "planning" / "assets" / "semantic_target_sets.json")
    nav_points_geojson = read_json(asset_root / "mission" / "nav_points_enriched.geojson")
    nav_points_by_id = nav_index(nav_points_geojson)
    target_set_map = {item["target_set_id"]: item for item in target_sets["target_sets"]}
    catalog_prompt = semantic_catalog_prompt(target_sets, nav_points_geojson)

    examples: List[Dict] = []

    for category, templates in CATEGORY_QUERY_TEMPLATES.items():
        if category == "sports_facility":
            nav_ids = []
            for target_set_id in sorted(SPORTS_TARGET_SET_IDS):
                nav_ids.extend(target_set_map[target_set_id]["nav_point_ids"])
            target_set_ids = sorted(SPORTS_TARGET_SET_IDS)
        else:
            target_set_id = f"category::{category}"
            if target_set_id not in target_set_map:
                continue
            nav_ids = target_set_map[target_set_id]["nav_point_ids"]
            target_set_ids = [target_set_id]
        for query in templates:
            examples.append(build_example(query, target_set_ids, nav_ids, f"Category selection for {category}", catalog_prompt, f"category:{category}"))

    for building in semantic_catalog["buildings"]:
        target_set_id = f"building::{building['name']}"
        nav_ids = building.get("nav_point_ids", [])
        if not nav_ids:
            continue
        for alias in building_aliases(building):
            templates = DINING_QUERY_TEMPLATES if building.get("category") == "dining" else BUILDING_QUERY_TEMPLATES
            for template in templates:
                query = template.format(name=alias, alias=alias)
                examples.append(build_example(query, [target_set_id], nav_ids, f"Specific building selection for {building['name']}", catalog_prompt, f"building:{building['name']}"))

    for nav in semantic_catalog.get("standalone_nav_points", []):
        if nav.get("semantic_type") != "gate_or_entrance":
            continue
        anchor_id = nav["id"]
        anchor_name = nav["name"]
        generic_ids = nearby_nav_ids(anchor_id, nav_points_by_id, DEFAULT_NEARBY_RADIUS_M)
        sports_ids = nearby_nav_ids(anchor_id, nav_points_by_id, DEFAULT_NEARBY_RADIUS_M, "sports_facility")
        teaching_ids = nearby_nav_ids(anchor_id, nav_points_by_id, DEFAULT_NEARBY_RADIUS_M, "teaching_building")
        dorm_ids = nearby_nav_ids(anchor_id, nav_points_by_id, DEFAULT_NEARBY_RADIUS_M, "dormitory")
        examples.append(build_example(f"巡检{anchor_name}附近的巡检点", [], generic_ids, f"Nearby selection around {anchor_name}", catalog_prompt, f"nearby:{anchor_id}:generic"))
        examples.append(build_example(f"检查{anchor_name}周边的目标点", [], generic_ids, f"Nearby selection around {anchor_name}", catalog_prompt, f"nearby:{anchor_id}:generic"))
        examples.append(build_example(f"巡检{anchor_name}附近的运动场地", [], sports_ids, f"Nearby sports selection around {anchor_name}", catalog_prompt, f"nearby:{anchor_id}:sports"))
        examples.append(build_example(f"检查{anchor_name}周边的教学楼", [], teaching_ids, f"Nearby teaching-building selection around {anchor_name}", catalog_prompt, f"nearby:{anchor_id}:teaching"))
        examples.append(build_example(f"巡检{anchor_name}附近的宿舍楼", [], dorm_ids, f"Nearby dormitory selection around {anchor_name}", catalog_prompt, f"nearby:{anchor_id}:dormitory"))

    train_set, eval_set = stable_split(examples)
    train_path = output_dir / "semantic_sft_train.jsonl"
    eval_path = output_dir / "semantic_sft_eval.jsonl"
    summary_path = output_dir / "semantic_sft_summary.json"

    train_path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in train_set) + "\n", encoding="utf-8")
    eval_path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in eval_set) + "\n", encoding="utf-8")
    summary_path.write_text(
        json.dumps(
            {
                "asset_root": str(asset_root),
                "train_examples": len(train_set),
                "eval_examples": len(eval_set),
                "target_sets": len(target_sets["target_sets"]),
                "nav_points": len(nav_points_geojson["features"]),
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"train": str(train_path), "eval": str(eval_path), "summary": str(summary_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
