"""Bounded, non-publishable H1 locomotion curriculum calibration."""

from __future__ import annotations

import copy
import functools
import time
from pathlib import Path
from typing import Any

from .contract import digest_bytes, digest_json, validate_profile
from .environment import make_environment
from .errors import TrainingError
from .model import prepare_training_model
from .preflight import runtime_preflight, static_preflight
from .trainer import _deterministic_zip, _flat_observation_size, _host_float


def validate_calibration_profile(
    base_profile: dict[str, Any],
    calibration_profile: dict[str, Any],
) -> None:
    """Validate high-impact bindings not expressible by JSON Schema alone."""

    validate_profile(base_profile)
    if calibration_profile.get("profileVersion") != "0.1.0":
        raise TrainingError(
            "CALIBRATION_PROFILE_UNSUPPORTED",
            "Calibration profileVersion must be 0.1.0.",
        )
    if calibration_profile.get("status") != "research":
        raise TrainingError(
            "CALIBRATION_STATUS_INVALID",
            "Calibration is a research-only operation.",
        )
    if calibration_profile.get("stage") != "stand":
        raise TrainingError(
            "CALIBRATION_STAGE_UNSUPPORTED",
            "The first calibration stage must be stand.",
        )
    actual_base_digest = digest_json(base_profile)
    if calibration_profile.get("baseTrainingProfileDigest") != actual_base_digest:
        raise TrainingError(
            "CALIBRATION_BASE_PROFILE_MISMATCH",
            "Calibration is not bound to the exact base training Profile.",
            {
                "expected": actual_base_digest,
                "actual": calibration_profile.get("baseTrainingProfileDigest"),
            },
        )
    base_runtime = base_profile["runtime"]
    calibration_runtime = calibration_profile.get("runtime", {})
    if calibration_runtime.get("packageLockDigest") != base_runtime["packageLockDigest"]:
        raise TrainingError(
            "CALIBRATION_PACKAGE_LOCK_MISMATCH",
            "Calibration must use the package lock bound by the base Profile.",
            {
                "expected": base_runtime["packageLockDigest"],
                "actual": calibration_runtime.get("packageLockDigest"),
            },
        )
    overrides = calibration_profile.get("trainingOverrides", {})
    timesteps = overrides.get("numTimesteps")
    environments = overrides.get("numEnvs")
    if (
        not isinstance(timesteps, int)
        or not 100_000 <= timesteps <= 5_000_000
        or not isinstance(environments, int)
        or not 256 <= environments <= 8192
    ):
        raise TrainingError(
            "CALIBRATION_BUDGET_INVALID",
            "Research calibration must remain within the 100K-5M and 256-8192 bounds.",
        )
    command = calibration_profile.get("environment", {}).get("commandDistribution", {})
    if (
        command.get("linearVelocityX") != [0.0, 0.0]
        or command.get("linearVelocityY") != [0.0, 0.0]
        or command.get("angularVelocityYaw") != [0.0, 0.0]
        or command.get("zeroCommandProbability") != 1.0
    ):
        raise TrainingError(
            "CALIBRATION_STAND_COMMAND_INVALID",
            "Stand calibration must use an exact zero command distribution.",
        )
    artifact_policy = calibration_profile.get("artifactPolicy", {})
    if artifact_policy != {
        "checkpoint": "research_only",
        "distribution": "internal_only",
    }:
        raise TrainingError(
            "CALIBRATION_ARTIFACT_POLICY_INVALID",
            "Calibration checkpoints must remain internal research artifacts.",
        )


