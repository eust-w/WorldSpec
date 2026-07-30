#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="${ROOT_DIR}/examples/h1-kitchen/locomotion-task-load-supervisor-profile.json"
IMAGE_BUILD_REPORT="${ROOT_DIR}/examples/h1-kitchen/task-load-supervisor-image-build.a800.passed.json"

read -r image_source_revision built_image profile_image < <(
  python3 - "${IMAGE_BUILD_REPORT}" "${PROFILE}" <<'PY'
import json
import pathlib
import sys

build = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
profile = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
print(build["sourceCommit"], build["image"], profile["runtime"]["containerImage"])
PY
)
if [[ "${built_image}" != "${profile_image}" ]]; then
  echo "ERROR: A6-S Profile is not bound to its image build report" >&2
  exit 2
fi

export WORLD_SPEC_IMAGE_SOURCE_REVISION="${image_source_revision}"
export WORLD_SPEC_MIDTERM_PROFILE="${PROFILE}"
export WORLD_SPEC_WARM_START_REPORT="${ROOT_DIR}/examples/h1-kitchen/locomotion-task-load-formal.a800.failed-summary.json"
export WORLD_SPEC_WARM_START_CHECKPOINT="${ROOT_DIR}/runs/a800/worldspec-h1-midterm-cdbm5/midterm-checkpoint.zip"
export WORLD_SPEC_RETENTION_TEACHER_REPORT="${ROOT_DIR}/examples/h1-kitchen/locomotion-capture.a800.passed.json"
export WORLD_SPEC_RETENTION_TEACHER_CHECKPOINT="${ROOT_DIR}/runs/a800/worldspec-h1-midterm-rmnnr/midterm-checkpoint.zip"
export WORLD_SPEC_SUPERVISOR_STAND_REPORT="${ROOT_DIR}/examples/h1-kitchen/locomotion-calibration.a800.passed.json"
export WORLD_SPEC_SUPERVISOR_STAND_CHECKPOINT="${ROOT_DIR}/runs/a800/worldspec-h1-calibration-4mklr/calibration-checkpoint.zip"

exec "${ROOT_DIR}/scripts/run_a800_h1_locomotion_midterm.sh"
