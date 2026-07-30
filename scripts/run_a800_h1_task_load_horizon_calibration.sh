#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="${WORLD_SPEC_TASK_LOAD_CALIBRATION_PROFILE:-${ROOT_DIR}/examples/h1-kitchen/locomotion-task-load-horizon-profile.json}"
IMAGE_BUILD_REPORT="${ROOT_DIR}/examples/h1-kitchen/task-load-horizon-training-image-build.a800.passed.json"
SOURCE_REPORT="${ROOT_DIR}/examples/h1-kitchen/locomotion-task-load-deployment-eval.a800.failed.json"
SOURCE_CHECKPOINT="${WORLD_SPEC_TASK_LOAD_RETENTION_WARM_START_CHECKPOINT:-${ROOT_DIR}/runs/a800/worldspec-h1-midterm-zg6kg/midterm-checkpoint.zip}"
STAND_REPORT="${ROOT_DIR}/examples/h1-kitchen/locomotion-calibration.a800.passed.json"
STAND_CHECKPOINT="${WORLD_SPEC_TASK_LOAD_RETENTION_STAND_CHECKPOINT:-${ROOT_DIR}/runs/a800/worldspec-h1-calibration-4mklr/calibration-checkpoint.zip}"
SETTLE_REPORT="${ROOT_DIR}/examples/h1-kitchen/locomotion-capture.a800.passed.json"
SETTLE_CHECKPOINT="${WORLD_SPEC_TASK_LOAD_RETENTION_SETTLE_CHECKPOINT:-${ROOT_DIR}/runs/a800/worldspec-h1-midterm-rmnnr/midterm-checkpoint.zip}"
A5CK_REPORT="${WORLD_SPEC_A5CK_REPORT:-${ROOT_DIR}/runs/a800/worldspec-h1-midterm-5nn2q/whole-body-control-report.json}"
A5CK_CONTROLLER="${WORLD_SPEC_A5CK_CONTROLLER:-${ROOT_DIR}/runs/a800/worldspec-h1-midterm-5nn2q/whole-body-controller.json}"
A5CK_TRACE="${WORLD_SPEC_A5CK_TRACE:-${ROOT_DIR}/runs/a800/worldspec-h1-midterm-5nn2q/evaluation-traces.jsonl}"
PRIOR_REPORT="${WORLD_SPEC_TASK_LOAD_PRIOR_REPORT:-${ROOT_DIR}/runs/a800/worldspec-h1-midterm-zg6kg/midterm-report.json}"
PRIOR_CHECKPOINT="${WORLD_SPEC_TASK_LOAD_PRIOR_CHECKPOINT:-${ROOT_DIR}/runs/a800/worldspec-h1-midterm-zg6kg/midterm-checkpoint.zip}"

for required in \
  "${PROFILE}" \
  "${IMAGE_BUILD_REPORT}" \
  "${SOURCE_REPORT}" \
  "${SOURCE_CHECKPOINT}" \
  "${STAND_REPORT}" \
  "${STAND_CHECKPOINT}" \
  "${SETTLE_REPORT}" \
  "${SETTLE_CHECKPOINT}" \
  "${A5CK_REPORT}" \
  "${A5CK_CONTROLLER}" \
  "${A5CK_TRACE}"; do
  if [[ ! -r "${required}" ]]; then
    printf 'ERROR: required task-load retention input is not readable: %s\n' \
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
  echo "ERROR: horizon-calibration Profile is not bound to its image build report" >&2
  exit 2
fi
export WORLD_SPEC_IMAGE_SOURCE_REVISION="${image_source_revision}"

if python3 - "${PROFILE}" <<'PY'
import json
import pathlib
import sys
raise SystemExit(
    0
    if json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))["stage"]
    == "loaded_track_settle_task_load_horizon"
    else 1
)
PY
then
  for required in "${PRIOR_REPORT}" "${PRIOR_CHECKPOINT}"; do
    if [[ ! -r "${required}" ]]; then
      printf 'ERROR: required prior-attempt evidence is not readable: %s\n' \
        "${required}" >&2
      exit 2
    fi
  done
fi

python3 - \
  "${PROFILE}" \
  "${SOURCE_REPORT}" \
  "${SOURCE_CHECKPOINT}" \
  "${STAND_REPORT}" \
  "${STAND_CHECKPOINT}" \
  "${SETTLE_REPORT}" \
  "${SETTLE_CHECKPOINT}" \
  "${A5CK_REPORT}" \
  "${A5CK_CONTROLLER}" \
  "${A5CK_TRACE}" \
  "${PRIOR_REPORT}" \
  "${PRIOR_CHECKPOINT}" <<'PY'
import hashlib
import json
import pathlib
import sys

profile = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
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

evidence = profile["a5ckEvidence"]
for label, path, key in (
    ("report", pathlib.Path(sys.argv[8]), "reportDigest"),
    ("controller", pathlib.Path(sys.argv[9]), "controllerDigest"),
    ("trace", pathlib.Path(sys.argv[10]), "traceDigest"),
):
    digest = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
    if digest != evidence[key]:
        raise SystemExit(f"A5-CK {label} digest mismatch")
trace_records = sum(
    1
    for line in pathlib.Path(sys.argv[10]).read_text(encoding="utf-8").splitlines()
    if line.strip()
)
if trace_records != evidence["traceRecordCount"]:
    raise SystemExit("A5-CK trace record count mismatch")
if profile["stage"] == "loaded_track_settle_task_load_horizon":
    prior = profile["priorAttempt"]
    report = pathlib.Path(sys.argv[11]).read_bytes()
    checkpoint = pathlib.Path(sys.argv[12]).read_bytes()
    if (
        f"sha256:{hashlib.sha256(report).hexdigest()}"
        != prior["sourceReportDigest"]
        or len(report) != prior["sourceReportSizeBytes"]
    ):
        raise SystemExit("prior attempt report identity mismatch")
    if (
        f"sha256:{hashlib.sha256(checkpoint).hexdigest()}"
        != prior["checkpointDigest"]
        or len(checkpoint) != prior["checkpointSizeBytes"]
    ):
        raise SystemExit("prior attempt checkpoint identity mismatch")
PY

export WORLD_SPEC_MIDTERM_PROFILE="${PROFILE}"
export WORLD_SPEC_WARM_START_REPORT="${SOURCE_REPORT}"
export WORLD_SPEC_WARM_START_CHECKPOINT="${SOURCE_CHECKPOINT}"
export WORLD_SPEC_RETENTION_TEACHER_REPORT="${STAND_REPORT}"
export WORLD_SPEC_RETENTION_TEACHER_CHECKPOINT="${STAND_CHECKPOINT}"
export WORLD_SPEC_SETTLE_TEACHER_REPORT="${SETTLE_REPORT}"
export WORLD_SPEC_SETTLE_TEACHER_CHECKPOINT="${SETTLE_CHECKPOINT}"

exec "${ROOT_DIR}/scripts/run_a800_h1_locomotion_midterm.sh"
