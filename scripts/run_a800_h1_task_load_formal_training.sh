#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="${WORLD_SPEC_TASK_LOAD_FORMAL_PROFILE:-${ROOT_DIR}/examples/h1-kitchen/locomotion-task-load-formal-profile.json}"
IMAGE_BUILD_REPORT="${ROOT_DIR}/examples/h1-kitchen/task-load-formal-training-image-build.a800.passed.json"
SOURCE_REPORT="${ROOT_DIR}/examples/h1-kitchen/locomotion-task-load-horizon.a800.passed.json"
SOURCE_CHECKPOINT="${WORLD_SPEC_TASK_LOAD_FORMAL_WARM_START_CHECKPOINT:-${ROOT_DIR}/runs/a800/worldspec-h1-midterm-dsl8l/midterm-checkpoint.zip}"
STAND_REPORT="${ROOT_DIR}/examples/h1-kitchen/locomotion-calibration.a800.passed.json"
STAND_CHECKPOINT="${WORLD_SPEC_TASK_LOAD_FORMAL_STAND_CHECKPOINT:-${ROOT_DIR}/runs/a800/worldspec-h1-calibration-4mklr/calibration-checkpoint.zip}"
SETTLE_REPORT="${ROOT_DIR}/examples/h1-kitchen/locomotion-capture.a800.passed.json"
SETTLE_CHECKPOINT="${WORLD_SPEC_TASK_LOAD_FORMAL_SETTLE_CHECKPOINT:-${ROOT_DIR}/runs/a800/worldspec-h1-midterm-rmnnr/midterm-checkpoint.zip}"

for required in \
  "${PROFILE}" \
  "${IMAGE_BUILD_REPORT}" \
  "${SOURCE_REPORT}" \
  "${SOURCE_CHECKPOINT}" \
  "${STAND_REPORT}" \
  "${STAND_CHECKPOINT}" \
  "${SETTLE_REPORT}" \
  "${SETTLE_CHECKPOINT}"; do
  if [[ ! -r "${required}" ]]; then
    printf 'ERROR: required formal-training input is not readable: %s\n' \
      "${required}" >&2
    exit 2
  fi
done

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
  echo "ERROR: formal-training Profile is not bound to its image build report" >&2
  exit 2
fi
export WORLD_SPEC_IMAGE_SOURCE_REVISION="${image_source_revision}"

python3 - \
  "${PROFILE}" \
  "${SOURCE_REPORT}" \
  "${SOURCE_CHECKPOINT}" \
  "${STAND_REPORT}" \
  "${STAND_CHECKPOINT}" \
  "${SETTLE_REPORT}" \
  "${SETTLE_CHECKPOINT}" <<'PY'
import hashlib
import json
import pathlib
import sys

profile = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
if profile["stage"] != "loaded_track_settle_task_load_formal":
    raise SystemExit("formal-training stage mismatch")
for spec_name, report_name, checkpoint_name in (
    ("warmStart", sys.argv[2], sys.argv[3]),
    ("standTeacher", sys.argv[4], sys.argv[5]),
    ("settleTeacher", sys.argv[6], sys.argv[7]),
):
    spec = profile[spec_name]
    report = pathlib.Path(report_name).read_bytes()
    checkpoint = pathlib.Path(checkpoint_name).read_bytes()
    if f"sha256:{hashlib.sha256(report).hexdigest()}" != spec["sourceReportDigest"]:
        raise SystemExit(f"{spec_name} report digest mismatch")
    if (
        f"sha256:{hashlib.sha256(checkpoint).hexdigest()}"
        != spec["checkpointDigest"]
        or len(checkpoint) != spec["checkpointSizeBytes"]
    ):
        raise SystemExit(f"{spec_name} checkpoint identity mismatch")
source = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
if (
    source["formalTrainingGate"] != "passed"
    or source["qualityAssessment"]["status"] != "passed"
    or source["training"]["profileStage"]
    != "loaded_track_settle_task_load_horizon"
):
    raise SystemExit("formal-training source evidence is not passing")
PY

export WORLD_SPEC_MIDTERM_PROFILE="${PROFILE}"
export WORLD_SPEC_WARM_START_REPORT="${SOURCE_REPORT}"
export WORLD_SPEC_WARM_START_CHECKPOINT="${SOURCE_CHECKPOINT}"
export WORLD_SPEC_RETENTION_TEACHER_REPORT="${STAND_REPORT}"
export WORLD_SPEC_RETENTION_TEACHER_CHECKPOINT="${STAND_CHECKPOINT}"
export WORLD_SPEC_SETTLE_TEACHER_REPORT="${SETTLE_REPORT}"
export WORLD_SPEC_SETTLE_TEACHER_CHECKPOINT="${SETTLE_CHECKPOINT}"
export WORLD_SPEC_A800_TIMEOUT_SECONDS="${WORLD_SPEC_A800_TIMEOUT_SECONDS:-43200}"

exec "${ROOT_DIR}/scripts/run_a800_h1_locomotion_midterm.sh"
