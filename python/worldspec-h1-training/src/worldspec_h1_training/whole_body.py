"""A5-C hierarchical whole-body task-space control spike.

The controller solves a small box-constrained convex QP on the host.  Its
decision vector contains planar base velocity, torso velocity, and the four
right-arm joint velocities.  The frozen locomotion/stand policies remain the
only leg controller.  MuJoCo bias forces are passed to MJX as explicit,
traceable feed-forward torque; no hidden constraint or kinematic teleport is
introduced.
"""

from __future__ import annotations

import copy
import functools
import json
import tempfile
from pathlib import Path
from typing import Any

from .contract import canonical_bytes, digest_bytes, digest_json, validate_profile
from .errors import TrainingError
from .kitchen_task import (
    TASK_CAPACITY,
    TASK_SCENE,
    _target_for_phase,
    _task_metrics,
    prepare_kitchen_task_model,
)
from .midterm import _load_deterministic_teacher_policy
from .preflight import runtime_preflight, static_preflight
from .supervisor import SUPERVISOR, SupervisorState, make_supervisor_evaluation_profile
from .trainer import _flat_observation_size
from .warm_start import materialize_warm_start, validate_network_compatibility

WHOLE_BODY_CONTROLLER = {
    "mode": "hierarchical_box_qp_with_inverse_dynamics_feedforward",
    "decisionVariables": [
        "base_velocity_x",
        "base_velocity_y",
        "base_yaw_rate",
        "torso_velocity",
        "right_shoulder_pitch_velocity",
        "right_shoulder_roll_velocity",
        "right_shoulder_yaw_velocity",
        "right_elbow_velocity",
    ],
    "controlledJoints": [
        "torso",
        "right_shoulder_pitch",
        "right_shoulder_roll",
        "right_shoulder_yaw",
        "right_elbow",
    ],
    "qpIterations": 48,
    "cartesianGain": 4.0,
    "maximumCartesianSpeed": 0.35,
    "velocityLowerBounds": [-0.08, -0.06, -0.15, -0.5, -0.8, -0.8, -0.8, -0.8],
    "velocityUpperBounds": [0.08, 0.06, 0.15, 0.5, 0.8, 0.8, 0.8, 0.8],
    "regularization": [2.0, 2.0, 3.0, 0.35, 0.15, 0.15, 0.15, 0.15],
    "targetHorizonSeconds": 0.4,
    "maximumJointTargetStep": 0.30,
    "jointLimitMarginRadians": 0.05,
    "feedforwardScale": 1.0,
    "feedforwardControlReserve": 0.20,
}

WHOLE_BODY_GATES = {
    "settleSteps": 25,
    "trackingSteps": 180,
    "positionToleranceMeters": 0.035,
    "holdSteps": 20,
    "maximumTcpSpeed": 0.15,
    "maximumBaseTranslation": 0.20,
    "maximumBaseLateralDrift": 0.12,
    "minimumBaseHeight": 0.80,
    "minimumUprightCosine": 0.80,
    "maximumProjectedGradient": 1e-5,
    "maximumNonFiniteSamples": 0,
}

A5R_FAILED_REPORT_DIGEST = (
    "sha256:c55d67244d28d3abdfef787b7858fceabea61a534fe1beb674fdc3bad7a67da0"
)


def solve_box_qp(
    hessian,
    gradient,
    lower,
    upper,
    *,
    iterations: int,
):
    """Solve a strictly-convex box QP using deterministic coordinate descent."""

    import numpy as np

    h = np.asarray(hessian, dtype=float)
    g = np.asarray(gradient, dtype=float)
    lo = np.asarray(lower, dtype=float)
    hi = np.asarray(upper, dtype=float)
    if (
        h.ndim != 2
        or h.shape[0] != h.shape[1]
        or g.shape != (h.shape[0],)
        or lo.shape != g.shape
        or hi.shape != g.shape
        or not np.all(np.isfinite(h))
        or not np.all(np.isfinite(g))
        or not np.all(lo <= hi)
        or np.any(np.diag(h) <= 0)
    ):
        raise TrainingError("WHOLE_BODY_QP_INVALID", "Box QP inputs are invalid.")
    solution = np.zeros_like(g)
    solution = np.clip(solution, lo, hi)
    for _ in range(iterations):
        for index in range(solution.size):
            residual = g[index] + float(h[index] @ solution)
            solution[index] = np.clip(
                solution[index] - residual / h[index, index],
                lo[index],
                hi[index],
            )
    full_gradient = h @ solution + g
    projected = solution - np.clip(solution - full_gradient, lo, hi)
    objective = 0.5 * float(solution @ h @ solution) + float(g @ solution)
    return solution, objective, float(np.max(np.abs(projected)))


