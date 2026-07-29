from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from worldspec_h1_training.contract import digest_json
from worldspec_h1_training.errors import TrainingError
from worldspec_h1_training.whole_body import (
    A5CF_FAILURE_EVIDENCE,
    A5CI_DIAGNOSTIC_EVIDENCE,
    A5R_FAILED_REPORT_DIGEST,
    DYNAMIC_ARM_TRACKING,
    TASK_POLICY_HANDOFF,
    WHOLE_BODY_CONTROLLER,
    WHOLE_BODY_GATES,
    TaskPolicyHandoffState,
    WholeBodyTaskSpaceController,
    assess_diagnostic_trace,
    compare_whole_body_traces,
    make_whole_body_evaluation_profile,
    solve_box_qp,
    validate_diagnostic_trace_record,
    validate_whole_body_profile,
    whole_body_controller_semantic_projection,
    whole_body_profile_semantic_projection,
)

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "examples" / "h1-kitchen" / "locomotion-training-profile.json"
SUPERVISOR = ROOT / "examples" / "h1-kitchen" / "locomotion-supervisor-profile.json"
CONTROL = ROOT / "examples" / "h1-kitchen" / "whole-body-control-profile.json"
HANDOFF = ROOT / "examples" / "h1-kitchen" / "whole-body-policy-handoff-profile.json"
DYNAMIC_ARM = ROOT / "examples" / "h1-kitchen" / "whole-body-dynamic-arm-profile.json"


def _profiles() -> tuple[dict, dict, dict]:
    return tuple(
        json.loads(path.read_text(encoding="utf-8")) for path in (BASE, SUPERVISOR, CONTROL)
    )


def test_a5c_profile_is_bound_to_failure_and_forbids_full_task_claim() -> None:
    base, supervisor, control = _profiles()

    validate_whole_body_profile(base, supervisor, control)

    assert control["baseTrainingProfileDigest"] == digest_json(base)
    assert control["supervisorProfileDigest"] == digest_json(supervisor)
    assert control["failedA5RReportDigest"] == A5R_FAILED_REPORT_DIGEST
    assert control["controller"] == WHOLE_BODY_CONTROLLER
    assert control["qualityGates"] == WHOLE_BODY_GATES
    assert control["artifactPolicy"]["fullTaskClaim"] == "forbidden"
    assert control["artifactPolicy"]["l3Claim"] == "forbidden"


def test_a5c_effective_profile_uses_single_environment_runtime() -> None:
    base, supervisor, control = _profiles()

    effective = make_whole_body_evaluation_profile(base, supervisor, control)

    assert effective["training"]["seed"] == 41
    assert effective["training"]["numEnvs"] == 1
    assert effective["runtime"]["ccdIterations"] == 50
    assert effective["runtime"]["mjxCapacity"] == control["runtime"]["mjxCapacity"]


def test_a5cf_profile_binds_exact_diagnostic_evidence_and_handoff() -> None:
    base, supervisor, _ = _profiles()
    handoff = json.loads(HANDOFF.read_text(encoding="utf-8"))

    validate_whole_body_profile(base, supervisor, handoff)

    assert handoff["diagnosticEvidence"] == A5CI_DIAGNOSTIC_EVIDENCE
    assert handoff["taskPolicyHandoff"] == TASK_POLICY_HANDOFF
    assert handoff["qualityGates"] == WHOLE_BODY_GATES


@pytest.mark.parametrize("missing", ["diagnosticEvidence", "taskPolicyHandoff"])
def test_a5cf_rejects_partial_handoff_lineage(missing: str) -> None:
    base, supervisor, _ = _profiles()
    handoff = json.loads(HANDOFF.read_text(encoding="utf-8"))
    handoff.pop(missing)

    with pytest.raises(TrainingError) as captured:
        validate_whole_body_profile(base, supervisor, handoff)

    assert captured.value.code == "WHOLE_BODY_HANDOFF_LINEAGE_INCOMPLETE"


def test_a5cg_profile_binds_exact_a5cf_evidence_and_dynamic_arm_contract() -> None:
    base, supervisor, _ = _profiles()
    profile = json.loads(DYNAMIC_ARM.read_text(encoding="utf-8"))

    validate_whole_body_profile(base, supervisor, profile)

    assert profile["a5cfEvidence"] == A5CF_FAILURE_EVIDENCE
    assert profile["dynamicArmTracking"] == DYNAMIC_ARM_TRACKING
    assert profile["taskPolicyHandoff"] == TASK_POLICY_HANDOFF


