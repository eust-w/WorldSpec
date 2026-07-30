"""Task-load-aware, single-run full A5 kitchen integration probe.

This module deliberately separates the one-run integration gate from the
historical five-run A5 report.  It combines the passing A6-S task-load
locomotion supervisor with the latest A5-CK whole-body controller lineage and
executes the complete ordered drawer/cup task exactly once.
"""

from __future__ import annotations

import copy
import functools
import json
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .contract import canonical_bytes, digest_bytes, digest_json, validate_profile
from .errors import TrainingError
from .kitchen_task import (
    ERGONOMIC_TASK_SCENE,
    PHASES,
    TASK_CAPACITY,
    TASK_CONTROLLER,
    TASK_GATES,
    KitchenTaskState,
    _gripper_for_phase,
    _target_for_phase,
    _task_metrics,
    prepare_kitchen_task_model,
)
from .midterm import _load_deterministic_teacher_policy
from .preflight import runtime_preflight, static_preflight
from .supervisor import SUPERVISOR, SupervisorState, make_supervisor_evaluation_profile
from .trainer import _flat_observation_size
from .warm_start import materialize_warm_start, validate_network_compatibility
from .whole_body import (
    DYNAMIC_ARM_TRACKING,
    TASK_GEOMETRY_CALIBRATION,
    TASK_POLICY_HANDOFF,
    WHOLE_BODY_CONTROLLER,
    TaskPolicyHandoffState,
    WholeBodyTaskSpaceController,
    _diagnostic_trace_errors,
    _trace_number,
    assess_diagnostic_trace,
)

A6_SUPERVISOR_EVIDENCE = {
    "job": "worldspec-h1-midterm-69xm4",
    "profileDigest": (
        "sha256:731c1812787a3c63230d49220f5e08a48b7d04f7e7967bf476d0d066d083eec4"
    ),
    "reportDigest": (
        "sha256:1ebb614d7315442a98937e09b58b888796922547b1ecc962e3a8aa49ae3325c0"
    ),
    "reportSizeBytes": 23_042,
    "controllerDigest": (
        "sha256:62c7c3127797998b147260c65a125f632011f6cba4796f9ed555e563e2f4631d"
    ),
    "traceDigest": (
        "sha256:6fcd89018a3152c4ece0d8261b143a898ec7d3c4e858289202d1d5f7e8cc1b4f"
    ),
    "formalTaskLoadSupervisorGate": "passed",
    "deterministicTestsPassed": 10,
}

A5CK_CONTROL_LINEAGE = {
    "profileDigest": (
        "sha256:23fcf6908136c57880871ac0a1f9e1f13339b5d8f562eb0af8d710362f75efa8"
    ),
    "sourceJob": "worldspec-h1-midterm-5nn2q",
    "sourceTraceDigest": (
        "sha256:175427d1d3d74da7fe5c422f3290f07ae6dfa6c21179626dd4d4558915012bd9"
    ),
    "formalControlGate": "failed",
    "terminalReason": "fall_height",
    "reuseBoundary": "controller_contract_only",
}

FULL_TASK_SINGLE_GATES = {
    "probeRuns": 1,
    "minimumForwardDisplacement": TASK_GATES["minimumForwardDisplacement"],
    "maximumForwardDisplacement": TASK_GATES["maximumForwardDisplacement"],
    "minimumBaseHeight": TASK_GATES["minimumBaseHeight"],
    "minimumUprightCosine": TASK_GATES["minimumUprightCosine"],
    "drawerOpenThreshold": TASK_GATES["drawerOpenThreshold"],
    "drawerClosedThreshold": TASK_GATES["drawerClosedThreshold"],
    "cupInsideMargin": TASK_GATES["cupInsideMargin"],
    "maximumCupLinearSpeed": TASK_GATES["maximumCupLinearSpeed"],
    "maximumCupAngularSpeed": TASK_GATES["maximumCupAngularSpeed"],
    "minimumStableSteps": TASK_GATES["minimumStableSteps"],
    "maximumTaskBaseTranslation": 0.20,
    "maximumTaskBaseLateralDrift": 0.12,
    "maximumProjectedGradient": 1e-5,
    "maximumNonFiniteSamples": 0,
}

