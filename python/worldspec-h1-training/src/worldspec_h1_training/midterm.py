"""Loaded H1+Robotiq walk/settle curriculum calibration."""

from __future__ import annotations

import copy
import functools
import tempfile
import time
from pathlib import Path
from typing import Any

from .contract import digest_bytes, digest_json, validate_profile
from .errors import TrainingError
from .evaluation import evaluate_policy_suite
from .model import prepare_training_model
from .preflight import runtime_preflight, static_preflight
from .trainer import _deterministic_zip, _flat_observation_size, _host_float
from .warm_start import materialize_warm_start, validate_network_compatibility

STAND_REPORT_DIGEST = (
    "sha256:8a92a910ca52540fff50bab37e20e7e28d4ea06ae0acd20d0079e8b45e65f660"
)
STAND_CHECKPOINT_DIGEST = (
    "sha256:fc91edb936de7391b7e075596e5aaa944acc656664cdb820dbb21c149cf7921c"
)
STAND_CHECKPOINT_SIZE = 6_280_684


def validate_midterm_profile(
    base_profile: dict[str, Any],
    profile: dict[str, Any],
) -> None:
    """Validate the fail-closed midterm curriculum contract."""

    validate_profile(base_profile)
    if profile.get("profileVersion") != "0.1.0":
        raise TrainingError(
            "MIDTERM_PROFILE_UNSUPPORTED",
            "Midterm profileVersion must be 0.1.0.",
        )
    if profile.get("status") != "research" or profile.get("stage") != (
        "loaded_track_settle"
    ):
        raise TrainingError(
            "MIDTERM_STAGE_INVALID",
            "Midterm calibration must be the loaded_track_settle research stage.",
        )
    if profile.get("baseTrainingProfileDigest") != digest_json(base_profile):
        raise TrainingError(
            "MIDTERM_BASE_PROFILE_MISMATCH",
            "Midterm calibration is not bound to the exact base training Profile.",
        )
    source = profile.get("warmStart", {})
    if (
        source.get("sourceStage") != "stand-v2.1"
        or source.get("sourceReportDigest") != STAND_REPORT_DIGEST
        or source.get("checkpointDigest") != STAND_CHECKPOINT_DIGEST
        or source.get("checkpointSizeBytes") != STAND_CHECKPOINT_SIZE
    ):
        raise TrainingError(
            "MIDTERM_STAND_EVIDENCE_MISMATCH",
            "Midterm calibration must bind the accepted stand-v2.1 report and checkpoint.",
        )
    if source.get("optimizerState") != "reset" or source.get("restore") != {
        "normalizer": True,
        "policy": True,
        "value": True,
    }:
        raise TrainingError(
            "MIDTERM_WARM_START_INVALID",
            "Midterm calibration must restore normalizer/policy/value and reset optimizer.",
        )
    if source.get("distribution") != "internal_only":
        raise TrainingError(
            "MIDTERM_WARM_START_DISTRIBUTION_INVALID",
            "Midterm warm-start input must remain internal-only.",
        )
    overrides = profile.get("trainingOverrides", {})
    expected = {
        "numTimesteps": 16_777_216,
        "numEnvs": 4096,
        "numEvals": 8,
        "episodeLength": 1000,
        "unrollLength": 20,
        "numMinibatches": 16,
        "numUpdatesPerBatch": 4,
        "batchSize": 256,
    }
    if overrides != expected:
        raise TrainingError(
            "MIDTERM_TRAINING_OVERRIDES_INVALID",
            "Midterm calibration budget and topology are frozen.",
            {"expected": expected, "actual": overrides},
        )
    if (overrides["batchSize"] * overrides["numMinibatches"]) % overrides[
        "numEnvs"
    ]:
        raise TrainingError(
            "MIDTERM_BATCH_TOPOLOGY_INVALID",
            "batchSize times numMinibatches must be divisible by numEnvs.",
        )
    command = profile.get("environment", {}).get("commandDistribution")
    if command != {
        "linearVelocityX": [0.0, 0.6],
        "linearVelocityY": [-0.1, 0.1],
        "angularVelocityYaw": [-0.25, 0.25],
        "zeroCommandProbability": 0.2,
    }:
        raise TrainingError(
            "MIDTERM_COMMAND_INVALID",
            "Midterm command distribution is not the approved kitchen range.",
        )
    runtime = profile.get("runtime", {})
    if runtime.get("containerDigest") != (
        runtime.get("containerImage", "").rsplit("@", maxsplit=1)[-1]
    ):
        raise TrainingError(
            "MIDTERM_CONTAINER_BINDING_MISMATCH",
            "Midterm containerImage and containerDigest must identify the same OCI image.",
        )
    if runtime.get("packageLockDigest") != base_profile["runtime"]["packageLockDigest"]:
        raise TrainingError(
            "MIDTERM_PACKAGE_LOCK_MISMATCH",
            "Midterm calibration must use the base Profile package lock.",
        )
    if profile.get("artifactPolicy") != {
        "checkpoint": "research_only",
        "distribution": "internal_only",
    }:
        raise TrainingError(
            "MIDTERM_ARTIFACT_POLICY_INVALID",
            "Midterm outputs must remain internal research artifacts.",
        )


