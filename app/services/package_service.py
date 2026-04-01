import hashlib
import json
import zipfile
from pathlib import Path
from typing import Dict

import requests


REQUIRED_FILES = [
    "manifest.json",
    "semantic.json",
    "route_graph.json",
    "goals.json",
    "robots.json",
    "constraints.json",
]


def download_package(package_url: str, save_path: Path, auth_token: str = None) -> None:
    headers = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    response = requests.get(package_url, headers=headers, timeout=120)
    response.raise_for_status()
    save_path.write_bytes(response.content)


def verify_sha256(file_path: Path, expected_sha256: str) -> None:
    if not expected_sha256:
        return

    digest = hashlib.sha256()
    with file_path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)

    actual = digest.hexdigest()
    if actual != expected_sha256:
        raise ValueError(f"sha256 mismatch: {actual} != {expected_sha256}")


def unzip_package(zip_path: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zip_file:
        zip_file.extractall(output_dir)
    return resolve_package_dir(output_dir)


def resolve_package_dir(output_dir: Path) -> Path:
    if (output_dir / "manifest.json").exists():
        return output_dir

    subdirs = [path for path in output_dir.iterdir() if path.is_dir()]
    if len(subdirs) == 1 and (subdirs[0] / "manifest.json").exists():
        return subdirs[0]

    return output_dir


def validate_package(package_dir: Path) -> None:
    missing = [name for name in REQUIRED_FILES if not (package_dir / name).exists()]
    if missing:
        raise FileNotFoundError(f"missing required files: {', '.join(missing)}")


def load_json(file_path: Path) -> Dict:
    with file_path.open("r", encoding="utf-8") as file_obj:
        return json.load(file_obj)
