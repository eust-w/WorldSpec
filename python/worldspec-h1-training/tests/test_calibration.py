from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from worldspec_h1_training.calibration import (
    make_calibration_training_profile,
    validate_calibration_profile,
)
from worldspec_h1_training.contract import digest_json
from worldspec_h1_training.errors import TrainingError
from worldspec_h1_training.trainer import _flat_observation_size

ROOT = Path(__file__).resolve().parents[3]
BASE_PROFILE = ROOT / "examples" / "h1-kitchen" / "locomotion-training-profile.json"
CALIBRATION_PROFILE = ROOT / "examples" / "h1-kitchen" / "locomotion-calibration-profile.json"
INVALID_BATCH_PROFILE = (
    ROOT
    / "examples"
    / "h1-kitchen"
    / "locomotion-calibration-profile.stand-v2-invalid.json"
)


def _profiles() -> tuple[dict, dict]:
    return (
        json.loads(BASE_PROFILE.read_text(encoding="utf-8")),
        json.loads(CALIBRATION_PROFILE.read_text(encoding="utf-8")),
    )


def test_stand_calibration_is_digest_bound_and_bounded() -> None:
    base, calibration = _profiles()
    effective = make_calibration_training_profile(base, calibration)

    assert calibration["baseTrainingProfileDigest"] == digest_json(base)
    assert effective["training"]["numTimesteps"] == 4_194_304
    assert effective["training"]["numEnvs"] == 4096
    assert effective["training"]["batchSize"] == 256
    assert effective["runtime"]["containerDigest"] == calibration["runtime"]["containerDigest"]
    assert effective["training"]["commandDistribution"] == {
        "linearVelocityX": [0.0, 0.0],
        "linearVelocityY": [0.0, 0.0],
        "angularVelocityYaw": [0.0, 0.0],
        "zeroCommandProbability": 1.0,
    }
    assert effective["trainingEnvironment"]["reward"]["survival"] == 5.0
    assert "trainingEnvironment" not in base


def test_calibration_rejects_a_different_base_profile() -> None:
    base, calibration = _profiles()
    changed = copy.deepcopy(base)
    changed["training"]["seed"] += 1

    with pytest.raises(
        TrainingError,
        match="exact base training Profile",
    ):
        validate_calibration_profile(changed, calibration)


def test_stand_calibration_rejects_nonzero_commands() -> None:
    base, calibration = _profiles()
    calibration["environment"]["commandDistribution"]["linearVelocityX"] = [
        0.0,
        0.1,
    ]

    with pytest.raises(
        TrainingError,
        match="exact zero command",
    ):
        validate_calibration_profile(base, calibration)


def test_calibration_checkpoint_cannot_be_marked_publishable() -> None:
    base, calibration = _profiles()
    calibration["artifactPolicy"]["distribution"] = "publishable"

    with pytest.raises(
        TrainingError,
        match="internal research artifacts",
    ):
        validate_calibration_profile(base, calibration)


def test_calibration_rejects_a_different_package_lock() -> None:
    base, calibration = _profiles()
    calibration["runtime"]["packageLockDigest"] = "sha256:" + ("0" * 64)

    with pytest.raises(
        TrainingError,
        match="package lock bound by the base Profile",
    ):
        validate_calibration_profile(base, calibration)


def test_calibration_rejects_an_invalid_batch_topology() -> None:
    base, _ = _profiles()
    calibration = json.loads(INVALID_BATCH_PROFILE.read_text(encoding="utf-8"))

    with pytest.raises(
        TrainingError,
        match="batchSize times numMinibatches must be divisible by numEnvs",
    ):
        validate_calibration_profile(base, calibration)


def test_observation_shape_is_flattened_for_report_metadata() -> None:
    assert _flat_observation_size(42) == 42
    assert _flat_observation_size((42,)) == 42
    assert _flat_observation_size((3, 14)) == 42

    with pytest.raises(
        TrainingError,
        match="positive product",
    ):
        _flat_observation_size((0, 42))