def make_midterm_training_profile(
    base_profile: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    validate_midterm_profile(base_profile, profile)
    effective = copy.deepcopy(base_profile)
    effective["runtime"]["containerDigest"] = profile["runtime"]["containerDigest"]
    effective["runtime"]["packageLockDigest"] = profile["runtime"]["packageLockDigest"]
    effective["training"].update(profile["trainingOverrides"])
    effective["training"]["hyperparameterStatus"] = "research_midterm_override"
    effective["training"]["commandDistribution"] = copy.deepcopy(
        profile["environment"]["commandDistribution"]
    )
    effective["trainingEnvironment"] = copy.deepcopy(profile["environment"])
    effective["validation"] = copy.deepcopy(profile["qualityGates"])
    return effective


def run_midterm_calibration(
    base_profile: dict[str, Any],
    profile: dict[str, Any],
    bundle_dir: Path,
    model_dir: Path,
    output_dir: Path,
    warm_start_archive: Path,
) -> dict[str, Any]:
    """Warm-start, train, evaluate, and retain a midterm checkpoint."""

    import numpy as np
    from brax.training.agents.ppo import networks as ppo_networks
    from brax.training.agents.ppo import train as ppo
    from mujoco_playground import wrapper

    effective = make_midterm_training_profile(base_profile, profile)
    static = static_preflight(base_profile, bundle_dir)
    training_model, derivation = prepare_training_model(base_profile, bundle_dir, model_dir)
    runtime = runtime_preflight(effective, training_model)
    from .environment import make_environment

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
                "MIDTERM_METRIC_NONFINITE",
                "Midterm PPO produced a non-finite scalar metric.",
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
    with tempfile.TemporaryDirectory(prefix="worldspec-h1-warm-start-") as temporary:
        selected_step, initialization = materialize_warm_start(
            warm_start_archive,
            Path(temporary) / "checkpoint",
            profile["warmStart"]["checkpointDigest"],
            profile["warmStart"]["checkpointSizeBytes"],
        )
        observation_size = _flat_observation_size(environment.observation_size["state"])
        action_size = int(environment.action_size)
        validate_network_compatibility(initialization, observation_size, action_size)
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
            restore_checkpoint_path=str(selected_step),
            restore_value_fn=True,
            wrap_env_fn=wrapper.wrap_for_brax_training,
            num_eval_envs=min(128, training["numEnvs"]),
        )
    if len(progress_records) < 2:
        raise TrainingError(
            "MIDTERM_PROGRESS_MISSING",
            "Midterm calibration did not report enough progress records.",
        )
    final_progress = progress_records[-1]
    final_mean_episode_length = final_progress["metrics"].get("eval/avg_episode_length")
    if final_mean_episode_length is None:
        raise TrainingError(
            "MIDTERM_EPISODE_METRIC_MISSING",
            "Midterm calibration did not report eval/avg_episode_length.",
        )
    tests, traces = evaluate_policy_suite(
        effective,
        environment,
        make_inference_fn,
        params,
    )
    checkpoint_archive = output_dir / "midterm-checkpoint.zip"
    _deterministic_zip(checkpoint_dir, checkpoint_archive)
    with (output_dir / "evaluation-traces.jsonl").open("w", encoding="utf-8") as stream:
        import json

        for record in traces:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
    expected_tests = profile["qualityGates"]["requiredConsecutivePasses"] * 2
    tests_gate = len(tests) == expected_tests and all(
        item["result"] == "pass" for item in tests
    )
    episode_gate = (
        float(final_mean_episode_length)
        >= profile["qualityGates"]["minimumFinalMeanEpisodeLength"]
    )
    quality_passed = tests_gate and episode_gate
    return {
        "baseTrainingProfileDigest": digest_json(base_profile),
        "midtermProfileDigest": digest_json(profile),
        "effectiveTrainingProfileDigest": digest_json(effective),
        "warmStart": initialization,
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
            "path": "evaluation-traces.jsonl",
            "digest": digest_bytes((output_dir / "evaluation-traces.jsonl").read_bytes()),
            "sizeBytes": (output_dir / "evaluation-traces.jsonl").stat().st_size,
        },
    }
