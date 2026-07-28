"""Fail-closed H1 locomotion training adapter for the accepted A+R route."""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import io
import json
import os
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .cas import FileCas
from .runner import Handler, WorkerFailure


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _profile(job: dict[str, Any], cas: FileCas) -> tuple[dict[str, Any], str]:
    profiles = job.get("profileDigests", [])
    if len(profiles) != 1:
        raise WorkerFailure(
            "WORKER_PROFILE_CARDINALITY_INVALID",
            "H1 training requires exactly one LocomotionTrainingProfile digest.",
            {"actual": len(profiles), "required": 1},
        )
    try:
        profile = json.loads(cas.read(profiles[0]))
    except json.JSONDecodeError as error:
        raise WorkerFailure(
            "WORKER_PROFILE_INVALID",
            "LocomotionTrainingProfile is not valid JSON.",
        ) from error
    if profile.get("route") != "target_dynamics_retraining":
        raise WorkerFailure(
            "TRAINING_ROUTE_MISMATCH",
            "The H1 training worker only implements target-dynamics retraining.",
        )
    runtime = profile.get("runtime", {})
    expected_runtime = {
        "engine": "mujoco_mjx",
        "algorithm": "ppo",
        "targetPlatform": "linux_x86_64_nvidia",
    }
    actual_runtime = {key: runtime.get(key) for key in expected_runtime}
    if profile.get("profileVersion") != "0.1.0" or actual_runtime != expected_runtime:
        raise WorkerFailure(
            "TRAINING_PROFILE_UNSUPPORTED",
            "The H1 worker requires the WorldSpec 0.1 MuJoCo/MJX PPO profile.",
            {"expectedRuntime": expected_runtime, "actualRuntime": actual_runtime},
        )
    framework = profile.get("framework", {})
    expected_framework = {
        "name": "mujoco_playground",
        "sourceLockDigest": (
            "sha256:af7152dbf8334361cd06ba5c27367dd0cee14c5500f3218cae7bfa0497cbb3aa"
        ),
        "sourceCommit": "124a73fa3303f75a62f8fe04d329b829ed0ebdfb",
        "physicsImplementation": "warp",
        "trainer": "brax_jax_ppo",
        "referenceEnvironment": "H1JoystickGaitTracking",
        "targetEnvironmentAdapter": "worldspec_h1_loaded_velocity_v1",
        "decisionStatus": "accepted",
    }
    actual_framework = {key: framework.get(key) for key in expected_framework}
    if actual_framework != expected_framework:
        raise WorkerFailure(
            "TRAINING_FRAMEWORK_BINDING_MISMATCH",
            "The H1 worker requires the accepted MuJoCo Playground source lock.",
            {"expected": expected_framework, "actual": actual_framework},
        )
    target = profile.get("target", {})
    if target.get("gripperCount") != 1 or target.get("effector") != (
        "effector://h1/right-robotiq-2f85"
    ):
        raise WorkerFailure(
            "TRAINING_TARGET_MISMATCH",
            "The v0.1 reference training route is locked to one right Robotiq 2F-85.",
        )
    validation = profile.get("validation", {})
    settle_values = [
        validation.get("nominalDurationSeconds"),
        validation.get("settleWindowSeconds"),
        validation.get("maximumSettleLinearSpeed"),
        validation.get("maximumSettleAngularSpeed"),
    ]
    if (
        validation.get("requiredConsecutivePasses") != 5
        or any(type(value) not in (int, float) for value in settle_values)
        or settle_values[0] <= 0
        or settle_values[1] <= 0
        or settle_values[1] > settle_values[0]
        or settle_values[2] < 0
        or settle_values[3] < 0
    ):
        raise WorkerFailure(
            "TRAINING_VALIDATION_PROFILE_INVALID",
            "The v0.1 H1 route requires five runs and explicit stop-and-settle thresholds.",
        )
    expected_outputs = {
        "orbax_checkpoint_archive",
        "policy_manifest",
        "training_result",
        "evaluation_traces",
        "environment_lock",
    }
    if set(profile.get("outputs", [])) != expected_outputs:
        raise WorkerFailure(
            "TRAINING_OUTPUT_PROFILE_INVALID",
            "The H1 profile does not declare the complete native output contract.",
        )
    return profile, profiles[0]


