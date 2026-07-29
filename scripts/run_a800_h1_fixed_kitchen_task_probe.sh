#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export WORLD_SPEC_MIDTERM_PROFILE="${ROOT_DIR}/examples/h1-kitchen/kitchen-task-profile.json"
export WORLD_SPEC_WARM_START_REPORT="${ROOT_DIR}/examples/h1-kitchen/locomotion-transition.a800.failed.json"
export WORLD_SPEC_WARM_START_CHECKPOINT="${ROOT_DIR}/runs/a800/worldspec-h1-midterm-nxszt/midterm-checkpoint.zip"
export WORLD_SPEC_RETENTION_TEACHER_REPORT="${ROOT_DIR}/examples/h1-kitchen/locomotion-capture.a800.passed.json"
export WORLD_SPEC_RETENTION_TEACHER_CHECKPOINT="${ROOT_DIR}/runs/a800/worldspec-h1-midterm-rmnnr/midterm-checkpoint.zip"
export WORLD_SPEC_SUPERVISOR_STAND_REPORT="${ROOT_DIR}/examples/h1-kitchen/locomotion-calibration.a800.passed.json"
export WORLD_SPEC_SUPERVISOR_STAND_CHECKPOINT="${ROOT_DIR}/runs/a800/worldspec-h1-calibration-4mklr/calibration-checkpoint.zip"

exec "${ROOT_DIR}/scripts/run_a800_h1_locomotion_midterm.sh"