@pytest.mark.parametrize("missing", ["a5cfEvidence", "dynamicArmTracking"])
def test_a5cg_rejects_partial_dynamic_arm_lineage(missing: str) -> None:
    base, supervisor, _ = _profiles()
    profile = json.loads(DYNAMIC_ARM.read_text(encoding="utf-8"))
    profile.pop(missing)

    with pytest.raises(TrainingError) as captured:
        validate_whole_body_profile(base, supervisor, profile)

    assert captured.value.code == "WHOLE_BODY_DYNAMIC_ARM_LINEAGE_INCOMPLETE"


def test_a5cg_rejects_missing_handoff_and_contract_drift() -> None:
    base, supervisor, _ = _profiles()
    profile = json.loads(DYNAMIC_ARM.read_text(encoding="utf-8"))
    profile.pop("taskPolicyHandoff")
    profile.pop("diagnosticEvidence")

    with pytest.raises(TrainingError) as captured:
        validate_whole_body_profile(base, supervisor, profile)

    assert captured.value.code == "WHOLE_BODY_DYNAMIC_ARM_HANDOFF_MISSING"

    profile = json.loads(DYNAMIC_ARM.read_text(encoding="utf-8"))
    profile["dynamicArmTracking"]["baseCommand"] = "qp"
    with pytest.raises(TrainingError) as captured:
        validate_whole_body_profile(base, supervisor, profile)

    assert captured.value.code == "WHOLE_BODY_DYNAMIC_ARM_INVALID"


def test_task_policy_handoff_uses_hysteresis_capture_and_blend() -> None:
    state = TaskPolicyHandoffState()
    motion = np.asarray([1.0])
    capture = np.asarray([2.0])
    stand = np.asarray([3.0])

    assert state.prepare(0.02) == "stand"
    action, policy, alpha = state.select(motion, capture, stand)
    assert (action.tolist(), policy, alpha) == ([3.0], "stand", 1.0)

    assert state.prepare(0.06) == "motion"
    assert state.prepare(0.03) == "motion"
    action, policy, alpha = state.select(motion, capture, stand)
    assert (action.tolist(), policy, alpha) == ([1.0], "motion", 0.0)

    assert state.prepare(0.019) == "capture"
    for _ in range(20):
        action, policy, alpha = state.select(motion, capture, stand)
        assert (action.tolist(), policy, alpha) == ([2.0], "capture", 0.0)
        state.observe(policy, linear_speed=0.01, angular_speed=0.01)
    assert state.phase == "blend"

    blend_actions = []
    for _ in range(TASK_POLICY_HANDOFF["blendSteps"]):
        action, policy, alpha = state.select(motion, capture, stand)
        blend_actions.append((action.item(), alpha))
        state.observe(policy, linear_speed=0.01, angular_speed=0.01)
    assert blend_actions[0] == pytest.approx((2.2, 0.2))
    assert blend_actions[-1] == pytest.approx((3.0, 1.0))
    assert state.phase == "stand"


def test_task_policy_handoff_allows_motion_reentry_before_completion() -> None:
    state = TaskPolicyHandoffState()
    state.prepare(0.06)
    state.prepare(0.01)
    assert state.phase == "capture"

    state.observe("capture", linear_speed=0.5, angular_speed=0.5)
    assert state.prepare(0.051) == "motion"
    assert state.capture_steps == 0
    assert state.handoff_failed is False


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("failedA5RReportDigest", "sha256:" + ("0" * 64), "A5-R failure"),
        ("controller", {}, "controller contract"),
        ("qualityGates", {}, "gates cannot be relaxed"),
    ],
)
def test_a5c_rejects_lineage_or_gate_drift(field: str, value, match: str) -> None:
    base, supervisor, control = _profiles()
    candidate = copy.deepcopy(control)
    candidate[field] = value

    with pytest.raises(TrainingError, match=match):
        validate_whole_body_profile(base, supervisor, candidate)


def test_box_qp_matches_diagonal_solution_and_reports_kkt_residual() -> None:
    hessian = np.diag([2.0, 4.0])
    gradient = np.asarray([-2.0, 8.0])

    solution, objective, projected_gradient = solve_box_qp(
        hessian,
        gradient,
        np.asarray([-0.5, -1.0]),
        np.asarray([0.75, 1.0]),
        iterations=16,
    )

    assert solution == pytest.approx([0.75, -1.0])
    assert objective == pytest.approx(-6.9375)
    assert projected_gradient <= 1e-12