def make_calibration_training_profile(
    base_profile: dict[str, Any],
    calibration_profile: dict[str, Any],
) -> dict[str, Any]:
    """Create the in-memory effective Profile without mutating either input."""

    validate_calibration_profile(base_profile, calibration_profile)
    effective = copy.deepcopy(base_profile)
    effective["runtime"]["containerDigest"] = calibration_profile["runtime"]["containerDigest"]
    effective["runtime"]["packageLockDigest"] = calibration_profile["runtime"]["packageLockDigest"]
    effective["training"].update(calibration_profile["trainingOverrides"])
    effective["training"]["hyperparameterStatus"] = "research_calibration_override"
    effective["training"]["commandDistribution"] = copy.deepcopy(
        calibration_profile["environment"]["commandDistribution"]
    )
    effective["trainingEnvironment"] = copy.deepcopy(calibration_profile["environment"])
    return effective


def _evaluate_standing(
    effective_profile: dict[str, Any],
    calibration_profile: dict[str, Any],
    environment,
    make_inference_fn,
    params,
) -> list[dict[str, Any]]:
    import jax
    import jax.numpy as jp
    import numpy as np

    inference = jax.jit(make_inference_fn(params, deterministic=True))
    reset = jax.jit(environment.reset)
    step = jax.jit(environment.step)
    gates = calibration_profile["qualityGates"]
    validation = effective_profile["validation"]
    dt = (
        effective_profile["training"]["simulationTimestepSeconds"]
        * effective_profile["control"]["controlDecimation"]
    )
    steps = max(
        1,
        round(gates["deterministicEvaluationDurationSeconds"] / dt),
    )
    tests: list[dict[str, Any]] = []
    for run_index in range(gates["requiredDeterministicPasses"]):
        rng = jax.random.PRNGKey(effective_profile["training"]["seed"] + run_index)
        state = reset(rng)
        start_xy = np.asarray(state.data.qpos[:2], dtype=float)
        minimum_height = float("inf")
        minimum_upright = float("inf")
        maximum_planar_drift = 0.0
        done_seen = False
        terminal_reasons: set[str] = set()
        completed_steps = 0
        for _ in range(steps):
            info = dict(state.info)
            info["command"] = jp.zeros(3)
            state = state.replace(info=info)
            rng, action_rng = jax.random.split(rng)
            action, _ = inference(state.obs, action_rng)
            state = step(state, action)
            jax.block_until_ready(state.reward)
            height = float(np.asarray(state.data.xpos[environment.pelvis_body_id, 2]))
            upright = float(np.asarray(environment.upvector(state.data)[2]))
            planar_drift = float(
                np.linalg.norm(np.asarray(state.data.qpos[:2], dtype=float) - start_xy)
            )
            minimum_height = min(minimum_height, height)
            minimum_upright = min(minimum_upright, upright)
            maximum_planar_drift = max(maximum_planar_drift, planar_drift)
            completed_steps += 1
            if bool(np.asarray(state.done)):
                done_seen = True
                terminal_reasons.update(
                    name
                    for name, value in state.info["termination"].items()
                    if bool(np.asarray(value))
                )
                break
        passed = (
            not done_seen
            and completed_steps == steps
            and minimum_height >= validation["minimumBaseHeight"]
            and minimum_upright >= validation["minimumUprightCosine"]
            and maximum_planar_drift <= gates["maximumPlanarDrift"]
        )
        tests.append(
            {
                "run": run_index,
                "result": "pass" if passed else "fail",
                "completedSteps": completed_steps,
                "requiredSteps": steps,
                "minimumBaseHeight": minimum_height,
                "minimumUprightCosine": minimum_upright,
                "maximumPlanarDrift": maximum_planar_drift,
                "doneSeen": done_seen,
                "terminalReasons": sorted(terminal_reasons),
            }
        )
    return tests