FULL_TASK_PHASE_CONTROLLER = {
    "phases": copy.deepcopy(PHASES),
    "positionToleranceMeters": TASK_CONTROLLER["positionToleranceMeters"],
    "openGripperCommand": TASK_CONTROLLER["openGripperCommand"],
    "closedGripperCommand": TASK_CONTROLLER["closedGripperCommand"],
    "phaseMinimumSteps": copy.deepcopy(TASK_CONTROLLER["phaseMinimumSteps"]),
    "phaseMaximumSteps": copy.deepcopy(TASK_CONTROLLER["phaseMaximumSteps"]),
}

FULL_TASK_LOCOMOTION_HANDOFF = copy.deepcopy(SUPERVISOR)
FULL_TASK_LOCOMOTION_HANDOFF["captureGate"]["maximumSteps"] = 50
FULL_TASK_HANDOFF_EVIDENCE = {
    "job": "worldspec-h1-midterm-brj2f",
    "reportDigest": (
        "sha256:3147789c6573a6fdb017bfe59cf865a2344379843bffdf275376bcdddb0c7ac5"
    ),
    "reportSizeBytes": 16_408,
    "traceDigest": (
        "sha256:f9e1b25de7b630f194cd85a03282577b4a63b0e368e47de14771c9d56f777697"
    ),
    "traceSizeBytes": 1_424_163,
    "diagnosticStatus": "passed",
    "failedReason": "locomotion_handoff_timeout",
    "captureStepsObserved": 40,
    "stableStepsAtTerminal": 2,
    "firstStableStep": 188,
    "qualityGatesChanged": False,
}
FULL_TASK_BASE_ANCHOR_RECOVERY = {
    "mode": "disabled_locked_stand_policy",
    "enabled": False,
    "policy": "standPolicy",
    "command": [0.0, 0.0, 0.0],
    "armDuringManipulation": "track_current_task_space_solution",
    "motionPolicyReentry": "forbidden",
    "qualityGatesChanged": False,
}
FULL_TASK_ARM_RECOVERY_EVIDENCE = {
    "job": "worldspec-h1-midterm-z8fbf",
    "reportDigest": (
        "sha256:53e2b58a0aee444e9430e5be5167ebbd628973b178864df414c6aa9777eb9fd0"
    ),
    "reportSizeBytes": 17_688,
    "traceDigest": (
        "sha256:2b60b2885c74deba9dd2eaa1f375501f0dd2027449362d5a4fb381a446dd5cee"
    ),
    "traceSizeBytes": 2_657_263,
    "diagnosticStatus": "passed",
    "failedReason": "reach_handle_timeout",
    "completedPhase": "reach_handle",
    "baseAnchorRecoverySteps": 100,
    "finalTargetErrorMeters": 0.07562772505351109,
    "qualityGatesChanged": False,
}
FULL_TASK_BASE_LOCK_EVIDENCE = {
    "job": "worldspec-h1-midterm-gz47f",
    "reportDigest": (
        "sha256:1feb9ff6050d774fba20e521574cb61095a9a3084f373b64d7c7bf093d6705c3"
    ),
    "reportSizeBytes": 18_329,
    "traceDigest": (
        "sha256:bcaa26d8537fce06b154f9031b296b35e198d802684cd7d4a433338d8db74224"
    ),
    "traceSizeBytes": 2_299_733,
    "diagnosticStatus": "passed",
    "failedReason": "robot_termination:fall_height,fall_upright",
    "completedPhase": "reach_handle",
    "baseAnchorRecoverySteps": 87,
    "minimumBaseHeight": 0.46340638399124146,
    "minimumUprightCosine": 0.2332257628440857,
    "taskBaseLateralDrift": 0.8904498987831175,
    "maximumBaseAnchorCommand": 0.1,
    "qualityGatesChanged": False,
}


