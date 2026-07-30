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
    CHECKPOINT_SELECTION,
    DYNAMIC_ARM_CURRICULUM,
    MOTION_TEACHER,
    PREVIOUS_ATTEMPT,
    PREVIOUS_QUALITY_FAILURE,
    QUALITY_GATES,
    RUNTIME_FAILURE,
    SNAPSHOT_CURRICULUM,
    assess_manipulation_checkpoint_candidate,
    make_manipulation_balance_training_profile,
    select_manipulation_checkpoint_candidate,
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
    assert profile["runtimeFailure"] == RUNTIME_FAILURE
    assert profile["previousQualityFailure"] == PREVIOUS_QUALITY_FAILURE
    assert profile["checkpointSelection"] == CHECKPOINT_SELECTION
    assert effective["training"]["numTimesteps"] == 16_777_216
    assert effective["training"]["numEnvs"] == 4096
    assert effective["training"]["episodeLength"] == 100
    assert effective["training"]["hyperparameterStatus"] == (
        "research_manipulation_balance_override"
    )
    assert effective["trainingEnvironment"]["snapshotCurriculum"] == SNAPSHOT_CURRICULUM
    assert SNAPSHOT_CURRICULUM["fromRestProbability"] == 0.5
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
    profile["environment"]["snapshotCurriculum"]["fromRestProbability"] = 0.25

    with pytest.raises(TrainingError, match="environment"):
        validate_manipulation_balance_profile(base, profile)


def test_manipulation_balance_rejects_previous_attempt_drift() -> None:
    base, profile = _profiles()
    profile["previousAttempt"]["formalGate"] = "passed"

    with pytest.raises(TrainingError, match="previousAttempt"):
        validate_manipulation_balance_profile(base, profile)


def test_manipulation_balance_rejects_checkpoint_selection_drift() -> None:
    base, profile = _profiles()
    profile["checkpointSelection"]["expectedCandidateCount"] = 6

    with pytest.raises(TrainingError, match="checkpointSelection"):
        validate_manipulation_balance_profile(base, profile)


def test_manipulation_balance_rejects_runtime_failure_lineage_drift() -> None:
    base, profile = _profiles()
    profile["runtimeFailure"]["savedCheckpointCount"] = 6

    with pytest.raises(TrainingError, match="runtimeFailure"):
        validate_manipulation_balance_profile(base, profile)


def test_manipulation_balance_rejects_previous_quality_failure_drift() -> None:
    base, profile = _profiles()
    profile["previousQualityFailure"]["selectedStep"] += 1

    with pytest.raises(TrainingError, match="previousQualityFailure"):
        validate_manipulation_balance_profile(base, profile)


def test_manipulation_balance_adds_unbounded_recovery_costs() -> None:
    base, profile = _profiles()

    effective = make_manipulation_balance_training_profile(base, profile)

    reward = effective["trainingEnvironment"]["reward"]
    assert reward["baseAnchorErrorCost"] == 25.0
    assert reward["settleLinearErrorCost"] == 2.0

    source = (
        ROOT
        / "python"
        / "worldspec-h1-training"
        / "src"
        / "worldspec_h1_training"
        / "environment.py"
    ).read_text(encoding="utf-8")
    assert "legacy_reward = jp.clip(" in source
    assert "reward = legacy_reward - unbounded_recovery_cost * self.dt" in source


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

    assert 'if suite == "post_walk_capture"' in source
    assert "evaluation_profile" in source
    assert '"fromRestProbability"' in source
    assert "] = 0.0" in source
    assert "evaluate_manipulation_balance_suite(" in source
    assert "effective,\n        suite," in source
    assert "if int(item[\"step\"]) == step" in source
    assert "MANIPULATION_CANDIDATE_PROGRESS_MISSING" in source
    assert "training_and_suite_evaluation_process_boundary_v4" in source
    assert "train_manipulation_balance_portfolio" in source
    assert "MANIPULATION_PORTFOLIO_STATE_MISSING" in source
    assert "from brax.training.acme import running_statistics" in source
    assert "run_manipulation_balance_candidate_suite" in source
    assert "MANIPULATION_EVALUATION_RESULT_SET_MISMATCH" in source


def test_portfolio_evaluation_uses_an_independent_model_directory() -> None:
    entrypoint = (
        ROOT / "ops" / "a800" / "h1-locomotion-midterm-entrypoint.sh"
    ).read_text(encoding="utf-8")

    assert 'run_model_dir="${MODEL_DIR}"' in entrypoint
    assert 'MODEL_DIR="${MODEL_DIR}-evaluation-${candidate_step}-${evaluation_suite}"' in (
        entrypoint
    )
    assert "for evaluation_suite in post_walk_capture from_rest" in entrypoint
    assert "manipulation_portfolio_aggregation" in entrypoint
    assert 'MODEL_DIR="${run_model_dir}"' in entrypoint


def _tests(post_walk_passes: int, from_rest_passes: int) -> list[dict]:
    tests: list[dict] = []
    for suite, passes in (
        ("post_walk_capture", post_walk_passes),
        ("from_rest", from_rest_passes),
    ):
        for index in range(5):
            tests.append(
                {
                    "suite": suite,
                    "result": "pass" if index < passes else "fail",
                }
            )
    return tests


def test_checkpoint_assessment_preserves_all_formal_gates() -> None:
    assessment = assess_manipulation_checkpoint_candidate(
        12_288_000,
        95.0,
        _tests(5, 5),
    )

    assert assessment == {
        "step": 12_288_000,
        "meanEpisodeLength": 95.0,
        "meanEpisodeLengthGate": True,
        "testsPassed": 10,
        "testsRequired": 10,
        "postWalkTestsPassed": 5,
        "fromRestTestsPassed": 5,
        "deterministicSuiteGate": True,
        "formalGate": True,
    }


def test_checkpoint_selection_prefers_passing_candidate_over_terminal_failure() -> None:
    selected = select_manipulation_checkpoint_candidate(
        [
            assess_manipulation_checkpoint_candidate(
                12_288_000,
                94.0,
                _tests(5, 5),
            ),
            assess_manipulation_checkpoint_candidate(
                17_203_200,
                97.453125,
                _tests(3, 5),
            ),
        ]
    )

    assert selected["step"] == 12_288_000
    assert selected["formalGate"] is True


def test_checkpoint_selection_uses_pass_count_without_upgrading_failure() -> None:
    selected = select_manipulation_checkpoint_candidate(
        [
            assess_manipulation_checkpoint_candidate(
                9_830_400,
                96.0,
                _tests(4, 5),
            ),
            assess_manipulation_checkpoint_candidate(
                17_203_200,
                97.0,
                _tests(3, 5),
            ),
        ]
    )

    assert selected["step"] == 9_830_400
    assert selected["formalGate"] is False


def test_checkpoint_selection_rejects_empty_portfolio() -> None:
    with pytest.raises(TrainingError, match="at least one candidate"):
        select_manipulation_checkpoint_candidate([])
