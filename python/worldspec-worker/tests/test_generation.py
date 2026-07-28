import hashlib
import json
from pathlib import Path

import pytest

from worldspec_worker.cas import FileCas
from worldspec_worker.generation import _model_cache, nerfstudio_handler, trellis2_handler
from worldspec_worker.runner import WorkerFailure


def generation_job(
    cas: FileCas, backend: str, modality: str, output_formats: list[str]
) -> dict:
    source_digest = cas.put(b"source")
    profile = {
        "id": f"generationprofile://test/{backend}",
        "profileVersion": "0.1.0",
        "modality": modality,
        "backend": backend,
        "backendVersion": "1.1.5" if backend == "nerfstudio" else "source-lock",
        "containerDigest": f"sha256:{'1' * 64}",
        "modelDigests": [f"sha256:{'2' * 64}"] if backend == "trellis2" else [],
        "outputFormats": output_formats,
        "evidenceCeiling": "generated",
        "parameters": {},
    }
    profile_digest = cas.put(json.dumps(profile).encode())
    return {
        "id": f"job://test/{backend}",
        "protocolVersion": "0.1.0",
        "operation": "generate",
        "inputs": [
            {
                "id": "artifact://test/source",
                "digest": source_digest,
                "mediaType": "image/png",
                "path": "source.png",
            }
        ],
        "profileDigests": [profile_digest],
        "limits": {"timeoutSeconds": 10, "memoryBytes": 1024, "gpuCount": 1},
        "submittedAt": "2026-07-28T00:00:00Z",
    }


@pytest.mark.parametrize(
    ("handler", "backend", "modality", "formats"),
    [
        (trellis2_handler, "trellis2", "single_image", ["glb", "quality_report"]),
        (
            nerfstudio_handler,
            "nerfstudio",
            "multi_view",
            ["nerf", "camera_poses", "quality_report"],
        ),
    ],
)
def test_real_generation_requires_exact_oci_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    handler: object,
    backend: str,
    modality: str,
    formats: list[str],
) -> None:
    cas = FileCas(tmp_path)
    job = generation_job(cas, backend, modality, formats)
    monkeypatch.delenv("WORLDSPEC_CONTAINER_DIGEST", raising=False)
    with pytest.raises(WorkerFailure) as missing:
        handler(job, cas)  # type: ignore[operator]
    assert missing.value.code == "WORKER_CONTAINER_BINDING_MISSING"
    assert missing.value.details["executionEvidence"] == "not_executed"

    monkeypatch.setenv("WORLDSPEC_CONTAINER_DIGEST", f"sha256:{'3' * 64}")
    with pytest.raises(WorkerFailure) as mismatch:
        handler(job, cas)  # type: ignore[operator]
    assert mismatch.value.code == "WORKER_CONTAINER_BINDING_MISMATCH"
    assert mismatch.value.details["executionEvidence"] == "not_executed"


def test_unsupported_output_fails_before_runtime(tmp_path: Path) -> None:
    cas = FileCas(tmp_path)
    job = generation_job(cas, "trellis2", "single_image", ["3dgs"])
    with pytest.raises(WorkerFailure) as captured:
        trellis2_handler(job, cas)
    assert captured.value.code == "GENERATION_OUTPUT_UNSUPPORTED"


def test_trellis_rejects_non_image_before_runtime(tmp_path: Path) -> None:
    cas = FileCas(tmp_path)
    job = generation_job(cas, "trellis2", "single_image", ["glb"])
    job["inputs"][0]["mediaType"] = "application/octet-stream"
    with pytest.raises(WorkerFailure) as captured:
        trellis2_handler(job, cas)
    assert captured.value.code == "WORKER_SOURCE_FORMAT_UNSUPPORTED"


def model_bundle(
    root: Path, backend: str, payload: bytes, declared_payload: bytes | None = None
) -> tuple[str, Path]:
    locked_payload = payload if declared_payload is None else declared_payload
    file_entry = {
        "path": "weights/model.bin",
        "digest": f"sha256:{hashlib.sha256(locked_payload).hexdigest()}",
        "sizeBytes": len(locked_payload),
    }
    identity = {
        "formatVersion": "0.1.0",
        "backend": backend,
        "files": [file_entry],
    }
    digest = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    bundle = root / digest.removeprefix("sha256:")
    (bundle / "weights").mkdir(parents=True)
    (bundle / "weights/model.bin").write_bytes(payload)
    (bundle / "worldspec-model.json").write_text(
        json.dumps({**identity, "digest": digest}), encoding="utf-8"
    )
    return digest, bundle


def test_model_bundle_is_content_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    digest, bundle = model_bundle(tmp_path, "trellis2", b"locked model")
    monkeypatch.setenv("WORLDSPEC_MODEL_CACHE_ROOT", str(tmp_path))
    assert _model_cache({"modelDigests": [digest]}, "trellis2") == bundle


def test_model_bundle_rejects_tampered_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    digest, _ = model_bundle(
        tmp_path, "trellis2", b"tampered model", declared_payload=b"locked model"
    )
    monkeypatch.setenv("WORLDSPEC_MODEL_CACHE_ROOT", str(tmp_path))
    with pytest.raises(WorkerFailure) as captured:
        _model_cache({"modelDigests": [digest]}, "trellis2")
    assert captured.value.code == "MODEL_BUNDLE_FILE_MISMATCH"
