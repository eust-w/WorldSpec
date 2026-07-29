#!/usr/bin/env bash
set -Eeuo pipefail

readonly SOURCE_DIR=/scratch/worldspec
readonly SOURCE_CACHE=/scratch/h1-source-cache
readonly BUNDLE_DIR=/scratch/h1-bundle
readonly MODEL_DIR=/scratch/h1-training-model
readonly INPUT_DIR=/scratch/inputs
readonly RESULT_DIR=/scratch/results
readonly ARTIFACT_DIR="${RESULT_DIR}/artifacts"
readonly SOURCE_ARCHIVE=/opt/worldspec-source/worldspec.tar.gz
CURRENT_STAGE=initialization

stage() {
  CURRENT_STAGE="$1"
  printf 'WORLDSPEC_A800_MIDTERM_STAGE=%s\n' "$1"
}

fail() {
  local exit_code=$?
  printf 'WORLDSPEC_A800_MIDTERM_FAILED=%s\n' "${CURRENT_STAGE}"
  exit "${exit_code}"
}

trap fail ERR

for required in \
  WORLD_SPEC_REPOSITORY \
  WORLD_SPEC_PROBE_DEFINITION_REVISION \
  WORLD_SPEC_IMAGE_SOURCE_REVISION \
  WORLD_SPEC_PROBE_INPUT_REVISION \
  WORLD_SPEC_RUNTIME_IMAGE \
  WORLD_SPEC_PACKAGE_LOCK_DIGEST \
  WORLD_SPEC_SOURCE_ARCHIVE_DIGEST; do
  if [[ -z "${!required:-}" ]]; then
    printf 'ERROR: %s is required\n' "${required}" >&2
    exit 2
  fi
done

mkdir -p \
  "${HOME}" \
  "${XDG_CACHE_HOME}" \
  "${TMPDIR}" \
  "${SOURCE_DIR}" \
  "${MODEL_DIR}" \
  "${INPUT_DIR}" \
  "${RESULT_DIR}" \
  "${ARTIFACT_DIR}"

stage security_and_gpu_inventory
if [[ "$(id -u)" != "10001" ]] || [[ "$(id -g)" != "10001" ]]; then
  echo "ERROR: midterm did not start as uid/gid 10001" >&2
  exit 1
fi
if touch /worldspec-root-write-test 2>/dev/null; then
  rm -f /worldspec-root-write-test
  echo "ERROR: root filesystem is writable" >&2
  exit 1
fi
nvidia-smi --query-gpu=name,driver_version,memory.total \
  --format=csv,noheader,nounits >"${RESULT_DIR}/gpu.csv"

stage source_verification
python - "${SOURCE_ARCHIVE}" "${WORLD_SPEC_SOURCE_ARCHIVE_DIGEST}" <<'PY'
import hashlib
import pathlib
import sys

archive = pathlib.Path(sys.argv[1])
actual = f"sha256:{hashlib.sha256(archive.read_bytes()).hexdigest()}"
if actual != sys.argv[2]:
    raise SystemExit(f"source archive digest mismatch: expected={sys.argv[2]} actual={actual}")
PY
tar -xzf "${SOURCE_ARCHIVE}" -C "${SOURCE_DIR}"
python - \
  "${SOURCE_DIR}/python/worldspec-h1-training/uv.lock" \
  "${WORLD_SPEC_PACKAGE_LOCK_DIGEST}" <<'PY'
import hashlib
import pathlib
import sys

actual = f"sha256:{hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest()}"
if actual != sys.argv[2]:
    raise SystemExit(f"package lock mismatch: expected={sys.argv[2]} actual={actual}")
PY

stage waiting_for_input
for ((attempt = 0; attempt < 1800; attempt++)); do
  if [[ -f "${INPUT_DIR}/input-ready" ]]; then
    break
  fi
  sleep 1
done
if [[ ! -f "${INPUT_DIR}/input-ready" ]]; then
  echo "ERROR: launcher did not provide midterm inputs" >&2
  exit 1
