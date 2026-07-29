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

STAND_REPORT_DIGEST = "sha256:8a92a910ca52540fff50bab37e20e7e28d4ea06ae0acd20d0079e8b45e65f660"
STAND_CHECKPOINT_DIGEST = "sha256:fc91edb936de7391b7e075596e5aaa944acc656664cdb820dbb21c149cf7921c"
STAND_CHECKPOINT_SIZE = 6_280_684
FAILED_MIDTERM_REPORT_DIGEST = (
    "sha256:961ab5fa5c5f70482f46c8751496f3806f2377654d75d5bba4e6a9d7491a1e39"
)
FAILED_MIDTERM_CHECKPOINT_DIGEST = (
    "sha256:86d8e0de7c900fdbbf945cca1160518f4e27bf7735f40323de7ffadbf07d2c6a"
)
FAILED_MIDTERM_CHECKPOINT_SIZE = 8_821_958
FAILED_TRANSITION_REPORT_DIGEST = (
    "sha256:1d7310274a58e78e21570fe0916c23af49573f41d769037393967d41ce89705d"
)
FAILED_TRANSITION_CHECKPOINT_DIGEST = (
    "sha256:2e4590c9291c81581205aee02c4bf168b9532790a14aecac839faee68954d356"
)
FAILED_TRANSITION_CHECKPOINT_SIZE = 8_838_595

