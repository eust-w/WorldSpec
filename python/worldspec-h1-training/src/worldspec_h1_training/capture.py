"""Motion-state capture-policy calibration for the loaded H1 target."""

from __future__ import annotations

import copy
import functools
import json
import tempfile
import time
from pathlib import Path
from typing import Any

from .contract import digest_bytes, digest_json, validate_profile
from .errors import TrainingError
from .midterm import (
    FAILED_TRANSITION_CHECKPOINT_DIGEST,
    FAILED_TRANSITION_CHECKPOINT_SIZE,
    FAILED_TRANSITION_REPORT_DIGEST,
    STAND_CHECKPOINT_DIGEST,
    STAND_CHECKPOINT_SIZE,
    STAND_REPORT_DIGEST,
    _load_deterministic_teacher_policy,
)
from .model import prepare_training_model
from .preflight import runtime_preflight, static_preflight
from .trainer import _deterministic_zip, _flat_observation_size, _host_float
from .warm_start import materialize_warm_start, validate_network_compatibility

CAPTURE_WARM_START = {
    "sourceStage": "stand-v2.1",
    "sourceReportDigest": STAND_REPORT_DIGEST,
    "checkpointDigest": STAND_CHECKPOINT_DIGEST,
    "checkpointSizeBytes": STAND_CHECKPOINT_SIZE,
    "distribution": "internal_only",
    "restore": {"normalizer": True, "policy": True, "value": True},
    "optimizerState": "reset",
}
MOTION_TEACHER = {
    "sourceStage": "loaded-track-settle-transition-v2-failed",
    "sourceReportDigest": FAILED_TRANSITION_REPORT_DIGEST,
    "checkpointDigest": FAILED_TRANSITION_CHECKPOINT_DIGEST,
    "checkpointSizeBytes": FAILED_TRANSITION_CHECKPOINT_SIZE,
    "distribution": "internal_only",
    "mode": "deterministic_motion_rollout",
    "scope": "capture_state_generation_and_evaluation",
}
CAPTURE_TRAINING_OVERRIDES = {
    "numTimesteps": 8_388_608,
    "numEnvs": 4096,
    "numEvals": 6,
    "episodeLength": 100,
    "unrollLength": 20,
    "numMinibatches": 16,
    "numUpdatesPerBatch": 4,
    "batchSize": 256,
    "learningRate": 0.0001,
    "entropyCost": 0.003,
}
ZERO_COMMAND = {
    "linearVelocityX": [0.0, 0.0],
    "linearVelocityY": [0.0, 0.0],
    "angularVelocityYaw": [0.0, 0.0],
    "zeroCommandProbability": 1.0,
}
CAPTURE_CURRICULUM = {
    "mode": "motion_snapshot_to_zero",
    "snapshotCount": 4096,
    "handoffStepRange": [140, 159],
    "captureSteps": 100,
    "motionCommandDistribution": {
        "linearVelocityX": [0.4, 0.6],
        "linearVelocityY": [-0.05, 0.05],
        "angularVelocityYaw": [-0.1, 0.1],
    },
}
CAPTURE_REWARD = {
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
    "settleLinear": 12.0,
    "settleYaw": 5.0,
    "settleActionRateScale": 0.25,
}
CAPTURE_QUALITY_GATES = {
    "minimumFinalMeanEpisodeLength": 90.0,
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
}