class WholeBodyTaskSpaceController:
    """Host-side task allocator and inverse-dynamics feed-forward generator."""

    def __init__(self, model, control_profile: dict[str, Any]) -> None:
        import mujoco
        import numpy as np

        self._mujoco = mujoco
        self._np = np
        self._model = model
        self._data = mujoco.MjData(model)
        self._site = mujoco.mj_name2id(
            model,
            mujoco.mjtObj.mjOBJ_SITE,
            "right_gripper_pinch",
        )
        pelvis = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "pelvis")
        if self._site < 0 or pelvis < 0:
            raise TrainingError(
                "WHOLE_BODY_CONTROL_BINDING_MISSING",
                "Whole-body controller requires pelvis and right_gripper_pinch.",
            )
        root_joint = int(model.body_jntadr[pelvis])
        root_dof = int(model.jnt_dofadr[root_joint])
        self._base_dofs = np.asarray([root_dof, root_dof + 1, root_dof + 5], dtype=int)
        self._joint_names = WHOLE_BODY_CONTROLLER["controlledJoints"]
        self._joint_ids = np.asarray(
            [
                mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name)
                for name in self._joint_names
            ],
            dtype=int,
        )
        held_names = control_profile["heldJoints"]
        self._held_joint_ids = np.asarray(
            [
                mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name)
                for name in held_names
            ],
            dtype=int,
        )
        held_actuator_ids = np.asarray(
            [
                mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, name)
                for name in control_profile["heldActuators"]
            ],
            dtype=int,
        )
        if (
            (self._joint_ids < 0).any()
            or (self._held_joint_ids < 0).any()
            or (held_actuator_ids < 0).any()
        ):
            raise TrainingError(
                "WHOLE_BODY_CONTROL_BINDING_MISSING",
                "Whole-body joint or actuator binding is absent from the target model.",
            )
        self._joint_qpos = model.jnt_qposadr[self._joint_ids]
        self._joint_dofs = model.jnt_dofadr[self._joint_ids]
        self._joint_ranges = model.jnt_range[self._joint_ids]
        self._held_qpos = model.jnt_qposadr[self._held_joint_ids]
        self._held_dofs = model.jnt_dofadr[self._held_joint_ids]
        self._held_ranges = model.jnt_range[self._held_joint_ids]
        self._held_index = {
            name: index for index, name in enumerate(control_profile["heldJoints"])
        }
        self._held_ctrlrange = model.actuator_ctrlrange[held_actuator_ids]

    def solve(self, qpos, qvel, target, *, allow_base: bool = True) -> dict[str, Any]:
        np = self._np
        qpos_value = np.asarray(qpos, dtype=float)
        qvel_value = np.asarray(qvel, dtype=float)
        target_value = np.asarray(target, dtype=float)
        self._data.qpos[:] = qpos_value
        self._data.qvel[:] = qvel_value
        self._mujoco.mj_forward(self._model, self._data)
        current = self._data.site_xpos[self._site].copy()
        error = target_value - current
        desired = float(WHOLE_BODY_CONTROLLER["cartesianGain"]) * error
        desired_norm = float(np.linalg.norm(desired))
        speed_limit = float(WHOLE_BODY_CONTROLLER["maximumCartesianSpeed"])
        if desired_norm > speed_limit:
            desired *= speed_limit / desired_norm
        jacp = np.zeros((3, self._model.nv))
        jacr = np.zeros((3, self._model.nv))
        self._mujoco.mj_jacSite(
            self._model,
            self._data,
            jacp,
            jacr,
            self._site,
        )
        selected_dofs = np.concatenate((self._base_dofs, self._joint_dofs))
        jacobian = jacp[:, selected_dofs]
        regularization = np.asarray(WHOLE_BODY_CONTROLLER["regularization"], dtype=float)
        hessian = jacobian.T @ jacobian + np.diag(regularization**2)
        gradient = -(jacobian.T @ desired)
        lower = np.asarray(WHOLE_BODY_CONTROLLER["velocityLowerBounds"], dtype=float)
        upper = np.asarray(WHOLE_BODY_CONTROLLER["velocityUpperBounds"], dtype=float)
        if not allow_base:
            lower = lower.copy()
            upper = upper.copy()
            lower[:3] = 0.0
            upper[:3] = 0.0
        decision, objective, projected_gradient = solve_box_qp(
            hessian,
            gradient,
            lower,
            upper,
            iterations=int(WHOLE_BODY_CONTROLLER["qpIterations"]),
        )
        held_targets = qpos_value[self._held_qpos].copy()
        horizon = float(WHOLE_BODY_CONTROLLER["targetHorizonSeconds"])
        maximum_step = float(WHOLE_BODY_CONTROLLER["maximumJointTargetStep"])
        margin = float(WHOLE_BODY_CONTROLLER["jointLimitMarginRadians"])
        joint_delta = np.clip(decision[3:] * horizon, -maximum_step, maximum_step)
        joint_targets = np.clip(
            qpos_value[self._joint_qpos] + joint_delta,
            self._joint_ranges[:, 0] + margin,
            self._joint_ranges[:, 1] - margin,
        )
        for name, value in zip(self._joint_names, joint_targets, strict=True):
            held_targets[self._held_index[name]] = value
        feedforward = (
            float(WHOLE_BODY_CONTROLLER["feedforwardScale"])
            * self._data.qfrc_bias[self._held_dofs]
        )
        reserve = float(WHOLE_BODY_CONTROLLER["feedforwardControlReserve"])
        limits = np.max(np.abs(self._held_ctrlrange), axis=1) * (1.0 - reserve)
        feedforward = np.clip(feedforward, -limits, limits)
        predicted_velocity = jacobian @ decision
        return {
            "baseCommand": [float(value) for value in decision[:3]],
            "heldTargets": [float(value) for value in held_targets],
            "feedforwardTorque": [float(value) for value in feedforward],
            "tcpPosition": [float(value) for value in current],
            "targetErrorMeters": float(np.linalg.norm(error)),
            "predictedVelocityResidual": float(
                np.linalg.norm(predicted_velocity - desired)
            ),
            "qpObjective": objective,
            "qpProjectedGradient": projected_gradient,
            "decision": [float(value) for value in decision],
        }

    def site_state(self, qpos, qvel, target) -> dict[str, Any]:
        np = self._np
        self._data.qpos[:] = np.asarray(qpos, dtype=float)
        self._data.qvel[:] = np.asarray(qvel, dtype=float)
        self._mujoco.mj_forward(self._model, self._data)
        jacp = np.zeros((3, self._model.nv))
        jacr = np.zeros((3, self._model.nv))
        self._mujoco.mj_jacSite(
            self._model,
            self._data,
            jacp,
            jacr,
            self._site,
        )
        velocity = jacp @ np.asarray(qvel, dtype=float)
        position = self._data.site_xpos[self._site].copy()
        return {
            "tcpPosition": [float(value) for value in position],
            "tcpSpeed": float(np.linalg.norm(velocity)),
            "targetErrorMeters": float(
                np.linalg.norm(np.asarray(target, dtype=float) - position)
            ),
            "heldPositions": [
                float(value) for value in self._data.qpos[self._held_qpos]
            ],
            "heldVelocities": [
                float(value) for value in self._data.qvel[self._held_dofs]
            ],
        }