def validate_full_task_single_profile(
    base_profile: dict[str, Any],
    supervisor_profile: dict[str, Any],
    profile: dict[str, Any],
) -> None:
    """Validate the independently gated, one-run full A5 contract."""

    validate_profile(base_profile)
    make_supervisor_evaluation_profile(base_profile, supervisor_profile)
    if (
        supervisor_profile.get("stage") != "task_load_phase_aware_supervisor_probe"
        or profile.get("profileVersion") != "0.1.0"
        or profile.get("status") != "research"
        or profile.get("stage") != "task_load_fixed_kitchen_single_probe"
    ):
        raise TrainingError(
            "FULL_TASK_SINGLE_PROFILE_UNSUPPORTED",
            "The single full-A5 gate requires the passing A6-S supervisor stage.",
        )
    if profile.get("baseTrainingProfileDigest") != digest_json(base_profile):
        raise TrainingError(
            "FULL_TASK_SINGLE_BASE_PROFILE_MISMATCH",
            "The full-A5 probe is not bound to the exact base Profile.",
        )
    if profile.get("supervisorProfileDigest") != digest_json(supervisor_profile):
        raise TrainingError(
            "FULL_TASK_SINGLE_SUPERVISOR_MISMATCH",
            "The full-A5 probe is not bound to the exact A6-S Profile.",
        )
    if profile.get("supervisorEvidence") != A6_SUPERVISOR_EVIDENCE:
        raise TrainingError(
            "FULL_TASK_SINGLE_SUPERVISOR_EVIDENCE_INVALID",
            "The full-A5 probe requires the frozen passing A6-S evidence.",
        )
    for key in ("motionPolicy", "capturePolicy", "standPolicy"):
        if profile.get(key) != supervisor_profile.get(key):
            raise TrainingError(
                "FULL_TASK_SINGLE_POLICY_LINEAGE_MISMATCH",
                "The full-A5 probe must reuse the exact A6-S policy identities.",
            )
    expected_contracts = (
        ("controlLineage", A5CK_CONTROL_LINEAGE),
        ("scene", ERGONOMIC_TASK_SCENE),
        ("wholeBodyController", WHOLE_BODY_CONTROLLER),
        ("taskPolicyHandoff", TASK_POLICY_HANDOFF),
        ("dynamicArmTracking", DYNAMIC_ARM_TRACKING),
        ("taskGeometryCalibration", TASK_GEOMETRY_CALIBRATION),
        ("baseAnchorRecovery", FULL_TASK_BASE_ANCHOR_RECOVERY),
        ("taskSceneLocomotionHandoff", FULL_TASK_LOCOMOTION_HANDOFF),
        ("taskSceneHandoffEvidence", FULL_TASK_HANDOFF_EVIDENCE),
        ("taskSceneArmRecoveryEvidence", FULL_TASK_ARM_RECOVERY_EVIDENCE),
        ("taskSceneBaseLockEvidence", FULL_TASK_BASE_LOCK_EVIDENCE),
        ("phaseController", FULL_TASK_PHASE_CONTROLLER),
        ("qualityGates", FULL_TASK_SINGLE_GATES),
    )
    for key, expected in expected_contracts:
        if profile.get(key) != expected:
            raise TrainingError(
                f"FULL_TASK_SINGLE_{key.upper()}_INVALID",
                f"The full-A5 {key} contract changed.",
            )
    runtime = profile.get("runtime", {})
    if (
        runtime.get("ccdIterations") != 50
        or runtime.get("evaluationEnvironments") != 1
        or runtime.get("mjxCapacity") != TASK_CAPACITY
    ):
        raise TrainingError(
            "FULL_TASK_SINGLE_RUNTIME_INVALID",
            "The single full-A5 probe requires CCD=50 and its frozen capacity.",
        )
    if (
        runtime.get("containerDigest")
        != runtime.get("containerImage", "").rsplit("@", maxsplit=1)[-1]
    ):
        raise TrainingError(
            "FULL_TASK_SINGLE_CONTAINER_BINDING_MISMATCH",
            "containerImage and containerDigest must identify one OCI image.",
        )
    if runtime.get("packageLockDigest") != base_profile["runtime"]["packageLockDigest"]:
        raise TrainingError(
            "FULL_TASK_SINGLE_PACKAGE_LOCK_MISMATCH",
            "The full-A5 probe must preserve the frozen package lock.",
        )
    if profile.get("artifactPolicy") != {
        "controller": "research_only",
        "distribution": "internal_only",
        "fiveRunClaim": "forbidden",
        "l3Claim": "forbidden",
    }:
        raise TrainingError(
            "FULL_TASK_SINGLE_ARTIFACT_POLICY_INVALID",
            "A single A5 run cannot claim 5/5 or L3.",
        )


