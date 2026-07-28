"""Pure contract validation for WorldSpec H1 training."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .errors import TrainingError

SOURCE_COMMIT = "124a73fa3303f75a62f8fe04d329b829ed0ebdfb"
SOURCE_LOCK_DIGEST = "sha256:af7152dbf8334361cd06ba5c27367dd0cee14c5500f3218cae7bfa0497cbb3aa"
REFERENCE_ENVIRONMENT = "H1JoystickGaitTracking"
TARGET_ENVIRONMENT = "worldspec_h1_loaded_velocity_v1"


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def digest_bytes(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def digest_json(value: object) -> str:
    return digest_bytes(canonical_bytes(value))


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TrainingError("TRAINING_JSON_INVALID", f"Cannot read JSON object: {path}") from error
    if not isinstance(value, dict):
        raise TrainingError("TRAINING_JSON_INVALID", f"Expected JSON object: {path}")
    return value


def _equal_lengths(label: str, values: list[object]) -> None:
    lengths = [len(value) for value in values if isinstance(value, list)]
    if len(lengths) != len(values) or len(set(lengths)) != 1:
        raise TrainingError(
            "TRAINING_CONTROL_CARDINALITY_INVALID",
            f"{label} control arrays must have equal lengths.",
            {"lengths": lengths},
        )


def validate_profile(profile: dict[str, Any]) -> None:
    if profile.get("profileVersion") != "0.1.0":
        raise TrainingError("TRAINING_PROFILE_UNSUPPORTED", "profileVersion must be 0.1.0.")
    if profile.get("route") != "target_dynamics_retraining":
        raise TrainingError(
            "TRAINING_ROUTE_MISMATCH",
            "Only target-dynamics retraining is accepted for v0.1.",
        )
    framework = profile.get("framework", {})
    expected_framework = {
        "name": "mujoco_playground",
        "sourceLockDigest": SOURCE_LOCK_DIGEST,
        "sourceCommit": SOURCE_COMMIT,
        "physicsImplementation": "warp",
        "trainer": "brax_jax_ppo",
        "referenceEnvironment": REFERENCE_ENVIRONMENT,
        "targetEnvironmentAdapter": TARGET_ENVIRONMENT,
        "decisionStatus": "accepted",
    }
    actual_framework = {key: framework.get(key) for key in expected_framework}
    if actual_framework != expected_framework:
        raise TrainingError(
            "TRAINING_FRAMEWORK_BINDING_MISMATCH",
            "The profile is not bound to the accepted MuJoCo Playground source.",
            {"expected": expected_framework, "actual": actual_framework},
        )
    runtime = profile.get("runtime", {})
    expected_runtime = {
        "engine": "mujoco_mjx",
        "algorithm": "ppo",
        "targetPlatform": "linux_x86_64_nvidia",
        "mjxCapacity": {
            "activeContactsPerEnvironment": 16,
            "ccdContactsPerEnvironment": 8,
            "njmax": 128,
        },
    }
    actual_runtime = {key: runtime.get(key) for key in expected_runtime}
    if actual_runtime != expected_runtime:
        raise TrainingError(
            "TRAINING_RUNTIME_PROFILE_INVALID",
            "The runtime must be MuJoCo/MJX PPO on Linux x86_64 NVIDIA.",
            {"expected": expected_runtime, "actual": actual_runtime},
        )
    target = profile.get("target", {})
    if (
        target.get("gripperCount") != 1
        or target.get("effector") != "effector://h1/right-robotiq-2f85"
    ):
        raise TrainingError(
            "TRAINING_TARGET_MISMATCH",
            "The reference route is locked to one right Robotiq 2F-85.",
        )
    control = profile.get("control", {})
    policy = [
        control.get("policyJoints"),
        control.get("policyActuators"),
        control.get("policyKps"),
        control.get("policyKds"),
        control.get("defaultAngles"),
    ]
    held = [
        control.get("heldJoints"),
        control.get("heldActuators"),
        control.get("heldTargets"),
        control.get("heldKps"),
        control.get("heldKds"),
    ]
    _equal_lengths("policy", policy)
    _equal_lengths("held", held)
    if len(policy[0]) != 10 or len(held[0]) != 9:
        raise TrainingError(
            "TRAINING_CONTROL_CARDINALITY_INVALID",
            "The v0.1 reference controller requires 10 policy and 9 held joints.",
        )
    if set(policy[0]) & set(held[0]):
        raise TrainingError(
            "TRAINING_CONTROL_OVERLAP",
            "A joint cannot be policy-controlled and held at the same time.",
        )
    if (
        control.get("gripperActuators") != ["right_gripper_fingers_actuator"]
        or len(control.get("gripperCommands", [])) != 1
    ):
        raise TrainingError(
            "TRAINING_GRIPPER_CONTROL_INVALID",
            "The reference profile must bind one right gripper command.",
        )
    training = profile.get("training", {})
    if training.get("matmulPrecision") != "highest":
        raise TrainingError(
            "TRAINING_PRECISION_INVALID",
            "Ampere reference training requires highest JAX matmul precision.",
        )
    validation = profile.get("validation", {})
    duration = validation.get("nominalDurationSeconds")
    settle_window = validation.get("settleWindowSeconds")
    settle_linear = validation.get("maximumSettleLinearSpeed")
    settle_angular = validation.get("maximumSettleAngularSpeed")
    if (
        validation.get("requiredConsecutivePasses") != 5
        or any(
            type(value) not in (int, float)
            for value in (duration, settle_window, settle_linear, settle_angular)
        )
        or duration <= 0
        or settle_window <= 0
        or settle_window > duration
        or settle_linear < 0
        or settle_angular < 0
    ):
        raise TrainingError(
            "TRAINING_VALIDATION_PROFILE_INVALID",
            "The v0.1 route requires five runs and explicit stop-and-settle thresholds.",
        )
    expected_outputs = {
        "orbax_checkpoint_archive",
        "policy_manifest",
        "training_result",
        "evaluation_traces",
        "environment_lock",
    }
    if set(profile.get("outputs", [])) != expected_outputs:
        raise TrainingError(
            "TRAINING_OUTPUT_PROFILE_INVALID",
            "The profile does not declare the complete native output contract.",
        )


def safe_artifact(bundle_dir: Path, logical_path: str) -> Path:
    relative = Path(logical_path)
    if not relative.parts or relative.is_absolute() or ".." in relative.parts:
        raise TrainingError(
            "TRAINING_BUNDLE_PATH_INVALID",
            "Bundle artifacts must use safe relative paths.",
            {"path": logical_path},
        )
    candidate = (bundle_dir / relative).resolve()
    if bundle_dir not in candidate.parents or not candidate.is_file() or candidate.is_symlink():
        raise TrainingError(
            "TRAINING_BUNDLE_FILE_INVALID",
            "Bundle artifact is missing, escapes the bundle, or is a symlink.",
            {"path": logical_path},
        )
    return candidate


def validate_bundle(profile: dict[str, Any], bundle_dir: Path) -> dict[str, Any]:
    bundle_dir = bundle_dir.resolve(strict=True)
    manifest = read_json(safe_artifact(bundle_dir, "composition-manifest.json"))
    target = profile["target"]
    expected = {
        "bundleDigest": target["bundleDigest"],
        "sourceLockDigest": target["sourceLockDigest"],
        "compositionProfileDigest": target["compositionProfileDigest"],
    }
    actual = {key: manifest.get(key) for key in expected}
    if actual != expected:
        raise TrainingError(
            "TRAINING_BUNDLE_BINDING_MISMATCH",
            "Composition bundle does not match the training target.",
            {"expected": expected, "actual": actual},
        )
    inventory = manifest.get("artifacts")
    if not isinstance(inventory, list) or not inventory:
        raise TrainingError(
            "TRAINING_BUNDLE_MANIFEST_INVALID",
            "Composition manifest has no immutable artifact inventory.",
        )
    declared: set[str] = set()
    for item in inventory:
        if not isinstance(item, dict):
            raise TrainingError(
                "TRAINING_BUNDLE_MANIFEST_INVALID",
                "Every bundle artifact entry must be an object.",
            )
        logical_path = item.get("path")
        if not isinstance(logical_path, str) or logical_path in declared:
            raise TrainingError(
                "TRAINING_BUNDLE_MANIFEST_INVALID",
                "Artifact paths must be unique strings.",
            )
        declared.add(logical_path)
        path = safe_artifact(bundle_dir, logical_path)
        payload = path.read_bytes()
        if digest_bytes(payload) != item.get("digest") or len(payload) != item.get("sizeBytes"):
            raise TrainingError(
                "TRAINING_BUNDLE_FILE_MISMATCH",
                "Artifact digest or size does not match the composition manifest.",
                {"path": logical_path},
            )
    actual_files = {
        path.relative_to(bundle_dir).as_posix()
        for path in bundle_dir.rglob("*")
        if path.is_file() and path.name != "composition-manifest.json"
    }
    if actual_files != declared:
        raise TrainingError(
            "TRAINING_BUNDLE_UNDECLARED_FILES",
            "Bundle inventory is not complete.",
            {
                "undeclared": sorted(actual_files - declared),
                "missing": sorted(declared - actual_files),
            },
        )
    return manifest
