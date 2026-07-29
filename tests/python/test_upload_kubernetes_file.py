from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from upload_kubernetes_file import ChunkUploadError, upload_to_pod


def _digest(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def test_chunk_upload_retries_and_verifies_identity(tmp_path: Path) -> None:
    payload = bytes(range(251)) * 5000
    source = tmp_path / "checkpoint.zip"
    source.write_bytes(payload)
    calls: dict[int, int] = {}
    phase_calls = {"truncate": 0, "verify": 0}

    def fake_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        if "truncate" in command:
            phase_calls["truncate"] += 1
            if phase_calls["truncate"] == 1:
                return subprocess.CompletedProcess(command, 1, b"", b"error: EOF")
            return subprocess.CompletedProcess(command, 0, b"", b"")
        if "worldspec-upload-chunk" in command:
            marker = command.index("worldspec-upload-chunk")
            declared_size = int(command[marker + 2])
            declared_digest = command[marker + 3]
            index = int(command[marker + 5])
            calls[index] = calls.get(index, 0) + 1
            if index == 1 and calls[index] == 1:
                return subprocess.CompletedProcess(command, 1, b"", b"temporary EOF")
            chunk = payload[index * 512 * 1024 : (index + 1) * 512 * 1024]
            assert kwargs["input"] == chunk
            assert declared_size == len(chunk)
            assert declared_digest == hashlib.sha256(chunk).hexdigest()
            return subprocess.CompletedProcess(command, 0, b"", b"")
        phase_calls["verify"] += 1
        if phase_calls["verify"] == 1:
            return subprocess.CompletedProcess(command, 1, b"", b"temporary EOF")
        return subprocess.CompletedProcess(
            command,
            0,
            f"{len(payload)} {_digest(payload).removeprefix('sha256:')}\n".encode(),
            b"",
        )

    result = upload_to_pod(
        command_prefix=["kubectl", "-n", "test"],
        pod="pod-a",
        container="worker",
        source=source,
        remote_path="/scratch/inputs/checkpoint.zip",
        expected_size=len(payload),
        expected_digest=_digest(payload),
        run=fake_run,
    )

    assert result["chunkCount"] == 3
    assert calls[1] == 2
    assert phase_calls == {"truncate": 2, "verify": 2}


def test_chunk_upload_rejects_wrong_local_digest(tmp_path: Path) -> None:
    source = tmp_path / "checkpoint.zip"
    source.write_bytes(b"checkpoint")

    with pytest.raises(ChunkUploadError, match="local source identity mismatch"):
        upload_to_pod(
            command_prefix=["kubectl"],
            pod="pod-a",
            container="worker",
            source=source,
            remote_path="/scratch/inputs/checkpoint.zip",
            expected_size=source.stat().st_size,
            expected_digest="sha256:" + ("0" * 64),
        )


def test_chunk_upload_rejects_path_traversal(tmp_path: Path) -> None:
    source = tmp_path / "checkpoint.zip"
    source.write_bytes(b"checkpoint")

    with pytest.raises(ChunkUploadError, match="absolute normalized"):
        upload_to_pod(
            command_prefix=["kubectl"],
            pod="pod-a",
            container="worker",
            source=source,
            remote_path="/scratch/../escape",
            expected_size=source.stat().st_size,
            expected_digest=_digest(source.read_bytes()),
        )