def validate_capture_profile(base_profile: dict[str, Any], profile: dict[str, Any]) -> None:
    """Validate the immutable A3 capture-policy calibration contract."""

    validate_profile(base_profile)
    if (
        profile.get("profileVersion") != "0.1.0"
        or profile.get("status") != "research"
        or profile.get("stage") != "loaded_track_settle_capture"
    ):
        raise TrainingError(
            "CAPTURE_PROFILE_UNSUPPORTED",
            "Capture calibration must use loaded_track_settle_capture v0.1.",
        )
    if profile.get("baseTrainingProfileDigest") != digest_json(base_profile):
        raise TrainingError(
            "CAPTURE_BASE_PROFILE_MISMATCH",
            "Capture calibration is not bound to the exact base training Profile.",
        )
    if profile.get("warmStart") != CAPTURE_WARM_START:
        raise TrainingError(
            "CAPTURE_WARM_START_INVALID",
            "Capture calibration must warm-start from the passing stand-v2.1 checkpoint.",
        )
    if profile.get("motionTeacher") != MOTION_TEACHER:
        raise TrainingError(
            "CAPTURE_MOTION_TEACHER_INVALID",
            "Capture calibration must bind the frozen transition-v2 motion teacher.",
        )
    if profile.get("trainingOverrides") != CAPTURE_TRAINING_OVERRIDES:
        raise TrainingError(
            "CAPTURE_TRAINING_OVERRIDES_INVALID",
            "Capture calibration budget, optimizer, and topology are frozen.",
        )
    environment = profile.get("environment", {})
    if (
        environment.get("commandDistribution") != ZERO_COMMAND
        or environment.get("captureCurriculum") != CAPTURE_CURRICULUM
        or environment.get("reward") != CAPTURE_REWARD
        or environment.get("termination")
        != {
            "minimumBaseHeight": 0.5,
            "minimumUprightCosine": 0.25,
            "jointLimitToleranceRadians": 0.02,
        }
        or environment.get("targets") != {"baseHeight": 0.98}
        or environment.get("sigmas")
        != {
            "tracking": 0.2,
            "upright": 0.05,
            "baseHeight": 0.02,
            "pose": 0.2,
            "settleTracking": 0.05,
        }
        or environment.get("commandResampleSteps") != 100
    ):
        raise TrainingError(
            "CAPTURE_ENVIRONMENT_INVALID",
            "Capture calibration must retain the frozen motion-snapshot curriculum.",
        )
    if profile.get("qualityGates") != CAPTURE_QUALITY_GATES:
        raise TrainingError(
            "CAPTURE_QUALITY_GATES_INVALID",
            "Capture calibration cannot relax the terminal hold or stand gates.",
        )
    runtime = profile.get("runtime", {})
    if runtime.get("ccdIterations") != 50:
        raise TrainingError(
            "CAPTURE_CCD_ITERATIONS_INVALID",
            "Capture calibration requires the bounded CCD=50 setting.",
        )
    if runtime.get("containerDigest") != runtime.get("containerImage", "").rsplit("@", 1)[-1]:
        raise TrainingError(
            "CAPTURE_CONTAINER_BINDING_MISMATCH",
            "Capture containerImage and containerDigest must identify one OCI image.",
        )
    if runtime.get("packageLockDigest") != base_profile["runtime"]["packageLockDigest"]:
        raise TrainingError(
            "CAPTURE_PACKAGE_LOCK_MISMATCH",
            "Capture calibration must use the base Profile package lock.",
        )
    if profile.get("artifactPolicy") != {
        "checkpoint": "research_only",
        "snapshotBank": "research_only",
        "distribution": "internal_only",
    }:
        raise TrainingError(
            "CAPTURE_ARTIFACT_POLICY_INVALID",
            "Capture checkpoint and state bank must remain internal research artifacts.",
        )


