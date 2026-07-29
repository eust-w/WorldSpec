#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORLD_SPEC_DIAGNOSTIC_REPLAY_PROFILE="${WORLD_SPEC_DIAGNOSTIC_REPLAY_PROFILE:-${ROOT_DIR}/examples/h1-kitchen/whole-body-diagnostic-replay-profile.json}"
export WORLD_SPEC_DIAGNOSTIC_REPLAY_PROFILE

if [[ ! -r "${WORLD_SPEC_DIAGNOSTIC_REPLAY_PROFILE}" ]]; then
  echo "ERROR: WORLD_SPEC_DIAGNOSTIC_REPLAY_PROFILE must name a readable C2 replay-lock Profile" >&2
  exit 2
fi

export WORLD_SPEC_MIDTERM_PROFILE="${ROOT_DIR}/examples/h1-kitchen/whole-body-control-profile.json"
export WORLD_SPEC_WARM_START_REPORT="${ROOT_DIR}/examples/h1-kitchen/locomotion-transition.a800.failed.json"
export WORLD_SPEC_WARM_START_CHECKPOINT="${ROOT_DIR}/runs/a800/worldspec-h1-midterm-nxszt/midterm-checkpoint.zip"
export WORLD_SPEC_RETENTION_TEACHER_REPORT="${ROOT_DIR}/examples/h1-kitchen/locomotion-capture.a800.passed.json"
export WORLD_SPEC_RETENTION_TEACHER_CHECKPOINT="${ROOT_DIR}/runs/a800/worldspec-h1-midterm-rmnnr/midterm-checkpoint.zip"
export WORLD_SPEC_SUPERVISOR_STAND_REPORT="${ROOT_DIR}/examples/h1-kitchen/locomotion-calibration.a800.passed.json"
export WORLD_SPEC_SUPERVISOR_STAND_CHECKPOINT="${ROOT_DIR}/runs/a800/worldspec-h1-calibration-4mklr/calibration-checkpoint.zip"
export WORLD_SPEC_A5C_BASELINE_SUMMARY="${ROOT_DIR}/examples/h1-kitchen/whole-body-control.a800.failed-summary.json"
export WORLD_SPEC_A5C_BASELINE_REPORT="${ROOT_DIR}/runs/a800/worldspec-h1-midterm-d5z6c/whole-body-control-report.json"
export WORLD_SPEC_A5C_BASELINE_CONTROLLER="${ROOT_DIR}/runs/a800/worldspec-h1-midterm-d5z6c/whole-body-controller.json"
export WORLD_SPEC_A5C_BASELINE_TRACE="${ROOT_DIR}/runs/a800/worldspec-h1-midterm-d5z6c/evaluation-traces.jsonl"

read -r image_source runtime_image package_lock < <(
  python3 - "${WORLD_SPEC_DIAGNOSTIC_REPLAY_PROFILE}" <<'PY'
import json
import pathlib
import sys

profile = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
runtime = profile["runtime"]
print(
    runtime["imageSourceRevision"],
    runtime["containerImage"],
    runtime["packageLockDigest"],
)
PY
)
export WORLD_SPEC_IMAGE_SOURCE_REVISION="${image_source}"
export WORLD_SPEC_H1_RUNTIME_IMAGE="${runtime_image}"
export WORLD_SPEC_PACKAGE_LOCK_DIGEST="${package_lock}"

exec "${ROOT_DIR}/scripts/run_a800_h1_locomotion_midterm.sh"