def test_trace_diagnostics_report_joint_state_and_actuator_saturation() -> None:
    controller = object.__new__(WholeBodyTaskSpaceController)
    controller._np = np
    controller._policy_joint_names = ["left_hip"]
    controller._policy_qpos = np.asarray([7])
    controller._policy_dofs = np.asarray([6])
    controller._policy_ranges = np.asarray([[-0.5, 0.5]])
    controller._held_joint_names = ["torso"]
    controller._held_qpos = np.asarray([8])
    controller._held_dofs = np.asarray([7])
    controller._held_ranges = np.asarray([[-1.0, 1.0]])
    controller._actuator_names = ["left_hip", "torso", "gripper"]
    controller._actuator_ids = np.asarray([0, 1, 2])
    controller._actuator_ctrlrange = np.asarray([[-100.0, 100.0], [-50.0, 50.0], [-1.0, 1.0]])
    controller._actuator_limited = np.asarray([True, True, True])
    controller._actuator_slices = {
        "policy": slice(0, 1),
        "held": slice(1, 2),
        "gripper": slice(2, 3),
    }
    qpos = np.arange(9, dtype=float)
    qvel = np.arange(8, dtype=float) * 0.1

    diagnostic = controller.diagnostic_state(
        qpos,
        qvel,
        np.asarray([100.0, 25.0, 0.0]),
        joint_limit_tolerance=0.1,
    )

    assert diagnostic["jointState"]["policy"][0]["name"] == "left_hip"
    assert diagnostic["jointState"]["policy"][0]["position"] == pytest.approx(7.0)
    assert diagnostic["jointState"]["policy"][0]["velocity"] == pytest.approx(0.6)
    assert diagnostic["jointState"]["policy"][0]["lowerLimit"] == pytest.approx(-0.5)
    assert diagnostic["jointState"]["policy"][0]["upperLimit"] == pytest.approx(0.5)
    assert diagnostic["jointState"]["policy"][0]["tolerance"] == pytest.approx(0.1)
    assert diagnostic["jointState"]["policy"][0]["violated"] is True
    assert diagnostic["jointState"]["held"][0]["name"] == "torso"
    assert diagnostic["jointState"]["held"][0]["position"] == pytest.approx(8.0)
    assert diagnostic["jointState"]["held"][0]["velocity"] == pytest.approx(0.7)
    assert diagnostic["actuation"]["saturationCount"] == 1
    assert diagnostic["actuation"]["maximumUtilization"] == pytest.approx(1.0)
    assert diagnostic["actuation"]["groups"]["policy"][0]["saturated"] is True
    assert diagnostic["actuation"]["groups"]["held"][0]["saturated"] is False


def _expected_control() -> dict:
    return {
        "policyJoints": ["left_hip"],
        "heldJoints": ["torso"],
        "policyActuators": ["left_hip"],
        "heldActuators": ["torso"],
        "gripperActuators": ["gripper"],
    }


def _diagnostic_record(
    *,
    reason: str | None = None,
    done: bool = False,
) -> dict:
    termination = {
        "joint_limit": False,
        "fall_height": False,
        "fall_upright": False,
        "nonfinite": False,
    }
    if reason is not None:
        termination[reason] = True
    policy_violated = reason == "joint_limit"
    return {
        "step": 4,
        "timeSeconds": 0.1,
        "phase": "locomotion",
        "activePolicy": "motion",
        "command": [0.5, 0.0, 0.0],
        "basePosition": [0.1, 0.0, 1.0],
        "baseState": {
            "position": [0.1, 0.0, 1.0],
            "linearVelocity": [0.5, 0.0, 0.0],
            "angularVelocity": [0.0, 0.0, 0.0],
            "height": 1.0,
            "uprightCosine": 0.99,
        },
        "minimumBaseHeight": 0.99,
        "minimumUprightCosine": 0.98,
        "finite": reason != "nonfinite",
        "done": done,
        "termination": termination,
        "jointState": {
            "policy": [
                {
                    "name": "left_hip",
                    "position": 0.61 if policy_violated else 0.0,
                    "velocity": 0.1,
                    "lowerLimit": -0.5,
                    "upperLimit": 0.5,
                    "tolerance": 0.1,
                    "violated": policy_violated,
                }
            ],
            "held": [
                {
                    "name": "torso",
                    "position": 0.0,
                    "velocity": 0.0,
                    "lowerLimit": -1.0,
                    "upperLimit": 1.0,
                    "tolerance": 0.1,
                    "violated": False,
                }
            ],
        },
        "actuation": {
            "groups": {
                "policy": [
                    {
                        "name": "left_hip",
                        "appliedControl": 100.0,
                        "lowerLimit": -100.0,
                        "upperLimit": 100.0,
                        "limited": True,
                        "utilization": 1.0,
                        "saturated": True,
                    }
                ],
                "held": [
                    {
                        "name": "torso",
                        "appliedControl": 25.0,
                        "lowerLimit": -50.0,
                        "upperLimit": 50.0,
                        "limited": True,
                        "utilization": 0.5,
                        "saturated": False,
                    }
                ],
                "gripper": [
                    {
                        "name": "gripper",
                        "appliedControl": 0.0,
                        "lowerLimit": -1.0,
                        "upperLimit": 1.0,
                        "limited": False,
                        "utilization": 0.0,
                        "saturated": False,
                    }
                ],
            },
            "saturationCount": 1,
            "maximumUtilization": 1.0,
        },
        "control": None,
        "site": None,
    }


