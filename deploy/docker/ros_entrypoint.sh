#!/usr/bin/env bash
set -e

source /opt/ros/galactic/setup.bash

if [ -f /workspace/ros2_ws/install/local_setup.bash ]; then
  source /workspace/ros2_ws/install/local_setup.bash
fi

exec "$@"
