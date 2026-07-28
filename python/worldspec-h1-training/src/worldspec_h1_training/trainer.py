"""Brax JAX PPO training and fixed-profile evaluation."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from .contract import digest_bytes, digest_json
from .errors import TrainingError


def _host_float(value: Any) -> float:
    import numpy as np

    array = np.asarray(value)
    if array.size != 1:
        raise TrainingError("TRAINING_METRIC_SHAPE_INVALID", "Expected a scalar training metric.")
    return float(array.reshape(()))


def _deterministic_zip(source: Path, destination: Path) -> None:
    files = sorted(
        (path for path in source.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(source).as_posix().encode(),
    )
    if not files:
        raise TrainingError(
            "TRAINING_CHECKPOINT_MISSING",
            "Brax/Orbax did not produce a checkpoint.",
        )
    with zipfile.ZipFile(
        destination, mode="w", compression=zipfile.ZIP_STORED, allowZip64=True
    ) as archive:
        for path in files:
            if path.is_symlink():
                raise TrainingError(
                    "TRAINING_CHECKPOINT_SYMLINK",
                    "Checkpoint archives cannot contain symlinks.",
                )
            info = zipfile.ZipInfo(
                path.relative_to(source).as_posix(),
                date_time=(1980, 1, 1, 0, 0, 0),
            )
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())


def _evaluate(
    profile: dict[str, Any],
    env,
    make_inference_fn,
    params,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    import jax
    import jax.numpy as jp
    import numpy as np

    inference = jax.jit(make_inference_fn(params, deterministic=True))
    reset = jax.jit(env.reset)
    step = jax.jit(env.step)
    validation = profile["validation"]
    dt = profile["training"]["simulationTimestepSeconds"] * profile["control"]["controlDecimation"]
    steps = max(1, round(validation["nominalDurationSeconds"] / dt))
    command_steps = max(1, int(steps * 0.75))
    settle_steps = max(1, round(validation["settleWindowSeconds"] / dt))
    traces: list[dict[str, Any]] = []
    tests: list[dict[str, Any]] = []
    for run_index in range(validation["requiredConsecutivePasses"]):
        rng = jax.random.PRNGKey(profile["training"]["seed"] + run_index)
        state = reset(rng)
        start_x = float(np.asarray(state.data.qpos[0]))
        start_y = float(np.asarray(state.data.qpos[1]))
        minimum_height = float("inf")
        minimum_upright = float("inf")
        nonfinite = 0
        done_seen = False
        maximum_settle_linear_speed = 0.0
        maximum_settle_angular_speed = 0.0
        for index in range(steps):
            command = jp.asarray([0.5, 0.0, 0.0]) if index < command_steps else jp.zeros(3)
            info = dict(state.info)
            info["command"] = command
            state = state.replace(info=info)
            rng, action_rng = jax.random.split(rng)
            action, _ = inference(state.obs, action_rng)
            state = step(state, action)
            qpos = np.asarray(state.data.qpos)
            qvel = np.asarray(state.data.qvel)
            height = float(np.asarray(state.data.xpos[env.pelvis_body_id, 2]))
            upright = float(np.asarray(env.upvector(state.data)[2]))
            finite = bool(np.isfinite(qpos).all() and np.isfinite(qvel).all())
            minimum_height = min(minimum_height, height)
            minimum_upright = min(minimum_upright, upright)
            nonfinite += 0 if finite else 1
            done_seen |= bool(np.asarray(state.done))
            local_velocity = np.asarray(env.local_velocity(state.data))
            angular_velocity = np.asarray(env.angular_velocity(state.data))
            if index >= steps - settle_steps:
                maximum_settle_linear_speed = max(
                    maximum_settle_linear_speed,
                    float(np.linalg.norm(local_velocity)),
                )
                maximum_settle_angular_speed = max(
                    maximum_settle_angular_speed,
                    float(np.linalg.norm(angular_velocity)),
                )
            traces.append(
                {
                    "run": run_index,
                    "step": index,
                    "timeSeconds": (index + 1) * dt,
                    "basePosition": [float(qpos[0]), float(qpos[1]), height],
                    "uprightCosine": upright,
                    "localVelocity": [float(value) for value in local_velocity],
                    "angularVelocity": [float(value) for value in angular_velocity],
                    "done": bool(np.asarray(state.done)),
                    "finite": finite,
                }
            )
        final_qpos = np.asarray(state.data.qpos)
        displacement = float(final_qpos[0] - start_x)
        lateral = abs(float(final_qpos[1] - start_y))
        passed = (
            displacement >= validation["minimumForwardDisplacement"]
            and lateral <= validation["maximumLateralDrift"]
            and minimum_height >= validation["minimumBaseHeight"]
            and minimum_upright >= validation["minimumUprightCosine"]
            and maximum_settle_linear_speed <= validation["maximumSettleLinearSpeed"]
            and maximum_settle_angular_speed <= validation["maximumSettleAngularSpeed"]
            and nonfinite <= validation["maximumNonFiniteSamples"]
            and not done_seen
        )
        tests.append(
            {
                "id": f"test://worldspec/h1-training/nominal-run-{run_index + 1}",
                "result": "pass" if passed else "fail",
                "metrics": {
                    "forwardDisplacement": displacement,
                    "lateralDrift": lateral,
                    "minimumBaseHeight": minimum_height,
                    "minimumUprightCosine": minimum_upright,
                    "maximumSettleLinearSpeed": maximum_settle_linear_speed,
                    "maximumSettleAngularSpeed": maximum_settle_angular_speed,
                    "nonFiniteSamples": nonfinite,
                    "doneSeen": done_seen,
                },
            }
        )
    return tests, traces


def train_and_evaluate(
    profile: dict[str, Any],
    env,
    output_dir: Path,
    model_derivation: dict[str, Any],
) -> None:
    """Run PPO and materialize the strict output contract."""

    import functools
    import time

    from brax.training.agents.ppo import networks as ppo_networks
    from brax.training.agents.ppo import train as ppo
    from mujoco_playground import wrapper

    training = profile["training"]
    checkpoint_dir = output_dir / "checkpoints"
    checkpoint_dir.mkdir(parents=True)
    progress_records: list[dict[str, Any]] = []
    started = time.monotonic()

    def progress(step: int, metrics: dict[str, Any]) -> None:
        progress_records.append(
            {
                "step": int(step),
                "elapsedSeconds": time.monotonic() - started,
                "metrics": {
                    key: _host_float(value)
                    for key, value in metrics.items()
                    if getattr(value, "size", 1) == 1
                },
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
        environment=env,
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
    tests, traces = _evaluate(profile, env, make_inference_fn, params)
    if any(test["result"] != "pass" for test in tests):
        raise TrainingError(
            "TRAINING_NOMINAL_EVALUATION_FAILED",
            "The trained policy failed one or more required nominal runs.",
            {"tests": tests},
        )
    checkpoint_archive = output_dir / "policy-checkpoint.zip"
    _deterministic_zip(checkpoint_dir, checkpoint_archive)
    checkpoint_digest = digest_bytes(checkpoint_archive.read_bytes())
    policy_manifest = {
        "manifestVersion": "0.1.0",
        "policyFormat": "orbax_checkpoint_zip",
        "checkpointDigest": checkpoint_digest,
        "trainingProfileDigest": digest_json(profile),
        "targetBundleDigest": profile["target"]["bundleDigest"],
        "frameworkSourceLockDigest": profile["framework"]["sourceLockDigest"],
        "frameworkSourceCommit": profile["framework"]["sourceCommit"],
        "physicsImplementation": profile["framework"]["physicsImplementation"],
        "trainer": profile["framework"]["trainer"],
        "targetEnvironmentAdapter": profile["framework"]["targetEnvironmentAdapter"],
        "observationSize": int(env.observation_size["state"]),
        "actionSize": int(env.action_size),
        "modelDerivation": model_derivation,
        "evidenceStatus": "executed",
    }
    (output_dir / "policy-manifest.json").write_text(
        json.dumps(policy_manifest, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    with (output_dir / "evaluation-traces.jsonl").open("w", encoding="utf-8") as stream:
        for record in traces:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
    runtime = profile["runtime"]
    environment_lock = {
        "containerDigest": runtime["containerDigest"],
        "packageLockDigest": runtime["packageLockDigest"],
        "backendPackage": runtime["backendPackage"],
        "backendVersion": runtime["backendVersion"],
        "frameworkSourceLockDigest": profile["framework"]["sourceLockDigest"],
        "frameworkSourceCommit": profile["framework"]["sourceCommit"],
        "jaxMatmulPrecision": training["matmulPrecision"],
    }
    (output_dir / "environment-lock.json").write_text(
        json.dumps(environment_lock, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    metrics = {
        "tests": tests,
        "diagnostics": [],
        "trainingProgress": progress_records,
        "checkpointDigest": checkpoint_digest,
    }
    (output_dir / "metrics.json").write_text(
        json.dumps(metrics, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
