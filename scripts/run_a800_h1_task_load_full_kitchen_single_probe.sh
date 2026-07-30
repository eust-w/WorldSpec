#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="${ROOT_DIR}/examples/h1-kitchen/task-load-full-kitchen-single-profile.json"
IMAGE_BUILD_REPORT="${ROOT_DIR}/examples/h1-kitchen/task-load-full-kitchen-single-image-build.a800.passed.json"
SUPERVISOR_REPORT="${ROOT_DIR}/runs/a800/worldspec-h1-midterm-69xm4/task-load-supervisor-report.json"
SUPERVISOR_CONTROLLER="${ROOT_DIR}/runs/a800/worldspec-h1-midterm-69xm4/task-load-phase-aware-supervisor.json"
SUPERVISOR_TRACE="${ROOT_DIR}/runs/a800/worldspec-h1-midterm-69xm4/evaluation-traces.jsonl"

read -r image_source_revision built_image profile_image < <(
  python3 - \
    "${IMAGE_BUILD_REPORT}" \
    "${PROFILE}" \
    "${SUPERVISOR_REPORT}" \
    "${SUPERVISOR_CONTROLLER}" \
    "${SUPERVISOR_TRACE}" <<'PY'
import hashlib
import json
import pathlib
import sys


def digest(path: pathlib.Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


build = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
profile = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
report_path = pathlib.Path(sys.argv[3])
controller_path = pathlib.Path(sys.argv[4])
trace_path = pathlib.Path(sys.argv[5])
report = json.loads(report_path.read_text(encoding="utf-8"))
evidence = profile["supervisorEvidence"]

checks = {
    "A6-S Profile is bound to its image build report": (
        build["image"] == profile["runtime"]["containerImage"]
    ),
    "A6-S source revision is bound to the runtime": (
        build["sourceCommit"] == profile["runtime"]["imageSourceRevision"]
    ),
    "A6-S report digest is bound": digest(report_path) == evidence["reportDigest"],
    "A6-S report size is bound": report_path.stat().st_size == evidence["reportSizeBytes"],
    "A6-S controller digest is bound": (
        digest(controller_path) == evidence["controllerDigest"]
    ),
    "A6-S trace digest is bound": digest(trace_path) == evidence["traceDigest"],
    "A6-S report gate passed": report["formalTaskLoadSupervisorGate"] == "passed",
    "A6-S report job is bound": report_path.parent.name == evidence["job"],
}
failures = [name for name, passed in checks.items() if not passed]
if failures:
    raise SystemExit("ERROR: " + "; ".join(failures))

print(build["sourceCommit"], build["image"], profile["runtime"]["containerImage"])
PY
)
if [[ "${built_image}" != "${profile_image}" ]]; then
  echo "ERROR: A6-K1 Profile is not bound to its image build report" >&2
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