fi

stage input_verification
python - \
  "${SOURCE_DIR}/examples/h1-kitchen/locomotion-midterm-profile.json" \
  "${SOURCE_DIR}/examples/h1-kitchen/locomotion-calibration.a800.passed.json" \
  "${INPUT_DIR}/stand-report.json" \
  "${INPUT_DIR}/stand-checkpoint.zip" \
  "${WORLD_SPEC_RUNTIME_IMAGE}" \
  "${WORLD_SPEC_PACKAGE_LOCK_DIGEST}" <<'PY'
import hashlib
import json
import pathlib
import sys

profile = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
checked_report_path = pathlib.Path(sys.argv[2])
input_report_path = pathlib.Path(sys.argv[3])
checkpoint_path = pathlib.Path(sys.argv[4])
checked_report = checked_report_path.read_bytes()
input_report = input_report_path.read_bytes()
if input_report != checked_report:
    raise SystemExit("uploaded stand report differs from the repository-bound report")
source = profile["warmStart"]
report_digest = f"sha256:{hashlib.sha256(input_report).hexdigest()}"
checkpoint_payload = checkpoint_path.read_bytes()
checkpoint_digest = f"sha256:{hashlib.sha256(checkpoint_payload).hexdigest()}"
if report_digest != source["sourceReportDigest"]:
    raise SystemExit("stand report digest mismatch")
if (
    checkpoint_digest != source["checkpointDigest"]
    or len(checkpoint_payload) != source["checkpointSizeBytes"]
):
    raise SystemExit("stand checkpoint digest or size mismatch")
report = json.loads(input_report)
if report["qualityAssessment"]["status"] != "passed":
    raise SystemExit("stand source report is not passing")
if report["researchCheckpoint"]["digest"] != checkpoint_digest:
    raise SystemExit("stand report/checkpoint lineage mismatch")
if profile["runtime"]["containerImage"] != sys.argv[5]:
    raise SystemExit("midterm Profile container image mismatch")
if profile["runtime"]["packageLockDigest"] != sys.argv[6]:
    raise SystemExit("midterm Profile package lock mismatch")
PY

stage installed_runtime
python - <<'PY'
import importlib.metadata as metadata

expected = {
    "brax": "0.14.2",
    "flax": "0.11.2",
    "jax": "0.6.2",
    "jaxlib": "0.6.2",
    "jsonschema": "4.26.0",
    "mujoco": "3.6.0",
    "mujoco-mjx": "3.6.0",
    "orbax-checkpoint": "0.11.31",
    "playground": "0.2.0",
    "warp-lang": "1.11.0",
    "worldspec-h1-training": "0.1.0",
    "worldspec-worker": "0.1.0",
}
actual = {name: metadata.version(name) for name in expected}
if actual != expected:
    raise SystemExit(f"installed package mismatch: expected={expected!r} actual={actual!r}")
PY

stage source_materialization
python "${SOURCE_DIR}/scripts/fetch_h1_kitchen_sources.py" \
  --output "${SOURCE_CACHE}"

stage target_composition
python "${SOURCE_DIR}/scripts/compose_h1_robotiq.py" \
  --cache "${SOURCE_CACHE}" \
  --output "${BUNDLE_DIR}"

stage loaded_track_settle
env \
  SOURCE_DIR="${SOURCE_DIR}" \
  BUNDLE_DIR="${BUNDLE_DIR}" \
  MODEL_DIR="${MODEL_DIR}" \
  INPUT_DIR="${INPUT_DIR}" \
  RESULT_DIR="${RESULT_DIR}" \
  ARTIFACT_DIR="${ARTIFACT_DIR}" \
  python - <<'PY'
from __future__ import annotations

import csv
import importlib.metadata
import json
import os
import platform
from datetime import datetime, timezone
from pathlib import Path

import jax

from worldspec_h1_training.contract import read_json
from worldspec_h1_training.midterm import run_midterm_calibration

