#!/usr/bin/env bash
set -Eeuo pipefail

readonly SOURCE_DIR=/scratch/worldspec
readonly SOURCE_CACHE=/scratch/h1-source-cache
readonly BUNDLE_DIR=/scratch/h1-bundle
readonly MODEL_DIR=/scratch/h1-training-model
readonly RESULT_DIR=/scratch/results
readonly SOURCE_ARCHIVE=/opt/worldspec-source/worldspec.tar.gz
CURRENT_STAGE=initialization

stage() {
  CURRENT_STAGE="$1"
  printf 'WORLDSPEC_A800_LOCKED_PROBE_STAGE=%s\n' "$1"
}

fail() {
  local exit_code=$?
  printf 'WORLDSPEC_A800_LOCKED_PROBE_FAILED=%s\n' "${CURRENT_STAGE}"
  exit "${exit_code}"
}

trap fail ERR

for required in \
  WORLD_SPEC_REPOSITORY \
  WORLD_SPEC_PROBE_DEFINITION_REVISION \
  WORLD_SPEC_IMAGE_SOURCE_REVISION \
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
  "${RESULT_DIR}"

stage security_and_gpu_inventory
if [[ "$(id -u)" != "10001" ]] || [[ "$(id -g)" != "10001" ]]; then
  echo "ERROR: locked runtime did not start as uid/gid 10001" >&2
  exit 1
fi
if touch /worldspec-root-write-test 2>/dev/null; then
  rm -f /worldspec-root-write-test
  echo "ERROR: root filesystem is writable" >&2
  exit 1
fi
nvidia-smi --query-gpu=name,driver_version,memory.total \
  --format=csv,noheader,nounits |
  tee "${RESULT_DIR}/gpu.csv"

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

stage installed_runtime
command -v worldspec-worker
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

stage mjx_one_step
env \
  SOURCE_DIR="${SOURCE_DIR}" \
  BUNDLE_DIR="${BUNDLE_DIR}" \
  MODEL_DIR="${MODEL_DIR}" \
  RESULT_DIR="${RESULT_DIR}" \
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
import jax.numpy as jp
import numpy as np

from worldspec_h1_training.contract import digest_json, read_json
from worldspec_h1_training.environment import make_environment
from worldspec_h1_training.model import prepare_training_model
from worldspec_h1_training.preflight import runtime_preflight, static_preflight

source_dir = Path(os.environ["SOURCE_DIR"])
bundle_dir = Path(os.environ["BUNDLE_DIR"])
model_dir = Path(os.environ["MODEL_DIR"])
result_dir = Path(os.environ["RESULT_DIR"])
profile = read_json(
    source_dir / "examples" / "h1-kitchen" / "locomotion-training-profile.json"
)

static = static_preflight(profile, bundle_dir)
training_model, derivation = prepare_training_model(profile, bundle_dir, model_dir)
runtime = runtime_preflight(profile, training_model)
environment = make_environment(profile, training_model)
state = environment.reset(jax.random.PRNGKey(profile["training"]["seed"]))
state = environment.step(state, jp.zeros(environment.action_size))
observation = np.asarray(jax.block_until_ready(state.obs["state"]))
qpos = np.asarray(jax.block_until_ready(state.data.qpos))
qvel = np.asarray(jax.block_until_ready(state.data.qvel))

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
versions = {name: importlib.metadata.version(name) for name in package_names}
report = {
    "id": (
        "runtime-report://worldspec/h1-mjx-warp/a800-locked-"
        + os.environ["WORLD_SPEC_IMAGE_SOURCE_REVISION"][:12]
    ),
    "reportVersion": "0.1.0",
    "status": "passed",
    "scope": "h1_locked_oci_runtime_probe",
    "executionEvidence": "executed",
    "runtimeAcceptance": "locked",
    "probeDefinition": {
        "repository": os.environ["WORLD_SPEC_REPOSITORY"],
        "commit": os.environ["WORLD_SPEC_PROBE_DEFINITION_REVISION"],
    },
    "imageSource": {
        "repository": os.environ["WORLD_SPEC_REPOSITORY"],
        "commit": os.environ["WORLD_SPEC_IMAGE_SOURCE_REVISION"],
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
    "packages": versions,
    "packageLockDigest": os.environ["WORLD_SPEC_PACKAGE_LOCK_DIGEST"],
    "profileDigest": digest_json(profile),
    "staticPreflight": static,
    "runtimePreflight": runtime,
    "target": {
        "sourceBundleDigest": derivation["sourceBundleDigest"],
        "derivedModelDigest": derivation["derivedModelDigest"],
        "qposSize": int(qpos.size),
        "qvelSize": int(qvel.size),
        "actuatorCount": int(environment.mj_model.nu),
    },
    "oneStep": {
        "observationSize": int(observation.size),
        "observationFinite": bool(np.isfinite(observation).all()),
        "qposFinite": bool(np.isfinite(qpos).all()),
        "qvelFinite": bool(np.isfinite(qvel).all()),
        "rewardFinite": bool(np.isfinite(np.asarray(state.reward)).all()),
    },
    "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
}
if report["gpu"]["jaxBackend"] != "gpu":
    raise SystemExit("JAX did not select the GPU backend")
finite_keys = ("observationFinite", "qposFinite", "qvelFinite", "rewardFinite")
if any(report["oneStep"].get(key) is not True for key in finite_keys):
    raise SystemExit("MJX one-step finite-state gate failed")

report_path = result_dir / "locked-runtime-report.json"
report_path.write_text(
    json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print("WORLDSPEC_A800_LOCKED_PROBE_RESULT=" + json.dumps(report, separators=(",", ":")))
PY

stage completed
