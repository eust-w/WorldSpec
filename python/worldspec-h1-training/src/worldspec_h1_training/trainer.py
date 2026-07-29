"""Brax JAX PPO training and fixed-profile evaluation."""

from __future__ import annotations

import copy
import json
import zipfile
from pathlib import Path
from typing import Any

from .contract import digest_bytes, digest_json
from .errors import TrainingError
from .evaluation import evaluate_policy_suite


def _host_float(value: Any) -> float:
    import numpy as np

    array = np.asarray(value)
    if array.size != 1:
        raise TrainingError("TRAINING_METRIC_SHAPE_INVALID", "Expected a scalar training metric.")
    return float(array.reshape(()))


def _flat_observation_size(value: Any) -> int:
    """Return the flattened size for scalar or shaped observation metadata."""

    if isinstance(value, int):
        return value
    size = 1
    try:
        for dimension in value:
            size *= int(dimension)
    except (TypeError, ValueError) as error:
        raise TrainingError(
            "TRAINING_OBSERVATION_SIZE_INVALID",
            "Observation metadata must be an integer or a finite shape.",
            {"value": repr(value)},
        ) from error
    if size <= 0:
        raise TrainingError(
            "TRAINING_OBSERVATION_SIZE_INVALID",
            "Observation shape dimensions must have a positive product.",
            {"value": repr(value)},
        )
    return size


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


def train_and_evaluate(
    profile: dict[str, Any],
    env,
    output_dir: Path,
    model_derivation: dict[str, Any],
    restore_checkpoint_path: Path | None = None,
    initialization: dict[str, Any] | None = None,
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
        restore_checkpoint_path=(
            str(restore_checkpoint_path) if restore_checkpoint_path is not None else None
        ),
        restore_value_fn=restore_checkpoint_path is not None,
        wrap_env_fn=wrapper.wrap_for_brax_training,
        num_eval_envs=min(128, training["numEnvs"]),
    )
    evaluation_profile = profile
    expected_test_count = 10
    if training["hyperparameterStatus"] != "calibrated_task_profile":
        evaluation_profile = copy.deepcopy(profile)
        validation = evaluation_profile["validation"]
        validation.setdefault(
            "moveDurationSeconds",
            validation["nominalDurationSeconds"] * 0.75,
        )
        validation.setdefault("maximumForwardDisplacement", 1.0e9)
        validation.setdefault("maximumTrackingRmse", 1.0e9)
        validation.setdefault(
            "maximumStandPlanarDrift",
            validation["maximumLateralDrift"],
        )
        expected_test_count = 5
    tests, traces = evaluate_policy_suite(
        evaluation_profile,
        env,
        make_inference_fn,
        params,
    )
    if expected_test_count == 5:
        tests = [test for test in tests if test["suite"] == "walk_settle"]
        traces = [trace for trace in traces if trace["suite"] == "walk_settle"]
    quality_passed = len(tests) == expected_test_count and all(
        test["result"] == "pass" for test in tests
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
        "observationSize": _flat_observation_size(env.observation_size["state"]),
        "actionSize": int(env.action_size),
        "modelDerivation": model_derivation,
        "initialization": initialization,
        "policyStatus": "policy_candidate" if quality_passed else "non_publishable",
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
        "initialization": initialization,
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
        "qualityStatus": "passed" if quality_passed else "failed",
        "policyStatus": "policy_candidate" if quality_passed else "non_publishable",
    }
    (output_dir / "metrics.json").write_text(
        json.dumps(metrics, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
