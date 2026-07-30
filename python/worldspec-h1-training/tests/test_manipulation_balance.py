from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from worldspec_h1_training.contract import digest_json
from worldspec_h1_training.errors import TrainingError
from worldspec_h1_training.manipulation_balance import (
    A6K1_CAPTURE_FAILURE,
    ANCHOR_RECOVERY,
    CAPTURE_WARM_START,
    DYNAMIC_ARM_CURRICULUM,
    MOTION_TEACHER,
    PREVIOUS_ATTEMPT,
    QUALITY_GATES,
    SNAPSHOT_CURRICULUM,
    make_manipulation_balance_training_profile,
    validate_manipulation_balance_profile,
)

ROOT = Path(__file__).resolve().parents[3]
BASE_PROFILE = ROOT / "examples" / "h1-kitchen" / "locomotion-training-profile.json"
MANIPULATION_PROFILE = (
    ROOT / "examples" / "h1-kitchen" / "locomotion-manipulation-balance-profile.json"
)


def _profiles() -> tuple[dict, dict]:
    return (
        json.loads(BASE_PROFILE.read_text(encoding="utf-8")),
        json.loads(MANIPULATION_PROFILE.read_text(encoding="utf-8")),
    )


def test_manipulation_balance_contract_is_evidence_bound() -> None:
    base, profile = _profiles()

    effective = make_manipulation_balance_training_profile(base, profile)

    assert profile["baseTrainingProfileDigest"] == digest_json(base)
    assert profile["warmStart"] == CAPTURE_WARM_START
    assert profile["motionTeacher"] == MOTION_TEACHER
    assert profile["a6k1CaptureFailure"] == A6K1_CAPTURE_FAILURE
    assert profile["previousAttempt"] == PREVIOUS_ATTEMPT
    assert effective["training"]["numTimesteps"] == 16_777_216
    assert effective["training"]["numEnvs"] == 4096
    assert effective["training"]["episodeLength"] == 100
    assert effective["training"]["hyperparameterStatus"] == (
        "research_manipulation_balance_override"
    )
    assert effective["trainingEnvironment"]["snapshotCurriculum"] == SNAPSHOT_CURRICULUM
    assert SNAPSHOT_CURRICULUM["fromRestProbability"] == 0.25
    assert effective["trainingEnvironment"]["dynamicArmCurriculum"] == DYNAMIC_ARM_CURRICULUM
    assert (
        effective["trainingEnvironment"]["dynamicArmCurriculum"]["anchorRecovery"]
        == ANCHOR_RECOVERY
    )
    assert effective["validation"] == QUALITY_GATES


def test_manipulation_balance_rejects_capture_lineage_drift() -> None:
    base, profile = _profiles()
    profile["warmStart"]["checkpointDigest"] = "sha256:" + ("0" * 64)

    with pytest.raises(TrainingError, match="warmStart"):
        validate_manipulation_balance_profile(base, profile)


def test_manipulation_balance_rejects_motion_teacher_drift() -> None:
    base, profile = _profiles()
    profile["motionTeacher"]["checkpointSizeBytes"] += 1

    with pytest.raises(TrainingError, match="motionTeacher"):
        validate_manipulation_balance_profile(base, profile)


def test_manipulation_balance_rejects_dynamic_arm_relaxation() -> None:
    base, profile = _profiles()
    profile["environment"]["dynamicArmCurriculum"]["trajectoryScale"] = [0.5, 1.0]

    with pytest.raises(TrainingError, match="environment"):
        validate_manipulation_balance_profile(base, profile)


def test_manipulation_balance_rejects_anchor_recovery_drift() -> None:
    base, profile = _profiles()
    profile["environment"]["dynamicArmCurriculum"]["anchorRecovery"]["linearGain"] = 1.0

    with pytest.raises(TrainingError, match="environment"):
        validate_manipulation_balance_profile(base, profile)


def test_manipulation_balance_rejects_reset_mixture_drift() -> None:
    base, profile = _profiles()
    profile["environment"]["snapshotCurriculum"]["fromRestProbability"] = 0.5

    with pytest.raises(TrainingError, match="environment"):
        validate_manipulation_balance_profile(base, profile)


def test_manipulation_balance_rejects_previous_attempt_drift() -> None:
    base, profile = _profiles()
    profile["previousAttempt"]["formalGate"] = "passed"

    with pytest.raises(TrainingError, match="previousAttempt"):
        validate_manipulation_balance_profile(base, profile)


def test_manipulation_balance_rejects_quality_gate_relaxation() -> None:
    base, profile = _profiles()
    profile["qualityGates"]["minimumBaseHeight"] = 0.7

    with pytest.raises(TrainingError, match="qualityGates"):
        validate_manipulation_balance_profile(base, profile)


def test_manipulation_balance_profile_does_not_mutate_base() -> None:
    base, profile = _profiles()
    original = copy.deepcopy(base)

    make_manipulation_balance_training_profile(base, profile)

    assert base == original


def test_environment_applies_mixed_capture_and_rest_reset() -> None:
    source = (
        ROOT
        / "python"
        / "worldspec-h1-training"
        / "src"
        / "worldspec_h1_training"
        / "environment.py"
    ).read_text(encoding="utf-8")

    assert 'snapshot.get("fromRestProbability", 0.0)' in source
    assert "from_rest = jax.random.bernoulli(" in source
    assert "qpos = jp.where(from_rest, self._initial_qpos, bank_qpos)" in source
    assert "jp.where(from_rest, jp.zeros(self.mjx_model.nv), bank_qvel)" in source


def test_post_walk_evaluation_disables_rest_mixture() -> None:
    source = (
        ROOT
        / "python"
        / "worldspec-h1-training"
        / "src"
        / "worldspec_h1_training"
        / "manipulation_balance.py"
    ).read_text(encoding="utf-8")

    assert "snapshot_eval_profile" in source
    assert '"fromRestProbability"' in source
    assert "] = 0.0" in source
