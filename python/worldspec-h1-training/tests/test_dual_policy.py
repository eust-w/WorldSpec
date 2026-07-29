from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from worldspec_h1_training.contract import digest_json
from worldspec_h1_training.dual_policy import (
    action_handoff,
    make_dual_policy_evaluation_profile,
    validate_dual_policy_profile,
)
from worldspec_h1_training.errors import TrainingError

ROOT = Path(__file__).resolve().parents[3]
BASE_PROFILE = ROOT / "examples" / "h1-kitchen" / "locomotion-training-profile.json"
DUAL_PROFILE = ROOT / "examples" / "h1-kitchen" / "locomotion-dual-policy-profile.json"


def _profiles() -> tuple[dict, dict]:
    return (
        json.loads(BASE_PROFILE.read_text(encoding="utf-8")),
        json.loads(DUAL_PROFILE.read_text(encoding="utf-8")),
    )


def test_dual_policy_contract_binds_both_lineages_without_training() -> None:
    base, dual = _profiles()

    effective = make_dual_policy_evaluation_profile(base, dual)

    assert dual["baseTrainingProfileDigest"] == digest_json(base)
    assert dual["motionPolicy"]["selectedRole"] == "motion"
    assert dual["standPolicy"]["selectedRole"] == "zero_velocity_and_stand"
    assert dual["supervisor"]["handoff"]["blendSteps"] == 5
    assert "minimumFinalMeanEpisodeLength" not in dual["qualityGates"]
    assert effective["runtime"]["ccdIterations"] == 50
    assert effective["training"]["numEnvs"] == 1
    assert {key: value for key, value in effective["training"].items() if key != "numEnvs"} == {
        key: value for key, value in base["training"].items() if key != "numEnvs"
    }


def test_dual_policy_rejects_motion_source_drift() -> None:
    base, dual = _profiles()
    dual["motionPolicy"]["checkpointDigest"] = "sha256:" + ("0" * 64)

    with pytest.raises(TrainingError, match="transition-v2 motion checkpoint"):
        validate_dual_policy_profile(base, dual)


def test_dual_policy_rejects_stand_source_drift() -> None:
    base, dual = _profiles()
    dual["standPolicy"]["sourceReportDigest"] = "sha256:" + ("0" * 64)

    with pytest.raises(TrainingError, match="stand-v2.1 checkpoint"):
        validate_dual_policy_profile(base, dual)


def test_dual_policy_rejects_gate_relaxation() -> None:
    base, dual = _profiles()
    dual["qualityGates"]["maximumSettleLinearSpeed"] = 0.5

    with pytest.raises(TrainingError, match="cannot relax"):
        validate_dual_policy_profile(base, dual)


def test_dual_policy_rejects_handoff_drift() -> None:
    base, dual = _profiles()
    dual["supervisor"]["handoff"]["blendSteps"] = 10

    with pytest.raises(TrainingError, match="five-step linear action handoff"):
        validate_dual_policy_profile(base, dual)


def test_action_handoff_uses_five_linear_steps() -> None:
    motion = 10.0
    stand = 0.0

    assert action_handoff(motion, stand, 149) == (10.0, "motion", 0.0)
    assert action_handoff(motion, stand, 150) == (8.0, "blend", 0.2)
    assert action_handoff(motion, stand, 151) == (6.0, "blend", 0.4)
    assert action_handoff(motion, stand, 152) == (4.0, "blend", 0.6)
    assert action_handoff(motion, stand, 153) == (
        pytest.approx(2.0),
        "blend",
        0.8,
    )
    assert action_handoff(motion, stand, 154) == (0.0, "blend", 1.0)
    assert action_handoff(motion, stand, 155) == (0.0, "stand", 1.0)


def test_dual_policy_effective_profile_is_a_deep_copy() -> None:
    base, dual = _profiles()
    original = copy.deepcopy(base)

    effective = make_dual_policy_evaluation_profile(base, dual)
    effective["validation"]["maximumSettleLinearSpeed"] = 10.0

    assert base == original
