#!/usr/bin/env bash
set -Eeuo pipefail

readonly SOURCE_DIR=/scratch/worldspec
readonly SOURCE_CACHE=/scratch/h1-source-cache
readonly BUNDLE_DIR=/scratch/h1-bundle
readonly MODEL_DIR=/scratch/h1-training-model
readonly RESULT_DIR=/scratch/results
readonly SOURCE_ARCHIVE=/opt/worldspec-source/worldspec.tar.gz
readonly PROBE_MODE="${WORLD_SPEC_PROBE_MODE:-locked_runtime}"
if [[ "${PROBE_MODE}" == "capacity_scale" ]]; then
  readonly LOG_PREFIX=WORLDSPEC_A800_CAPACITY_SCALE
elif [[ "${PROBE_MODE}" == "ccd_iterations" ]]; then
  readonly LOG_PREFIX=WORLDSPEC_A800_CCD_ITERATIONS
else
  readonly LOG_PREFIX=WORLDSPEC_A800_LOCKED_PROBE
fi
CURRENT_STAGE=initialization

stage() {
  CURRENT_STAGE="$1"
  printf '%s_STAGE=%s\n' "${LOG_PREFIX}" "$1"
}

fail() {
  local exit_code=$?
  printf '%s_FAILED=%s\n' "${LOG_PREFIX}" "${CURRENT_STAGE}"
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
if [[ "${PROBE_MODE}" != "locked_runtime" ]] &&
  [[ "${PROBE_MODE}" != "capacity_scale" ]] &&
  [[ "${PROBE_MODE}" != "ccd_iterations" ]]; then
  printf 'ERROR: unsupported WORLD_SPEC_PROBE_MODE: %s\n' "${PROBE_MODE}" >&2
  exit 2
fi

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
  WORLD_SPEC_PROBE_MODE="${PROBE_MODE}" \
  python - <<'PY'
from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import os
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

import jax
import jax.numpy as jp
import numpy as np
from mujoco_playground import wrapper

from worldspec_h1_training.contract import digest_json, read_json
from worldspec_h1_training.environment import make_environment
from worldspec_h1_training.midterm import make_transition_training_profile
from worldspec_h1_training.model import prepare_training_model
from worldspec_h1_training.preflight import runtime_preflight, static_preflight

source_dir = Path(os.environ["SOURCE_DIR"])
bundle_dir = Path(os.environ["BUNDLE_DIR"])
model_dir = Path(os.environ["MODEL_DIR"])
result_dir = Path(os.environ["RESULT_DIR"])
base_profile = read_json(
    source_dir / "examples" / "h1-kitchen" / "locomotion-training-profile.json"
)
probe_mode = os.environ["WORLD_SPEC_PROBE_MODE"]
if probe_mode == "ccd_iterations":
    transition_profile = read_json(
        source_dir / "examples" / "h1-kitchen" / "locomotion-transition-profile.json"
    )
    profile = make_transition_training_profile(base_profile, transition_profile)
else:
    transition_profile = None
    profile = base_profile

static = static_preflight(base_profile, bundle_dir)
training_model, derivation = prepare_training_model(base_profile, bundle_dir, model_dir)
runtime = runtime_preflight(profile, training_model)
environment = make_environment(profile, training_model)
if probe_mode in {"capacity_scale", "ccd_iterations"}:
    num_envs = (
        4096
        if probe_mode == "ccd_iterations"
        else profile["training"]["numEnvs"]
    )
    wrapped = wrapper.wrap_for_brax_training(
        environment,
        episode_length=profile["training"]["episodeLength"],
        action_repeat=1,
    )
    reset = jax.jit(wrapped.reset)
    step = jax.jit(wrapped.step)
    keys = jax.random.split(
        jax.random.PRNGKey(profile["training"]["seed"]),
        num_envs,
    )
    reset_started = time.monotonic()
    state = reset(keys)
    jax.block_until_ready(state.obs["state"])
    reset_elapsed = time.monotonic() - reset_started
    action_rng = jax.random.PRNGKey(profile["training"]["seed"] + 1)
    action = (
        jax.random.uniform(
            action_rng,
            shape=(num_envs, wrapped.action_size),
            minval=-0.25,
            maxval=0.25,
        )
        if probe_mode == "ccd_iterations"
        else jp.zeros((num_envs, wrapped.action_size))
    )
    step_started = time.monotonic()
    rollout_steps = 200 if probe_mode == "ccd_iterations" else 1
    for _ in range(rollout_steps):
        state = step(state, action)
        jax.block_until_ready(state.obs["state"])
    step_elapsed = time.monotonic() - step_started
else:
    num_envs = 1
    reset_started = time.monotonic()
    state = environment.reset(jax.random.PRNGKey(profile["training"]["seed"]))
    reset_elapsed = time.monotonic() - reset_started
    step_started = time.monotonic()
    state = environment.step(state, jp.zeros(environment.action_size))
    step_elapsed = time.monotonic() - step_started
observation = np.asarray(jax.block_until_ready(state.obs["state"]))
qpos = np.asarray(jax.block_until_ready(state.data.qpos))
qvel = np.asarray(jax.block_until_ready(state.data.qvel))
reward = np.asarray(jax.block_until_ready(state.reward))
done = np.asarray(jax.block_until_ready(state.done))

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
capacity = profile["runtime"]["mjxCapacity"]
common_report = {
    "reportVersion": "0.1.0",
    "status": "passed",
    "executionEvidence": "executed",
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
    "packages": versions,
    "packageLockDigest": os.environ["WORLD_SPEC_PACKAGE_LOCK_DIGEST"],
    "profileDigest": digest_json(profile),
    "staticPreflight": static,
    "runtimePreflight": runtime,
}
finite = {
    "observationFinite": bool(np.isfinite(observation).all()),
    "qposFinite": bool(np.isfinite(qpos).all()),
    "qvelFinite": bool(np.isfinite(qvel).all()),
    "rewardFinite": bool(np.isfinite(reward).all()),
}
if probe_mode == "capacity_scale":
    report = {
        **common_report,
        "id": (
            "capacity-report://worldspec/h1-mjx-warp/a800-"
            + os.environ["WORLD_SPEC_PROBE_INPUT_REVISION"][:12]
        ),
        "scope": "h1_mjx_capacity_scale_probe",
        "runtimeAcceptance": "capacity_scale_preflight",
        "canonicalTrainingStatus": "not_executed",
        "runtimeCapacity": {
            **capacity,
            "numEnvs": num_envs,
            "effectiveNaconmax": capacity["activeContactsPerEnvironment"] * num_envs,
            "effectiveNaccdmax": capacity["ccdContactsPerEnvironment"] * num_envs,
            "naconmaxSemantics": "shared_across_all_worlds",
            "naccdmaxSemantics": "shared_across_all_worlds",
            "njmaxSemantics": "per_world",
        },
        "target": {
            "sourceBundleDigest": derivation["sourceBundleDigest"],
            "derivedModelDigest": derivation["derivedModelDigest"],
            "singleEnvironmentQposSize": int(environment.mj_model.nq),
            "singleEnvironmentQvelSize": int(environment.mj_model.nv),
            "actuatorCount": int(environment.mj_model.nu),
        },
        "batchedOneStep": {
            "numEnvs": num_envs,
            "observationShape": list(observation.shape),
            "qposShape": list(qpos.shape),
            "qvelShape": list(qvel.shape),
            "rewardShape": list(reward.shape),
            "doneShape": list(done.shape),
            "resetElapsedSeconds": reset_elapsed,
            "stepElapsedSeconds": step_elapsed,
            **finite,
        },
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    report_path = result_dir / "capacity-scale-report.json"
    result_prefix = "WORLDSPEC_A800_CAPACITY_SCALE_RESULT="
elif probe_mode == "ccd_iterations":
    report = {
        **common_report,
        "id": (
            "ccd-report://worldspec/h1-mjx-warp/a800-"
            + os.environ["WORLD_SPEC_PROBE_INPUT_REVISION"][:12]
        ),
        "scope": "h1_ccd_iterations_numeric_spike",
        "runtimeAcceptance": "numeric_spike",
        "canonicalTrainingStatus": "not_executed",
        "candidate": {
            "baselineIterations": 35,
            "candidateIterations": 50,
            "numEnvs": num_envs,
            "rolloutSteps": rollout_steps,
            "selectionPolicy": "single_predeclared_candidate",
        },
        "target": {
            "sourceBundleDigest": derivation["sourceBundleDigest"],
            "derivedModelDigest": derivation["derivedModelDigest"],
            "singleEnvironmentQposSize": int(environment.mj_model.nq),
            "singleEnvironmentQvelSize": int(environment.mj_model.nv),
            "actuatorCount": int(environment.mj_model.nu),
            "appliedCcdIterations": int(environment.ccd_iterations),
        },
        "batchedRollout": {
            "numEnvs": num_envs,
            "rolloutSteps": rollout_steps,
            "observationShape": list(observation.shape),
            "qposShape": list(qpos.shape),
            "qvelShape": list(qvel.shape),
            "rewardShape": list(reward.shape),
            "doneShape": list(done.shape),
            "resetElapsedSeconds": reset_elapsed,
            "rolloutElapsedSeconds": step_elapsed,
            "meanStepElapsedSeconds": step_elapsed / rollout_steps,
            **finite,
        },
        "transitionProfileDigest": digest_json(transition_profile),
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    report_path = result_dir / "ccd-iterations-spike-report.json"
    result_prefix = "WORLDSPEC_A800_CCD_ITERATIONS_RESULT="
else:
    report = {
        **common_report,
        "id": (
            "runtime-report://worldspec/h1-mjx-warp/a800-locked-"
            + os.environ["WORLD_SPEC_IMAGE_SOURCE_REVISION"][:12]
        ),
        "scope": "h1_locked_oci_runtime_probe",
        "runtimeAcceptance": "locked",
        "target": {
            "sourceBundleDigest": derivation["sourceBundleDigest"],
            "derivedModelDigest": derivation["derivedModelDigest"],
            "qposSize": int(qpos.size),
            "qvelSize": int(qvel.size),
            "actuatorCount": int(environment.mj_model.nu),
        },
        "oneStep": {
            "observationSize": int(observation.size),
            **finite,
        },
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    report_path = result_dir / "locked-runtime-report.json"
    result_prefix = "WORLDSPEC_A800_LOCKED_PROBE_RESULT="
if report["gpu"]["jaxBackend"] != "gpu":
    raise SystemExit("JAX did not select the GPU backend")
finite_keys = ("observationFinite", "qposFinite", "qvelFinite", "rewardFinite")
finite_report = (
    report["batchedOneStep"]
    if probe_mode == "capacity_scale"
    else report["batchedRollout"]
    if probe_mode == "ccd_iterations"
    else report["oneStep"]
)
if any(finite_report.get(key) is not True for key in finite_keys):
    raise SystemExit("MJX one-step finite-state gate failed")

report_path.write_text(
    json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(result_prefix + json.dumps(report, separators=(",", ":")))
PY

stage completed