@pytest.mark.parametrize(
    "reason",
    ["joint_limit", "fall_height", "fall_upright"],
)
def test_diagnostic_trace_accepts_all_finite_termination_channels(reason: str) -> None:
    record = _diagnostic_record(reason=reason, done=True)

    validate_diagnostic_trace_record(record, _expected_control())

    assessment = assess_diagnostic_trace([record], _expected_control())
    assert assessment["status"] == "passed"
    assert assessment["terminalReasons"] == [reason]
    assert assessment["terminalJoints"] == (["left_hip"] if reason == "joint_limit" else [])
    assert assessment["controlSaturationSamples"] == 1
    assert assessment["maximumControlUtilization"] == pytest.approx(1.0)


def test_diagnostic_trace_records_nonfinite_as_failed_evidence() -> None:
    record = _diagnostic_record(reason="nonfinite", done=True)
    record["baseState"]["position"][0] = None

    with pytest.raises(TrainingError) as captured:
        validate_diagnostic_trace_record(record, _expected_control())

    assert captured.value.code == "DIAGNOSTIC_TRACE_INVALID"
    assessment = assess_diagnostic_trace([record], _expected_control())
    assert assessment["status"] == "failed"
    assert assessment["terminalReasons"] == ["nonfinite"]
    assert any("record_not_finite" in reason for reason in assessment["reasons"])


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        (
            lambda record: record["termination"].pop("fall_height"),
            "termination_channels_mismatch",
        ),
        (
            lambda record: record["termination"].update({"joint_limit": 1}),
            "termination_joint_limit_not_boolean",
        ),
        (
            lambda record: record["jointState"]["policy"][0].update({"name": "wrong"}),
            "policy_joint_names_mismatch",
        ),
        (
            lambda record: record["actuation"]["groups"]["held"].clear(),
            "held_actuator_names_mismatch",
        ),
        (
            lambda record: record["actuation"]["groups"]["held"][0].update({"utilization": 0.25}),
            "held_actuator_0_utilization_inconsistent",
        ),
        (
            lambda record: (
                record["control"].update({"qpObjective": float("nan")})
                if isinstance(record["control"], dict)
                else record.update({"control": {"qpObjective": float("nan")}})
            ),
            "control_nonfinite",
        ),
    ],
)
def test_diagnostic_trace_fails_closed_on_field_drift(mutation, expected_reason: str) -> None:
    record = _diagnostic_record()
    mutation(record)

    assessment = assess_diagnostic_trace([record], _expected_control())

    assert assessment["status"] == "failed"
    assert any(expected_reason in reason for reason in assessment["reasons"])


def test_diagnostic_trace_rejects_done_without_reason_and_unlocated_joint_limit() -> None:
    done_without_reason = _diagnostic_record(done=True)
    joint_without_location = _diagnostic_record(reason="joint_limit", done=True)
    joint_without_location["jointState"]["policy"][0]["position"] = 0.0
    joint_without_location["jointState"]["policy"][0]["violated"] = False

    first = assess_diagnostic_trace([done_without_reason], _expected_control())
    second = assess_diagnostic_trace([joint_without_location], _expected_control())

    assert any("done_without_termination_reason" in reason for reason in first["reasons"])
    assert any("joint_limit_without_violated_joint" in reason for reason in second["reasons"])


