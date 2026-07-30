#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="${ROOT_DIR}/examples/h1-kitchen/locomotion-manipulation-balance-profile.json"
IMAGE_BUILD_REPORT="${ROOT_DIR}/examples/h1-kitchen/manipulation-unbounded-recovery-checkpoint-portfolio-v12-training-image-build.a800.passed.json"

for required in "${PROFILE}" "${IMAGE_BUILD_REPORT}"; do
  if [[ ! -r "${required}" ]]; then
    printf 'ERROR: manipulation-balance launch input is not readable: %s\n' \
      "${required}" >&2
    exit 2
  fi
done

read -r image_source_revision built_image profile_image package_lock < <(
  python3 - "${IMAGE_BUILD_REPORT}" "${PROFILE}" <<'PY'
import json
import pathlib
import sys

build = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
profile = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
runtime = profile["runtime"]
if build["image"] != runtime["containerImage"]:
    raise SystemExit("ERROR: manipulation-balance Profile is not bound to its image build")
if build["packageLockDigest"] != runtime["packageLockDigest"]:
    raise SystemExit("ERROR: manipulation-balance package lock/image build mismatch")
print(
    build["sourceCommit"],
    build["image"],
    runtime["containerImage"],
    runtime["packageLockDigest"],
)
PY
)
if [[ "${built_image}" != "${profile_image}" ]]; then
  echo "ERROR: manipulation-balance image identity mismatch" >&2
  exit 2
fi

export WORLD_SPEC_IMAGE_SOURCE_REVISION="${image_source_revision}"
export WORLD_SPEC_MIDTERM_PROFILE="${PROFILE}"
export WORLD_SPEC_WARM_START_REPORT="${ROOT_DIR}/examples/h1-kitchen/locomotion-manipulation-suite-isolated.a800.quality-failed-summary.json"
export WORLD_SPEC_WARM_START_CHECKPOINT="${ROOT_DIR}/runs/a800/worldspec-h1-midterm-hnhb6/midterm-checkpoint.zip"
export WORLD_SPEC_MANIPULATION_SNAPSHOT_BANK="${ROOT_DIR}/runs/a800/worldspec-h1-midterm-hnhb6/manipulation-state-bank.npz"
export WORLD_SPEC_RETENTION_TEACHER_REPORT="${ROOT_DIR}/examples/h1-kitchen/locomotion-task-load-formal.a800.failed-summary.json"
export WORLD_SPEC_RETENTION_TEACHER_CHECKPOINT="${ROOT_DIR}/runs/a800/worldspec-h1-midterm-cdbm5/midterm-checkpoint.zip"
export WORLD_SPEC_H1_RUNTIME_IMAGE="${built_image}"
export WORLD_SPEC_PACKAGE_LOCK_DIGEST="${package_lock}"

exec "${ROOT_DIR}/scripts/run_a800_h1_locomotion_midterm.sh"
