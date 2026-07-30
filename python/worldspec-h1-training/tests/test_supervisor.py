from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from worldspec_h1_training.contract import digest_json
from worldspec_h1_training.errors import TrainingError
from worldspec_h1_training.supervisor import (
    TASK_LOAD_EVALUATION_ENVIRONMENT,
    TASK_LOAD_MOTION_POLICY_SOURCE,
    SupervisorState,
    make_supervisor_evaluation_profile,
    validate_supervisor_profile,
)

ROOT = Path(__file__).resolve().parents[3]
BASE_PROFILE = ROOT / "examples" / "h1-kitchen" / "locomotion-training-profile.json"
SUPERVISOR_PROFILE = ROOT / "examples" / "h1-kitchen" / "locomotion-supervisor-profile.json"
TASK_LOAD_SUPERVISOR_PROFILE = (
    ROOT / "examples" / "h1-kitchen" / "locomotion-task-load-supervisor-profile.json"
)


def _profiles() -> tuple[dict, dict]:
    return (
        json.loads(BASE_PROFILE.read_text(encoding="utf-8")),
        json.loads(SUPERVISOR_PROFILE.read_text(encoding="utf-8")),
    )


def test_supervisor_profile_binds_three_frozen_policies_without_training() -> None:
    base, profile = _profiles()

    effective = make_supervisor_evaluation_profile(base, profile)

    assert profile["baseTrainingProfileDigest"] == digest_json(base)
    assert profile["motionPolicy"]["selectedRole"] == "motion"
    assert profile["capturePolicy"]["selectedRole"] == "motion_state_capture"
    assert profile["standPolicy"]["selectedRole"] == "zero_velocity_and_stand"
    assert profile["supervisor"]["captureGate"]["minimumSteps"] == 20
    assert profile["supervisor"]["captureGate"]["maximumSteps"] == 40
    assert profile["supervisor"]["minimumStandDwellSteps"] == 10
    assert effective["training"]["numEnvs"] == 1
    assert {key: value for key, value in effective["training"].items() if key != "numEnvs"} == {
        key: value for key, value in base["training"].items() if key != "numEnvs"
    }


@pytest.mark.parametrize("policy", ["motionPolicy", "capturePolicy", "standPolicy"])
def test_supervisor_rejects_policy_lineage_drift(policy: str) -> None:
    base, profile = _profiles()
    profile[policy]["checkpointDigest"] = "sha256:" + ("0" * 64)

    with pytest.raises(TrainingError, match="frozen"):
        validate_supervisor_profile(base, profile)


def test_supervisor_rejects_stability_gate_relaxation() -> None:
    base, profile = _profiles()
    profile["supervisor"]["captureGate"]["maximumLinearSpeed"] = 0.5

    with pytest.raises(TrainingError, match="stability gate"):
        validate_supervisor_profile(base, profile)


def test_supervisor_rejects_stand_dwell_relaxation() -> None:
    base, profile = _profiles()
    profile["qualityGates"]["minimumStandDwellSteps"] = 1

    with pytest.raises(TrainingError, match="stand dwell"):
        validate_supervisor_profile(base, profile)


def test_supervisor_enters_blend_only_after_twenty_steps_and_five_stable_samples() -> None:
    state = SupervisorState()
    motion = 10.0
    capture = 5.0
    stand = 0.0

    action, phase, alpha = state.select(True, motion, capture, stand)
    assert (action, phase, alpha) == (10.0, "motion", 0.0)

    for _ in range(19):
        action, phase, alpha = state.select(False, motion, capture, stand)
        assert (action, phase, alpha) == (5.0, "capture", 0.0)
        state.observe(phase, 0.1, 0.1)
    assert state.phase == "capture"

    action, phase, _ = state.select(False, motion, capture, stand)
    state.observe(phase, 0.1, 0.1)
    assert state.phase == "blend"
    assert state.capture_steps == 20
    assert state.stable_steps == 20

    expected = [4.0, 3.0, 2.0, 1.0, 0.0]
    for value in expected:
        action, phase, _ = state.select(False, motion, capture, stand)
        assert phase == "blend"
        assert action == pytest.approx(value)
        state.observe(phase, 0.0, 0.0)
    assert state.phase == "stand"

    action, phase, alpha = state.select(False, motion, capture, stand)
    assert (action, phase, alpha) == (0.0, "stand", 1.0)
    state.observe(phase, 0.0, 0.0)
    assert state.stand_steps == 1


