from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from worldspec_h1_training.capture import (
    CAPTURE_CURRICULUM,
    CAPTURE_QUALITY_GATES,
    make_capture_training_profile,
    make_motion_rollout_profile,
    validate_capture_profile,
)
from worldspec_h1_training.contract import digest_json
from worldspec_h1_training.errors import TrainingError

ROOT = Path(__file__).resolve().parents[3]
BASE_PROFILE = ROOT / "examples" / "h1-kitchen" / "locomotion-training-profile.json"
CAPTURE_PROFILE = ROOT / "examples" / "h1-kitchen" / "locomotion-capture-profile.json"


def _profiles() -> tuple[dict, dict]:
    return (
        json.loads(BASE_PROFILE.read_text(encoding="utf-8")),
        json.loads(CAPTURE_PROFILE.read_text(encoding="utf-8")),
    )


def test_capture_contract_uses_motion_snapshots_and_stand_warm_start() -> None:
    base, capture = _profiles()

    effective = make_capture_training_profile(base, capture)
    motion = make_motion_rollout_profile(base, capture)

    assert capture["baseTrainingProfileDigest"] == digest_json(base)
    assert capture["warmStart"]["sourceStage"] == "stand-v2.1"
    assert capture["motionTeacher"]["sourceStage"] == ("loaded-track-settle-transition-v2-failed")
    assert effective["training"]["hyperparameterStatus"] == "research_capture_override"
    assert effective["training"]["numTimesteps"] == 8_388_608
    assert effective["training"]["numEnvs"] == 4096
    assert effective["training"]["episodeLength"] == 100
    assert effective["training"]["commandDistribution"]["zeroCommandProbability"] == 1.0
    assert effective["trainingEnvironment"]["captureCurriculum"] == CAPTURE_CURRICULUM
    assert effective["validation"] == CAPTURE_QUALITY_GATES
    assert effective["validation"]["settleWindowSeconds"] == 1.0
    assert effective["validation"]["settleMeasurementWindowSeconds"] == 0.2
    assert motion["training"]["numEnvs"] == 4096
    assert motion["training"]["commandDistribution"]["zeroCommandProbability"] == 0.0


def test_capture_rejects_motion_teacher_drift() -> None:
    base, capture = _profiles()
    capture["motionTeacher"]["checkpointDigest"] = "sha256:" + ("0" * 64)

    with pytest.raises(TrainingError, match="motion teacher"):
        validate_capture_profile(base, capture)


def test_capture_rejects_warm_start_drift() -> None:
    base, capture = _profiles()
    capture["warmStart"]["checkpointDigest"] = "sha256:" + ("0" * 64)

    with pytest.raises(TrainingError, match="stand-v2.1"):
        validate_capture_profile(base, capture)


def test_capture_rejects_terminal_measurement_relaxation() -> None:
    base, capture = _profiles()
    capture["qualityGates"]["settleMeasurementWindowSeconds"] = 0.1

    with pytest.raises(TrainingError, match="terminal hold"):
        validate_capture_profile(base, capture)


def test_capture_effective_profiles_do_not_mutate_base() -> None:
    base, capture = _profiles()
    original = copy.deepcopy(base)

    make_capture_training_profile(base, capture)
    make_motion_rollout_profile(base, capture)

    assert base == original


def test_capture_snapshot_code_selects_only_per_environment_state() -> None:
    source = (
        ROOT / "python" / "worldspec-h1-training" / "src" / "worldspec_h1_training" / "capture.py"
    ).read_text(encoding="utf-8")

    assert "jax.tree_util.tree_map" not in source
    assert "captured_qpos = select_rows" in source
    assert "captured_qvel = select_rows" in source
    assert "captured_last_action = select_rows" in source
