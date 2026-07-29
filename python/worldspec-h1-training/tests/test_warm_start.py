from __future__ import annotations

import json
import stat
import zipfile
from pathlib import Path

import pytest

from worldspec_h1_training.contract import digest_bytes
from worldspec_h1_training.errors import TrainingError
from worldspec_h1_training.warm_start import (
    materialize_warm_start,
    validate_network_compatibility,
)


def _write_checkpoint(path: Path, *, incompatible: bool = False) -> tuple[str, int]:
    network = {
        "action_size": 11 if incompatible else 10,
        "observation_size": {"state": {"shape": [42]}},
        "normalize_observations": True,
    }
    with zipfile.ZipFile(path, mode="w", compression=zipfile.ZIP_STORED) as archive:
        for step in ("000000000100", "000000000900"):
            archive.writestr(f"{step}/_CHECKPOINT_METADATA", b"metadata")
            archive.writestr(
                f"{step}/ppo_network_config.json",
                json.dumps(network).encode(),
            )
            archive.writestr(f"{step}/default/data", b"checkpoint-data")
    payload = path.read_bytes()
    return digest_bytes(payload), len(payload)


def test_warm_start_selects_latest_numeric_step_and_checks_abi(tmp_path: Path) -> None:
    archive = tmp_path / "checkpoint.zip"
    digest, size = _write_checkpoint(archive)

    latest, metadata = materialize_warm_start(
        archive,
        tmp_path / "materialized",
        digest,
        size,
    )
    validate_network_compatibility(metadata, observation_size=42, action_size=10)

    assert latest.name == "000000000900"
    assert metadata["selectedStep"] == 900
    assert metadata["optimizerState"] == "reset"
    assert metadata["restored"] == {
        "normalizer": True,
        "policy": True,
        "value": True,
        "optimizer": False,
    }


def test_warm_start_rejects_digest_mismatch(tmp_path: Path) -> None:
    archive = tmp_path / "checkpoint.zip"
    _, size = _write_checkpoint(archive)

    with pytest.raises(TrainingError, match="declared size and digest"):
        materialize_warm_start(
            archive,
            tmp_path / "materialized",
            "sha256:" + ("0" * 64),
            size,
        )


def test_warm_start_rejects_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "checkpoint.zip"
    with zipfile.ZipFile(archive, mode="w") as checkpoint:
        checkpoint.writestr("../escape", b"payload")
    payload = archive.read_bytes()

    with pytest.raises(TrainingError, match="unsafe path"):
        materialize_warm_start(
            archive,
            tmp_path / "materialized",
            digest_bytes(payload),
            len(payload),
        )


def test_warm_start_rejects_symbolic_links(tmp_path: Path) -> None:
    archive = tmp_path / "checkpoint.zip"
    with zipfile.ZipFile(archive, mode="w") as checkpoint:
        item = zipfile.ZipInfo("000000000001/link")
        item.create_system = 3
        item.external_attr = (stat.S_IFLNK | 0o777) << 16
        checkpoint.writestr(item, b"target")
    payload = archive.read_bytes()

    with pytest.raises(TrainingError, match="symbolic links"):
        materialize_warm_start(
            archive,
            tmp_path / "materialized",
            digest_bytes(payload),
            len(payload),
        )


def test_warm_start_rejects_incompatible_network(tmp_path: Path) -> None:
    archive = tmp_path / "checkpoint.zip"
    digest, size = _write_checkpoint(archive, incompatible=True)
    _, metadata = materialize_warm_start(
        archive,
        tmp_path / "materialized",
        digest,
        size,
    )

    with pytest.raises(TrainingError, match="observation/action ABI"):
        validate_network_compatibility(metadata, observation_size=42, action_size=10)
