"""Fail-closed H1 locomotion training adapter for the accepted A+R route."""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import os
import tempfile
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
    target = profile.get("target", {})
    if target.get("gripperCount") != 1 or target.get("effector") != (
        "effector://h1/right-robotiq-2f85"
    ):
        raise WorkerFailure(
            "TRAINING_TARGET_MISMATCH",
            "The v0.1 reference training route is locked to one right Robotiq 2F-85.",
        )
    return profile, profiles[0]


def _conformance(
    job: dict[str, Any], cas: FileCas, profile: dict[str, Any]
) -> dict[str, Any]:
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
    try:
        torch = importlib.import_module("torch")
    except ModuleNotFoundError as error:
        raise WorkerFailure(
            "WORKER_DEPENDENCY_UNAVAILABLE",
            "torch is absent from the locked H1 training worker.",
            {"executionEvidence": "not_executed"},
        ) from error
    if not torch.cuda.is_available():
        raise WorkerFailure(
            "WORKER_GPU_UNAVAILABLE",
            "CUDA is unavailable in the locked H1 training worker.",
            {"executionEvidence": "not_executed"},
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
    return torch, backend


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


def h1_training_handler(job: dict[str, Any], cas: FileCas) -> list[dict[str, Any]]:
    if job.get("operation") != "train":
        raise WorkerFailure(
            "WORKER_OPERATION_UNSUPPORTED",
            "The H1 locomotion training adapter only accepts train jobs.",
        )
    profile, profile_digest = _profile(job, cas)
    _conformance(job, cas, profile)
    torch, backend = _verify_runtime(profile, job)
    bundle = _bundle(profile)

    with tempfile.TemporaryDirectory(prefix="worldspec-h1-training-") as temporary:
        output = Path(temporary)
        backend.run_training(profile=profile, bundle_dir=bundle, output_dir=output)
        required = {
            "policy.pt": ("torchscript_policy", "application/octet-stream", "pt"),
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
        try:
            metrics = json.loads(payloads["metrics.json"])
            environment_lock = json.loads(payloads["environment-lock.json"])
        except json.JSONDecodeError as error:
            raise WorkerFailure(
                "TRAINING_OUTPUT_INVALID",
                "Training metrics and environment lock must be valid JSON.",
            ) from error
        tests = metrics.get("tests")
        if (
            not isinstance(tests, list)
            or not tests
            or any(
                not isinstance(test, dict) or test.get("result") != "pass"
                for test in tests
            )
        ):
            raise WorkerFailure(
                "TRAINING_VALIDATION_FAILED",
                "A policy is publishable only when every declared nominal test passes.",
            )
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
                "device": str(torch.cuda.get_device_name(0)),
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