def validate_whole_body_profile(
    base_profile: dict[str, Any],
    supervisor_profile: dict[str, Any],
    profile: dict[str, Any],
) -> None:
    validate_profile(base_profile)
    make_supervisor_evaluation_profile(base_profile, supervisor_profile)
    if (
        profile.get("profileVersion") != "0.1.0"
        or profile.get("status") != "research"
        or profile.get("stage") != "whole_body_task_space_control_spike"
    ):
        raise TrainingError(
            "WHOLE_BODY_PROFILE_UNSUPPORTED",
            "A5-C must use whole_body_task_space_control_spike v0.1.",
        )
    if profile.get("baseTrainingProfileDigest") != digest_json(base_profile):
        raise TrainingError(
            "WHOLE_BODY_BASE_PROFILE_MISMATCH",
            "A5-C is not bound to the base training Profile.",
        )
    if profile.get("supervisorProfileDigest") != digest_json(supervisor_profile):
        raise TrainingError(
            "WHOLE_BODY_SUPERVISOR_MISMATCH",
            "A5-C is not bound to the passing A4 supervisor Profile.",
        )
    if profile.get("failedA5RReportDigest") != A5R_FAILED_REPORT_DIGEST:
        raise TrainingError(
            "WHOLE_BODY_A5R_LINEAGE_MISMATCH",
            "A5-C must remain bound to the archived A5-R failure evidence.",
        )
    for key in ("motionPolicy", "capturePolicy", "standPolicy"):
        if profile.get(key) != supervisor_profile[key]:
            raise TrainingError(
                "WHOLE_BODY_POLICY_LINEAGE_MISMATCH",
                "A5-C must reuse the frozen A4 policy identities.",
            )
    if profile.get("scene") != TASK_SCENE:
        raise TrainingError(
            "WHOLE_BODY_SCENE_INVALID",
            "A5-C must reuse the repaired A5-R primitive scene.",
        )
    if profile.get("controller") != WHOLE_BODY_CONTROLLER:
        raise TrainingError(
            "WHOLE_BODY_CONTROLLER_INVALID",
            "A5-C controller contract changed.",
        )
    if profile.get("qualityGates") != WHOLE_BODY_GATES:
        raise TrainingError(
            "WHOLE_BODY_GATES_INVALID",
            "A5-C Spike gates cannot be relaxed.",
        )
    runtime = profile.get("runtime", {})
    if (
        runtime.get("ccdIterations") != 50
        or runtime.get("evaluationEnvironments") != 1
        or runtime.get("mjxCapacity") != TASK_CAPACITY
    ):
        raise TrainingError(
            "WHOLE_BODY_RUNTIME_INVALID",
            "A5-C requires the repaired one-environment A5-R runtime.",
        )
    if (
        runtime.get("containerDigest")
        != runtime.get("containerImage", "").rsplit("@", maxsplit=1)[-1]
    ):
        raise TrainingError(
            "WHOLE_BODY_CONTAINER_BINDING_MISMATCH",
            "A5-C containerImage and containerDigest differ.",
        )
    if profile.get("artifactPolicy") != {
        "controller": "research_only",
        "distribution": "internal_only",
        "fullTaskClaim": "forbidden",
        "l3Claim": "forbidden",
    }:
        raise TrainingError(
            "WHOLE_BODY_ARTIFACT_POLICY_INVALID",
            "A5-C Spike cannot claim the full task or L3.",
        )


