import hashlib
import json
from pathlib import Path

import pytest

from worldspec_worker import adapters
from worldspec_worker.adapters import cad_handler, openusd_handler
from worldspec_worker.cas import FileCas
from worldspec_worker.runner import WorkerFailure


def store(cas: FileCas, payload: bytes) -> str:
    digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    assert cas.put(payload) == digest
    return digest


def job(source_digest: str, profile_digest: str, path: str) -> dict:
    return {
        "id": "job://test/ingest",
        "protocolVersion": "0.1.0",
        "operation": "ingest",
        "inputs": [
            {
                "id": "artifact://test/source",
                "digest": source_digest,
                "mediaType": "application/octet-stream",
                "path": path,
            }
        ],
        "profileDigests": [profile_digest],
        "limits": {"timeoutSeconds": 10, "memoryBytes": 1024, "gpuCount": 0},
        "submittedAt": "2026-07-28T00:00:00Z",
    }


@pytest.mark.parametrize(
    ("handler", "format_name", "path"),
    [(cad_handler, "step", "part.step"), (openusd_handler, "openusd", "scene.usda")],
)
def test_optional_native_dependency_failure_is_explicit(
    tmp_path: Path,
    handler: object,
    format_name: str,
    path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cas = FileCas(tmp_path)
    source_digest = store(cas, b"invalid-but-never-opened")
    profile_digest = store(
        cas,
        json.dumps(
            {
                "id": "profile://test/ingestion",
                "profileVersion": "0.1.0",
                "formats": [format_name],
                "unitPolicy": "infer_and_review",
                "externalReferencePolicy": "reject",
                "nativePayloadPolicy": "preserve",
            }
        ).encode(),
    )
    def missing(module: str, distribution: str, version: str) -> object:
        raise WorkerFailure(
            "WORKER_DEPENDENCY_UNAVAILABLE",
            f"{distribution} is required by this isolated adapter.",
            {
                "module": module,
                "distribution": distribution,
                "requiredVersion": version,
                "executionEvidence": "not_executed",
            },
        )

    monkeypatch.setattr(adapters, "_require", missing)
    with pytest.raises(WorkerFailure) as captured:
        handler(job(source_digest, profile_digest, path), cas)  # type: ignore[operator]
    assert captured.value.code == "WORKER_DEPENDENCY_UNAVAILABLE"
    assert captured.value.details["executionEvidence"] == "not_executed"