def make_full_task_single_evaluation_profile(
    base_profile: dict[str, Any],
    supervisor_profile: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    validate_full_task_single_profile(base_profile, supervisor_profile, profile)
    effective = make_supervisor_evaluation_profile(base_profile, supervisor_profile)
    effective["runtime"]["containerDigest"] = profile["runtime"]["containerDigest"]
    effective["runtime"]["ccdIterations"] = profile["runtime"]["ccdIterations"]
    effective["runtime"]["mjxCapacity"] = copy.deepcopy(profile["runtime"]["mjxCapacity"])
    effective["training"]["numEnvs"] = 1
    effective["training"]["seed"] = profile["seed"]
    return effective


def evaluate_full_task_single(
    profile: dict[str, Any],
    env,
    motion_policy,
    capture_policy,
    stand_policy,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Execute one complete ordered A5 task under the A6-S task load."""

    import jax
    import jax.numpy as jp
    import numpy as np

    motion_inference = jax.jit(motion_policy)
    capture_inference = jax.jit(capture_policy)
    stand_inference = jax.jit(stand_policy)
    reset = jax.jit(env.reset)
    step = jax.jit(env.step)
    controller = WholeBodyTaskSpaceController(
        env.mj_model,
        profile["control"],
        DYNAMIC_ARM_TRACKING,
    )
    rng = jax.random.PRNGKey(profile["training"]["seed"])
    state = reset(rng)
    locomotion = SupervisorState(contract=FULL_TASK_LOCOMOTION_HANDOFF)
    task_policy = TaskPolicyHandoffState()
    task = KitchenTaskState()
    traces: list[dict[str, Any]] = []
    start_x = float(np.asarray(state.data.qpos[0]))
    minimum_height = float("inf")
    minimum_upright = float("inf")
    maximum_projected_gradient = 0.0
    nonfinite = 0
    done_seen = False
    failure: str | None = None
    terminal_reasons: set[str] = set()
    initial_task_base = None
    base_anchor_recovery_steps = 0
    maximum_base_anchor_command = 0.0
    initial_load_targets = list(
        profile["trainingEnvironment"]["taskLoadCurriculum"]["heldTargets"]
    )
    initial_load_feedforward = list(
        profile["trainingEnvironment"]["taskLoadCurriculum"]["heldFeedforward"]
    )

    def with_inputs(state_value, command, held_targets, feedforward, gripper):
        info = dict(state_value.info)
        info["command"] = command
        info["held_targets"] = jp.asarray(held_targets)
        info["held_feedforward"] = jp.asarray(feedforward)
        info["gripper_commands"] = jp.asarray([gripper])
        false_value = command[0] < command[0]
        info["transition_active"] = false_value
        info["stand_replay_active"] = false_value
        info["capture_active"] = false_value
        observation = {
            "state": env._observation(
                state_value.data,
                info["last_action"],
                command,
            )
        }
        return state_value.replace(info=info, obs=observation)

    maximum_steps = SUPERVISOR["moveSteps"] + SUPERVISOR["settleSteps"] + sum(
        TASK_CONTROLLER["phaseMaximumSteps"].values()
    )
    for index in range(maximum_steps):
        in_locomotion = index < SUPERVISOR["moveSteps"] + SUPERVISOR["settleSteps"]
        moving = index < SUPERVISOR["moveSteps"]
        control = None
        task_handoff_phase = None
        task_handoff_alpha = None
        if in_locomotion:
            phase = "locomotion" if moving else "locomotion_settle"
            command = jp.asarray([0.5, 0.0, 0.0]) if moving else jp.zeros(3)
            policy_command = command
            held_targets = initial_load_targets
            feedforward = initial_load_feedforward
            gripper = TASK_CONTROLLER["openGripperCommand"]
        else:
            if locomotion.phase != "stand":
                failure = "locomotion_supervisor_not_ready"
                break
            if initial_task_base is None:
                initial_task_base = np.asarray(state.data.qpos[:3], dtype=float).copy()
            phase = task.phase
            metrics_before = _task_metrics(env, state, ERGONOMIC_TASK_SCENE)
            target = _target_for_phase(phase, metrics_before, ERGONOMIC_TASK_SCENE)
            candidate = controller.solve(
                np.asarray(state.data.qpos),
                np.asarray(state.data.qvel),
                target,
                allow_base=False,
            )
            anchor_command = np.asarray(
                FULL_TASK_BASE_ANCHOR_RECOVERY["command"],
                dtype=float,
            )
            anchor_norm = 0.0
            maximum_base_anchor_command = max(maximum_base_anchor_command, anchor_norm)
            recovery_active = False
            control = candidate
            control["baseAnchorCommand"] = [float(value) for value in anchor_command]
            control["baseAnchorRecoveryActive"] = recovery_active
            control["appliedArmTargetSource"] = "current_task_space_solution"
            maximum_projected_gradient = max(
                maximum_projected_gradient,
                float(control["qpProjectedGradient"]),
            )
            command = jp.asarray(anchor_command)
            task_handoff_phase = task_policy.prepare(anchor_norm)
            policy_command = command
            held_targets = control["heldTargets"]
            feedforward = control["feedforwardTorque"]
            gripper = _gripper_for_phase(phase)

        state = with_inputs(
            state,
            policy_command,
            held_targets,
            feedforward,
            gripper,
        )
        rng, motion_rng, capture_rng, stand_rng = jax.random.split(rng, 4)
        motion_action, _ = motion_inference(state.obs, motion_rng)
        capture_action, _ = capture_inference(state.obs, capture_rng)
        stand_action, _ = stand_inference(state.obs, stand_rng)
        if in_locomotion:
            action, active_policy, _ = locomotion.select(
                moving,
                motion_action,
                capture_action,
                stand_action,
            )
        else:
            action, active_policy, task_handoff_alpha = task_policy.select(
                motion_action,
                capture_action,
                stand_action,
            )
        state = step(state, action)
        jax.block_until_ready(state.reward)

        qpos = np.asarray(state.data.qpos)
        qvel = np.asarray(state.data.qvel)
        linear = np.asarray(env.local_velocity(state.data), dtype=float)
        angular = np.asarray(env.angular_velocity(state.data), dtype=float)
        height = float(np.asarray(state.data.xpos[env.pelvis_body_id, 2]))
        upright = float(np.asarray(env.upvector(state.data)[2]))
        finite = bool(np.isfinite(qpos).all() and np.isfinite(qvel).all())
        done = bool(np.asarray(state.done))
        minimum_height = min(minimum_height, height)
        minimum_upright = min(minimum_upright, upright)
        nonfinite += 0 if finite else 1
        raw_termination = state.info.get("termination")
        termination: dict[str, bool | None] | Any
        if isinstance(raw_termination, Mapping):
            termination = {}
            for name, value in raw_termination.items():
                array = np.asarray(value)
                termination[name] = (
                    bool(array)
                    if array.shape == () and np.issubdtype(array.dtype, np.bool_)
                    else None
                )
            terminal_reasons.update(
                name for name, active in termination.items() if active is True
            )
        else:
            termination = raw_termination
        diagnostic = controller.diagnostic_state(
            qpos,
            qvel,
            state.data.ctrl,
            joint_limit_tolerance=float(env._joint_limit_tolerance),
        )
        task_metrics = _task_metrics(env, state, ERGONOMIC_TASK_SCENE)
        site = None
        if in_locomotion:
            locomotion.observe(
                active_policy,
                float(np.linalg.norm(linear)),
                float(np.linalg.norm(angular)),
            )
            if locomotion.handoff_failed:
                failure = "locomotion_handoff_timeout"
        else:
            task_policy.observe(
                active_policy,
                float(np.linalg.norm(linear)),
                float(np.linalg.norm(angular)),
            )
            if task_policy.handoff_failed:
                failure = failure or "task_policy_handoff_timeout"
            target = _target_for_phase(task.phase, task_metrics, ERGONOMIC_TASK_SCENE)
            site = controller.site_state(qpos, qvel, target)
            task.observe(
                target_error=site["targetErrorMeters"],
                drawer_position=task_metrics["drawerPosition"],
                cup_inside=task_metrics["cupInside"],
                cup_linear_speed=task_metrics["cupLinearSpeed"],
                cup_angular_speed=task_metrics["cupAngularSpeed"],
            )
            if task.failed_reason:
                failure = failure or task.failed_reason

        record = {
            "run": 0,
            "step": index,
            "timeSeconds": (index + 1) * env.dt,
            "phase": phase,
            "activePolicy": active_policy,
            "command": [_trace_number(value) for value in np.asarray(policy_command)],
            "policyCommand": [_trace_number(value) for value in np.asarray(policy_command)],
            "basePosition": [_trace_number(value) for value in qpos[:3]],
            "baseState": {
                "position": [_trace_number(value) for value in qpos[:3]],
                "linearVelocity": [_trace_number(value) for value in linear],
                "angularVelocity": [_trace_number(value) for value in angular],
                "height": _trace_number(height),
                "uprightCosine": _trace_number(upright),
            },
            "minimumBaseHeight": _trace_number(minimum_height),
            "minimumUprightCosine": _trace_number(minimum_upright),
            "gripperCommand": _trace_number(gripper),
            "taskMetrics": task_metrics,
            "finite": finite,
            "done": done,
            "termination": termination,
            "jointState": diagnostic["jointState"],
            "actuation": diagnostic["actuation"],
            "control": control,
            "site": site,
        }
        if not in_locomotion:
            record["taskPolicyHandoff"] = {
                "phase": task_handoff_phase,
                "blendAlpha": _trace_number(task_handoff_alpha),
                "requestedCommandNorm": _trace_number(np.linalg.norm(np.asarray(command))),
                "captureSteps": task_policy.capture_steps,
                "stableSteps": task_policy.stable_steps,
                "blendSteps": task_policy.blend_steps,
                "handoffFailed": task_policy.handoff_failed,
            }
            record["baseAnchorRecovery"] = {
                "active": bool(control["baseAnchorRecoveryActive"]),
                "command": copy.deepcopy(control["baseAnchorCommand"]),
                "steps": base_anchor_recovery_steps,
                "maximumCommandNorm": _trace_number(maximum_base_anchor_command),
                "armTargetSource": control["appliedArmTargetSource"],
            }
        traces.append(record)
        diagnostic_errors = _diagnostic_trace_errors(record, profile["control"])
        if diagnostic_errors:
            failure = failure or f"diagnostic_incomplete:{diagnostic_errors[0]}"
        if done:
            done_seen = True
            reason = ",".join(sorted(terminal_reasons)) or "unclassified"
            failure = failure or f"robot_termination:{reason}"
        if failure or (not in_locomotion and task.completed):
            break

    if initial_task_base is None:
        initial_task_base = np.asarray(state.data.qpos[:3], dtype=float)
    final_base = np.asarray(state.data.qpos[:3], dtype=float)
    task_base_delta = final_base - initial_task_base
    final = _task_metrics(env, state, ERGONOMIC_TASK_SCENE)
    released = float(np.asarray(state.info["gripper_commands"])[0]) == 0.0
    displacement = float(np.asarray(state.data.qpos[0])) - start_x
    diagnostic_assessment = assess_diagnostic_trace(traces, profile["control"])
    passed = (
        failure is None
        and task.completed
        and diagnostic_assessment["status"] == "passed"
        and FULL_TASK_SINGLE_GATES["minimumForwardDisplacement"]
        <= displacement
        <= FULL_TASK_SINGLE_GATES["maximumForwardDisplacement"]
        and minimum_height >= FULL_TASK_SINGLE_GATES["minimumBaseHeight"]
        and minimum_upright >= FULL_TASK_SINGLE_GATES["minimumUprightCosine"]
        and task.maximum_drawer_opening >= FULL_TASK_SINGLE_GATES["drawerOpenThreshold"]
        and final["drawerPosition"] <= FULL_TASK_SINGLE_GATES["drawerClosedThreshold"]
        and final["cupInside"]
        and released
        and final["cupLinearSpeed"] <= FULL_TASK_SINGLE_GATES["maximumCupLinearSpeed"]
        and final["cupAngularSpeed"] <= FULL_TASK_SINGLE_GATES["maximumCupAngularSpeed"]
        and float(np.linalg.norm(task_base_delta[:2]))
        <= FULL_TASK_SINGLE_GATES["maximumTaskBaseTranslation"]
        and abs(float(task_base_delta[1]))
        <= FULL_TASK_SINGLE_GATES["maximumTaskBaseLateralDrift"]
        and maximum_projected_gradient
        <= FULL_TASK_SINGLE_GATES["maximumProjectedGradient"]
        and nonfinite <= FULL_TASK_SINGLE_GATES["maximumNonFiniteSamples"]
        and not done_seen
    )
    return (
        {
            "id": "test://worldspec/h1-kitchen/task-load-full-loop-single/1",
            "result": "pass" if passed else "fail",
            "metrics": {
                "completedPhase": task.phase,
                "failedReason": failure,
                "forwardDisplacement": displacement,
                "taskBaseTranslation": float(np.linalg.norm(task_base_delta[:2])),
                "taskBaseLateralDrift": abs(float(task_base_delta[1])),
                "minimumBaseHeight": minimum_height,
                "minimumUprightCosine": minimum_upright,
                "maximumDrawerOpening": task.maximum_drawer_opening,
                "finalDrawerPosition": final["drawerPosition"],
                "cupInside": final["cupInside"],
                "cupReleased": released,
                "cupLinearSpeed": final["cupLinearSpeed"],
                "cupAngularSpeed": final["cupAngularSpeed"],
                "maximumProjectedGradient": maximum_projected_gradient,
                "nonFiniteSamples": nonfinite,
                "doneSeen": done_seen,
                "terminalReasons": diagnostic_assessment["terminalReasons"],
                "terminalJoints": diagnostic_assessment["terminalJoints"],
                "controlSaturationSamples": diagnostic_assessment[
                    "controlSaturationSamples"
                ],
                "maximumControlUtilization": diagnostic_assessment[
                    "maximumControlUtilization"
                ],
                "diagnosticStatus": diagnostic_assessment["status"],
                "diagnosticReasons": diagnostic_assessment["reasons"],
                "baseAnchorRecoverySteps": base_anchor_recovery_steps,
                "maximumBaseAnchorCommand": maximum_base_anchor_command,
            },
        },
        traces,
    )


def run_task_load_full_kitchen_single_probe(
    base_profile: dict[str, Any],
    supervisor_profile: dict[str, Any],
    profile: dict[str, Any],
    bundle_dir: Path,
    model_dir: Path,
    output_dir: Path,
    motion_archive: Path,
    capture_archive: Path,
    stand_archive: Path,
) -> dict[str, Any]:
    """Run the single full-A5 gate and retain all evidence on failure."""

    from brax.training.agents.ppo import networks as ppo_networks

    from .environment import make_environment

    effective = make_full_task_single_evaluation_profile(
        base_profile,
        supervisor_profile,
        profile,
    )
    static = static_preflight(base_profile, bundle_dir)
    task_model, derivation = prepare_kitchen_task_model(
        base_profile,
        bundle_dir,
        model_dir,
        task_scene=ERGONOMIC_TASK_SCENE,
    )
    runtime = runtime_preflight(effective, task_model)
    output_dir.mkdir(parents=True, exist_ok=True)
    network_factory = functools.partial(
        ppo_networks.make_ppo_networks,
        policy_hidden_layer_sizes=(128, 128, 128, 128),
        value_hidden_layer_sizes=(256, 256, 256, 256, 256),
        policy_obs_key="state",
        value_obs_key="state",
    )
    environment = make_environment(effective, task_model)
    observation_size = _flat_observation_size(environment.observation_size["state"])
    action_size = int(environment.action_size)
    loaded: dict[str, dict[str, Any]] = {}
    policies: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="worldspec-h1-full-task-single-") as temporary:
        root = Path(temporary)
        for role, archive, source in (
            ("motion", motion_archive, profile["motionPolicy"]),
            ("capture", capture_archive, profile["capturePolicy"]),
            ("stand", stand_archive, profile["standPolicy"]),
        ):
            step_path, initialization = materialize_warm_start(
                archive,
                root / role,
                source["checkpointDigest"],
                source["checkpointSizeBytes"],
            )
            validate_network_compatibility(initialization, observation_size, action_size)
            policies[role] = _load_deterministic_teacher_policy(
                step_path,
                initialization,
                network_factory,
            )
            initialization["role"] = source["selectedRole"]
            loaded[role] = initialization
        test, traces = evaluate_full_task_single(
            effective,
            environment,
            policies["motion"],
            policies["capture"],
            policies["stand"],
        )
    trace_path = output_dir / "evaluation-traces.jsonl"
    with trace_path.open("w", encoding="utf-8") as stream:
        for record in traces:
            stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    controller_artifact = {
        "controllerVersion": "0.1.0",
        "status": "research_only",
        "profileDigest": digest_json(profile),
        "supervisorProfileDigest": digest_json(supervisor_profile),
        "supervisorEvidence": copy.deepcopy(A6_SUPERVISOR_EVIDENCE),
        "controlLineage": copy.deepcopy(A5CK_CONTROL_LINEAGE),
        "wholeBodyController": copy.deepcopy(WHOLE_BODY_CONTROLLER),
        "taskPolicyHandoff": copy.deepcopy(TASK_POLICY_HANDOFF),
        "dynamicArmTracking": copy.deepcopy(DYNAMIC_ARM_TRACKING),
        "taskGeometryCalibration": copy.deepcopy(TASK_GEOMETRY_CALIBRATION),
        "baseAnchorRecovery": copy.deepcopy(FULL_TASK_BASE_ANCHOR_RECOVERY),
        "taskSceneLocomotionHandoff": copy.deepcopy(FULL_TASK_LOCOMOTION_HANDOFF),
        "taskSceneHandoffEvidence": copy.deepcopy(FULL_TASK_HANDOFF_EVIDENCE),
        "taskSceneArmRecoveryEvidence": copy.deepcopy(FULL_TASK_ARM_RECOVERY_EVIDENCE),
        "taskSceneBaseLockEvidence": copy.deepcopy(FULL_TASK_BASE_LOCK_EVIDENCE),
        "phaseController": copy.deepcopy(FULL_TASK_PHASE_CONTROLLER),
        "scene": copy.deepcopy(ERGONOMIC_TASK_SCENE),
        "policies": {
            role: {
                "checkpointDigest": value["archiveDigest"],
                "selectedStep": value["selectedStep"],
            }
            for role, value in loaded.items()
        },
        "distribution": "internal_only",
        "fiveRunClaim": "forbidden",
        "l3Claim": "forbidden",
    }
    controller_path = output_dir / "task-load-full-kitchen-controller.json"
    controller_path.write_bytes(canonical_bytes(controller_artifact))
    passed = test["result"] == "pass"
    return {
        "baseTrainingProfileDigest": digest_json(base_profile),
        "supervisorProfileDigest": digest_json(supervisor_profile),
        "taskProfileDigest": digest_json(profile),
        "supervisorEvidence": copy.deepcopy(A6_SUPERVISOR_EVIDENCE),
        "controlLineage": copy.deepcopy(A5CK_CONTROL_LINEAGE),
        "taskSceneHandoffEvidence": copy.deepcopy(FULL_TASK_HANDOFF_EVIDENCE),
        "taskSceneArmRecoveryEvidence": copy.deepcopy(FULL_TASK_ARM_RECOVERY_EVIDENCE),
        "taskSceneBaseLockEvidence": copy.deepcopy(FULL_TASK_BASE_LOCK_EVIDENCE),
        "policies": loaded,
        "staticPreflight": static,
        "runtimePreflight": runtime,
        "target": {
            "sourceBundleDigest": derivation["parentDerivation"]["sourceBundleDigest"],
            "derivedModelDigest": derivation["derivedModelDigest"],
            "observationSize": observation_size,
            "actionSize": action_size,
        },
        "scene": copy.deepcopy(ERGONOMIC_TASK_SCENE),
        "controller": {
            "wholeBodyController": copy.deepcopy(WHOLE_BODY_CONTROLLER),
            "taskPolicyHandoff": copy.deepcopy(TASK_POLICY_HANDOFF),
            "dynamicArmTracking": copy.deepcopy(DYNAMIC_ARM_TRACKING),
            "baseAnchorRecovery": copy.deepcopy(FULL_TASK_BASE_ANCHOR_RECOVERY),
            "taskSceneLocomotionHandoff": copy.deepcopy(FULL_TASK_LOCOMOTION_HANDOFF),
            "phaseController": copy.deepcopy(FULL_TASK_PHASE_CONTROLLER),
        },
        "qualityAssessment": {
            "status": "passed" if passed else "failed",
            "singleRunGate": passed,
            "tests": [test],
        },
        "controllerArtifact": {
            "path": controller_path.name,
            "digest": digest_bytes(controller_path.read_bytes()),
            "sizeBytes": controller_path.stat().st_size,
            "distribution": "internal_only",
        },
        "traceArtifact": {
            "path": trace_path.name,
            "digest": digest_bytes(trace_path.read_bytes()),
            "sizeBytes": trace_path.stat().st_size,
            "distribution": "internal_only",
        },
        "claimBoundary": {
            "status": "research_single_integration_only",
            "fiveRunClaim": "forbidden",
            "l3Claim": "forbidden",
            "reasons": [
                "single_run_does_not_establish_fixed_scene_five_of_five",
                "right_gripper_mount_evidence_is_estimated_and_unvalidated",
                "task_scene_is_self_authored_primitive_proxy_not_real_kitchen_evidence",
                "randomized_robustness_not_evaluated",
            ],
        },
    }