def make_whole_body_evaluation_profile(
    base_profile: dict[str, Any],
    supervisor_profile: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    validate_whole_body_profile(base_profile, supervisor_profile, profile)
    effective = make_supervisor_evaluation_profile(base_profile, supervisor_profile)
    effective["runtime"]["containerDigest"] = profile["runtime"]["containerDigest"]
    effective["runtime"]["ccdIterations"] = profile["runtime"]["ccdIterations"]
    effective["runtime"]["mjxCapacity"] = copy.deepcopy(profile["runtime"]["mjxCapacity"])
    effective["training"]["numEnvs"] = 1
    effective["training"]["seed"] = profile["seed"]
    return effective


def evaluate_whole_body_control_spike(
    profile: dict[str, Any],
    env,
    motion_policy,
    capture_policy,
    stand_policy,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    import jax
    import jax.numpy as jp
    import numpy as np

    motion_inference = jax.jit(motion_policy)
    capture_inference = jax.jit(capture_policy)
    stand_inference = jax.jit(stand_policy)
    reset = jax.jit(env.reset)
    step = jax.jit(env.step)
    controller = WholeBodyTaskSpaceController(env.mj_model, profile["control"])
    rng = jax.random.PRNGKey(profile["training"]["seed"])
    state = reset(rng)
    supervisor = SupervisorState()
    traces: list[dict[str, Any]] = []
    nonfinite = 0
    done_seen = False
    failure = None
    hold_steps = 0
    initial_task_base = None
    minimum_height = float("inf")
    minimum_upright = float("inf")
    maximum_projected_gradient = 0.0
    terminal_reasons: set[str] = set()

    def with_inputs(state_value, command, held_targets, feedforward):
        info = dict(state_value.info)
        info["command"] = command
        info["held_targets"] = jp.asarray(held_targets)
        info["held_feedforward"] = jp.asarray(feedforward)
        info["gripper_commands"] = jp.asarray([0.0])
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

    total_steps = (
        SUPERVISOR["moveSteps"]
        + SUPERVISOR["settleSteps"]
        + WHOLE_BODY_GATES["settleSteps"]
        + WHOLE_BODY_GATES["trackingSteps"]
    )
    final_site = None
    for index in range(total_steps):
        moving = index < SUPERVISOR["moveSteps"]
        supervisor_settle_end = SUPERVISOR["moveSteps"] + SUPERVISOR["settleSteps"]
        transitioning = not moving and index < supervisor_settle_end
        if moving or transitioning:
            phase = "locomotion"
            if transitioning:
                phase = "locomotion_settle"
            command = (
                jp.asarray([0.5, 0.0, 0.0])
                if moving
                else jp.asarray([0.0, 0.0, 0.0])
            )
            held_targets = [0.0] * 9
            feedforward = [0.0] * 9
            control = None
        else:
            if supervisor.phase != "stand":
                failure = "locomotion_supervisor_not_ready"
                break
            if initial_task_base is None:
                initial_task_base = np.asarray(state.data.qpos[:3], dtype=float).copy()
            settle_end = supervisor_settle_end + WHOLE_BODY_GATES["settleSteps"]
            phase = "whole_body_settle" if index < settle_end else "track_handle"
            metrics = _task_metrics(env, state)
            target_phase = "stand_ready" if phase == "whole_body_settle" else "reach_handle"
            target = _target_for_phase(target_phase, metrics)
            control = controller.solve(
                np.asarray(state.data.qpos),
                np.asarray(state.data.qvel),
                target,
            )
            command = jp.asarray(control["baseCommand"])
            held_targets = control["heldTargets"]
            feedforward = control["feedforwardTorque"]
            maximum_projected_gradient = max(
                maximum_projected_gradient,
                control["qpProjectedGradient"],
            )
        state = with_inputs(state, command, held_targets, feedforward)
        rng, motion_rng, capture_rng, stand_rng = jax.random.split(rng, 4)
        motion_action, _ = motion_inference(state.obs, motion_rng)
        capture_action, _ = capture_inference(state.obs, capture_rng)
        stand_action, _ = stand_inference(state.obs, stand_rng)
        if moving or transitioning:
            action, active_policy, _ = supervisor.select(
                moving,
                motion_action,
                capture_action,
                stand_action,
            )
        else:
            use_motion = bool(np.linalg.norm(np.asarray(command)) > 0.01)
            action = motion_action if use_motion else stand_action
            active_policy = "motion" if use_motion else "stand"
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
        termination = {
            name: bool(np.asarray(value))
            for name, value in state.info["termination"].items()
        }
        terminal_reasons.update(
            name for name, active in termination.items() if active
        )
        minimum_height = min(minimum_height, height)
        minimum_upright = min(minimum_upright, upright)
        nonfinite += 0 if finite else 1
        if moving or transitioning:
            supervisor.observe(
                active_policy,
                float(np.linalg.norm(linear)),
                float(np.linalg.norm(angular)),
            )
            if supervisor.handoff_failed:
                failure = "locomotion_handoff_timeout"
            site = None
        else:
            metrics = _task_metrics(env, state)
            target_phase = "stand_ready" if phase == "whole_body_settle" else "reach_handle"
            target = _target_for_phase(target_phase, metrics)
            site = controller.site_state(qpos, qvel, target)
            final_site = site
            within = (
                phase == "track_handle"
                and site["targetErrorMeters"]
                <= WHOLE_BODY_GATES["positionToleranceMeters"]
                and site["tcpSpeed"] <= WHOLE_BODY_GATES["maximumTcpSpeed"]
            )
            hold_steps = hold_steps + 1 if within else 0
        traces.append(
            {
                "step": index,
                "timeSeconds": (index + 1) * env.dt,
                "phase": phase,
                "activePolicy": active_policy,
                "command": [float(value) for value in np.asarray(command)],
                "basePosition": [float(value) for value in qpos[:3]],
                "minimumBaseHeight": minimum_height,
                "minimumUprightCosine": minimum_upright,
                "finite": finite,
                "done": done,
                "termination": termination,
                "control": control,
                "site": site,
            }
        )
        if done:
            done_seen = True
            reason = ",".join(sorted(terminal_reasons)) or "unclassified"
            failure = failure or f"robot_termination:{reason}"
        if failure:
            break
    if initial_task_base is None:
        initial_task_base = np.asarray(state.data.qpos[:3], dtype=float)
    final_base = np.asarray(state.data.qpos[:3], dtype=float)
    base_delta = final_base - initial_task_base
    passed = (
        failure is None
        and final_site is not None
        and hold_steps >= WHOLE_BODY_GATES["holdSteps"]
        and final_site["targetErrorMeters"]
        <= WHOLE_BODY_GATES["positionToleranceMeters"]
        and final_site["tcpSpeed"] <= WHOLE_BODY_GATES["maximumTcpSpeed"]
        and float(np.linalg.norm(base_delta[:2]))
        <= WHOLE_BODY_GATES["maximumBaseTranslation"]
        and abs(float(base_delta[1]))
        <= WHOLE_BODY_GATES["maximumBaseLateralDrift"]
        and minimum_height >= WHOLE_BODY_GATES["minimumBaseHeight"]
        and minimum_upright >= WHOLE_BODY_GATES["minimumUprightCosine"]
        and maximum_projected_gradient
        <= WHOLE_BODY_GATES["maximumProjectedGradient"]
        and nonfinite <= WHOLE_BODY_GATES["maximumNonFiniteSamples"]
        and not done_seen
    )
    return (
        {
            "id": "test://worldspec/h1-kitchen/whole-body-control-spike/1",
            "result": "pass" if passed else "fail",
            "metrics": {
                "failedReason": failure,
                "holdSteps": hold_steps,
                "finalTargetErrorMeters": (
                    final_site["targetErrorMeters"] if final_site else None
                ),
                "finalTcpSpeed": final_site["tcpSpeed"] if final_site else None,
                "baseTranslation": float(np.linalg.norm(base_delta[:2])),
                "baseLateralDrift": abs(float(base_delta[1])),
                "minimumBaseHeight": minimum_height,
                "minimumUprightCosine": minimum_upright,
                "maximumProjectedGradient": maximum_projected_gradient,
                "nonFiniteSamples": nonfinite,
                "doneSeen": done_seen,
                "terminalReasons": sorted(terminal_reasons),
            },
        },
        traces,
    )


def run_whole_body_control_spike(
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
    from brax.training.agents.ppo import networks as ppo_networks

    from .environment import make_environment

    effective = make_whole_body_evaluation_profile(
        base_profile,
        supervisor_profile,
        profile,
    )
    static = static_preflight(base_profile, bundle_dir)
    task_model, derivation = prepare_kitchen_task_model(base_profile, bundle_dir, model_dir)
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
    with tempfile.TemporaryDirectory(prefix="worldspec-h1-whole-body-") as temporary:
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
        test, traces = evaluate_whole_body_control_spike(
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
        "controller": copy.deepcopy(WHOLE_BODY_CONTROLLER),
        "scene": copy.deepcopy(TASK_SCENE),
        "policies": {
            role: {
                "checkpointDigest": value["archiveDigest"],
                "selectedStep": value["selectedStep"],
            }
            for role, value in loaded.items()
        },
        "distribution": "internal_only",
        "fullTaskClaim": "forbidden",
        "l3Claim": "forbidden",
    }
    controller_path = output_dir / "whole-body-controller.json"
    controller_path.write_bytes(canonical_bytes(controller_artifact))
    passed = test["result"] == "pass"
    return {
        "baseTrainingProfileDigest": digest_json(base_profile),
        "supervisorProfileDigest": digest_json(supervisor_profile),
        "controlProfileDigest": digest_json(profile),
        "policies": loaded,
        "staticPreflight": static,
        "runtimePreflight": runtime,
        "target": {
            "sourceBundleDigest": derivation["parentDerivation"]["sourceBundleDigest"],
            "derivedModelDigest": derivation["derivedModelDigest"],
            "observationSize": observation_size,
            "actionSize": action_size,
        },
        "scene": copy.deepcopy(TASK_SCENE),
        "controller": copy.deepcopy(WHOLE_BODY_CONTROLLER),
        "qualityAssessment": {
            "status": "passed" if passed else "failed",
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
            "status": "control_spike_only",
            "fullTaskClaim": "forbidden",
            "l3Claim": "forbidden",
            "reasons": [
                "only_handle_tracking_is_evaluated",
                "whole_body_control_is_not_yet_validated_for_physical_grasp",
                "right_gripper_mount_evidence_is_estimated",
            ],
        },
    }
