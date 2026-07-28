"""Bounded PPO smoke execution for the locked H1 target runtime.

This module deliberately does not call ``train_and_evaluate`` and never emits
the publishable training output contract.  It proves only that the exact target
model can compile and execute a non-zero Brax PPO update on the selected GPU.
"""

from __future__ import annotations

import copy
import functools
import time
from pathlib import Path
from typing import Any

from .contract import digest_json, validate_profile
from .environment import make_environment
from .errors import TrainingError
from .model import prepare_training_model
from .preflight import runtime_preflight, static_preflight
from .trainer import _host_float

SMOKE_OVERRIDES: dict[str, int] = {
    "numTimesteps": 32768,
    "numEnvs": 256,
    "numEvals": 2,
    "episodeLength": 200,
    "unrollLength": 10,
    "numMinibatches": 8,
    "numUpdatesPerBatch": 1,
    "batchSize": 32,
}


def make_smoke_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Return a non-publishable, bounded copy of the canonical profile."""

    validate_profile(profile)
    smoke = copy.deepcopy(profile)
    smoke["training"].update(SMOKE_OVERRIDES)
    smoke["training"]["hyperparameterStatus"] = "research_smoke_override"
    return smoke


def run_ppo_smoke(
    profile: dict[str, Any],
    bundle_dir: Path,
    model_dir: Path,
) -> dict[str, Any]:
    """Compile PPO, execute updates, and run one trained-policy environment step."""

    import jax
    import numpy as np
    from brax.training.agents.ppo import networks as ppo_networks
    from brax.training.agents.ppo import train as ppo
    from mujoco_playground import wrapper

    canonical_digest = digest_json(profile)
    smoke = make_smoke_profile(profile)
    smoke_digest = digest_json(smoke)
    static = static_preflight(profile, bundle_dir)
    training_model, derivation = prepare_training_model(profile, bundle_dir, model_dir)
    runtime = runtime_preflight(profile, training_model)
    environment = make_environment(smoke, training_model)
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
                "TRAINING_SMOKE_METRIC_NONFINITE",
                "PPO smoke produced a non-finite scalar metric.",
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
    make_inference_fn, params, _ = ppo.train(
        environment=environment,
        progress_fn=progress,
        policy_params_fn=lambda *_: None,
        num_timesteps=smoke["training"]["numTimesteps"],
        num_evals=smoke["training"]["numEvals"],
        reward_scaling=1.0,
        episode_length=smoke["training"]["episodeLength"],
        normalize_observations=True,
        action_repeat=1,
        unroll_length=smoke["training"]["unrollLength"],
        num_minibatches=smoke["training"]["numMinibatches"],
        num_updates_per_batch=smoke["training"]["numUpdatesPerBatch"],
        discounting=smoke["training"]["discounting"],
        learning_rate=smoke["training"]["learningRate"],
        entropy_cost=smoke["training"]["entropyCost"],
        num_envs=smoke["training"]["numEnvs"],
        batch_size=smoke["training"]["batchSize"],
        max_grad_norm=1.0,
        network_factory=network_factory,
        seed=smoke["training"]["seed"],
        wrap_env_fn=wrapper.wrap_for_brax_training,
        num_eval_envs=min(32, smoke["training"]["numEnvs"]),
    )
    if len(progress_records) < 2 or max(item["step"] for item in progress_records) <= 0:
        raise TrainingError(
            "TRAINING_SMOKE_UPDATE_MISSING",
            "PPO smoke did not report a non-zero training step.",
            {"progress": progress_records},
        )

    reset = jax.jit(environment.reset)
    step = jax.jit(environment.step)
    inference = jax.jit(make_inference_fn(params, deterministic=True))
    rng = jax.random.PRNGKey(smoke["training"]["seed"])
    state = reset(rng)
    rng, action_rng = jax.random.split(rng)
    action, _ = inference(state.obs, action_rng)
    next_state = step(state, action)
    action_value = np.asarray(jax.block_until_ready(action))
    observation = np.asarray(jax.block_until_ready(next_state.obs["state"]))
    qpos = np.asarray(jax.block_until_ready(next_state.data.qpos))
    qvel = np.asarray(jax.block_until_ready(next_state.data.qvel))
    reward = np.asarray(jax.block_until_ready(next_state.reward))
    finite = {
        "actionFinite": bool(np.isfinite(action_value).all()),
        "observationFinite": bool(np.isfinite(observation).all()),
        "qposFinite": bool(np.isfinite(qpos).all()),
        "qvelFinite": bool(np.isfinite(qvel).all()),
        "rewardFinite": bool(np.isfinite(reward).all()),
    }
    if not all(finite.values()):
        raise TrainingError(
            "TRAINING_SMOKE_INFERENCE_NONFINITE",
            "The trained-policy smoke step produced a non-finite value.",
            finite,
        )
    final_progress = progress_records[-1]
    return {
        "canonicalProfileDigest": canonical_digest,
        "smokeProfileDigest": smoke_digest,
        "smokeOverrides": SMOKE_OVERRIDES,
        "staticPreflight": static,
        "runtimePreflight": runtime,
        "target": {
            "sourceBundleDigest": derivation["sourceBundleDigest"],
            "derivedModelDigest": derivation["derivedModelDigest"],
            "observationSize": int(observation.size),
            "actionSize": int(action_value.size),
        },
        "training": {
            "progressRecordCount": len(progress_records),
            "maximumReportedStep": max(item["step"] for item in progress_records),
            "elapsedSeconds": time.monotonic() - started,
            "firstProgress": progress_records[0],
            "finalProgress": final_progress,
        },
        "trainedInference": {
            **finite,
            "actionL2Norm": float(np.linalg.norm(action_value)),
            "reward": float(reward.reshape(())),
        },
    }