def test_supervisor_fails_closed_after_forty_unstable_capture_steps() -> None:
    state = SupervisorState()

    for _ in range(40):
        _, phase, _ = state.select(False, 1.0, 0.5, 0.0)
        state.observe(phase, 0.5, 0.5)

    assert state.phase == "capture"
    assert state.handoff_failed is True
    assert state.stable_steps == 0


def test_supervisor_effective_profile_is_a_deep_copy() -> None:
    base, profile = _profiles()
    original = copy.deepcopy(base)

    effective = make_supervisor_evaluation_profile(base, profile)
    effective["validation"]["maximumSettleLinearSpeed"] = 10.0

    assert base == original


def test_task_load_supervisor_binds_100m_motion_and_static_right_arm_load() -> None:
    base, _ = _profiles()
    profile = json.loads(TASK_LOAD_SUPERVISOR_PROFILE.read_text(encoding="utf-8"))

    effective = make_supervisor_evaluation_profile(base, profile)

    assert profile["motionPolicy"] == TASK_LOAD_MOTION_POLICY_SOURCE
    assert effective["trainingEnvironment"] == TASK_LOAD_EVALUATION_ENVIRONMENT
    assert effective["training"]["commandDistribution"] == {
        "linearVelocityX": [0.0, 0.8],
        "linearVelocityY": [-0.15, 0.15],
        "angularVelocityYaw": [-0.35, 0.35],
        "zeroCommandProbability": 0.2,
    }
    assert effective["training"]["numTimesteps"] == base["training"]["numTimesteps"]
    assert effective["training"]["numEnvs"] == 1
    assert "transitionCurriculum" not in effective["trainingEnvironment"]


def test_task_load_supervisor_rejects_load_or_100m_lineage_drift() -> None:
    base, profile = _profiles()
    profile["stage"] = "task_load_phase_aware_supervisor_probe"
    profile["motionPolicy"] = copy.deepcopy(TASK_LOAD_MOTION_POLICY_SOURCE)
    profile["evaluationEnvironment"] = copy.deepcopy(TASK_LOAD_EVALUATION_ENVIRONMENT)
    profile["evaluationEnvironment"]["taskLoadCurriculum"]["heldTargetScale"] = [0.5, 1.0]

    with pytest.raises(TrainingError, match="static right-arm task-load"):
        validate_supervisor_profile(base, profile)

    profile["evaluationEnvironment"] = copy.deepcopy(TASK_LOAD_EVALUATION_ENVIRONMENT)
    profile["motionPolicy"]["checkpointDigest"] = "sha256:" + ("0" * 64)
    with pytest.raises(TrainingError, match="frozen"):
        validate_supervisor_profile(base, profile)


def test_a800_supervisor_entrypoint_and_launcher_are_fail_closed() -> None:
    entrypoint = (ROOT / "ops" / "a800" / "h1-locomotion-midterm-entrypoint.sh").read_text(
        encoding="utf-8"
    )
    launcher = (ROOT / "scripts" / "run_a800_h1_locomotion_midterm.sh").read_text(encoding="utf-8")
    wrapper = (ROOT / "scripts" / "run_a800_h1_phase_aware_supervisor_probe.sh").read_text(
        encoding="utf-8"
    )
    task_load_wrapper = (ROOT / "scripts" / "run_a800_h1_task_load_supervisor_probe.sh").read_text(
        encoding="utf-8"
    )

    assert "phase_aware_supervisor_probe" in entrypoint
    assert "run_phase_aware_supervisor_probe" in entrypoint
    assert "supervisor-stand-checkpoint.zip" in entrypoint
    assert "WORLDSPEC_A800_SUPERVISOR_RESULT=" in entrypoint
    assert "formalSupervisorGate" in launcher
    assert "phase-aware-supervisor.json" in launcher
    assert "task_load_phase_aware_supervisor_probe" in entrypoint
    assert "formalTaskLoadSupervisorGate" in launcher
    assert "task-load-phase-aware-supervisor.json" in launcher
    assert "loaded-track-settle-task-load-formal-v1-failed" in entrypoint
    assert "WORLD_SPEC_RETAIN_INCOMPLETE_REMOTE" in launcher
    assert "remote_evidence_retained=true" in launcher
    assert "WORLD_SPEC_SUPERVISOR_STAND_CHECKPOINT" in wrapper
    assert "locomotion-task-load-formal.a800.failed-summary.json" in task_load_wrapper
    assert "worldspec-h1-midterm-cdbm5" in task_load_wrapper
    assert "task-load-supervisor-image-build.a800.passed.json" in task_load_wrapper
    assert "100000000" not in entrypoint
    assert "100000000" not in wrapper
    assert "100000000" not in task_load_wrapper
