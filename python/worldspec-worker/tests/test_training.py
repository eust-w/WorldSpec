import json
from pathlib import Path

import pytest

from worldspec_worker import training
from worldspec_worker.cas import FileCas
from worldspec_worker.runner import WorkerFailure
from worldspec_worker.training import h1_training_handler

SOURCE_LOCK = f"sha256:{'a' * 64}"
COMPOSITION_PROFILE = f"sha256:{'b' * 64}"
BUNDLE = f"sha256:{'c' * 64}"


def profile(runtime_status: str = "planned") -> dict:
    runtime = {
        "engine": "mujoco_mjx",
        "algorithm": "ppo",
        "status": runtime_status,
        "targetPlatform": "linux_x86_64_nvidia",
        "minimumGpuCount": 1,
    }
    if runtime_status == "locked":
        runtime.update(
            {
                "containerDigest": f"sha256:{'d' * 64}",
                "backendPackage": "worldspec_h1_training",
                "backendVersion": "0.1.0",
                "packageLockDigest": f"sha256:{'e' * 64}",
            }
        )
    return {
        "profileVersion": "0.1.0",
        "route": "target_dynamics_retraining",
        "target": {
            "sourceLockDigest": SOURCE_LOCK,
            "compositionProfileDigest": COMPOSITION_PROFILE,
            "bundleDigest": BUNDLE,
            "effector": "effector://h1/right-robotiq-2f85",
            "gripperCount": 1,
        },
        "runtime": runtime,
    }


def conformance(bundle: str = BUNDLE) -> dict:
    return {
        "bundleDigest": bundle,
        "sourceLockDigest": SOURCE_LOCK,
        "compositionProfileDigest": COMPOSITION_PROFILE,
        "executionEvidence": "executed",
        "summary": {"overall": "pass"},
    }


def job(cas: FileCas, training_profile: dict, report: dict) -> dict:
    profile_digest = cas.put(json.dumps(training_profile).encode())
    report_digest = cas.put(json.dumps(report).encode())
    return {
        "id": "job://test/h1-train",
        "protocolVersion": "0.1.0",
        "operation": "train",
        "inputs": [
            {
                "id": "artifact://test/h1-conformance",
                "digest": report_digest,
                "mediaType": "application/json",
                "path": "native-load-conformance.json",
            }
        ],
        "profileDigests": [profile_digest],
        "limits": {"timeoutSeconds": 10, "memoryBytes": 1024, "gpuCount": 1},
        "submittedAt": "2026-07-28T00:00:00Z",
    }


def test_planned_training_profile_fails_closed(tmp_path: Path) -> None:
    cas = FileCas(tmp_path)
    with pytest.raises(WorkerFailure) as captured:
        h1_training_handler(job(cas, profile(), conformance()), cas)
    assert captured.value.code == "TRAINING_RUNTIME_NOT_LOCKED"
    assert captured.value.details["executionEvidence"] == "not_executed"


def test_training_rejects_wrong_target_conformance(tmp_path: Path) -> None:
    cas = FileCas(tmp_path)
    wrong = f"sha256:{'f' * 64}"
    with pytest.raises(WorkerFailure) as captured:
        h1_training_handler(job(cas, profile(), conformance(wrong)), cas)
    assert captured.value.code == "TRAINING_CONFORMANCE_BINDING_MISMATCH"


def test_locked_training_requires_exact_container_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cas = FileCas(tmp_path)
    training_job = job(cas, profile("locked"), conformance())
    monkeypatch.delenv("WORLDSPEC_CONTAINER_DIGEST", raising=False)
    with pytest.raises(WorkerFailure) as captured:
        h1_training_handler(training_job, cas)
    assert captured.value.code == "WORKER_CONTAINER_BINDING_MISSING"

    monkeypatch.setenv("WORLDSPEC_CONTAINER_DIGEST", f"sha256:{'f' * 64}")
    with pytest.raises(WorkerFailure) as mismatch:
        h1_training_handler(training_job, cas)
    assert mismatch.value.code == "WORKER_CONTAINER_BINDING_MISMATCH"


def test_training_is_locked_to_right_single_gripper(tmp_path: Path) -> None:
    cas = FileCas(tmp_path)
    invalid = profile()
    invalid["target"]["gripperCount"] = 2
    with pytest.raises(WorkerFailure) as captured:
        h1_training_handler(job(cas, invalid, conformance()), cas)
    assert captured.value.code == "TRAINING_TARGET_MISMATCH"


def test_locked_backend_output_contract_is_digest_addressed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cas = FileCas(tmp_path / "cas")
    locked = profile("locked")
    training_job = job(cas, locked, conformance())

    class FakeCuda:
        @staticmethod
        def get_device_name(_index: int) -> str:
            return "CI fake device - not execution evidence"

    class FakeTorch:
        cuda = FakeCuda()

    class FakeBackend:
        @staticmethod
        def run_training(
            profile: dict, bundle_dir: Path, output_dir: Path
        ) -> None:
            assert profile["target"]["bundleDigest"] == BUNDLE
            assert bundle_dir.name == "verified-bundle"
            (output_dir / "policy.pt").write_bytes(b"policy")
            (output_dir / "evaluation-traces.jsonl").write_text(
                '{"result":"pass"}\n', encoding="utf-8"
            )
            (output_dir / "environment-lock.json").write_text(
                json.dumps(
                    {
                        "containerDigest": locked["runtime"]["containerDigest"],
                        "packageLockDigest": locked["runtime"]["packageLockDigest"],
                        "backendPackage": locked["runtime"]["backendPackage"],
                        "backendVersion": locked["runtime"]["backendVersion"],
                    }
                ),
                encoding="utf-8",
            )
            (output_dir / "metrics.json").write_text(
                json.dumps(
                    {
                        "tests": [
                            {
                                "id": "test://worldspec/h1-training/ci-contract",
                                "result": "pass",
                                "metrics": {"mockContractOnly": True},
                            }
                        ],
                        "diagnostics": [],
                    }
                ),
                encoding="utf-8",
            )

    bundle = tmp_path / "verified-bundle"
    bundle.mkdir()
    monkeypatch.setattr(
        training, "_verify_runtime", lambda _profile, _job: (FakeTorch(), FakeBackend())
    )
    monkeypatch.setattr(training, "_bundle", lambda _profile: bundle)

    outputs = h1_training_handler(training_job, cas)
    assert [item["role"] for item in outputs] == [
        "torchscript_policy",
        "evaluation_traces",
        "environment_lock",
        "training_result",
    ]
    result = json.loads(cas.read(outputs[-1]["digest"]))
    assert result["status"] == "succeeded"
    assert result["executionEvidence"] == "executed"
    assert result["targetBundleDigest"] == BUNDLE
    assert len(result["artifacts"]) == 3
