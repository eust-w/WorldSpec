#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export WORLD_SPEC_TASK_LOAD_CALIBRATION_PROFILE="${ROOT_DIR}/examples/h1-kitchen/locomotion-task-load-survival-profile.json"

exec "${ROOT_DIR}/scripts/run_a800_h1_task_load_retention_calibration.sh"