def _conformance(job: dict[str, Any], cas: FileCas, profile: dict[str, Any]) -> dict[str, Any]:
    inputs = job.get("inputs", [])
    if len(inputs) != 1:
        raise WorkerFailure(
            "WORKER_INPUT_CARDINALITY_INVALID",
            "H1 training requires exactly one executed composition conformance input.",
            {"actual": len(inputs), "required": 1},
        )
    try:
        report = json.loads(cas.read(inputs[0]["digest"]))
    except json.JSONDecodeError as error:
        raise WorkerFailure(
            "TRAINING_CONFORMANCE_INVALID",
            "Composition conformance input is not valid JSON.",
        ) from error
    target = profile["target"]
    expected = {
        "bundleDigest": target["bundleDigest"],
        "sourceLockDigest": target["sourceLockDigest"],
        "compositionProfileDigest": target["compositionProfileDigest"],
    }
    actual = {key: report.get(key) for key in expected}
    if actual != expected:
        raise WorkerFailure(
            "TRAINING_CONFORMANCE_BINDING_MISMATCH",
            "Composition conformance does not bind the selected A+R target.",
            {"expected": expected, "actual": actual},
        )
    if (
        report.get("executionEvidence") != "executed"
        or report.get("summary", {}).get("overall") != "pass"
    ):
        raise WorkerFailure(
            "TRAINING_TARGET_NOT_LOADABLE",
            "Training requires an executed, passing native-load conformance report.",
        )
    return report


def _verify_runtime(profile: dict[str, Any], job: dict[str, Any]) -> Any:
    runtime = profile["runtime"]
    if runtime.get("status") != "locked":
        raise WorkerFailure(
            "TRAINING_RUNTIME_NOT_LOCKED",
            "The A+R route is accepted, but its Linux GPU runtime is not locked.",
            {"executionEvidence": "not_executed", "runtimeStatus": runtime.get("status")},
        )
    expected_container = runtime["containerDigest"]
    actual_container = os.environ.get("WORLDSPEC_CONTAINER_DIGEST")
    if actual_container is None:
        raise WorkerFailure(
            "WORKER_CONTAINER_BINDING_MISSING",
            "A real H1 training run requires WORLDSPEC_CONTAINER_DIGEST.",
            {"expected": expected_container, "executionEvidence": "not_executed"},
        )
    if actual_container != expected_container:
        raise WorkerFailure(
            "WORKER_CONTAINER_BINDING_MISMATCH",
            "The training OCI digest does not match the locked profile.",
            {
                "expected": expected_container,
                "actual": actual_container,
                "executionEvidence": "not_executed",
            },
        )
    expected_package_lock = runtime["packageLockDigest"]
    actual_package_lock = os.environ.get("WORLDSPEC_PACKAGE_LOCK_DIGEST")
    if actual_package_lock is None:
        raise WorkerFailure(
            "TRAINING_PACKAGE_LOCK_BINDING_MISSING",
            "A real H1 training run requires WORLDSPEC_PACKAGE_LOCK_DIGEST.",
            {"expected": expected_package_lock, "executionEvidence": "not_executed"},
        )
    if actual_package_lock != expected_package_lock:
        raise WorkerFailure(
            "TRAINING_PACKAGE_LOCK_BINDING_MISMATCH",
            "The training package lock does not match the profile.",
            {
                "expected": expected_package_lock,
                "actual": actual_package_lock,
                "executionEvidence": "not_executed",
            },
        )
    if int(job.get("limits", {}).get("gpuCount", 0)) < runtime["minimumGpuCount"]:
        raise WorkerFailure(
            "WORKER_GPU_NOT_REQUESTED",
            "The H1 training job requests fewer GPUs than the profile requires.",
            {"executionEvidence": "not_executed"},
        )
    if os.environ.get("JAX_DEFAULT_MATMUL_PRECISION") != "highest":
        raise WorkerFailure(
            "TRAINING_PRECISION_ENV_MISSING",
            "JAX_DEFAULT_MATMUL_PRECISION must be highest before worker startup.",
            {"executionEvidence": "not_executed"},
        )
    try:
        jax = importlib.import_module("jax")
    except ModuleNotFoundError as error:
        raise WorkerFailure(
            "WORKER_DEPENDENCY_UNAVAILABLE",
            "jax is absent from the locked H1 training worker.",
            {"executionEvidence": "not_executed"},
        ) from error
    if jax.default_backend() != "gpu":
        raise WorkerFailure(
            "WORKER_GPU_UNAVAILABLE",
            "JAX did not select a GPU backend in the locked H1 training worker.",
            {
                "backend": jax.default_backend(),
                "executionEvidence": "not_executed",
            },
        )
    try:
        backend = importlib.import_module(runtime["backendPackage"])
        actual_version = importlib.metadata.version(runtime["backendPackage"])
    except (ModuleNotFoundError, importlib.metadata.PackageNotFoundError) as error:
        raise WorkerFailure(
            "TRAINING_BACKEND_UNAVAILABLE",
            "The locked worldspec_h1_training backend is unavailable.",
            {"executionEvidence": "not_executed"},
        ) from error
    if actual_version != runtime["backendVersion"]:
        raise WorkerFailure(
            "TRAINING_BACKEND_VERSION_MISMATCH",
            "The training backend version does not match the profile.",
            {
                "expected": runtime["backendVersion"],
                "actual": actual_version,
                "executionEvidence": "not_executed",
            },
        )
    if not callable(getattr(backend, "run_training", None)):
        raise WorkerFailure(
            "TRAINING_BACKEND_API_INVALID",
            "worldspec_h1_training must expose run_training(profile, bundle_dir, output_dir).",
            {"executionEvidence": "not_executed"},
        )
    return jax, backend


