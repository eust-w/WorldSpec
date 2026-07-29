from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from worldspec_h1_training.contract import digest_json
from worldspec_h1_training.errors import TrainingError
from worldspec_h1_training.midterm import (
    make_midterm_training_profile,
    make_transition_training_profile,
    validate_midterm_profile,
    validate_transition_profile,
)

ROOT = Path(__file__).resolve().parents[3]
BASE_PROFILE = ROOT / "examples" / "h1-kitchen" / "locomotion-training-profile.json"
MIDTERM_PROFILE = ROOT / "examples" / "h1-kitchen" / "locomotion-midterm-profile.json"
TRANSITION_PROFILE = (
    ROOT / "examples" / "h1-kitchen" / "locomotion-transition-profile.json"
)


def _profiles() -> tuple[dict, dict]:
    return (
        json.loads(BASE_PROFILE.read_text(encoding="utf-8")),
        json.loads(MIDTERM_PROFILE.read_text(encoding="utf-8")),
    )


def test_midterm_contract_is_digest_bound_and_task_focused() -> None:
    base, midterm = _profiles()
    effective = make_midterm_training_profile(base, midterm)

    assert midterm["baseTrainingProfileDigest"] == digest_json(base)
    assert effective["training"]["numTimesteps"] == 16_777_216
    assert effective["training"]["numEnvs"] == 4096
    assert effective["training"]["numEvals"] == 8
    assert effective["training"]["hyperparameterStatus"] == "research_midterm_override"
    assert effective["training"]["commandDistribution"] == {
        "linearVelocityX": [0.0, 0.6],
        "linearVelocityY": [-0.1, 0.1],
        "angularVelocityYaw": [-0.25, 0.25],
        "zeroCommandProbability": 0.2,
    }
    assert effective["validation"]["requiredConsecutivePasses"] == 5
    assert effective["validation"]["minimumFinalMeanEpisodeLength"] == 900.0


def test_midterm_rejects_optimizer_restore() -> None:
    base, midterm = _profiles()
    midterm["warmStart"]["optimizerState"] = "restored"

    with pytest.raises(TrainingError, match="reset optimizer"):
        validate_midterm_profile(base, midterm)


def test_midterm_rejects_changed_command_range() -> None:
    base, midterm = _profiles()
    changed = copy.deepcopy(midterm)
    changed["environment"]["commandDistribution"]["linearVelocityX"] = [0.0, 0.8]

    with pytest.raises(TrainingError, match="approved kitchen range"):
        validate_midterm_profile(base, changed)


def test_midterm_rejects_unbound_stand_report() -> None:
    base, midterm = _profiles()
    midterm["warmStart"]["sourceReportDigest"] = "sha256:" + ("0" * 64)

    with pytest.raises(TrainingError, match="stand-v2.1 report"):
        validate_midterm_profile(base, midterm)


def test_transition_contract_targets_the_failed_settle_behavior() -> None:
    base = json.loads(BASE_PROFILE.read_text(encoding="utf-8"))
    transition = json.loads(TRANSITION_PROFILE.read_text(encoding="utf-8"))

    effective = make_transition_training_profile(base, transition)

    assert effective["training"]["hyperparameterStatus"] == "research_transition_override"
    assert effective["runtime"]["ccdIterations"] == 50
    assert effective["trainingEnvironment"]["transitionCurriculum"] == {
        "mode": "move_then_zero",
        "transitionCycleProbability": 0.75,
        "moveSteps": 150,
        "settleSteps": 50,
        "motionCommandDistribution": {
            "linearVelocityX": [0.4, 0.6],
            "linearVelocityY": [-0.05, 0.05],
            "angularVelocityYaw": [-0.1, 0.1],
        },
    }
    assert effective["trainingEnvironment"]["reward"]["settleLinear"] == 8.0
    assert effective["trainingEnvironment"]["reward"]["settleYaw"] == 3.0
    assert effective["validation"]["maximumSettleLinearSpeed"] == 0.2
    assert effective["validation"]["maximumSettleAngularSpeed"] == 0.4


def test_transition_rejects_a_relaxed_settle_gate() -> None:
    base = json.loads(BASE_PROFILE.read_text(encoding="utf-8"))
    transition = json.loads(TRANSITION_PROFILE.read_text(encoding="utf-8"))
    transition["qualityGates"]["maximumSettleLinearSpeed"] = 0.5

    with pytest.raises(TrainingError, match="quality gates"):
        validate_transition_profile(base, transition)


def test_transition_rejects_unbound_failed_checkpoint() -> None:
    base = json.loads(BASE_PROFILE.read_text(encoding="utf-8"))
    transition = json.loads(TRANSITION_PROFILE.read_text(encoding="utf-8"))
    transition["warmStart"]["checkpointDigest"] = "sha256:" + ("0" * 64)

    with pytest.raises(TrainingError, match="failed v1 report"):
        validate_transition_profile(base, transition)
