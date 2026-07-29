#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TRANSITION_PROFILE="${ROOT_DIR}/examples/h1-kitchen/locomotion-transition-profile.json"
SOURCE_REPORT="${ROOT_DIR}/examples/h1-kitchen/locomotion-midterm.a800.failed.json"
SOURCE_CHECKPOINT="${WORLD_SPEC_TRANSITION_CHECKPOINT:-${ROOT_DIR}/runs/a800/worldspec-h1-midterm-h7l7l/midterm-checkpoint.zip}"
CCD_REPORT="${WORLD_SPEC_CCD_SPIKE_REPORT:-}"

for required in \
  "${TRANSITION_PROFILE}" \
  "${SOURCE_REPORT}" \
  "${SOURCE_CHECKPOINT}" \
  "${CCD_REPORT}"; do
  if [[ -z "${required}" ]] || [[ ! -r "${required}" ]]; then
    printf 'ERROR: required transition input is not readable: %s\n' "${required:-unset}" >&2
    exit 2
  fi
done

python3 - "${TRANSITION_PROFILE}" "${CCD_REPORT}" <<'PY'
import json
import hashlib
import pathlib
import sys

profile = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
report = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
expected = profile["runtime"]["ccdIterations"]
profile_digest = "sha256:" + hashlib.sha256(
    json.dumps(
        profile,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
).hexdigest()
if (
    report.get("status") != "passed"
    or report.get("runtimeAcceptance") != "numeric_spike"
    or report.get("canonicalTrainingStatus") != "not_executed"
    or report.get("transitionProfileDigest") != profile_digest
    or report.get("container", {}).get("image")
    != profile["runtime"]["containerImage"]
    or report.get("runtimePreflight", {}).get("ccdIterations") != expected
    or report.get("target", {}).get("appliedCcdIterations") != expected
    or report.get("candidate")
    != {
        "baselineIterations": 35,
        "candidateIterations": 50,
        "numEnvs": 4096,
        "rolloutSteps": 200,
        "selectionPolicy": "single_predeclared_candidate",
    }
    or report.get("logDiagnostics", {}).get("clean") is not True
):
    raise SystemExit("CCD numeric spike did not release transition calibration")
PY

export WORLD_SPEC_MIDTERM_PROFILE="${TRANSITION_PROFILE}"
export WORLD_SPEC_WARM_START_REPORT="${SOURCE_REPORT}"
export WORLD_SPEC_WARM_START_CHECKPOINT="${SOURCE_CHECKPOINT}"

exec "${ROOT_DIR}/scripts/run_a800_h1_locomotion_midterm.sh"
