#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEFAULT_SRC_ROOT="${PROJECT_ROOT}/../NCEPU_OSM_Info"
DEFAULT_DST_ROOT="${PROJECT_ROOT}/data/assets/ncepu"

SRC_ROOT="${1:-${DEFAULT_SRC_ROOT}}"
DST_ROOT="${2:-${DEFAULT_DST_ROOT}}"

echo "[sync] source: ${SRC_ROOT}"
echo "[sync] target: ${DST_ROOT}"

mkdir -p "${DST_ROOT}"

for dir in world mission fleet planning source; do
  if [ ! -d "${SRC_ROOT}/${dir}" ]; then
    continue
  fi
  mkdir -p "${DST_ROOT}/${dir}"
  cp -r "${SRC_ROOT}/${dir}/." "${DST_ROOT}/${dir}/"
done

python3 "${SCRIPT_DIR}/normalize_asset_paths.py" "${DST_ROOT}"

echo "[sync] runtime assets copied into mission_planner."
