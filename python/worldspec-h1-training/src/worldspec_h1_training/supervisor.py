"""Phase-aware H1 motion-to-capture-to-stand supervisor probe."""

from __future__ import annotations

import copy
import functools
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contract import canonical_bytes, digest_bytes, digest_json, validate_profile
from .dual_policy import MOTION_POLICY_SOURCE, STAND_POLICY_SOURCE
from .errors import TrainingError
from .midterm import _load_deterministic_teacher_policy
from .model import prepare_training_model
from .preflight import runtime_preflight, static_preflight
from .trainer import _flat_observation_size
from .warm_start import materialize_warm_start, validate_network_compatibility

CAPTURE_POLICY_SOURCE = {
    "sourceStage": "loaded-track-settle-capture-v1-passed",
    "sourceReportDigest": (
        "sha256:8261f863d71cb66de46facb37b3c5ed121811e80fdabac057629ed366a52666f"
    ),
    "checkpointDigest": ("sha256:7f8c45e7c0bf1d485706ca694c44e74bfd351ab4f753bfacff947e9f7e75cfbe"),
    "checkpointSizeBytes": 6_280_278,
    "distribution": "internal_only",
    "selectedRole": "motion_state_capture",
}
TASK_LOAD_MOTION_POLICY_SOURCE = {
    "sourceStage": "loaded-track-settle-task-load-formal-v1-failed",
    "sourceReportDigest": (
        "sha256:31e4991a33721928df2b2887f00dccd339dfe261dfbf1aaec4597579c6c784d9"
    ),
    "checkpointDigest": ("sha256:61ebfa89d0fa5e7d7fc6488c524cf21c742c6a25efb5854a2bd689a61c895016"),
    "checkpointSizeBytes": 1_260_210,
    "distribution": "internal_only",
    "selectedRole": "motion",
}
TASK_LOAD_EVALUATION_ENVIRONMENT = {
    "commandDistribution": {
        "linearVelocityX": [0.0, 0.8],
        "linearVelocityY": [-0.15, 0.15],
        "angularVelocityYaw": [-0.35, 0.35],
        "zeroCommandProbability": 0.2,
    },
    "taskLoadCurriculum": {
        "mode": "static_right_arm_pose",
        "sourceJob": "worldspec-h1-midterm-5nn2q",
        "sourceTraceDigest": (
            "sha256:175427d1d3d74da7fe5c422f3290f07ae6dfa6c21179626dd4d4558915012bd9"
        ),
        "heldTargetScale": [1.0, 1.0],
        "initialBaseVelocityX": [0.0, 0.0],
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
    },
    "termination": {
        "minimumBaseHeight": 0.5,
        "minimumUprightCosine": 0.25,
        "jointLimitToleranceRadians": 0.02,
    },
    "reward": {
        "survival": 3.0,
        "trackingLinear": 6.0,
        "trackingYaw": 2.0,
        "upright": 3.0,
        "baseHeight": 2.0,
        "pose": 0.5,
        "verticalVelocityCost": 1.0,
        "angularVelocityXYCost": 0.5,
        "torqueCost": 0.000002,
        "actionRateCost": 0.03,
        "settleLinear": 16.0,
        "settleYaw": 6.0,
        "settleActionRateScale": 0.15,
        "standDistillation": 4.0,
        "settleDistillation": 4.0,
        "standTeacherActionCost": 1.0,
        "settleTeacherActionCost": 1.0,
        "terminationPenalty": 100,
    },
    "targets": {"baseHeight": 0.98},
    "sigmas": {
        "tracking": 0.2,
        "upright": 0.05,
        "baseHeight": 0.02,
        "pose": 0.2,
        "settleTracking": 0.05,
        "standDistillation": 0.05,
        "settleDistillation": 0.05,
    },
    "commandResampleSteps": 200,
}
SUPERVISOR = {
    "mode": "phase_aware_velocity_stability_gate",
    "motionCommandThreshold": 0.05,
    "moveSteps": 150,
    "settleSteps": 50,
    "captureGate": {
        "minimumSteps": 20,
        "maximumSteps": 40,
        "maximumLinearSpeed": 0.12,
        "maximumAngularSpeed": 0.20,
        "requiredConsecutiveStableSteps": 5,
    },
    "handoff": {
        "mode": "linear_action_blend",
        "blendSteps": 5,
        "durationSeconds": 0.1,
        "observationCommand": [0.0, 0.0, 0.0],
    },
    "minimumStandDwellSteps": 10,
    "standRegressionPolicy": "standPolicy",
}
QUALITY_GATES = {
    "nominalDurationSeconds": 4.0,
    "moveDurationSeconds": 3.0,
    "settleWindowSeconds": 1.0,
    "settleMeasurementWindowSeconds": 0.2,
    "requiredConsecutivePasses": 5,
    "minimumForwardDisplacement": 1.0,
    "maximumForwardDisplacement": 2.2,
    "maximumLateralDrift": 0.2,
    "maximumTrackingRmse": 0.25,
    "minimumBaseHeight": 0.8,
    "minimumUprightCosine": 0.8,
    "maximumSettleLinearSpeed": 0.2,
    "maximumSettleAngularSpeed": 0.4,
    "maximumStandPlanarDrift": 0.2,
    "maximumNonFiniteSamples": 0,
    "minimumStandDwellSteps": 10,
}