def _safe_bundle_file(bundle: Path, logical_path: str) -> Path:
    relative = Path(logical_path)
    if not relative.parts or relative.is_absolute() or ".." in relative.parts:
        raise WorkerFailure(
            "TRAINING_BUNDLE_MANIFEST_INVALID",
            "The composition manifest contains an unsafe artifact path.",
            {"path": logical_path, "executionEvidence": "not_executed"},
        )
    candidate = (bundle / relative).resolve()
    if bundle not in candidate.parents or not candidate.is_file() or candidate.is_symlink():
        raise WorkerFailure(
            "TRAINING_BUNDLE_FILE_INVALID",
            "A composition artifact is missing, escapes the bundle, or is a symlink.",
            {"path": logical_path, "executionEvidence": "not_executed"},
        )
    return candidate


def _bundle(profile: dict[str, Any]) -> Path:
    root_value = os.environ.get("WORLDSPEC_TRAINING_BUNDLE_ROOT")
    if not root_value:
        raise WorkerFailure(
            "TRAINING_BUNDLE_CACHE_UNCONFIGURED",
            "WORLDSPEC_TRAINING_BUNDLE_ROOT is required for a real training run.",
            {"executionEvidence": "not_executed"},
        )
    root = Path(root_value).resolve()
    expected_bundle_digest = profile["target"]["bundleDigest"]
    bundle = (root / expected_bundle_digest.removeprefix("sha256:")).resolve()
    if root not in bundle.parents or not bundle.is_dir() or bundle.is_symlink():
        raise WorkerFailure(
            "TRAINING_BUNDLE_UNAVAILABLE",
            "The immutable A+R composition bundle is absent from the training cache.",
            {"bundleDigest": expected_bundle_digest, "executionEvidence": "not_executed"},
        )
    manifest_path = _safe_bundle_file(bundle, "composition-manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise WorkerFailure(
            "TRAINING_BUNDLE_MANIFEST_INVALID",
            "composition-manifest.json is not valid JSON.",
            {"executionEvidence": "not_executed"},
        ) from error
    if manifest.get("bundleDigest") != expected_bundle_digest:
        raise WorkerFailure(
            "TRAINING_BUNDLE_BINDING_MISMATCH",
            "The cached bundle does not match the target bundle digest.",
            {"executionEvidence": "not_executed"},
        )
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise WorkerFailure(
            "TRAINING_BUNDLE_MANIFEST_INVALID",
            "The composition manifest has no immutable artifact inventory.",
            {"executionEvidence": "not_executed"},
        )
    declared_paths: set[str] = set()
    for item in artifacts:
        if not isinstance(item, dict):
            raise WorkerFailure(
                "TRAINING_BUNDLE_MANIFEST_INVALID",
                "Every composition artifact must be an object.",
                {"executionEvidence": "not_executed"},
            )
        logical_path = str(item.get("path", ""))
        if logical_path in declared_paths:
            raise WorkerFailure(
                "TRAINING_BUNDLE_MANIFEST_INVALID",
                "The composition manifest contains duplicate artifact paths.",
                {"path": logical_path, "executionEvidence": "not_executed"},
            )
        declared_paths.add(logical_path)
        path = _safe_bundle_file(bundle, logical_path)
        payload = path.read_bytes()
        digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
        if digest != item.get("digest") or len(payload) != item.get("sizeBytes"):
            raise WorkerFailure(
                "TRAINING_BUNDLE_FILE_MISMATCH",
                "A composition artifact fails digest or size verification.",
                {"path": item.get("path"), "executionEvidence": "not_executed"},
            )
    actual_paths = {
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*")
        if path.is_file() and path.name != "composition-manifest.json"
    }
    if actual_paths != declared_paths:
        raise WorkerFailure(
            "TRAINING_BUNDLE_UNDECLARED_FILES",
            "The training bundle contains undeclared or omitted files.",
            {
                "undeclared": sorted(actual_paths - declared_paths),
                "missing": sorted(declared_paths - actual_paths),
                "executionEvidence": "not_executed",
            },
        )
    return bundle