TRANSITION_COMMAND = {
    "linearVelocityX": [0.0, 0.6],
    "linearVelocityY": [-0.1, 0.1],
    "angularVelocityYaw": [-0.25, 0.25],
    "zeroCommandProbability": 0.2,
}
TRANSITION_CURRICULUM = {
    "mode": "move_then_zero",
    "transitionCycleProbability": 0.75,
    "moveSteps": 150,
    "settleSteps": 50,
    "motionCommandDistribution": {
        "linearVelocityX": [0.4, 0.6],
        "linearVelocityY": [-0.05, 0.05],
        "angularVelocityYaw": [-0.1, 0.1],
    },
}
TRANSITION_REWARD_ADDITIONS = {
    "settleLinear": 8.0,
    "settleYaw": 3.0,
    "settleActionRateScale": 0.25,
}
TRANSITION_QUALITY_GATES = {
    "minimumFinalMeanEpisodeLength": 900.0,
    "nominalDurationSeconds": 4.0,
    "moveDurationSeconds": 3.0,
    "settleWindowSeconds": 1.0,
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
RETENTION_TRAINING_OVERRIDES = {
    "numTimesteps": 8_388_608,
    "numEnvs": 4096,
    "numEvals": 6,
    "episodeLength": 1000,
    "unrollLength": 20,
    "numMinibatches": 16,
    "numUpdatesPerBatch": 4,
    "batchSize": 256,
    "learningRate": 0.0001,
    "entropyCost": 0.003,
}
RETENTION_CURRICULUM = {
    "mode": "move_then_zero_with_stand_replay",
    "transitionCycleProbability": 0.6,
    "standReplayProbability": 0.4,
    "moveSteps": 150,
    "settleSteps": 50,
    "motionCommandDistribution": {
        "linearVelocityX": [0.4, 0.6],
        "linearVelocityY": [-0.05, 0.05],
        "angularVelocityYaw": [-0.1, 0.1],
    },
}
RETENTION_REWARD_ADDITIONS = {
    **TRANSITION_REWARD_ADDITIONS,
    "standDistillation": 4.0,
}
RETENTION_TEACHER = {
    "sourceStage": "stand-v2.1",
    "sourceReportDigest": STAND_REPORT_DIGEST,
    "checkpointDigest": STAND_CHECKPOINT_DIGEST,
    "checkpointSizeBytes": STAND_CHECKPOINT_SIZE,
    "distribution": "internal_only",
    "mode": "deterministic_action_distillation",
    "scope": "stand_replay_only",
}


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
    if profile.get("status") != "research" or profile.get("stage") != ("loaded_track_settle"):
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
    if (overrides["batchSize"] * overrides["numMinibatches"]) % overrides["numEnvs"]:
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
    if (
        runtime.get("containerDigest")
        != (runtime.get("containerImage", "").rsplit("@", maxsplit=1)[-1])
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


def validate_transition_profile(
    base_profile: dict[str, Any],
    profile: dict[str, Any],
) -> None:
    """Validate the explicit move-to-zero transition calibration contract."""

    validate_profile(base_profile)
    if (
        profile.get("profileVersion") != "0.1.0"
        or profile.get("status") != "research"
        or profile.get("stage") != "loaded_track_settle_transition"
    ):
        raise TrainingError(
            "TRANSITION_PROFILE_UNSUPPORTED",
            "Transition calibration must use loaded_track_settle_transition v0.1.",
        )
    if profile.get("baseTrainingProfileDigest") != digest_json(base_profile):
        raise TrainingError(
            "TRANSITION_BASE_PROFILE_MISMATCH",
            "Transition calibration is not bound to the exact base training Profile.",
        )
    source = profile.get("warmStart", {})
    if (
        source.get("sourceStage") != "loaded-track-settle-v1-failed"
        or source.get("sourceReportDigest") != FAILED_MIDTERM_REPORT_DIGEST
        or source.get("checkpointDigest") != FAILED_MIDTERM_CHECKPOINT_DIGEST
        or source.get("checkpointSizeBytes") != FAILED_MIDTERM_CHECKPOINT_SIZE
    ):
        raise TrainingError(
            "TRANSITION_SOURCE_EVIDENCE_MISMATCH",
            "Transition calibration must bind the failed v1 report and internal checkpoint.",
        )
    if source.get("optimizerState") != "reset" or source.get("restore") != {
        "normalizer": True,
        "policy": True,
        "value": True,
    }:
        raise TrainingError(
            "TRANSITION_WARM_START_INVALID",
            "Transition calibration must restore normalizer/policy/value and reset optimizer.",
        )
    if source.get("distribution") != "internal_only":
        raise TrainingError(
            "TRANSITION_WARM_START_DISTRIBUTION_INVALID",
            "Transition warm-start input must remain internal-only.",
        )
    expected_overrides = {
        "numTimesteps": 16_777_216,
        "numEnvs": 4096,
        "numEvals": 8,
        "episodeLength": 1000,
        "unrollLength": 20,
        "numMinibatches": 16,
        "numUpdatesPerBatch": 4,
        "batchSize": 256,
    }
    if profile.get("trainingOverrides") != expected_overrides:
        raise TrainingError(
            "TRANSITION_TRAINING_OVERRIDES_INVALID",
            "Transition calibration budget and topology are frozen.",
        )
    environment = profile.get("environment", {})
    if environment.get("commandDistribution") != TRANSITION_COMMAND:
        raise TrainingError(
            "TRANSITION_COMMAND_INVALID",
            "Transition calibration must retain the accepted kitchen command range.",
        )
    if environment.get("transitionCurriculum") != TRANSITION_CURRICULUM:
        raise TrainingError(
            "TRANSITION_CURRICULUM_INVALID",
            "Transition calibration must use the explicit 3-second move and 1-second settle cycle.",
        )
    reward = environment.get("reward", {})
    expected_reward = {
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
        **TRANSITION_REWARD_ADDITIONS,
    }
    if reward != expected_reward:
        raise TrainingError(
            "TRANSITION_REWARD_INVALID",
            "Transition calibration must retain the complete braking reward contract.",
        )
    if {key: reward.get(key) for key in TRANSITION_REWARD_ADDITIONS} != (
        TRANSITION_REWARD_ADDITIONS
    ):
        raise TrainingError(
            "TRANSITION_REWARD_INVALID",
            "Transition calibration must retain the braking and settling reward additions.",
        )
    if (
        environment.get("termination")
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
        or environment.get("commandResampleSteps") != 200
    ):
        raise TrainingError(
            "TRANSITION_TIMING_INVALID",
            "Transition calibration timing and settle sigma are frozen.",
        )
    if profile.get("qualityGates") != TRANSITION_QUALITY_GATES:
        raise TrainingError(
            "TRANSITION_QUALITY_GATES_INVALID",
            "Transition quality gates must remain identical to the failed v1 contract.",
        )
    runtime = profile.get("runtime", {})
    if runtime.get("ccdIterations") != 50:
        raise TrainingError(
            "TRANSITION_CCD_ITERATIONS_INVALID",
            "Transition calibration requires the bounded CCD candidate of 50 iterations.",
        )
    if (
        runtime.get("containerDigest")
        != (runtime.get("containerImage", "").rsplit("@", maxsplit=1)[-1])
    ):
        raise TrainingError(
            "TRANSITION_CONTAINER_BINDING_MISMATCH",
            "Transition containerImage and containerDigest must identify the same OCI image.",
        )
    if runtime.get("packageLockDigest") != base_profile["runtime"]["packageLockDigest"]:
        raise TrainingError(
            "TRANSITION_PACKAGE_LOCK_MISMATCH",
            "Transition calibration must use the base Profile package lock.",
        )
    if profile.get("artifactPolicy") != {
        "checkpoint": "research_only",
        "distribution": "internal_only",
    }:
        raise TrainingError(
            "TRANSITION_ARTIFACT_POLICY_INVALID",
            "Transition outputs must remain internal research artifacts.",
        )


def validate_retention_profile(
    base_profile: dict[str, Any],
    profile: dict[str, Any],
) -> None:
    """Validate the stand-replay and teacher-distillation calibration contract."""

    validate_profile(base_profile)
    if (
        profile.get("profileVersion") != "0.1.0"
        or profile.get("status") != "research"
        or profile.get("stage") != "loaded_track_settle_retention"
    ):
        raise TrainingError(
            "RETENTION_PROFILE_UNSUPPORTED",
            "Retention calibration must use loaded_track_settle_retention v0.1.",
        )
    if profile.get("baseTrainingProfileDigest") != digest_json(base_profile):
        raise TrainingError(
            "RETENTION_BASE_PROFILE_MISMATCH",
            "Retention calibration is not bound to the exact base training Profile.",
        )
    source = profile.get("warmStart", {})
    if (
        source.get("sourceStage") != "loaded-track-settle-transition-v2-failed"
        or source.get("sourceReportDigest") != FAILED_TRANSITION_REPORT_DIGEST
        or source.get("checkpointDigest") != FAILED_TRANSITION_CHECKPOINT_DIGEST
        or source.get("checkpointSizeBytes") != FAILED_TRANSITION_CHECKPOINT_SIZE
    ):
        raise TrainingError(
            "RETENTION_SOURCE_EVIDENCE_MISMATCH",
            "Retention calibration must bind the failed transition report and checkpoint.",
        )
    if source.get("optimizerState") != "reset" or source.get("restore") != {
        "normalizer": True,
        "policy": True,
        "value": True,
    }:
        raise TrainingError(
            "RETENTION_WARM_START_INVALID",
            "Retention calibration must restore normalizer/policy/value and reset optimizer.",
        )
    if source.get("distribution") != "internal_only":
        raise TrainingError(
            "RETENTION_WARM_START_DISTRIBUTION_INVALID",
            "Retention warm-start input must remain internal-only.",
        )
    if profile.get("retentionTeacher") != RETENTION_TEACHER:
        raise TrainingError(
            "RETENTION_TEACHER_INVALID",
            "Retention calibration must bind stand-v2.1 as the read-only teacher.",
        )
    if profile.get("trainingOverrides") != RETENTION_TRAINING_OVERRIDES:
        raise TrainingError(
            "RETENTION_TRAINING_OVERRIDES_INVALID",
            "Retention calibration budget, optimizer, and topology are frozen.",
        )
    environment = profile.get("environment", {})
    if environment.get("commandDistribution") != TRANSITION_COMMAND:
        raise TrainingError(
            "RETENTION_COMMAND_INVALID",
            "Retention calibration must retain the accepted kitchen command range.",
        )
    if environment.get("transitionCurriculum") != RETENTION_CURRICULUM:
        raise TrainingError(
            "RETENTION_CURRICULUM_INVALID",
            "Retention calibration must use 60% transition and 40% stand replay.",
        )
    reward = environment.get("reward", {})
    expected_reward = {
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
        **RETENTION_REWARD_ADDITIONS,
    }
    if reward != expected_reward:
        raise TrainingError(
            "RETENTION_REWARD_INVALID",
            "Retention calibration must retain braking plus teacher distillation rewards.",
        )
    if (
        environment.get("termination")
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
            "standDistillation": 0.05,
        }
        or environment.get("commandResampleSteps") != 200
    ):
        raise TrainingError(
            "RETENTION_TIMING_INVALID",
            "Retention timing, replay cycle, and distillation sigma are frozen.",
        )
    if profile.get("qualityGates") != TRANSITION_QUALITY_GATES:
        raise TrainingError(
            "RETENTION_QUALITY_GATES_INVALID",
            "Retention quality gates must remain identical to the prior contract.",
        )
    runtime = profile.get("runtime", {})
    if runtime.get("ccdIterations") != 50:
        raise TrainingError(
            "RETENTION_CCD_ITERATIONS_INVALID",
            "Retention calibration must retain the passing CCD=50 candidate.",
        )
    if (
        runtime.get("containerDigest")
        != (runtime.get("containerImage", "").rsplit("@", maxsplit=1)[-1])
    ):
        raise TrainingError(
            "RETENTION_CONTAINER_BINDING_MISMATCH",
            "Retention containerImage and containerDigest must identify one OCI image.",
        )
    if runtime.get("packageLockDigest") != base_profile["runtime"]["packageLockDigest"]:
        raise TrainingError(
            "RETENTION_PACKAGE_LOCK_MISMATCH",
            "Retention calibration must use the base Profile package lock.",
        )
    if profile.get("artifactPolicy") != {
        "checkpoint": "research_only",
        "distribution": "internal_only",
    }:
        raise TrainingError(
            "RETENTION_ARTIFACT_POLICY_INVALID",
            "Retention outputs must remain internal research artifacts.",
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


def make_transition_training_profile(
    base_profile: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    validate_transition_profile(base_profile, profile)
    effective = copy.deepcopy(base_profile)
    effective["runtime"]["containerDigest"] = profile["runtime"]["containerDigest"]
    effective["runtime"]["packageLockDigest"] = profile["runtime"]["packageLockDigest"]
    effective["runtime"]["ccdIterations"] = profile["runtime"]["ccdIterations"]
    effective["training"].update(profile["trainingOverrides"])
    effective["training"]["hyperparameterStatus"] = "research_transition_override"
    effective["training"]["commandDistribution"] = copy.deepcopy(
        profile["environment"]["commandDistribution"]
    )
    effective["trainingEnvironment"] = copy.deepcopy(profile["environment"])
    effective["validation"] = copy.deepcopy(profile["qualityGates"])
    return effective


def make_retention_training_profile(
    base_profile: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    validate_retention_profile(base_profile, profile)
    effective = copy.deepcopy(base_profile)
    effective["runtime"]["containerDigest"] = profile["runtime"]["containerDigest"]
    effective["runtime"]["packageLockDigest"] = profile["runtime"]["packageLockDigest"]
    effective["runtime"]["ccdIterations"] = profile["runtime"]["ccdIterations"]
    effective["training"].update(profile["trainingOverrides"])
    effective["training"]["hyperparameterStatus"] = "research_retention_override"
    effective["training"]["commandDistribution"] = copy.deepcopy(
        profile["environment"]["commandDistribution"]
    )
    effective["trainingEnvironment"] = copy.deepcopy(profile["environment"])
    effective["validation"] = copy.deepcopy(profile["qualityGates"])
    return effective


def _load_deterministic_teacher_policy(
    selected_step: Path,
    initialization: dict[str, Any],
    network_factory: Any,
) -> Any:
    """Load a teacher without Brax's null-kernel config deserialization bug."""

    from brax.training.acme import running_statistics
    from brax.training.agents.ppo import checkpoint as ppo_checkpoint
    from brax.training.agents.ppo import networks as ppo_networks

    config = initialization["networkConfig"]
    observation = config["observation_size"]["state"]
    shape = observation["shape"]
    action_size = config["action_size"]
    if (
        not isinstance(shape, list)
        or len(shape) != 1
        or not isinstance(shape[0], int)
        or shape[0] <= 0
        or not isinstance(action_size, int)
        or action_size <= 0
    ):
        raise TrainingError(
            "RETENTION_TEACHER_NETWORK_CONFIG_INVALID",
            "Teacher checkpoint has an invalid observation or action ABI.",
        )
    teacher_network = network_factory(
        {"state": shape[0]},
        action_size,
        preprocess_observations_fn=running_statistics.normalize,
    )
    teacher_params = ppo_checkpoint.load(selected_step)
    return ppo_networks.make_inference_fn(teacher_network)(
        teacher_params,
        deterministic=True,
    )


def run_midterm_calibration(
    base_profile: dict[str, Any],
    profile: dict[str, Any],
    bundle_dir: Path,
    model_dir: Path,
    output_dir: Path,
    warm_start_archive: Path,
    retention_teacher_archive: Path | None = None,
) -> dict[str, Any]:
    """Warm-start, train, evaluate, and retain a midterm checkpoint."""

    import numpy as np
    from brax.training.agents.ppo import networks as ppo_networks
    from brax.training.agents.ppo import train as ppo
    from mujoco_playground import wrapper

    if profile.get("stage") == "loaded_track_settle_transition":
        effective = make_transition_training_profile(base_profile, profile)
    elif profile.get("stage") == "loaded_track_settle_retention":
        effective = make_retention_training_profile(base_profile, profile)
        if retention_teacher_archive is None:
            raise TrainingError(
                "RETENTION_TEACHER_ARCHIVE_MISSING",
                "Retention calibration requires the stand-v2.1 teacher archive.",
            )
    else:
        effective = make_midterm_training_profile(base_profile, profile)
    static = static_preflight(base_profile, bundle_dir)
    training_model, derivation = prepare_training_model(base_profile, bundle_dir, model_dir)
    runtime = runtime_preflight(effective, training_model)
    from .environment import make_environment

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
    teacher_initialization: dict[str, Any] | None = None
    with tempfile.TemporaryDirectory(prefix="worldspec-h1-warm-start-") as temporary:
        selected_step, initialization = materialize_warm_start(
            warm_start_archive,
            Path(temporary) / "checkpoint",
            profile["warmStart"]["checkpointDigest"],
            profile["warmStart"]["checkpointSizeBytes"],
        )
        teacher_policy = None
        if retention_teacher_archive is not None:
            teacher_spec = profile["retentionTeacher"]
            teacher_step, teacher_initialization = materialize_warm_start(
                retention_teacher_archive,
                Path(temporary) / "stand-teacher",
                teacher_spec["checkpointDigest"],
                teacher_spec["checkpointSizeBytes"],
            )
            teacher_policy = _load_deterministic_teacher_policy(
                teacher_step,
                teacher_initialization,
                network_factory,
            )
            teacher_initialization = {
                **teacher_initialization,
                "mode": teacher_spec["mode"],
                "scope": teacher_spec["scope"],
            }
        environment = make_environment(
            effective,
            training_model,
            stand_teacher_policy=teacher_policy,
        )
        observation_size = _flat_observation_size(environment.observation_size["state"])
        action_size = int(environment.action_size)
        validate_network_compatibility(initialization, observation_size, action_size)
        if teacher_initialization is not None:
            validate_network_compatibility(
                teacher_initialization,
                observation_size,
                action_size,
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
    tests_gate = len(tests) == expected_tests and all(item["result"] == "pass" for item in tests)
    episode_gate = (
        float(final_mean_episode_length) >= profile["qualityGates"]["minimumFinalMeanEpisodeLength"]
    )
    quality_passed = tests_gate and episode_gate
    result = {
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
    if teacher_initialization is not None:
        result["retentionTeacher"] = teacher_initialization
    return result
