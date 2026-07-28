from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from copy_kubernetes_file import ChunkCopyError, copy_from_pod


def _digest(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def test_chunk_copy_retries_and_verifies_identity(tmp_path: Path) -> None:
    source = bytes(range(251)) * 5000
    calls: dict[int, int] = {}

    def fake_run(
        command: list[str],
        **_: object,
    ) -> subprocess.CompletedProcess[bytes]:
        chunk_size = int(next(item[3:] for item in command if item.startswith("bs=")))
        index = int(next(item[5:] for item in command if item.startswith("skip=")))
        calls[index] = calls.get(index, 0) + 1
        start = index * chunk_size
        payload = source[start : start + chunk_size]
        if index == 1 and calls[index] == 1:
            return subprocess.CompletedProcess(command, 1, payload[:100], b"unexpected EOF")
        return subprocess.CompletedProcess(command, 0, payload, b"")

    destination = tmp_path / "checkpoint.zip"
    result = copy_from_pod(
        command_prefix=["kubectl", "-n", "test"],
        pod="pod-a",
        container="worker",
        remote_path="/result/checkpoint.zip",
        destination=destination,
        expected_size=len(source),
        expected_digest=_digest(source),
        chunk_size=512 * 1024,
        retries=3,
        run=fake_run,
    )

    assert destination.read_bytes() == source
    assert result["chunkCount"] == 3
    assert calls[1] == 2
    assert not destination.with_name("checkpoint.zip.part").exists()


def test_chunk_copy_rejects_a_wrong_final_digest(tmp_path: Path) -> None:
    source = b"checkpoint"

    def fake_run(
        command: list[str],
        **_: object,
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(command, 0, source, b"")

    destination = tmp_path / "checkpoint.zip"
    with pytest.raises(ChunkCopyError, match="identity mismatch"):
        copy_from_pod(
            command_prefix=["kubectl"],
            pod="pod-a",
            container="worker",
            remote_path="/result/checkpoint.zip",
            destination=destination,
            expected_size=len(source),
            expected_digest="sha256:" + ("0" * 64),
            chunk_size=512 * 1024,
            run=fake_run,
        )

    assert not destination.exists()
    assert not destination.with_name("checkpoint.zip.part").exists()