def _artifact(
    cas: FileCas, payload: bytes, role: str, media_type: str, suffix: str
) -> dict[str, Any]:
    digest = cas.put(payload)
    identity = digest.removeprefix("sha256:")
    return {
        "id": f"artifact://worker/h1-training/{role}/{identity}",
        "digest": digest,
        "mediaType": media_type,
        "path": f"training/h1/{identity}.{suffix}",
        "sizeBytes": len(payload),
        "role": role,
    }


def _json_object(payload: bytes, name: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise WorkerFailure(
            "TRAINING_OUTPUT_INVALID",
            f"{name} must be a valid JSON object.",
        ) from error
    if not isinstance(value, dict):
        raise WorkerFailure(
            "TRAINING_OUTPUT_INVALID",
            f"{name} must be a JSON object.",
        )
    return value


def _validate_checkpoint_archive(payload: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            files = [item for item in archive.infolist() if not item.is_dir()]
            if not files:
                raise WorkerFailure(
                    "TRAINING_CHECKPOINT_INVALID",
                    "The Orbax checkpoint archive contains no files.",
                )
            for item in files:
                path = Path(item.filename)
                file_type = (item.external_attr >> 16) & 0o170000
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or file_type == 0o120000
                    or item.file_size == 0
                ):
                    raise WorkerFailure(
                        "TRAINING_CHECKPOINT_INVALID",
                        "The Orbax checkpoint archive contains an unsafe or empty entry.",
                        {"path": item.filename},
                    )
    except zipfile.BadZipFile as error:
        raise WorkerFailure(
            "TRAINING_CHECKPOINT_INVALID",
            "The training checkpoint is not a valid ZIP archive.",
        ) from error


def _validate_evaluation_traces(payload: bytes, required_runs: int) -> None:
    seen_runs: set[int] = set()
    for line_number, line in enumerate(payload.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise WorkerFailure(
                "TRAINING_TRACE_INVALID",
                "Evaluation traces must be newline-delimited JSON.",
                {"line": line_number},
            ) from error
        if not isinstance(record, dict) or not isinstance(record.get("run"), int):
            raise WorkerFailure(
                "TRAINING_TRACE_INVALID",
                "Every evaluation trace record must identify its nominal run.",
                {"line": line_number},
            )
        if record.get("finite") is not True or record.get("done") is not False:
            raise WorkerFailure(
                "TRAINING_TRACE_FAILED",
                "A nominal evaluation trace contains a non-finite or terminated state.",
                {"line": line_number, "run": record.get("run")},
            )
        seen_runs.add(record["run"])
    if seen_runs != set(range(required_runs)):
        raise WorkerFailure(
            "TRAINING_TRACE_RUNS_INCOMPLETE",
            "Evaluation traces do not cover all required consecutive runs.",
            {"expected": list(range(required_runs)), "actual": sorted(seen_runs)},
        )


def h1_training_handler(job: dict[str, Any], cas: FileCas) -> list[dict[str, Any]]:
    if job.get("operation") != "train":
        raise WorkerFailure(
            "WORKER_OPERATION_UNSUPPORTED",
            "The H1 locomotion training adapter only accepts train jobs.",
        )
    profile, profile_digest = _profile(job, cas)
    _conformance(job, cas, profile)
    jax, backend = _verify_runtime(profile, job)
    bundle = _bundle(profile)

    with tempfile.TemporaryDirectory(prefix="worldspec-h1-training-") as temporary:
        output = Path(temporary)
        backend.run_training(profile=profile, bundle_dir=bundle, output_dir=output)
        required = {
            "policy-checkpoint.zip": (
                "orbax_checkpoint_archive",
                "application/zip",
                "zip",
            ),
            "policy-manifest.json": (
                "policy_manifest",
                "application/json",
                "json",
            ),
            "evaluation-traces.jsonl": (
                "evaluation_traces",
                "application/x-ndjson",
                "jsonl",
            ),
            "environment-lock.json": (
                "environment_lock",
                "application/json",
                "json",
            ),
            "metrics.json": ("training_metrics", "application/json", "json"),
        }
        missing = sorted(name for name in required if not (output / name).is_file())
        if missing:
            raise WorkerFailure(
                "TRAINING_OUTPUT_MISSING",
                "The training backend did not produce the complete output contract.",
                {"missing": missing},
            )
        payloads = {name: (output / name).read_bytes() for name in required}
        if any(not payload for payload in payloads.values()):
            raise WorkerFailure(
                "TRAINING_OUTPUT_EMPTY",
                "The training backend produced an empty required artifact.",
            )
        _validate_checkpoint_archive(payloads["policy-checkpoint.zip"])
        metrics = _json_object(payloads["metrics.json"], "metrics.json")
        environment_lock = _json_object(payloads["environment-lock.json"], "environment-lock.json")
        policy_manifest = _json_object(payloads["policy-manifest.json"], "policy-manifest.json")
        tests = metrics.get("tests")
        required_runs = profile["validation"]["requiredConsecutivePasses"]
        if (
            not isinstance(tests, list)
            or len(tests) != required_runs
            or any(not isinstance(test, dict) or test.get("result") != "pass" for test in tests)
        ):
            raise WorkerFailure(
                "TRAINING_VALIDATION_FAILED",
                "A policy is publishable only when every declared nominal test passes.",
            )
        _validate_evaluation_traces(payloads["evaluation-traces.jsonl"], required_runs)
        runtime = profile["runtime"]
        expected_lock = {
            "containerDigest": runtime["containerDigest"],
            "packageLockDigest": runtime["packageLockDigest"],
            "backendPackage": runtime["backendPackage"],
            "backendVersion": runtime["backendVersion"],
        }
        actual_lock = {key: environment_lock.get(key) for key in expected_lock}
        if actual_lock != expected_lock:
            raise WorkerFailure(
                "TRAINING_ENVIRONMENT_LOCK_MISMATCH",
                "Training output is not bound to the selected runtime lock.",
                {"expected": expected_lock, "actual": actual_lock},
            )
        checkpoint_digest = (
            f"sha256:{hashlib.sha256(payloads['policy-checkpoint.zip']).hexdigest()}"
        )
        expected_policy = {
            "policyFormat": "orbax_checkpoint_zip",
            "checkpointDigest": checkpoint_digest,
            "trainingProfileDigest": profile_digest,
            "targetBundleDigest": profile["target"]["bundleDigest"],
            "frameworkSourceLockDigest": profile["framework"]["sourceLockDigest"],
            "frameworkSourceCommit": profile["framework"]["sourceCommit"],
            "physicsImplementation": profile["framework"]["physicsImplementation"],
            "trainer": profile["framework"]["trainer"],
            "targetEnvironmentAdapter": profile["framework"]["targetEnvironmentAdapter"],
            "evidenceStatus": "executed",
        }
        actual_policy = {key: policy_manifest.get(key) for key in expected_policy}
        if actual_policy != expected_policy:
            raise WorkerFailure(
                "TRAINING_POLICY_MANIFEST_MISMATCH",
                "The policy manifest is not bound to the checkpoint, target, and runtime source.",
                {"expected": expected_policy, "actual": actual_policy},
            )

        outputs = [
            _artifact(cas, payloads[name], role, media_type, suffix)
            for name, (role, media_type, suffix) in required.items()
            if name != "metrics.json"
        ]
        result = {
            "id": "trainingresult://worldspec/h1-menagerie-right-robotiq/executed",
            "resultVersion": "0.1.0",
            "trainingProfileDigest": profile_digest,
            "targetBundleDigest": profile["target"]["bundleDigest"],
            "status": "succeeded",
            "executionEvidence": "executed",
            "runtime": {
                **expected_lock,
                "device": str(jax.devices()[0]),
            },
            "artifacts": outputs,
            "tests": tests,
            "diagnostics": metrics.get("diagnostics", []),
            "generatedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        outputs.append(
            _artifact(
                cas,
                _canonical(result),
                "training_result",
                "application/vnd.worldspec.h1-training-result+json",
                "json",
            )
        )
        return outputs


TRAINING_ADAPTERS: dict[str, Handler] = {"h1-locomotion": h1_training_handler}
