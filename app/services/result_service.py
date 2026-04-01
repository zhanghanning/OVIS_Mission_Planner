import json
import zipfile
from pathlib import Path
from typing import Dict


def write_json(file_path: Path, payload: Dict) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", encoding="utf-8") as file_obj:
        json.dump(payload, file_obj, ensure_ascii=False, indent=2)


def pack_result_dir(result_dir: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for file_path in result_dir.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path == zip_path:
                continue
            zip_file.write(file_path, arcname=file_path.name)