@dataclass
class SupervisorState:
    """Small deterministic state machine used by the reference supervisor."""

    phase: str = "motion"
    capture_steps: int = 0
    stable_steps: int = 0
    blend_steps: int = 0
    stand_steps: int = 0
    handoff_failed: bool = False

    def select(self, moving: bool, motion_action, capture_action, stand_action):
        """Return the current action, phase label, and blend alpha."""

        if moving:
            if self.phase != "motion":
                raise TrainingError(
                    "SUPERVISOR_COMMAND_REENTRY",
                    "A4 does not allow motion-command reentry after capture starts.",
                )
            return motion_action, "motion", 0.0
        if self.phase == "motion":
            self.phase = "capture"
        if self.phase == "capture":
            return capture_action, "capture", 0.0
        if self.phase == "blend":
            blend_total = SUPERVISOR["handoff"]["blendSteps"]
            alpha = (self.blend_steps + 1) / blend_total
            return (
                (1.0 - alpha) * capture_action + alpha * stand_action,
                "blend",
                alpha,
            )
        if self.phase == "stand":
            return stand_action, "stand", 1.0
        raise TrainingError(
            "SUPERVISOR_PHASE_INVALID",
            f"Unsupported A4 supervisor phase: {self.phase}",
        )

    def observe(self, active_phase: str, linear_speed: float, angular_speed: float) -> None:
        """Advance the state machine after observing the executed physics step."""

        capture = SUPERVISOR["captureGate"]
        if active_phase == "capture":
            self.capture_steps += 1
            stable = (
                linear_speed <= capture["maximumLinearSpeed"]
                and angular_speed <= capture["maximumAngularSpeed"]
            )
            self.stable_steps = self.stable_steps + 1 if stable else 0
            if (
                self.capture_steps >= capture["minimumSteps"]
                and self.stable_steps >= capture["requiredConsecutiveStableSteps"]
            ):
                self.phase = "blend"
                self.blend_steps = 0
            elif self.capture_steps >= capture["maximumSteps"]:
                self.handoff_failed = True
        elif active_phase == "blend":
            self.blend_steps += 1
            if self.blend_steps >= SUPERVISOR["handoff"]["blendSteps"]:
                self.phase = "stand"
        elif active_phase == "stand":
            self.stand_steps += 1