def run_calibration(
    base_profile: dict[str, Any],
    calibration_profile: dict[str, Any],
    bundle_dir: Path,
    model_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Execute bounded PPO calibration and retain an internal-only checkpoint."""

    import numpy as np
    from brax.training.agents.ppo import networks as ppo_networks
    from brax.training.agents.ppo import train as ppo
    from mujoco_playground import wrapper

    effective = make_calibration_training_profile(base_profile, calibration_profile)
    static = static_preflight(base_profile, bundle_dir)
    training_model, derivation = prepare_training_model(base_profile, bundle_dir, model_dir)
    runtime = runtime_preflight(effective, training_model)
    environment = make_environment(effective, training_model)
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
                "CALIBRATION_METRIC_NONFINITE",
                "PPO calibration produced a non-finite scalar metric.",
                {"step": int(step), "metrics": scalar_metrics},
            )
        progress_records.append(
            {
                "step": int(step),
                "elapsedSeconds": time.monotonic() - started,
                "metrics": scalar_metrics,
            }
        )

    training = effective["training"]
    network_factory = functools.partial(
        ppo_networks.make_ppo_networks,
        policy_hidden_layer_sizes=(128, 128, 128, 128),
        value_hidden_layer_sizes=(256, 256, 256, 256, 256),
        policy_obs_key="state",
        value_obs_key="state",
    )
    make_inference_fn, params, _ = ppo.train(
        environment=environment,
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
        wrap_env_fn=wrapper.wrap_for_brax_training,
        num_eval_envs=min(128, training["numEnvs"]),
    )
    if len(progress_records) < 2:
        raise TrainingError(
            "CALIBRATION_PROGRESS_MISSING",
            "Calibration did not report enough progress records.",
        )
    final_progress = progress_records[-1]
    final_mean_episode_length = final_progress["metrics"].get("eval/avg_episode_length")
    if final_mean_episode_length is None:
        raise TrainingError(
            "CALIBRATION_EPISODE_METRIC_MISSING",
            "Calibration did not report eval/avg_episode_length.",
        )
    tests = _evaluate_standing(
        effective,
        calibration_profile,
        environment,
        make_inference_fn,
        params,
    )
    checkpoint_archive = output_dir / "calibration-checkpoint.zip"
    _deterministic_zip(checkpoint_dir, checkpoint_archive)
    baseline = float(calibration_profile["qualityGates"]["baselineMeanEpisodeLength"])
    improvement = float(final_mean_episode_length) / baseline
    gates = calibration_profile["qualityGates"]
    deterministic_passes = sum(test["result"] == "pass" for test in tests)
    mean_gate = float(final_mean_episode_length) >= gates["minimumFinalMeanEpisodeLength"]
    improvement_gate = improvement >= gates["minimumImprovementRatio"]
    deterministic_gate = deterministic_passes >= gates["requiredDeterministicPasses"]
    quality_passed = mean_gate and improvement_gate and deterministic_gate
    return {
        "baseTrainingProfileDigest": digest_json(base_profile),
        "calibrationProfileDigest": digest_json(calibration_profile),
        "effectiveTrainingProfileDigest": digest_json(effective),
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
            "observationSize": _flat_observation_size(environment.observation_size["state"]),
            "actionSize": int(environment.action_size),
        },
        "training": {
            "progressRecordCount": len(progress_records),
            "maximumReportedStep": max(item["step"] for item in progress_records),
            "elapsedSeconds": time.monotonic() - started,
            "firstProgress": progress_records[0],
            "finalProgress": final_progress,
        },
        "qualityAssessment": {
            "status": "passed" if quality_passed else "failed",
            "baselineMeanEpisodeLength": baseline,
            "finalMeanEpisodeLength": float(final_mean_episode_length),
            "episodeLengthImprovementRatio": improvement,
            "meanEpisodeLengthGate": mean_gate,
            "improvementGate": improvement_gate,
            "deterministicStandPasses": deterministic_passes,
            "requiredDeterministicStandPasses": gates["requiredDeterministicPasses"],
            "deterministicStandGate": deterministic_gate,
            "tests": tests,
        },
        "researchCheckpoint": {
            "path": checkpoint_archive.name,
            "digest": digest_bytes(checkpoint_archive.read_bytes()),
            "sizeBytes": checkpoint_archive.stat().st_size,
            "distribution": "internal_only",
        },
    }
