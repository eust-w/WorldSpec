#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RETENTION_PROFILE="${ROOT_DIR}/examples/h1-kitchen/locomotion-retention-profile.json"
SOURCE_REPORT="${ROOT_DIR}/examples/h1-kitchen/locomotion-transition.a800.failed.json"
SOURCE_CHECKPOINT="${WORLD_SPEC_RETENTION_WARM_START_CHECKPOINT:-${ROOT_DIR}/runs/a800/worldspec-h1-midterm-nxszt/midterm-checkpoint.zip}"
TEACHER_REPORT="${ROOT_DIR}/examples/h1-kitchen/locomotion-calibration.a800.passed.json"
TEACHER_CHECKPOINT="${WORLD_SPEC_RETENTION_TEACHER_CHECKPOINT:-${ROOT_DIR}/runs/a800/worldspec-h1-calibration-4mklr/calibration-checkpoint.zip}"

for required in \
  "${RETENTION_PROFILE}" \
  "${SOURCE_REPORT}" \
  "${SOURCE_CHECKPOINT}" \
  "${TEACHER_REPORT}" \
  "${TEACHER_CHECKPOINT}"; do
  if [[ ! -r "${required}" ]]; then
    printf 'ERROR: required retention input is not readable: %s\n' "${required}" >&2
    exit 2
  fi
done

python3 - \
  "${RETENTION_PROFILE}" \
  "${SOURCE_REPORT}" \
  "${SOURCE_CHECKPOINT}" \
  "${TEACHER_REPORT}" \
  "${TEACHER_CHECKPOINT}" <<'PY'
import hashlib
import json
import pathlib
import sys

profile = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
for spec_name, report_name, checkpoint_name in (
    ("warmStart", sys.argv[2], sys.argv[3]),
    ("retentionTeacher", sys.argv[4], sys.argv[5]),
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
PY

export WORLD_SPEC_MIDTERM_PROFILE="${RETENTION_PROFILE}"
export WORLD_SPEC_WARM_START_REPORT="${SOURCE_REPORT}"
export WORLD_SPEC_WARM_START_CHECKPOINT="${SOURCE_CHECKPOINT}"
export WORLD_SPEC_RETENTION_TEACHER_REPORT="${TEACHER_REPORT}"
export WORLD_SPEC_RETENTION_TEACHER_CHECKPOINT="${TEACHER_CHECKPOINT}"

exec "${ROOT_DIR}/scripts/run_a800_h1_locomotion_midterm.sh"
