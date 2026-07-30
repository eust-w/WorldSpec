#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TASK_LOAD_PROFILE="${ROOT_DIR}/examples/h1-kitchen/locomotion-task-load-profile.json"
SOURCE_REPORT="${ROOT_DIR}/examples/h1-kitchen/locomotion-transition.a800.failed.json"
SOURCE_CHECKPOINT="${WORLD_SPEC_TASK_LOAD_WARM_START_CHECKPOINT:-${ROOT_DIR}/runs/a800/worldspec-h1-midterm-nxszt/midterm-checkpoint.zip}"

for required in \
  "${TASK_LOAD_PROFILE}" \
  "${SOURCE_REPORT}" \
  "${SOURCE_CHECKPOINT}"; do
  if [[ ! -r "${required}" ]]; then
    printf 'ERROR: required task-load input is not readable: %s\n' "${required}" >&2
    exit 2
  fi
done

python3 - "${TASK_LOAD_PROFILE}" "${SOURCE_REPORT}" "${SOURCE_CHECKPOINT}" <<'PY'
import hashlib
import json
import pathlib
import sys

profile = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
spec = profile["warmStart"]
report = pathlib.Path(sys.argv[2]).read_bytes()
checkpoint = pathlib.Path(sys.argv[3]).read_bytes()
if f"sha256:{hashlib.sha256(report).hexdigest()}" != spec["sourceReportDigest"]:
    raise SystemExit("task-load warm-start report digest mismatch")
if (
    f"sha256:{hashlib.sha256(checkpoint).hexdigest()}" != spec["checkpointDigest"]
    or len(checkpoint) != spec["checkpointSizeBytes"]
):
    raise SystemExit("task-load warm-start checkpoint identity mismatch")
PY

export WORLD_SPEC_MIDTERM_PROFILE="${TASK_LOAD_PROFILE}"
export WORLD_SPEC_WARM_START_REPORT="${SOURCE_REPORT}"
export WORLD_SPEC_WARM_START_CHECKPOINT="${SOURCE_CHECKPOINT}"

exec "${ROOT_DIR}/scripts/run_a800_h1_locomotion_midterm.sh"
