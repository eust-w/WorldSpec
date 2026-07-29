#!/usr/bin/env bash
set -Eeuo pipefail

readonly SOURCE_DIR=/scratch/worldspec
readonly SOURCE_CACHE=/scratch/h1-source-cache
readonly BUNDLE_DIR=/scratch/h1-bundle
readonly INPUT_DIR=/scratch/inputs
readonly RESULT_DIR=/scratch/results
readonly ARTIFACT_DIR="${RESULT_DIR}/artifacts"
readonly SOURCE_ARCHIVE=/opt/worldspec-source/worldspec.tar.gz
CURRENT_STAGE=initialization

stage() {
  CURRENT_STAGE="$1"
  printf 'WORLDSPEC_A800_FORMAL_STAGE=%s\n' "$1"
}

fail() {
  local exit_code=$?
  printf 'WORLDSPEC_A800_FORMAL_FAILED=%s\n' "${CURRENT_STAGE}"
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
  "${INPUT_DIR}" \
  "${RESULT_DIR}" \
  "${ARTIFACT_DIR}"

stage security_and_gpu_inventory
if [[ "$(id -u)" != "10001" ]] || [[ "$(id -g)" != "10001" ]]; then
  echo "ERROR: formal training did not start as uid/gid 10001" >&2
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
  echo "ERROR: launcher did not provide formal-training inputs" >&2
  exit 1
fi

stage input_verification
python - \
  "${SOURCE_DIR}/examples/h1-kitchen/locomotion-training-profile.task-v1.json" \
  "${INPUT_DIR}/midterm-report.json" \
  "${INPUT_DIR}/midterm-checkpoint.zip" \
  "${WORLD_SPEC_RUNTIME_IMAGE}" \
  "${WORLD_SPEC_PACKAGE_LOCK_DIGEST}" <<'PY'
import hashlib
import json
import pathlib
import sys

profile = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
report_payload = pathlib.Path(sys.argv[2]).read_bytes()
report = json.loads(report_payload)
checkpoint_payload = pathlib.Path(sys.argv[3]).read_bytes()
checkpoint_digest = f"sha256:{hashlib.sha256(checkpoint_payload).hexdigest()}"
source = profile["initialization"]
checkpoint = report["researchCheckpoint"]
if (
    report["formalTrainingGate"] != "passed"
    or report["qualityAssessment"]["status"] != "passed"
    or report["midtermProfileDigest"] != source["sourceProfileDigest"]
):
    raise SystemExit("midterm report does not authorize formal training")
if (
    checkpoint_digest != checkpoint["digest"]
    or len(checkpoint_payload) != checkpoint["sizeBytes"]
    or checkpoint["distribution"] != source["requiredCheckpointDistribution"]
):
    raise SystemExit("midterm checkpoint/report lineage mismatch")
if profile["runtime"]["containerDigest"] != sys.argv[4].rsplit("@", 1)[-1]:
    raise SystemExit("formal Profile container digest mismatch")
if profile["runtime"]["packageLockDigest"] != sys.argv[5]:
    raise SystemExit("formal Profile package lock mismatch")
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

stage formal_100m_training
env \
  SOURCE_DIR="${SOURCE_DIR}" \
  BUNDLE_DIR="${BUNDLE_DIR}" \
  INPUT_DIR="${INPUT_DIR}" \
  ARTIFACT_DIR="${ARTIFACT_DIR}" \
  python - <<'PY'
from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import os
import platform
from datetime import datetime, timezone
from pathlib import Path

import jax

from worldspec_h1_training.contract import digest_json, read_json
from worldspec_h1_training.runner import run_training

source_dir = Path(os.environ["SOURCE_DIR"])
input_dir = Path(os.environ["INPUT_DIR"])
artifact_dir = Path(os.environ["ARTIFACT_DIR"])
profile = read_json(
    source_dir
    / "examples"
    / "h1-kitchen"
    / "locomotion-training-profile.task-v1.json"
)
midterm_report = read_json(input_dir / "midterm-report.json")
run_training(
    profile,
    Path(os.environ["BUNDLE_DIR"]),
    artifact_dir,
    warm_start_archive=input_dir / "midterm-checkpoint.zip",
    initialization_report=midterm_report,
)
metrics = read_json(artifact_dir / "metrics.json")
manifest = read_json(artifact_dir / "policy-manifest.json")
environment_lock = read_json(artifact_dir / "environment-lock.json")

def artifact(name: str, role: str, media_type: str) -> dict:
    path = artifact_dir / name
    payload = path.read_bytes()
    digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    return {
        "id": f"artifact://a800/h1-formal/{role}/{digest.removeprefix('sha256:')}",
        "digest": digest,
        "mediaType": media_type,
        "path": name,
        "sizeBytes": len(payload),
        "role": role,
    }

artifacts = [
    artifact("policy-checkpoint.zip", "orbax_checkpoint_archive", "application/zip"),
    artifact("policy-manifest.json", "policy_manifest", "application/json"),
    artifact("evaluation-traces.jsonl", "evaluation_traces", "application/x-ndjson"),
    artifact("environment-lock.json", "environment_lock", "application/json"),
]
tests = metrics["tests"]
all_passed = len(tests) == 10 and all(test["result"] == "pass" for test in tests)
with (Path("/scratch/results") / "gpu.csv").open(encoding="utf-8") as stream:
    gpu_row = next(csv.reader(stream))
result = {
    "id": (
        "trainingresult://worldspec/h1-kitchen-task/a800-"
        + os.environ["WORLD_SPEC_PROBE_INPUT_REVISION"][:12]
    ),
    "resultVersion": "0.1.0",
    "trainingProfileDigest": digest_json(profile),
    "targetBundleDigest": profile["target"]["bundleDigest"],
    "status": "succeeded" if all_passed else "failed",
    "executionEvidence": "executed",
    "policyStatus": (
        "policy_candidate" if all_passed else "non_publishable"
    ),
    "runtime": {
        "containerDigest": profile["runtime"]["containerDigest"],
        "packageLockDigest": profile["runtime"]["packageLockDigest"],
        "backendPackage": profile["runtime"]["backendPackage"],
        "backendVersion": profile["runtime"]["backendVersion"],
        "device": str(jax.devices()[0]),
    },
    "artifacts": artifacts,
    "tests": tests,
    "diagnostics": metrics.get("diagnostics", []),
    "executionContext": {
        "probeDefinitionCommit": os.environ["WORLD_SPEC_PROBE_DEFINITION_REVISION"],
        "imageSourceCommit": os.environ["WORLD_SPEC_IMAGE_SOURCE_REVISION"],
        "probeInputCommit": os.environ["WORLD_SPEC_PROBE_INPUT_REVISION"],
        "sourceArchiveDigest": os.environ["WORLD_SPEC_SOURCE_ARCHIVE_DIGEST"],
        "containerImage": os.environ["WORLD_SPEC_RUNTIME_IMAGE"],
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
        },
        "packages": {
            name: importlib.metadata.version(name)
            for name in (
                "brax",
                "jax",
                "jaxlib",
                "mujoco",
                "mujoco-mjx",
                "orbax-checkpoint",
                "playground",
                "warp-lang",
                "worldspec-h1-training",
            )
        },
        "initialization": manifest["initialization"],
        "environmentLock": environment_lock,
    },
    "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
}
(artifact_dir / "training-result.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print("WORLDSPEC_A800_FORMAL_RESULT=" + json.dumps(result, separators=(",", ":")))
PY

stage artifact_ready
for ((attempt = 0; attempt < 7200; attempt++)); do
  if [[ -f "${RESULT_DIR}/artifact-copied" ]]; then
    break
  fi
  sleep 1
done
if [[ ! -f "${RESULT_DIR}/artifact-copied" ]]; then
  echo "ERROR: launcher did not acknowledge formal artifact retrieval" >&2
  exit 1
fi

stage completed
