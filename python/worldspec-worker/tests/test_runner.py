import hashlib
import json
from pathlib import Path

from worldspec_worker.runner import run_job


def job(digest: str) -> dict:
    return {
        "id": "job://test/compile",
        "protocolVersion": "0.1.0",
        "operation": "compile",
        "inputs": [
            {
                "id": "artifact://test/input",
                "digest": digest,
                "mediaType": "application/json",
                "path": "world.json",
            }
        ],
        "profileDigests": [],
        "limits": {"timeoutSeconds": 10, "memoryBytes": 1024, "gpuCount": 0},
        "submittedAt": "2026-07-28T00:00:00Z",
    }


def store(root: Path, payload: bytes) -> str:
    value = hashlib.sha256(payload).hexdigest()
    path = root / "objects" / "sha256" / value[:2] / value[2:]
    path.parent.mkdir(parents=True)
    path.write_bytes(payload)
    return f"sha256:{value}"


def test_missing_real_handler_fails(tmp_path: Path) -> None:
    digest = store(tmp_path, b"{}")
    result = run_job(job(digest), tmp_path)
    assert result["status"] == "failed"
    assert result["diagnostics"][0]["code"] == "WORKER_HANDLER_UNAVAILABLE"


def test_mock_is_explicit_and_digest_preserving(tmp_path: Path) -> None:
    digest = store(tmp_path, json.dumps({"hello": "world"}).encode())
    result = run_job(job(digest), tmp_path, allow_mock=True)
    assert result["status"] == "succeeded"
    assert result["outputs"][0]["digest"] == digest
    assert result["outputs"][0]["role"] == "mock_ci_echo"
