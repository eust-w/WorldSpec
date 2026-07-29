#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
pointer="$(mktemp "${TMPDIR:-/tmp}/worldspec-midterm-result.XXXXXX")"

cleanup() {
  rm -f "${pointer}"
}
trap cleanup EXIT INT TERM

WORLD_SPEC_MIDTERM_RESULT_POINTER="${pointer}" \
  "${ROOT_DIR}/scripts/run_a800_h1_locomotion_midterm.sh"

if [[ ! -s "${pointer}" ]]; then
  echo "ERROR: passing midterm run did not publish its local result pointer" >&2
  exit 1
fi
midterm_result_dir="$(head -n 1 "${pointer}")"
midterm_report="${midterm_result_dir}/midterm-report.json"
midterm_checkpoint="${midterm_result_dir}/midterm-checkpoint.zip"
python3 - "${midterm_report}" <<'PY'
import json
import pathlib
import sys

report = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
if (
    report.get("formalTrainingGate") != "passed"
    or report.get("qualityAssessment", {}).get("status") != "passed"
):
    raise SystemExit("midterm gate is not passing; formal training is forbidden")
PY

WORLD_SPEC_MIDTERM_REPORT="${midterm_report}" \
WORLD_SPEC_MIDTERM_CHECKPOINT="${midterm_checkpoint}" \
  python3 "${ROOT_DIR}/scripts/run_a800_h1_locomotion_formal.py"