def validate_supervisor_profile(
    base_profile: dict[str, Any],
    profile: dict[str, Any],
) -> None:
    """Validate an immutable three-policy supervisor contract."""

    validate_profile(base_profile)
    stage = profile.get("stage")
    if (
        profile.get("profileVersion") != "0.1.0"
        or profile.get("status") != "research"
        or stage
        not in {
            "phase_aware_supervisor_probe",
            "task_load_phase_aware_supervisor_probe",
        }
    ):
        raise TrainingError(
            "SUPERVISOR_PROFILE_UNSUPPORTED",
            "Supervisor probes must use a supported v0.1 stage.",
        )
    if profile.get("baseTrainingProfileDigest") != digest_json(base_profile):
        raise TrainingError(
            "SUPERVISOR_BASE_PROFILE_MISMATCH",
            "A4 is not bound to the exact base training Profile.",
        )
    expected_motion = (
        TASK_LOAD_MOTION_POLICY_SOURCE
        if stage == "task_load_phase_aware_supervisor_probe"
        else MOTION_POLICY_SOURCE
    )
    for key, expected, label in (
        ("motionPolicy", expected_motion, "motion"),
        ("capturePolicy", CAPTURE_POLICY_SOURCE, "capture"),
        ("standPolicy", STAND_POLICY_SOURCE, "stand"),
    ):
        if profile.get(key) != expected:
            raise TrainingError(
                f"SUPERVISOR_{label.upper()}_SOURCE_MISMATCH",
                f"A4 must bind the frozen {label} policy lineage.",
            )
    if stage == "task_load_phase_aware_supervisor_probe":
        if profile.get("evaluationEnvironment") != TASK_LOAD_EVALUATION_ENVIRONMENT:
            raise TrainingError(
                "TASK_LOAD_SUPERVISOR_ENVIRONMENT_INVALID",
                "A6-S must use the frozen static right-arm task-load environment.",
            )
    elif "evaluationEnvironment" in profile:
        raise TrainingError(
            "SUPERVISOR_ENVIRONMENT_FORBIDDEN",
            "The historical A4 Profile cannot acquire a task-load environment.",
        )
    if profile.get("supervisor") != SUPERVISOR:
        raise TrainingError(
            "SUPERVISOR_CONTRACT_INVALID",
            "A4 must use the frozen capture stability gate and five-step handoff.",
        )
    if profile.get("qualityGates") != QUALITY_GATES:
        raise TrainingError(
            "SUPERVISOR_QUALITY_GATES_INVALID",
            "A4 cannot relax the walk, terminal hold, stand dwell, or regression gates.",
        )
    runtime = profile.get("runtime", {})
    if runtime.get("ccdIterations") != 50 or runtime.get("evaluationEnvironments") != 1:
        raise TrainingError(
            "SUPERVISOR_RUNTIME_INVALID",
            "A4 requires CCD=50 and one deterministic environment.",
        )
    if (
        runtime.get("containerDigest")
        != runtime.get("containerImage", "").rsplit("@", maxsplit=1)[-1]
    ):
        raise TrainingError(
            "SUPERVISOR_CONTAINER_BINDING_MISMATCH",
            "A4 containerImage and containerDigest must identify one OCI image.",
        )
    if runtime.get("packageLockDigest") != base_profile["runtime"]["packageLockDigest"]:
        raise TrainingError(
            "SUPERVISOR_PACKAGE_LOCK_MISMATCH",
            "A4 must use the base Profile package lock.",
        )
    if profile.get("artifactPolicy") != {
        "controller": "research_only",
        "distribution": "internal_only",
    }:
        raise TrainingError(
            "SUPERVISOR_ARTIFACT_POLICY_INVALID",
            "A4 supervisor evidence must remain internal research material.",
        )