source_dir = Path(os.environ["SOURCE_DIR"])
result_dir = Path(os.environ["RESULT_DIR"])
artifact_dir = Path(os.environ["ARTIFACT_DIR"])
base_profile = read_json(
    source_dir / "examples" / "h1-kitchen" / "locomotion-training-profile.json"
)
midterm_profile = read_json(
    source_dir / "examples" / "h1-kitchen" / "locomotion-midterm-profile.json"
)
result = run_midterm_calibration(
    base_profile,
    midterm_profile,
    Path(os.environ["BUNDLE_DIR"]),
    Path(os.environ["MODEL_DIR"]),
    artifact_dir,
    Path(os.environ["INPUT_DIR"]) / "stand-checkpoint.zip",
)
with (result_dir / "gpu.csv").open(encoding="utf-8") as stream:
    gpu_row = next(csv.reader(stream))
package_names = (
    "brax",
    "flax",
    "jax",
    "jaxlib",
    "jsonschema",
    "mujoco",
    "mujoco-mjx",
    "orbax-checkpoint",
    "playground",
    "warp-lang",
    "worldspec-h1-training",
    "worldspec-worker",
)
report = {
    "id": (
        "midterm-report://worldspec/h1-loaded-track-settle/a800-"
        + os.environ["WORLD_SPEC_PROBE_INPUT_REVISION"][:12]
    ),
    "reportVersion": "0.1.0",
    "status": "completed",
    "scope": "h1_loaded_track_settle_midterm",
    "executionEvidence": "executed",
    "runtimeAcceptance": "research_midterm",
    "policyStatus": "non_publishable",
    "formalTrainingGate": (
        "passed"
        if result["qualityAssessment"]["status"] == "passed"
        else "failed"
    ),
    "probeDefinition": {
        "repository": os.environ["WORLD_SPEC_REPOSITORY"],
        "commit": os.environ["WORLD_SPEC_PROBE_DEFINITION_REVISION"],
    },
    "imageSource": {
        "repository": os.environ["WORLD_SPEC_REPOSITORY"],
        "commit": os.environ["WORLD_SPEC_IMAGE_SOURCE_REVISION"],
    },
    "probeInput": {
        "repository": os.environ["WORLD_SPEC_REPOSITORY"],
        "commit": os.environ["WORLD_SPEC_PROBE_INPUT_REVISION"],
        "materialization": "verified_git_archive",
        "archiveDigest": os.environ["WORLD_SPEC_SOURCE_ARCHIVE_DIGEST"],
    },
    "container": {
        "image": os.environ["WORLD_SPEC_RUNTIME_IMAGE"],
        "runAsUser": 10001,
        "runAsGroup": 10001,
        "readOnlyRootFilesystem": True,
        "serviceAccountTokenMounted": False,
        "secretMountCount": 0,
    },
    "platform": {
        "system": platform.system(),
        "machine": platform.machine(),
        "python": platform.python_version(),
    },
    "gpu": {
        "name": gpu_row[0].strip(),
        "driverVersion": gpu_row[1].strip(),
        "memoryMiB": int(gpu_row[2].strip()),
        "jaxBackend": jax.default_backend(),
        "jaxDevices": [str(device) for device in jax.devices()],
    },
    "packages": {name: importlib.metadata.version(name) for name in package_names},
    "packageLockDigest": os.environ["WORLD_SPEC_PACKAGE_LOCK_DIGEST"],
    **result,
    "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
}
print("WORLDSPEC_A800_MIDTERM_RESULT=" + json.dumps(report, separators=(",", ":")))
PY

stage artifact_ready
for ((attempt = 0; attempt < 3600; attempt++)); do
  if [[ -f "${RESULT_DIR}/artifact-copied" ]]; then
    break
  fi
  sleep 1
done
if [[ ! -f "${RESULT_DIR}/artifact-copied" ]]; then
  echo "ERROR: launcher did not acknowledge midterm artifact retrieval" >&2
  exit 1
fi

stage completed
