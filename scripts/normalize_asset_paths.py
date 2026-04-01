#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _normalize_value(value, asset_root: Path):
    if isinstance(value, dict):
        return {key: _normalize_value(item, asset_root) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_value(item, asset_root) for item in value]
    if isinstance(value, str):
        if value.startswith(("http://", "https://")):
            return value
        expanded = Path(value).expanduser()
        if expanded.is_absolute():
            try:
                return Path(os.path.relpath(expanded, asset_root)).as_posix()
            except ValueError:
                return value
    return value


def normalize_asset_tree(asset_root: Path) -> int:
    changed = 0
    for json_path in sorted(asset_root.rglob("*.json")):
        data = json.loads(json_path.read_text(encoding="utf-8"))
        normalized = _normalize_value(data, asset_root)
        if normalized != data:
            json_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
            changed += 1
    return changed


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: normalize_asset_paths.py <asset_root>")
        return 2
    asset_root = Path(sys.argv[1]).resolve()
    changed = normalize_asset_tree(asset_root)
    print(f"[normalize_asset_paths] updated {changed} JSON files under {asset_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
