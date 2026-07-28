#!/usr/bin/env bash
set -Eeuo pipefail

readonly SOURCE_DIR=/scratch/worldspec
readonly SOURCE_CACHE=/scratch/h1-source-cache
readonly BUNDLE_DIR=/scratch/h1-bundle
readonly MODEL_DIR=/scratch/h1-training-model
readonly RESULT_DIR=/scratch/results
readonly BOOTSTRAP_DIR=/scratch/bootstrap
readonly SOURCE_ARCHIVE=/opt/worldspec-source/worldspec.tar.gz
readonly UV_VERSION=0.8.22
readonly PYTHON_VERSION=3.12.11
CURRENT_STAGE=initialization

stage() {
  CURRENT_STAGE="$1"
  printf 'WORLDSPEC_A800_SPIKE_STAGE=%s\n' "$1"
}

fail() {
  local exit_code=$?
  printf 'WORLDSPEC_A800_SPIKE_FAILED=%s\n' "${CURRENT_STAGE}"
  exit "${exit_code}"
}

trap fail ERR

for required in \
  WORLD_SPEC_REPOSITORY \
  WORLD_SPEC_REVISION \
  WORLD_SPEC_BASE_IMAGE \
  WORLD_SPEC_SOURCE_ARCHIVE_DIGEST; do
  if [[ -z "${!required:-}" ]]; then
    printf 'ERROR: %s is required\n' "${required}" >&2
    exit 2
  fi
done

mkdir -p \
  "${HOME}" \
  "${XDG_CACHE_HOME}" \
  "${UV_CACHE_DIR}" \
  "${UV_PYTHON_INSTALL_DIR}" \
  "${TMPDIR}" \
  "${RESULT_DIR}"

stage gpu_inventory
nvidia-smi --query-gpu=name,uuid,driver_version,memory.total \
  --format=csv,noheader,nounits |
  tee "${RESULT_DIR}/gpu.csv"

stage source_checkout
python3 - "${SOURCE_ARCHIVE}" "${WORLD_SPEC_SOURCE_ARCHIVE_DIGEST}" <<'PY'
import hashlib
import pathlib
import sys

archive = pathlib.Path(sys.argv[1])
expected = sys.argv[2]
actual = f"sha256:{hashlib.sha256(archive.read_bytes()).hexdigest()}"
if actual != expected:
    raise SystemExit(f"source archive digest mismatch: expected={expected} actual={actual}")
PY
mkdir -p "${SOURCE_DIR}"
tar -xzf "${SOURCE_ARCHIVE}" -C "${SOURCE_DIR}"

stage uv_bootstrap
python3 -m pip install --no-cache-dir --target "${BOOTSTRAP_DIR}" "uv==${UV_VERSION}"
PYTHONPATH="${BOOTSTRAP_DIR}" python3 -m uv python install "${PYTHON_VERSION}"

stage runtime_sync
(
  cd "${SOURCE_DIR}/python/worldspec-h1-training"
  PYTHONPATH="${BOOTSTRAP_DIR}" python3 -m uv sync \
    --frozen \
    --no-dev \
    --extra runtime \
    --python "${PYTHON_VERSION}"
)

readonly RUNTIME_PYTHON="${UV_PROJECT_ENVIRONMENT}/bin/python"
test -x "${RUNTIME_PYTHON}"
"${RUNTIME_PYTHON}" -m pip --version >/dev/null 2>&1 || true

stage source_materialization
"${RUNTIME_PYTHON}" "${SOURCE_DIR}/scripts/fetch_h1_kitchen_sources.py" \
  --output "${SOURCE_CACHE}"

stage target_composition
"${RUNTIME_PYTHON}" "${SOURCE_DIR}/scripts/compose_h1_robotiq.py" \
  --cache "${SOURCE_CACHE}" \
  --output "${BUNDLE_DIR}"

stage mjx_warp_preflight
PYTHONPATH="${SOURCE_DIR}/python/worldspec-h1-training/src" \
SOURCE_DIR="${SOURCE_DIR}" \
BUNDLE_DIR="${BUNDLE_DIR}" \
MODEL_DIR="${MODEL_DIR}" \
RESULT_DIR="${RESULT_DIR}" \
WORLD_SPEC_BASE_IMAGE="${WORLD_SPEC_BASE_IMAGE}" \
"${RUNTIME_PYTHON}" - <<'PY'
from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
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
training_model, derivation = prepare_training_model(
    profile, bundle_dir, model_dir
)
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
    "mujoco",
    "mujoco-mjx",
    "orbax-checkpoint",
    "playground",
    "warp-lang",
)
versions = {name: importlib.metadata.version(name) for name in package_names}
lock_bytes = (
    source_dir / "python" / "worldspec-h1-training" / "uv.lock"
).read_bytes()
report = {
    "reportVersion": "0.1.0",
    "status": "passed",
    "scope": "h1_mjx_warp_runtime_spike",
    "executionEvidence": "executed",
    "runtimeAcceptance": "executed_not_locked",
    "source": {
        "repository": os.environ["WORLD_SPEC_REPOSITORY"],
        "commit": os.environ["WORLD_SPEC_REVISION"],
        "materialization": "verified_git_archive",
        "archiveDigest": os.environ["WORLD_SPEC_SOURCE_ARCHIVE_DIGEST"],
    },
    "baseImage": os.environ["WORLD_SPEC_BASE_IMAGE"],
    "platform": {
        "system": platform.system(),
        "machine": platform.machine(),
        "python": platform.python_version(),
    },
    "gpu": {
        "name": gpu_row[0].strip(),
        "uuid": gpu_row[1].strip(),
        "driverVersion": gpu_row[2].strip(),
        "memoryMiB": int(gpu_row[3].strip()),
        "jaxBackend": jax.default_backend(),
        "jaxDevices": [str(device) for device in jax.devices()],
    },
    "packages": versions,
    "packageLockDigest": f"sha256:{hashlib.sha256(lock_bytes).hexdigest()}",
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
}
if report["gpu"]["jaxBackend"] != "gpu":
    raise SystemExit("JAX did not select the GPU backend")
finite_keys = (
    "observationFinite",
    "qposFinite",
    "qvelFinite",
    "rewardFinite",
)
if any(report["oneStep"].get(key) is not True for key in finite_keys):
    raise SystemExit("MJX one-step finite-state gate failed")

report_path = result_dir / "runtime-spike-report.json"
report_path.write_text(
    json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print("WORLDSPEC_A800_SPIKE_RESULT=" + json.dumps(report, separators=(",", ":")))
PY

stage completed