def make_capture_training_profile(
    base_profile: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    validate_capture_profile(base_profile, profile)
    effective = copy.deepcopy(base_profile)
    effective["runtime"]["containerDigest"] = profile["runtime"]["containerDigest"]
    effective["runtime"]["packageLockDigest"] = profile["runtime"]["packageLockDigest"]
    effective["runtime"]["ccdIterations"] = profile["runtime"]["ccdIterations"]
    effective["training"].update(profile["trainingOverrides"])
    effective["training"]["hyperparameterStatus"] = "research_capture_override"
    effective["training"]["commandDistribution"] = copy.deepcopy(ZERO_COMMAND)
    effective["trainingEnvironment"] = copy.deepcopy(profile["environment"])
    effective["validation"] = copy.deepcopy(profile["qualityGates"])
    return effective


def make_motion_rollout_profile(
    base_profile: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    validate_capture_profile(base_profile, profile)
    effective = copy.deepcopy(base_profile)
    effective["runtime"]["containerDigest"] = profile["runtime"]["containerDigest"]
    effective["runtime"]["packageLockDigest"] = profile["runtime"]["packageLockDigest"]
    effective["runtime"]["ccdIterations"] = profile["runtime"]["ccdIterations"]
    effective["training"]["numEnvs"] = CAPTURE_CURRICULUM["snapshotCount"]
    effective["training"]["commandDistribution"] = {
        **copy.deepcopy(CAPTURE_CURRICULUM["motionCommandDistribution"]),
        "zeroCommandProbability": 0.0,
    }
    return effective


def _with_command(env, state, command):
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


def generate_motion_snapshot_bank(
    env,
    motion_policy,
    *,
    seed: int,
    count: int,
    handoff_step_range: list[int],
    command_distribution: dict[str, list[float]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Roll the frozen motion policy to phase-diverse handoff states."""

    import jax
    import jax.numpy as jp
    import numpy as np

    low_step, high_step = handoff_step_range
    if count <= 0 or low_step <= 0 or high_step < low_step:
        raise TrainingError(
            "CAPTURE_SNAPSHOT_PROFILE_INVALID",
            "Snapshot count and handoff step range must be positive.",
        )
    root_key = jax.random.PRNGKey(seed)
    reset_key, command_key, step_key, policy_key = jax.random.split(root_key, 4)
    reset_keys = jax.random.split(reset_key, count)
    reset_batch = jax.jit(jax.vmap(env.reset))
    step_batch = jax.jit(jax.vmap(env.step))
    command_low = jp.asarray(
        [
            command_distribution["linearVelocityX"][0],
            command_distribution["linearVelocityY"][0],
            command_distribution["angularVelocityYaw"][0],
        ]
    )
    command_high = jp.asarray(
        [
            command_distribution["linearVelocityX"][1],
            command_distribution["linearVelocityY"][1],
            command_distribution["angularVelocityYaw"][1],
        ]
    )
    commands = jax.random.uniform(
        command_key,
        shape=(count, 3),
        minval=command_low,
        maxval=command_high,
    )
    handoff_steps = jax.random.randint(
        step_key,
        shape=(count,),
        minval=low_step,
        maxval=high_step + 1,
    )
    states = reset_batch(reset_keys)
    states = jax.jit(jax.vmap(functools.partial(_with_command, env)))(
        states,
        commands,
    )
    captured = states
    captured_failure = jp.zeros((count,), dtype=bool)
    failure = jp.zeros((count,), dtype=bool)
    inference = jax.jit(motion_policy)

    def select(mask, old, new):
        if not hasattr(new, "ndim"):
            return new
        expanded = mask.reshape((count,) + (1,) * (new.ndim - 1))
        return jp.where(expanded, new, old)

    for index in range(high_step):
        action, _ = inference(states.obs, jax.random.fold_in(policy_key, index))
        states = step_batch(states, action)
        failure = failure | states.done.astype(bool)
        hit = handoff_steps == index + 1
        captured = jax.tree_util.tree_map(
            lambda old, new, mask=hit: select(mask, old, new),
            captured,
            states,
        )
        captured_failure = jp.where(hit, failure, captured_failure)

    jax.block_until_ready(captured.data.qpos)
    failed_count = int(np.count_nonzero(np.asarray(captured_failure)))
    if failed_count:
        raise TrainingError(
            "CAPTURE_SNAPSHOT_ROLLOUT_FAILED",
            "Motion teacher terminated before one or more requested handoff states.",
            {"failedCount": failed_count, "snapshotCount": count},
        )
    bank = {
        "qpos": np.asarray(captured.data.qpos),
        "qvel": np.asarray(captured.data.qvel),
        "last_action": np.asarray(captured.info["last_action"]),
    }
    metadata = {
        "snapshotCount": count,
        "handoffStepMinimum": int(np.min(np.asarray(handoff_steps))),
        "handoffStepMaximum": int(np.max(np.asarray(handoff_steps))),
        "motionCommandMinimum": [float(value) for value in np.min(np.asarray(commands), axis=0)],
        "motionCommandMaximum": [float(value) for value in np.max(np.asarray(commands), axis=0)],
        "terminatedSnapshotCount": failed_count,
        "seed": seed,
    }
    return bank, {
        **metadata,
        "handoffSteps": np.asarray(handoff_steps),
        "motionCommands": np.asarray(commands),
    }


def save_snapshot_bank(
    path: Path,
    bank: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    import numpy as np

    np.savez_compressed(
        path,
        qpos=bank["qpos"],
        qvel=bank["qvel"],
        last_action=bank["last_action"],
        handoff_step=metadata["handoffSteps"],
        motion_command=metadata["motionCommands"],
    )
    payload = path.read_bytes()
    return {
        "path": path.name,
        "digest": digest_bytes(payload),
        "sizeBytes": len(payload),
        "distribution": "internal_only",
        "snapshotCount": metadata["snapshotCount"],
        "handoffStepMinimum": metadata["handoffStepMinimum"],
        "handoffStepMaximum": metadata["handoffStepMaximum"],
        "motionCommandMinimum": metadata["motionCommandMinimum"],
        "motionCommandMaximum": metadata["motionCommandMaximum"],
        "terminatedSnapshotCount": metadata["terminatedSnapshotCount"],
        "seed": metadata["seed"],
    }


def evaluate_capture_policy_suite(
    profile: dict[str, Any],
    env,
    motion_policy,
    capture_policy,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Evaluate motion-to-capture and capture-from-rest without action blending."""

    import jax
    import jax.numpy as jp
    import numpy as np

    motion_inference = jax.jit(motion_policy)
    capture_inference = jax.jit(capture_policy)
    reset = jax.jit(env.reset)
    step = jax.jit(env.step)
    validation = profile["validation"]
    dt = profile["training"]["simulationTimestepSeconds"] * profile["control"]["controlDecimation"]
    duration_steps = round(validation["nominalDurationSeconds"] / dt)
    move_steps = round(validation["moveDurationSeconds"] / dt)
    measure_steps = round(validation["settleMeasurementWindowSeconds"] / dt)
    required = validation["requiredConsecutivePasses"]
    tests: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []

    def run(run_index: int, mode: str) -> dict[str, Any]:
        rng = jax.random.PRNGKey(profile["training"]["seed"] + run_index)
        state = reset(rng)
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
        final_linear_speed = None
        final_angular_speed = None
        for index in range(duration_steps):
            moving = mode == "walk_settle" and index < move_steps
            command = jp.asarray([0.5, 0.0, 0.0]) if moving else jp.zeros(3)
            state = _with_command(env, state, command)
            rng, action_rng = jax.random.split(rng)
            if moving:
                action, _ = motion_inference(state.obs, action_rng)
                active_policy = "motion"
            else:
                action, _ = capture_inference(state.obs, action_rng)
                active_policy = "capture"
            action_array = np.asarray(action, dtype=float)
            if previous_action is not None:
                maximum_action_jump = max(
                    maximum_action_jump,
                    float(np.linalg.norm(action_array - previous_action)),
                )
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
            finite = bool(np.isfinite(qpos).all() and np.isfinite(qvel).all())
            if mode == "walk_settle" and index == move_steps:
                capture_start_linear_speed = linear_speed
                capture_start_angular_speed = angular_speed
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
                    "activePolicy": active_policy,
                    "basePosition": [float(qpos[0]), float(qpos[1]), height],
                    "uprightCosine": upright,
                    "localVelocity": [float(value) for value in local_velocity],
                    "angularVelocity": [float(value) for value in angular_velocity],
                    "done": done,
                    "finite": finite,
                }
            )
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
            )
        else:
            passed = (
                common
                and maximum_planar_drift <= validation["maximumStandPlanarDrift"]
                and maximum_terminal_linear_speed <= validation["maximumSettleLinearSpeed"]
                and maximum_terminal_angular_speed <= validation["maximumSettleAngularSpeed"]
            )
        return {
            "id": f"test://worldspec/h1-capture/{mode}/{run_index + 1}",
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


def run_capture_calibration(
    base_profile: dict[str, Any],
    profile: dict[str, Any],
    bundle_dir: Path,
    model_dir: Path,
    output_dir: Path,
    warm_start_archive: Path,
    motion_teacher_archive: Path,
) -> dict[str, Any]:
    """Generate motion handoff states, train capture, and run the ten-test gate."""

    import numpy as np
    from brax.training.agents.ppo import networks as ppo_networks
    from brax.training.agents.ppo import train as ppo
    from mujoco_playground import wrapper

    from .environment import make_environment

    effective = make_capture_training_profile(base_profile, profile)
    motion_profile = make_motion_rollout_profile(base_profile, profile)
    static = static_preflight(base_profile, bundle_dir)
    training_model, derivation = prepare_training_model(base_profile, bundle_dir, model_dir)
    runtime = runtime_preflight(effective, training_model)
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_dir = output_dir / "checkpoints"
    checkpoint_dir.mkdir()
    progress_records: list[dict[str, Any]] = []
    started = time.monotonic()

    def progress(step: int, metrics: dict[str, Any]) -> None:
        scalar_metrics = {
            key: _host_float(value)
            for key, value in metrics.items()
            if getattr(value, "size", 1) == 1
        }
        if not all(np.isfinite(value) for value in scalar_metrics.values()):
            raise TrainingError(
                "CAPTURE_METRIC_NONFINITE",
                "Capture PPO produced a non-finite scalar metric.",
                {"step": int(step), "metrics": scalar_metrics},
            )
        progress_records.append(
            {
                "step": int(step),
                "elapsedSeconds": time.monotonic() - started,
                "metrics": scalar_metrics,
            }
        )

    network_factory = functools.partial(
        ppo_networks.make_ppo_networks,
        policy_hidden_layer_sizes=(128, 128, 128, 128),
        value_hidden_layer_sizes=(256, 256, 256, 256, 256),
        policy_obs_key="state",
        value_obs_key="state",
    )
    training = effective["training"]
    with tempfile.TemporaryDirectory(prefix="worldspec-h1-capture-") as temporary:
        temporary_root = Path(temporary)
        selected_step, initialization = materialize_warm_start(
            warm_start_archive,
            temporary_root / "warm-start",
            CAPTURE_WARM_START["checkpointDigest"],
            CAPTURE_WARM_START["checkpointSizeBytes"],
        )
        motion_step, motion_initialization = materialize_warm_start(
            motion_teacher_archive,
            temporary_root / "motion-teacher",
            MOTION_TEACHER["checkpointDigest"],
            MOTION_TEACHER["checkpointSizeBytes"],
        )
        motion_policy = _load_deterministic_teacher_policy(
            motion_step,
            motion_initialization,
            network_factory,
        )
        motion_environment = make_environment(motion_profile, training_model)
        observation_size = _flat_observation_size(motion_environment.observation_size["state"])
        action_size = int(motion_environment.action_size)
        validate_network_compatibility(initialization, observation_size, action_size)
        validate_network_compatibility(motion_initialization, observation_size, action_size)
        bank, bank_metadata = generate_motion_snapshot_bank(
            motion_environment,
            motion_policy,
            seed=training["seed"] + 10_000,
            count=CAPTURE_CURRICULUM["snapshotCount"],
            handoff_step_range=CAPTURE_CURRICULUM["handoffStepRange"],
            command_distribution=CAPTURE_CURRICULUM["motionCommandDistribution"],
        )
        snapshot_artifact = save_snapshot_bank(
            output_dir / "capture-state-bank.npz",
            bank,
            bank_metadata,
        )
        capture_environment = make_environment(
            effective,
            training_model,
            capture_state_bank=bank,
        )
        make_inference_fn, params, _ = ppo.train(
            environment=capture_environment,
            progress_fn=progress,
            policy_params_fn=lambda *_: None,
            num_timesteps=training["numTimesteps"],
            num_evals=training["numEvals"],
            reward_scaling=1.0,
            episode_length=training["episodeLength"],
            normalize_observations=True,
            action_repeat=1,
            unroll_length=training["unrollLength"],
            num_minibatches=training["numMinibatches"],
            num_updates_per_batch=training["numUpdatesPerBatch"],
            discounting=training["discounting"],
            learning_rate=training["learningRate"],
            entropy_cost=training["entropyCost"],
            num_envs=training["numEnvs"],
            batch_size=training["batchSize"],
            max_grad_norm=1.0,
            network_factory=network_factory,
            seed=training["seed"],
            save_checkpoint_path=checkpoint_dir,
            restore_checkpoint_path=str(selected_step),
            restore_value_fn=True,
            wrap_env_fn=wrapper.wrap_for_brax_training,
            num_eval_envs=min(128, training["numEnvs"]),
        )
        evaluation_environment = make_environment(effective, training_model)
        capture_policy = make_inference_fn(params, deterministic=True)
        tests, traces = evaluate_capture_policy_suite(
            effective,
            evaluation_environment,
            motion_policy,
            capture_policy,
        )
    if len(progress_records) < 2:
        raise TrainingError(
            "CAPTURE_PROGRESS_MISSING",
            "Capture calibration did not report enough progress records.",
        )
    final_progress = progress_records[-1]
    final_mean_episode_length = final_progress["metrics"].get("eval/avg_episode_length")
    if final_mean_episode_length is None:
        raise TrainingError(
            "CAPTURE_EPISODE_METRIC_MISSING",
            "Capture calibration did not report eval/avg_episode_length.",
        )
    checkpoint_archive = output_dir / "midterm-checkpoint.zip"
    _deterministic_zip(checkpoint_dir, checkpoint_archive)
    trace_path = output_dir / "evaluation-traces.jsonl"
    with trace_path.open("w", encoding="utf-8") as stream:
        for record in traces:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
    expected_tests = profile["qualityGates"]["requiredConsecutivePasses"] * 2
    tests_gate = len(tests) == expected_tests and all(item["result"] == "pass" for item in tests)
    episode_gate = (
        float(final_mean_episode_length) >= profile["qualityGates"]["minimumFinalMeanEpisodeLength"]
    )
    quality_passed = tests_gate and episode_gate
    motion_initialization = {
        **motion_initialization,
        "mode": MOTION_TEACHER["mode"],
        "scope": MOTION_TEACHER["scope"],
    }
    return {
        "baseTrainingProfileDigest": digest_json(base_profile),
        "captureProfileDigest": digest_json(profile),
        "effectiveTrainingProfileDigest": digest_json(effective),
        "warmStart": initialization,
        "motionTeacher": motion_initialization,
        "snapshotBank": snapshot_artifact,
        "runtimeCapacity": {
            **base_profile["runtime"]["mjxCapacity"],
            "effectiveNaconmax": (
                base_profile["runtime"]["mjxCapacity"]["activeContactsPerEnvironment"]
                * training["numEnvs"]
            ),
            "effectiveNaccdmax": (
                base_profile["runtime"]["mjxCapacity"]["ccdContactsPerEnvironment"]
                * training["numEnvs"]
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
        "training": {
            "profileStage": profile["stage"],
            "progressRecordCount": len(progress_records),
            "maximumReportedStep": max(item["step"] for item in progress_records),
            "elapsedSeconds": time.monotonic() - started,
            "firstProgress": progress_records[0],
            "finalProgress": final_progress,
        },
        "qualityAssessment": {
            "status": "passed" if quality_passed else "failed",
            "finalMeanEpisodeLength": float(final_mean_episode_length),
            "minimumFinalMeanEpisodeLength": profile["qualityGates"][
                "minimumFinalMeanEpisodeLength"
            ],
            "meanEpisodeLengthGate": episode_gate,
            "deterministicSuiteGate": tests_gate,
            "tests": tests,
        },
        "researchCheckpoint": {
            "path": checkpoint_archive.name,
            "digest": digest_bytes(checkpoint_archive.read_bytes()),
            "sizeBytes": checkpoint_archive.stat().st_size,
            "distribution": "internal_only",
        },
        "traceArtifact": {
            "path": trace_path.name,
            "digest": digest_bytes(trace_path.read_bytes()),
            "sizeBytes": trace_path.stat().st_size,
        },
    }
