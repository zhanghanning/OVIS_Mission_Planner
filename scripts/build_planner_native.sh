#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SOURCE_FILE="${PROJECT_ROOT}/app/planners/native/formal_multi_robot_native.cpp"
OUTPUT_DIR="${MISSION_PLANNER_NATIVE_BUILD_DIR:-/tmp/mission_planner_native}"
OUTPUT_FILE="${MISSION_PLANNER_NATIVE_LIB_PATH:-${OUTPUT_DIR}/libmission_planner_native.so}"

mkdir -p "$(dirname "${OUTPUT_FILE}")"

if [[ ! -f "${SOURCE_FILE}" ]]; then
  echo "Native planner source not found: ${SOURCE_FILE}" >&2
  exit 1
fi

if [[ -f "${OUTPUT_FILE}" && "${OUTPUT_FILE}" -nt "${SOURCE_FILE}" ]]; then
  echo "${OUTPUT_FILE}"
  exit 0
fi

g++ \
  -O3 \
  -DNDEBUG \
  -std=c++17 \
  -shared \
  -fPIC \
  "${SOURCE_FILE}" \
  -o "${OUTPUT_FILE}"

echo "${OUTPUT_FILE}"
