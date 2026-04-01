#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="/workspace/mission_planner"
BUILD_SCRIPT="${PROJECT_ROOT}/scripts/build_planner_native.sh"

if [[ -x "${BUILD_SCRIPT}" ]]; then
  echo "Preparing native planner kernel..."
  if ! "${BUILD_SCRIPT}" >/tmp/mission_planner_native_build_path.txt 2>/tmp/mission_planner_native_build.log; then
    echo "Native planner build failed, falling back to Python planner." >&2
    cat /tmp/mission_planner_native_build.log >&2 || true
  else
    echo "Native planner ready at $(cat /tmp/mission_planner_native_build_path.txt)"
  fi
else
  echo "Native planner build script not found or not executable, using Python planner." >&2
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8081
