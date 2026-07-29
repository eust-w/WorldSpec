"""Static and Linux/NVIDIA runtime preflight."""

from __future__ import annotations

import importlib
import importlib.metadata
import os
import platform
from pathlib import Path
from typing import Any

from .contract import validate_bundle, validate_profile
from .errors import TrainingError


def static_preflight(profile: dict[str, Any], bundle_dir: Path) -> dict[str, Any]:
    validate_profile(profile)
    manifest = validate_bundle(profile, bundle_dir)
    report = {
        "status": "pass",
        "executionEvidence": "static_validation",
        "bundleDigest": manifest["bundleDigest"],
        "frameworkDecision": "accepted",
        "runtimeArtifactStatus": profile["runtime"]["status"],
    }
    return report


def runtime_preflight(profile: dict[str, Any], training_model: Path) -> dict[str, Any]:
    """Require the exact runtime properties needed for an evidence-bearing run."""

    if platform.system().lower() != "linux" or platform.machine().lower() not in {
        "x86_64",
        "amd64",
    }:
        raise TrainingError(
            "TRAINING_PLATFORM_UNSUPPORTED",
            "Evidence-bearing H1 training requires Linux x86_64.",
            {"os": platform.system(), "architecture": platform.machine()},
        )
    if os.environ.get("JAX_DEFAULT_MATMUL_PRECISION") != "highest":
        raise TrainingError(
            "TRAINING_PRECISION_ENV_MISSING",
            "JAX_DEFAULT_MATMUL_PRECISION must be highest before importing JAX.",
        )
    try:
        jax = importlib.import_module("jax")
        mujoco = importlib.import_module("mujoco")
        importlib.import_module("mujoco.mjx")
        importlib.import_module("mujoco_playground")
        importlib.import_module("brax")
        importlib.import_module("orbax.checkpoint")
        importlib.import_module("warp")
    except (ImportError, OSError) as error:
        raise TrainingError(
            "TRAINING_RUNTIME_DEPENDENCY_MISSING",
            "The locked MuJoCo/MJX PPO dependency set is unavailable.",
            {"dependencyError": str(error)},
        ) from error
    if jax.default_backend() != "gpu":
        raise TrainingError(
            "TRAINING_GPU_BACKEND_UNAVAILABLE",
            "JAX must select the GPU backend for an evidence-bearing run.",
            {"backend": jax.default_backend()},
        )
    versions = {
        "mujoco": importlib.metadata.version("mujoco"),
        "mujoco-mjx": importlib.metadata.version("mujoco-mjx"),
        "playground": importlib.metadata.version("playground"),
        "jax": importlib.metadata.version("jax"),
        "brax": importlib.metadata.version("brax"),
        "warp-lang": importlib.metadata.version("warp-lang"),
    }
    expected = {
        "mujoco": "3.6.0",
        "mujoco-mjx": "3.6.0",
        "playground": "0.2.0",
        "jax": "0.6.2",
        "brax": "0.14.2",
        "warp-lang": "1.11.0",
    }
    if versions != expected:
        raise TrainingError(
            "TRAINING_RUNTIME_VERSION_MISMATCH",
            "Installed runtime versions do not match the selected source baseline.",
            {"expected": expected, "actual": versions},
        )
    model = mujoco.MjModel.from_xml_path(str(training_model))
    requested_ccd_iterations = profile["runtime"].get("ccdIterations")
    if requested_ccd_iterations is not None:
        model.opt.ccd_iterations = int(requested_ccd_iterations)
    if model.nu < 20:
        raise TrainingError(
            "TRAINING_MODEL_CONTROL_INVALID",
            "The loaded target does not expose the expected H1 and gripper controls.",
            {"actuatorCount": int(model.nu)},
        )
    from mujoco import mjx

    mjx.put_model(model, impl=profile["framework"]["physicsImplementation"])
    report = {
        "status": "pass",
        "executionEvidence": "executed",
        "jaxBackend": jax.default_backend(),
        "devices": [str(device) for device in jax.devices()],
        "versions": versions,
        "physicsImplementation": profile["framework"]["physicsImplementation"],
    }
    if requested_ccd_iterations is not None:
        report["ccdIterations"] = int(model.opt.ccd_iterations)
    return report