def make_supervisor_evaluation_profile(
    base_profile: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    """Build the evaluation-only effective Profile without PPO updates."""

    validate_supervisor_profile(base_profile, profile)
    effective = copy.deepcopy(base_profile)
    effective["runtime"]["containerDigest"] = profile["runtime"]["containerDigest"]
    effective["runtime"]["packageLockDigest"] = profile["runtime"]["packageLockDigest"]
    effective["runtime"]["ccdIterations"] = profile["runtime"]["ccdIterations"]
    effective["training"]["numEnvs"] = profile["runtime"]["evaluationEnvironments"]
    if profile["stage"] == "task_load_phase_aware_supervisor_probe":
        effective["training"]["commandDistribution"] = copy.deepcopy(
            profile["evaluationEnvironment"]["commandDistribution"]
        )
        effective["trainingEnvironment"] = copy.deepcopy(profile["evaluationEnvironment"])
    effective["validation"] = copy.deepcopy(profile["qualityGates"])
    return effective


def evaluate_supervisor_suite(
    profile: dict[str, Any],
    env,
    motion_policy,
    capture_policy,
    stand_policy,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run five phase-aware walk/settle and five stand regression episodes."""

    import jax
    import jax.numpy as jp
    import numpy as np

    motion_inference = jax.jit(motion_policy)
    capture_inference = jax.jit(capture_policy)
    stand_inference = jax.jit(stand_policy)
    reset = jax.jit(env.reset)
    step = jax.jit(env.step)
    validation = profile["validation"]
    dt = profile["training"]["simulationTimestepSeconds"] * profile["control"]["controlDecimation"]
    duration_steps = round(validation["nominalDurationSeconds"] / dt)
    move_steps = SUPERVISOR["moveSteps"]
    settle_steps = SUPERVISOR["settleSteps"]
    measure_steps = round(validation["settleMeasurementWindowSeconds"] / dt)
    required = validation["requiredConsecutivePasses"]
    if duration_steps != move_steps + settle_steps:
        raise TrainingError(
            "SUPERVISOR_TIMING_MISMATCH",
            "A4 duration must resolve to exactly 150 move and 50 settle steps.",
        )
    tests: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []

    def with_command(state, command):
        info = dict(state.info)
        info["command"] = command
        false_value = command[0] < command[0]
        info["transition_active"] = false_value
        info["stand_replay_active"] = false_value
        info["capture_active"] = false_value
        observation = {
            "state": env._observation(
                state.data,
                info["last_action"],
                command,
            )
        }
        return state.replace(info=info, obs=observation)

    def run(run_index: int, mode: str) -> dict[str, Any]:
        rng = jax.random.PRNGKey(profile["training"]["seed"] + run_index)
        state = reset(rng)
        supervisor = SupervisorState()
        start_xy = np.asarray(state.data.qpos[:2], dtype=float)
        minimum_height = float("inf")
        minimum_upright = float("inf")
        maximum_planar_drift = 0.0
        maximum_terminal_linear_speed = 0.0
        maximum_terminal_angular_speed = 0.0
        maximum_action_jump = 0.0
        squared_tracking_error = 0.0
        tracking_samples = 0
        nonfinite = 0
        done_seen = False
        completed_steps = 0
        terminal_reasons: set[str] = set()
        previous_action = None
        capture_start_linear_speed = None
        capture_start_angular_speed = None
        handoff_activation_step = None
        stand_activation_step = None
        final_linear_speed = None
        final_angular_speed = None
        for index in range(duration_steps):
            moving = mode == "walk_settle" and index < move_steps
            command = jp.asarray([0.5, 0.0, 0.0]) if moving else jp.zeros(3)
            state = with_command(state, command)
            rng, motion_rng, capture_rng, stand_rng = jax.random.split(rng, 4)
            motion_action, _ = motion_inference(state.obs, motion_rng)
            capture_action, _ = capture_inference(state.obs, capture_rng)
            stand_action, _ = stand_inference(state.obs, stand_rng)
            if mode == "stand_regression":
                action = stand_action
                active_phase = "stand"
                blend_alpha = 1.0
            else:
                action, active_phase, blend_alpha = supervisor.select(
                    moving,
                    motion_action,
                    capture_action,
                    stand_action,
                )
                if active_phase == "blend" and handoff_activation_step is None:
                    handoff_activation_step = index
                if active_phase == "stand" and stand_activation_step is None:
                    stand_activation_step = index
            action_array = np.asarray(action, dtype=float)
            action_jump = (
                0.0
                if previous_action is None
                else float(np.linalg.norm(action_array - previous_action))
            )
            maximum_action_jump = max(maximum_action_jump, action_jump)
            previous_action = action_array
            state = step(state, action)
            jax.block_until_ready(state.reward)
            qpos = np.asarray(state.data.qpos)
            qvel = np.asarray(state.data.qvel)
            local_velocity = np.asarray(env.local_velocity(state.data), dtype=float)
            angular_velocity = np.asarray(env.angular_velocity(state.data), dtype=float)
            linear_speed = float(np.linalg.norm(local_velocity))
            angular_speed = float(np.linalg.norm(angular_velocity))
            height = float(np.asarray(state.data.xpos[env.pelvis_body_id, 2]))
            upright = float(np.asarray(env.upvector(state.data)[2]))
            done = bool(np.asarray(state.done))
            finite = bool(
                np.isfinite(qpos).all()
                and np.isfinite(qvel).all()
                and np.isfinite(action_array).all()
            )
            if mode == "walk_settle":
                if active_phase == "capture" and capture_start_linear_speed is None:
                    capture_start_linear_speed = linear_speed
                    capture_start_angular_speed = angular_speed
                supervisor.observe(active_phase, linear_speed, angular_speed)
            if index >= duration_steps - measure_steps:
                maximum_terminal_linear_speed = max(
                    maximum_terminal_linear_speed,
                    linear_speed,
                )
                maximum_terminal_angular_speed = max(
                    maximum_terminal_angular_speed,
                    angular_speed,
                )
            if moving:
                squared_tracking_error += float((local_velocity[0] - 0.5) ** 2)
                tracking_samples += 1
            position = np.asarray(qpos[:2], dtype=float)
            minimum_height = min(minimum_height, height)
            minimum_upright = min(minimum_upright, upright)
            maximum_planar_drift = max(
                maximum_planar_drift,
                float(np.linalg.norm(position - start_xy)),
            )
            nonfinite += 0 if finite else 1
            completed_steps += 1
            final_linear_speed = linear_speed
            final_angular_speed = angular_speed
            traces.append(
                {
                    "suite": mode,
                    "run": run_index,
                    "step": index,
                    "timeSeconds": (index + 1) * dt,
                    "command": [float(value) for value in np.asarray(command)],
                    "activePolicy": active_phase,
                    "blendAlpha": blend_alpha,
                    "captureSteps": supervisor.capture_steps,
                    "stableSteps": supervisor.stable_steps,
                    "standSteps": supervisor.stand_steps,
                    "handoffFailed": supervisor.handoff_failed,
                    "actionJumpNorm": action_jump,
                    "basePosition": [float(qpos[0]), float(qpos[1]), height],
                    "uprightCosine": upright,
                    "localVelocity": [float(value) for value in local_velocity],
                    "angularVelocity": [float(value) for value in angular_velocity],
                    "done": done,
                    "finite": finite,
                }
            )
            if mode == "walk_settle" and supervisor.handoff_failed:
                terminal_reasons.add("capture_handoff_timeout")
                break
            if done:
                done_seen = True
                terminal_reasons.update(
                    name
                    for name, value in state.info["termination"].items()
                    if bool(np.asarray(value))
                )
                break
        final_xy = np.asarray(state.data.qpos[:2], dtype=float)
        displacement = float(final_xy[0] - start_xy[0])
        lateral = abs(float(final_xy[1] - start_xy[1]))
        tracking_rmse = (
            float(np.sqrt(squared_tracking_error / tracking_samples)) if tracking_samples else 0.0
        )
        common = (
            not done_seen
            and completed_steps == duration_steps
            and nonfinite <= validation["maximumNonFiniteSamples"]
            and minimum_height >= validation["minimumBaseHeight"]
            and minimum_upright >= validation["minimumUprightCosine"]
        )
        if mode == "walk_settle":
            passed = (
                common
                and displacement >= validation["minimumForwardDisplacement"]
                and displacement <= validation["maximumForwardDisplacement"]
                and lateral <= validation["maximumLateralDrift"]
                and tracking_rmse <= validation["maximumTrackingRmse"]
                and maximum_terminal_linear_speed <= validation["maximumSettleLinearSpeed"]
                and maximum_terminal_angular_speed <= validation["maximumSettleAngularSpeed"]
                and not supervisor.handoff_failed
                and stand_activation_step is not None
                and supervisor.stand_steps >= validation["minimumStandDwellSteps"]
            )
        else:
            passed = (
                common
                and maximum_planar_drift <= validation["maximumStandPlanarDrift"]
                and maximum_terminal_linear_speed <= validation["maximumSettleLinearSpeed"]
                and maximum_terminal_angular_speed <= validation["maximumSettleAngularSpeed"]
            )
        return {
            "id": f"test://worldspec/h1-supervisor/{mode}/{run_index + 1}",
            "suite": mode,
            "result": "pass" if passed else "fail",
            "metrics": {
                "completedSteps": completed_steps,
                "requiredSteps": duration_steps,
                "forwardDisplacement": displacement,
                "lateralDrift": lateral,
                "maximumPlanarDrift": maximum_planar_drift,
                "trackingRmse": tracking_rmse,
                "minimumBaseHeight": minimum_height,
                "minimumUprightCosine": minimum_upright,
                "captureStartLinearSpeed": capture_start_linear_speed,
                "captureStartAngularSpeed": capture_start_angular_speed,
                "captureSteps": supervisor.capture_steps if mode == "walk_settle" else 0,
                "stableStepsAtHandoff": (
                    supervisor.stable_steps if handoff_activation_step is not None else 0
                ),
                "handoffActivationStep": handoff_activation_step,
                "standActivationStep": stand_activation_step,
                "standDwellSteps": (
                    supervisor.stand_steps if mode == "walk_settle" else duration_steps
                ),
                "handoffFailed": (supervisor.handoff_failed if mode == "walk_settle" else False),
                "maximumTerminalHoldLinearSpeed": maximum_terminal_linear_speed,
                "maximumTerminalHoldAngularSpeed": maximum_terminal_angular_speed,
                "finalLinearSpeed": final_linear_speed,
                "finalAngularSpeed": final_angular_speed,
                "maximumActionJumpNorm": maximum_action_jump,
                "measurementWindowSeconds": validation["settleMeasurementWindowSeconds"],
                "nonFiniteSamples": nonfinite,
                "doneSeen": done_seen,
                "terminalReasons": sorted(terminal_reasons),
            },
        }

    for run_index in range(required):
        tests.append(run(run_index, "walk_settle"))
    for run_index in range(required):
        tests.append(run(run_index, "stand_regression"))
    return tests, traces


def run_phase_aware_supervisor_probe(
    base_profile: dict[str, Any],
    profile: dict[str, Any],
    bundle_dir: Path,
    model_dir: Path,
    output_dir: Path,
    motion_archive: Path,
    capture_archive: Path,
    stand_archive: Path,
) -> dict[str, Any]:
    """Load three frozen policies and evaluate a reference supervisor."""

    from brax.training.agents.ppo import networks as ppo_networks

    from .environment import make_environment

    effective = make_supervisor_evaluation_profile(base_profile, profile)
    static = static_preflight(base_profile, bundle_dir)
    training_model, derivation = prepare_training_model(base_profile, bundle_dir, model_dir)
    runtime = runtime_preflight(effective, training_model)
    output_dir.mkdir(parents=True, exist_ok=True)
    network_factory = functools.partial(
        ppo_networks.make_ppo_networks,
        policy_hidden_layer_sizes=(128, 128, 128, 128),
        value_hidden_layer_sizes=(256, 256, 256, 256, 256),
        policy_obs_key="state",
        value_obs_key="state",
    )
    environment = make_environment(effective, training_model)
    observation_size = _flat_observation_size(environment.observation_size["state"])
    action_size = int(environment.action_size)
    loaded: dict[str, dict[str, Any]] = {}
    policies: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="worldspec-h1-supervisor-") as temporary:
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
        tests, traces = evaluate_supervisor_suite(
            effective,
            environment,
            policies["motion"],
            policies["capture"],
            policies["stand"],
        )
    controller = {
        "controllerVersion": "0.1.0",
        "status": "research_only",
        "supervisorProfileDigest": digest_json(profile),
        "baseTrainingProfileDigest": digest_json(base_profile),
        "policies": {
            role: {
                "checkpointDigest": value["archiveDigest"],
                "selectedStep": value["selectedStep"],
            }
            for role, value in loaded.items()
        },
        "supervisor": copy.deepcopy(profile["supervisor"]),
        "distribution": "internal_only",
    }
    task_load_stage = profile["stage"] == "task_load_phase_aware_supervisor_probe"
    if task_load_stage:
        controller["taskLoadCurriculum"] = copy.deepcopy(
            profile["evaluationEnvironment"]["taskLoadCurriculum"]
        )
    controller_path = output_dir / (
        "task-load-phase-aware-supervisor.json"
        if task_load_stage
        else "phase-aware-supervisor.json"
    )
    controller_path.write_bytes(canonical_bytes(controller))
    trace_path = output_dir / "evaluation-traces.jsonl"
    with trace_path.open("w", encoding="utf-8") as stream:
        for record in traces:
            stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    expected_tests = profile["qualityGates"]["requiredConsecutivePasses"] * 2
    tests_gate = len(tests) == expected_tests and all(item["result"] == "pass" for item in tests)
    capacity = base_profile["runtime"]["mjxCapacity"]
    return {
        "baseTrainingProfileDigest": digest_json(base_profile),
        "supervisorProfileDigest": digest_json(profile),
        "motionPolicy": loaded["motion"],
        "capturePolicy": loaded["capture"],
        "standPolicy": loaded["stand"],
        "runtimeCapacity": {
            **capacity,
            "effectiveNaconmax": (
                capacity["activeContactsPerEnvironment"] * effective["training"]["numEnvs"]
            ),
            "effectiveNaccdmax": (
                capacity["ccdContactsPerEnvironment"] * effective["training"]["numEnvs"]
            ),
        },
        "staticPreflight": static,
        "runtimePreflight": runtime,
        "target": {
            "sourceBundleDigest": derivation["sourceBundleDigest"],
            "derivedModelDigest": derivation["derivedModelDigest"],
            "observationSize": observation_size,
            "actionSize": action_size,
        },
        "supervisor": copy.deepcopy(profile["supervisor"]),
        **(
            {
                "taskLoadCurriculum": copy.deepcopy(
                    profile["evaluationEnvironment"]["taskLoadCurriculum"]
                )
            }
            if task_load_stage
            else {}
        ),
        "qualityAssessment": {
            "status": "passed" if tests_gate else "failed",
            "deterministicSuiteGate": tests_gate,
            "tests": tests,
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
    }
