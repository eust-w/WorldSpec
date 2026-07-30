from __future__ import annotations

import copy
import json
import sys
import types
from pathlib import Path

import pytest

from worldspec_h1_training.contract import digest_json
from worldspec_h1_training.errors import TrainingError
from worldspec_h1_training.midterm import (
    assess_checkpoint_candidate,
    make_midterm_training_profile,
    make_retention_training_profile,
    make_task_load_retention_training_profile,
    make_task_load_training_profile,
    make_transition_training_profile,
    select_checkpoint_candidate,
    validate_midterm_profile,
    validate_retention_profile,
    validate_task_load_profile,
    validate_task_load_retention_profile,
    validate_transition_profile,
)

ROOT = Path(__file__).resolve().parents[3]
BASE_PROFILE = ROOT / "examples" / "h1-kitchen" / "locomotion-training-profile.json"
MIDTERM_PROFILE = ROOT / "examples" / "h1-kitchen" / "locomotion-midterm-profile.json"
TRANSITION_PROFILE = ROOT / "examples" / "h1-kitchen" / "locomotion-transition-profile.json"
RETENTION_PROFILE = ROOT / "examples" / "h1-kitchen" / "locomotion-retention-profile.json"
TASK_LOAD_PROFILE = ROOT / "examples" / "h1-kitchen" / "locomotion-task-load-profile.json"
TASK_LOAD_RETENTION_PROFILE = (
    ROOT / "examples" / "h1-kitchen" / "locomotion-task-load-retention-profile.json"
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


def test_retention_contract_replays_stand_and_binds_teacher() -> None:
    base = json.loads(BASE_PROFILE.read_text(encoding="utf-8"))
    retention = json.loads(RETENTION_PROFILE.read_text(encoding="utf-8"))

    effective = make_retention_training_profile(base, retention)

    assert effective["training"]["hyperparameterStatus"] == "research_retention_override"
    assert effective["training"]["numTimesteps"] == 8_388_608
    assert effective["training"]["learningRate"] == 0.0001
    assert effective["training"]["entropyCost"] == 0.003
    assert effective["trainingEnvironment"]["transitionCurriculum"] == {
        "mode": "move_then_zero_with_stand_replay",
        "transitionCycleProbability": 0.6,
        "standReplayProbability": 0.4,
        "moveSteps": 150,
        "settleSteps": 50,
        "motionCommandDistribution": {
            "linearVelocityX": [0.4, 0.6],
            "linearVelocityY": [-0.05, 0.05],
            "angularVelocityYaw": [-0.1, 0.1],
        },
    }
    assert effective["trainingEnvironment"]["reward"]["standDistillation"] == 4.0
    assert retention["retentionTeacher"]["scope"] == "stand_replay_only"
    assert effective["validation"]["maximumStandPlanarDrift"] == 0.2


def test_retention_rejects_changed_replay_ratio() -> None:
    base = json.loads(BASE_PROFILE.read_text(encoding="utf-8"))
    retention = json.loads(RETENTION_PROFILE.read_text(encoding="utf-8"))
    retention["environment"]["transitionCurriculum"]["standReplayProbability"] = 0.3

    with pytest.raises(TrainingError, match="60% transition and 40% stand replay"):
        validate_retention_profile(base, retention)


def test_retention_rejects_unbound_teacher_checkpoint() -> None:
    base = json.loads(BASE_PROFILE.read_text(encoding="utf-8"))
    retention = json.loads(RETENTION_PROFILE.read_text(encoding="utf-8"))
    retention["retentionTeacher"]["checkpointDigest"] = "sha256:" + ("0" * 64)

    with pytest.raises(TrainingError, match="read-only teacher"):
        validate_retention_profile(base, retention)


def test_retention_rejects_relaxed_original_gate() -> None:
    base = json.loads(BASE_PROFILE.read_text(encoding="utf-8"))
    retention = json.loads(RETENTION_PROFILE.read_text(encoding="utf-8"))
    retention["qualityGates"]["maximumStandPlanarDrift"] = 0.6

    with pytest.raises(TrainingError, match="quality gates"):
        validate_retention_profile(base, retention)


def test_task_load_contract_binds_a5ck_and_preserves_gates() -> None:
    base = json.loads(BASE_PROFILE.read_text(encoding="utf-8"))
    task_load = json.loads(TASK_LOAD_PROFILE.read_text(encoding="utf-8"))

    effective = make_task_load_training_profile(base, task_load)

    assert effective["training"]["hyperparameterStatus"] == ("research_task_load_override")
    assert effective["training"]["numTimesteps"] == 16_777_216
    assert effective["trainingEnvironment"]["taskLoadCurriculum"] == {
        "mode": "static_right_arm_pose_and_base_disturbance",
        "sourceJob": "worldspec-h1-midterm-5nn2q",
        "sourceTraceDigest": (
            "sha256:175427d1d3d74da7fe5c422f3290f07ae6dfa6c21179626dd4d4558915012bd9"
        ),
        "heldTargetScale": [0.5, 1.0],
        "initialBaseVelocityX": [-0.1, 0.1],
        "heldTargets": [
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.1543052911758423,
            0.09892238825658843,
            -0.006488978405079102,
            -0.19852599334400028,
        ],
        "heldFeedforward": [
            0.032988220529269176,
            -1.1402555002525037,
            0.08486267857762098,
            0.012800121336152957,
            -1.0451398037469817,
            -0.9578816827225751,
            0.837737275364864,
            0.46023224988862355,
            -4.402542577541209,
        ],
        "observationAugmentation": "none",
        "qualityGatesChanged": False,
    }
    assert effective["validation"]["minimumBaseHeight"] == 0.8
    assert effective["validation"]["maximumSettleLinearSpeed"] == 0.2
    assert task_load["a5ckEvidence"]["maximumBackwardVelocity"] == (-2.459172010421753)


def test_task_load_rejects_a5ck_evidence_drift() -> None:
    base = json.loads(BASE_PROFILE.read_text(encoding="utf-8"))
    task_load = json.loads(TASK_LOAD_PROFILE.read_text(encoding="utf-8"))
    task_load["a5ckEvidence"]["traceRecordCount"] = 385

    with pytest.raises(TrainingError, match="A5-CK"):
        validate_task_load_profile(base, task_load)


def test_task_load_rejects_curriculum_drift() -> None:
    base = json.loads(BASE_PROFILE.read_text(encoding="utf-8"))
    task_load = json.loads(TASK_LOAD_PROFILE.read_text(encoding="utf-8"))
    task_load["environment"]["taskLoadCurriculum"]["heldTargetScale"] = [0.0, 1.0]

    with pytest.raises(TrainingError, match="arm-load curriculum"):
        validate_task_load_profile(base, task_load)


def test_task_load_rejects_relaxed_gate() -> None:
    base = json.loads(BASE_PROFILE.read_text(encoding="utf-8"))
    task_load = json.loads(TASK_LOAD_PROFILE.read_text(encoding="utf-8"))
    task_load["qualityGates"]["minimumBaseHeight"] = 0.75

    with pytest.raises(TrainingError, match="quality gates"):
        validate_task_load_profile(base, task_load)


def test_task_load_retention_binds_two_teachers_and_full_load() -> None:
    base = json.loads(BASE_PROFILE.read_text(encoding="utf-8"))
    profile = json.loads(TASK_LOAD_RETENTION_PROFILE.read_text(encoding="utf-8"))

    effective = make_task_load_retention_training_profile(base, profile)

    assert effective["training"]["hyperparameterStatus"] == (
        "research_task_load_retention_override"
    )
    assert effective["training"]["learningRate"] == 0.00005
    assert effective["training"]["entropyCost"] == 0.001
    assert effective["trainingEnvironment"]["taskLoadCurriculum"]["heldTargetScale"] == [1.0, 1.0]
    assert effective["trainingEnvironment"]["taskLoadCurriculum"]["initialBaseVelocityX"] == [
        0.0,
        0.0,
    ]
    assert effective["trainingEnvironment"]["reward"]["standDistillation"] == 4.0
    assert effective["trainingEnvironment"]["reward"]["settleDistillation"] == 4.0
    assert profile["standTeacher"]["scope"] == "stand_replay_only"
    assert profile["settleTeacher"]["scope"] == "transition_settle_only"


def test_task_load_retention_rejects_teacher_or_gate_drift() -> None:
    base = json.loads(BASE_PROFILE.read_text(encoding="utf-8"))
    profile = json.loads(TASK_LOAD_RETENTION_PROFILE.read_text(encoding="utf-8"))
    profile["settleTeacher"]["checkpointDigest"] = "sha256:" + ("0" * 64)

    with pytest.raises(TrainingError, match="capture policy"):
        validate_task_load_retention_profile(base, profile)

    profile = json.loads(TASK_LOAD_RETENTION_PROFILE.read_text(encoding="utf-8"))
    profile["qualityGates"]["maximumSettleLinearSpeed"] = 0.3
    with pytest.raises(TrainingError, match="cannot relax"):
        validate_task_load_retention_profile(base, profile)


def _candidate_tests(*, passing: bool) -> list[dict]:
    metrics = {
        "completedSteps": 200,
        "requiredSteps": 200,
        "forwardDisplacement": 1.4,
        "lateralDrift": 0.05,
        "maximumPlanarDrift": 0.1,
        "trackingRmse": 0.1,
        "minimumBaseHeight": 0.95,
        "minimumUprightCosine": 0.95,
        "maximumSettleLinearSpeed": 0.1 if passing else 0.5,
        "maximumSettleAngularSpeed": 0.2,
        "maximumTeacherActionMse": 0.0,
        "nonFiniteSamples": 0,
        "doneSeen": False,
        "terminalReasons": [],
    }
    return [
        {
            "id": f"test://worldspec/h1-policy/{suite}/{index}",
            "suite": suite,
            "result": "pass" if passing else "fail",
            "metrics": dict(metrics),
        }
        for suite in ("walk_settle", "stand_regression")
        for index in range(5)
    ]


def test_checkpoint_selection_prefers_a_formal_earlier_candidate() -> None:
    gates = json.loads(TASK_LOAD_RETENTION_PROFILE.read_text(encoding="utf-8"))["qualityGates"]
    passing = assess_checkpoint_candidate(
        2_457_600,
        930.0,
        _candidate_tests(passing=True),
        gates,
    )
    degraded = assess_checkpoint_candidate(
        17_203_200,
        980.0,
        _candidate_tests(passing=False),
        gates,
    )

    assert passing["formalGate"] is True
    assert degraded["formalGate"] is False
    assert select_checkpoint_candidate([degraded, passing]) == passing


def test_teacher_policy_loader_rebuilds_the_verified_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    def network_factory(observation_size, action_size, preprocess_observations_fn):
        calls["network"] = (
            observation_size,
            action_size,
            preprocess_observations_fn,
        )
        return "teacher-network"

    def make_inference_fn(network):
        calls["inference_network"] = network

        def bind(params, deterministic):
            calls["bound"] = (params, deterministic)
            return "teacher-policy"

        return bind

    checkpoint_module = types.SimpleNamespace(load=lambda path: ("params", path))
    networks_module = types.SimpleNamespace(make_inference_fn=make_inference_fn)
    statistics_module = types.SimpleNamespace(normalize="normalize")
    brax_module = types.ModuleType("brax")
    training_module = types.ModuleType("brax.training")
    acme_module = types.ModuleType("brax.training.acme")
    agents_module = types.ModuleType("brax.training.agents")
    ppo_module = types.ModuleType("brax.training.agents.ppo")
    acme_module.running_statistics = statistics_module
    ppo_module.checkpoint = checkpoint_module
    ppo_module.networks = networks_module
    training_module.acme = acme_module
    training_module.agents = agents_module
    agents_module.ppo = ppo_module
    brax_module.training = training_module
    for name, module in (
        ("brax", brax_module),
        ("brax.training", training_module),
        ("brax.training.acme", acme_module),
        ("brax.training.acme.running_statistics", statistics_module),
        ("brax.training.agents", agents_module),
        ("brax.training.agents.ppo", ppo_module),
        ("brax.training.agents.ppo.checkpoint", checkpoint_module),
        ("brax.training.agents.ppo.networks", networks_module),
    ):
        monkeypatch.setitem(sys.modules, name, module)

    from worldspec_h1_training.midterm import _load_deterministic_teacher_policy

    policy = _load_deterministic_teacher_policy(
        Path("/checkpoint/000004505600"),
        {
            "networkConfig": {
                "observation_size": {"state": {"shape": [42]}},
                "action_size": 10,
            }
        },
        network_factory,
    )

    assert policy == "teacher-policy"
    assert calls["network"] == ({"state": 42}, 10, "normalize")
    assert calls["inference_network"] == "teacher-network"
    assert calls["bound"] == (
        ("params", Path("/checkpoint/000004505600")),
        True,
    )