def test_semantic_projections_exclude_only_permitted_digest_fields() -> None:
    _, _, control = _profiles()
    controller = {
        "profileDigest": digest_json(control),
        "controller": copy.deepcopy(WHOLE_BODY_CONTROLLER),
        "scene": copy.deepcopy(control["scene"]),
    }
    replay_control = copy.deepcopy(control)
    replay_control["runtime"]["containerImage"] = "registry/image@sha256:" + ("1" * 64)
    replay_control["runtime"]["containerDigest"] = "sha256:" + ("1" * 64)
    replay_controller = copy.deepcopy(controller)
    replay_controller["profileDigest"] = "sha256:" + ("2" * 64)

    projected_profile = whole_body_profile_semantic_projection(control)
    projected_controller = whole_body_controller_semantic_projection(controller)

    assert projected_profile == whole_body_profile_semantic_projection(replay_control)
    assert projected_controller == whole_body_controller_semantic_projection(replay_controller)
    assert "containerImage" not in projected_profile["runtime"]
    assert "containerDigest" not in projected_profile["runtime"]
    assert (
        projected_profile["runtime"]["packageLockDigest"] == control["runtime"]["packageLockDigest"]
    )
    assert projected_profile["seed"] == 41
    assert "profileDigest" not in projected_controller
    assert projected_controller["controller"] == WHOLE_BODY_CONTROLLER

    replay_control["seed"] = 42
    replay_controller["controller"]["cartesianGain"] = 4.1
    assert projected_profile != whole_body_profile_semantic_projection(replay_control)
    assert projected_controller != whole_body_controller_semantic_projection(replay_controller)


def test_trace_comparison_reports_dynamic_differences_without_gate_result() -> None:
    reference = _diagnostic_record()
    replay = copy.deepcopy(reference)
    replay["activePolicy"] = "stand"
    replay["basePosition"][0] = 0.2
    replay["termination"] = {
        "joint_limit": False,
        "fall_height": True,
        "fall_upright": False,
        "nonfinite": False,
    }

    comparison = compare_whole_body_traces([reference], [replay])

    assert comparison["firstDynamicDivergenceStep"] == 4
    assert comparison["categoricalDifferences"]["activePolicy"]["differenceCount"] == 1
    assert comparison["categoricalDifferences"]["termination"]["differenceCount"] == 1
    assert comparison["numericDifferences"]["basePosition"][
        "maximumAbsoluteDifference"
    ] == pytest.approx(0.1)
    assert comparison["interpretation"] == "report_only_not_static_equivalence"
    assert "status" not in comparison


def test_a800_whole_body_spike_is_fail_closed_and_not_training() -> None:
    entrypoint = (ROOT / "ops" / "a800" / "h1-locomotion-midterm-entrypoint.sh").read_text(
        encoding="utf-8"
    )
    launcher = (ROOT / "scripts" / "run_a800_h1_locomotion_midterm.sh").read_text(encoding="utf-8")
    wrapper = (ROOT / "scripts" / "run_a800_h1_whole_body_control_spike.sh").read_text(
        encoding="utf-8"
    )

    assert "run_whole_body_control_spike" in entrypoint
    assert "WORLDSPEC_A800_WHOLE_BODY_RESULT=" in entrypoint
    assert "formalControlGate" in launcher
    assert "h1-whole-body-control-report.schema.json" in launcher
    assert "whole-body-controller.json" in launcher
    assert '"termination": termination' in (
        ROOT
        / "python"
        / "worldspec-h1-training"
        / "src"
        / "worldspec_h1_training"
        / "whole_body.py"
    ).read_text(encoding="utf-8")
    assert '"jointState": diagnostic["jointState"]' in (
        ROOT
        / "python"
        / "worldspec-h1-training"
        / "src"
        / "worldspec_h1_training"
        / "whole_body.py"
    ).read_text(encoding="utf-8")
    assert '"actuation": actuation' in (
        ROOT
        / "python"
        / "worldspec-h1-training"
        / "src"
        / "worldspec_h1_training"
        / "whole_body.py"
    ).read_text(encoding="utf-8")
    assert "whole-body-control-profile.json" in wrapper
    assert "100000000" not in wrapper

    handoff_wrapper = (
        ROOT / "scripts" / "run_a800_h1_whole_body_policy_handoff_spike.sh"
    ).read_text(encoding="utf-8")
    assert "whole-body-policy-handoff-profile.json" in handoff_wrapper
    assert "WORLD_SPEC_DIAGNOSTIC_REPLAY_PROFILE" not in handoff_wrapper
    assert "100000000" not in handoff_wrapper

    dynamic_arm_wrapper = (
        ROOT / "scripts" / "run_a800_h1_whole_body_dynamic_arm_spike.sh"
    ).read_text(encoding="utf-8")
    assert "whole-body-dynamic-arm-profile.json" in dynamic_arm_wrapper
    assert "WORLD_SPEC_DIAGNOSTIC_REPLAY_PROFILE" not in dynamic_arm_wrapper
    assert "100000000" not in dynamic_arm_wrapper
