"""Loaded H1+Robotiq walk/settle curriculum calibration."""

from __future__ import annotations

import copy
import functools
import shutil
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
FAILED_RETENTION_REPORT_DIGEST = (
    "sha256:e232bed2b23400871fbe406ec8bf89463e19c293693616370febc2bc78cc7397"
)
FAILED_RETENTION_CHECKPOINT_DIGEST = (
    "sha256:59697ea50339fa9ad17b9131c3369b761e0ff8345cf649be76549294472a4b8b"
)
FAILED_RETENTION_CHECKPOINT_SIZE = 6_327_077
CAPTURE_REPORT_DIGEST = "sha256:8261f863d71cb66de46facb37b3c5ed121811e80fdabac057629ed366a52666f"
CAPTURE_CHECKPOINT_DIGEST = (
    "sha256:7f8c45e7c0bf1d485706ca694c44e74bfd351ab4f753bfacff947e9f7e75cfbe"
)
CAPTURE_CHECKPOINT_SIZE = 6_280_278
FAILED_TASK_LOAD_RETENTION_REPORT_DIGEST = (
    "sha256:9bce23e1c4bf26edff4db38c862e7da1b84b749d046bc7cbb480328cdaac38a0"
)
FAILED_TASK_LOAD_RETENTION_REPORT_SIZE = 30_761
FAILED_TASK_LOAD_RETENTION_CHECKPOINT_DIGEST = (
    "sha256:c5360ff126c3eb716710f43f615ee7f1be7604c36af95c4fd07e9f9048b7e15b"
)
FAILED_TASK_LOAD_RETENTION_CHECKPOINT_SIZE = 1_258_786

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

A5CK_FAILURE_EVIDENCE = {
    "job": "worldspec-h1-midterm-5nn2q",
    "controlProfileDigest": (
        "sha256:23fcf6908136c57880871ac0a1f9e1f13339b5d8f562eb0af8d710362f75efa8"
    ),
    "reportDigest": "sha256:a9d4458eb2ed16186c73e41dbdb16e1753e35ee32e30b0407eae981931f0256b",
    "controllerDigest": ("sha256:0f1ffed386123d21cb45eb5708c2ed849cd22f7244e7a9ceb05a6df1bae8f0db"),
    "traceDigest": "sha256:175427d1d3d74da7fe5c422f3290f07ae6dfa6c21179626dd4d4558915012bd9",
    "traceRecordCount": 386,
    "terminalReason": "fall_height",
    "maximumForwardCommand": 0.5,
    "maximumBackwardVelocity": -2.459172010421753,
    "formalControlGate": "failed",
}

TASK_LOAD_TRAINING_OVERRIDES = {
    "numTimesteps": 16_777_216,
    "numEnvs": 4096,
    "numEvals": 8,
    "episodeLength": 1000,
    "unrollLength": 20,
    "numMinibatches": 16,
    "numUpdatesPerBatch": 4,
    "batchSize": 256,
}

TASK_LOAD_CURRICULUM = {
    "mode": "static_right_arm_pose_and_base_disturbance",
    "sourceJob": "worldspec-h1-midterm-5nn2q",
    "sourceTraceDigest": (
        "sha256:175427d1d3d74da7fe5c422f3290f07ae6dfa6c21179626dd4d4558915012bd9"
    ),
    "heldTargetScale": [0.5, 1.0],
    "initialBaseVelocityX": [-0.1, 0.1],
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
}

TASK_LOAD_RETENTION_TRAINING_OVERRIDES = {
    "numTimesteps": 16_777_216,
    "numEnvs": 4096,
    "numEvals": 8,
    "episodeLength": 1000,
    "unrollLength": 20,
    "numMinibatches": 16,
    "numUpdatesPerBatch": 4,
    "batchSize": 256,
    "learningRate": 0.00005,
    "entropyCost": 0.001,
}
TASK_LOAD_RETENTION_CURRICULUM = {
    "mode": "move_then_zero_with_stand_replay",
    "transitionCycleProbability": 0.75,
    "standReplayProbability": 0.25,
    "moveSteps": 150,
    "settleSteps": 50,
    "motionCommandDistribution": {
        "linearVelocityX": [0.4, 0.6],
        "linearVelocityY": [-0.05, 0.05],
        "angularVelocityYaw": [-0.1, 0.1],
    },
}
TASK_LOAD_RETENTION_LOAD = {
    **TASK_LOAD_CURRICULUM,
    "mode": "static_right_arm_pose",
    "heldTargetScale": [1.0, 1.0],
    "initialBaseVelocityX": [0.0, 0.0],
}
TASK_LOAD_RETENTION_REWARD_ADDITIONS = {
    "settleLinear": 16.0,
    "settleYaw": 6.0,
    "settleActionRateScale": 0.15,
    "standDistillation": 4.0,
    "settleDistillation": 4.0,
}
TASK_LOAD_RETENTION_STAND_TEACHER = {
    **RETENTION_TEACHER,
}
TASK_LOAD_RETENTION_SETTLE_TEACHER = {
    "sourceStage": "loaded-track-settle-capture-v1-passed",
    "sourceReportDigest": CAPTURE_REPORT_DIGEST,
    "checkpointDigest": CAPTURE_CHECKPOINT_DIGEST,
    "checkpointSizeBytes": CAPTURE_CHECKPOINT_SIZE,
    "distribution": "internal_only",
    "mode": "deterministic_action_distillation",
    "scope": "transition_settle_only",
}
TASK_LOAD_SURVIVAL_PRIOR_ATTEMPT = {
    "sourceStage": "loaded-track-settle-task-load-retention-v2-failed",
    "sourceReportDigest": FAILED_TASK_LOAD_RETENTION_REPORT_DIGEST,
    "sourceReportSizeBytes": FAILED_TASK_LOAD_RETENTION_REPORT_SIZE,
    "checkpointDigest": FAILED_TASK_LOAD_RETENTION_CHECKPOINT_DIGEST,
    "checkpointSizeBytes": FAILED_TASK_LOAD_RETENTION_CHECKPOINT_SIZE,
    "formalTrainingGate": "failed",
    "distribution": "internal_only",
}
FAILED_TASK_LOAD_SURVIVAL_REPORT_DIGEST = (
    "sha256:5b9b40a316e8cdb6d7f0119a6d5a2459f2036f27adcc3f5e917069bd7f259425"
)
FAILED_TASK_LOAD_SURVIVAL_REPORT_SIZE = 31_438
FAILED_TASK_LOAD_SURVIVAL_CHECKPOINT_DIGEST = (
    "sha256:c8487802fd06f08e2a08fce03e505cee31ec420c50a21559f601327392aab201"
)
FAILED_TASK_LOAD_SURVIVAL_CHECKPOINT_SIZE = 1_269_304
FAILED_TASK_LOAD_DEPLOYMENT_EVAL_REPORT_DIGEST = (
    "sha256:4a6d63e3bf7e1708e9289335aaf922b6911728100d103412e0d7f0404645bd2f"
)
FAILED_TASK_LOAD_DEPLOYMENT_EVAL_REPORT_SIZE = 31_753
FAILED_TASK_LOAD_DEPLOYMENT_EVAL_CHECKPOINT_DIGEST = (
    "sha256:93debf9cb817e35148dda6079bfdb6f7d5464f0259164c42bd071467ff7067d6"
)
FAILED_TASK_LOAD_DEPLOYMENT_EVAL_CHECKPOINT_SIZE = 1_259_611
TASK_LOAD_DEPLOYMENT_EVAL_PRIOR_ATTEMPT = {
    "sourceStage": "loaded-track-settle-task-load-survival-v3-failed",
    "sourceReportDigest": FAILED_TASK_LOAD_SURVIVAL_REPORT_DIGEST,
    "sourceReportSizeBytes": FAILED_TASK_LOAD_SURVIVAL_REPORT_SIZE,
    "checkpointDigest": FAILED_TASK_LOAD_SURVIVAL_CHECKPOINT_DIGEST,
    "checkpointSizeBytes": FAILED_TASK_LOAD_SURVIVAL_CHECKPOINT_SIZE,
    "formalTrainingGate": "failed",
    "distribution": "internal_only",
}
TASK_LOAD_HORIZON_PRIOR_ATTEMPT = {
    "sourceStage": "loaded-track-settle-task-load-deployment-eval-v4-failed",
    "sourceReportDigest": FAILED_TASK_LOAD_DEPLOYMENT_EVAL_REPORT_DIGEST,
    "sourceReportSizeBytes": FAILED_TASK_LOAD_DEPLOYMENT_EVAL_REPORT_SIZE,
    "checkpointDigest": FAILED_TASK_LOAD_DEPLOYMENT_EVAL_CHECKPOINT_DIGEST,
    "checkpointSizeBytes": FAILED_TASK_LOAD_DEPLOYMENT_EVAL_CHECKPOINT_SIZE,
    "formalTrainingGate": "failed",
    "distribution": "internal_only",
}
PASSED_TASK_LOAD_HORIZON_REPORT_DIGEST = (
    "sha256:33ab736bf9fab3eece7491628352ebc3f143dc0dba334c0cd693b34a5dcbedb7"
)
PASSED_TASK_LOAD_HORIZON_REPORT_SIZE = 31_625
PASSED_TASK_LOAD_HORIZON_CHECKPOINT_DIGEST = (
    "sha256:d5ddb461d27366e6959c22dac928d81ab0039b55030427c80e9ab6ffb09b1943"
)
PASSED_TASK_LOAD_HORIZON_CHECKPOINT_SIZE = 1_259_927
TASK_LOAD_FORMAL_PRIOR_ATTEMPT = {
    "sourceStage": "loaded-track-settle-task-load-horizon-v5-passed",
    "sourceReportDigest": PASSED_TASK_LOAD_HORIZON_REPORT_DIGEST,
    "sourceReportSizeBytes": PASSED_TASK_LOAD_HORIZON_REPORT_SIZE,
    "checkpointDigest": PASSED_TASK_LOAD_HORIZON_CHECKPOINT_DIGEST,
    "checkpointSizeBytes": PASSED_TASK_LOAD_HORIZON_CHECKPOINT_SIZE,
    "formalTrainingGate": "passed",
    "distribution": "internal_only",
}
TASK_LOAD_SURVIVAL_TRAINING_OVERRIDES = {
    **TASK_LOAD_RETENTION_TRAINING_OVERRIDES,
    "learningRate": 0.00002,
    "entropyCost": 0.0005,
}
TASK_LOAD_DEPLOYMENT_EVAL_TRAINING_OVERRIDES = {
    **TASK_LOAD_SURVIVAL_TRAINING_OVERRIDES,
    "deterministicEval": True,
}
TASK_LOAD_HORIZON_TRAINING_OVERRIDES = {
    **TASK_LOAD_DEPLOYMENT_EVAL_TRAINING_OVERRIDES,
    "discounting": 0.995,
    "gaeLambda": 0.99,
    "learningRate": 0.00001,
    "entropyCost": 0.0002,
    "clippingEpsilon": 0.2,
    "desiredKl": 0.01,
    "learningRateSchedule": "ADAPTIVE_KL",
    "learningRateScheduleMin": 0.0000025,
    "learningRateScheduleMax": 0.00001,
    "normalizeUntilCount": 1,
}
TASK_LOAD_FORMAL_TRAINING_OVERRIDES = {
    **TASK_LOAD_HORIZON_TRAINING_OVERRIDES,
    "numTimesteps": 100_000_000,
    "numEnvs": 8192,
    "numEvals": 10,
    "numMinibatches": 32,
}
TASK_LOAD_FORMAL_COMMAND = {
    "linearVelocityX": [0.0, 0.8],
    "linearVelocityY": [-0.15, 0.15],
    "angularVelocityYaw": [-0.35, 0.35],
    "zeroCommandProbability": 0.2,
}
TASK_LOAD_SURVIVAL_REWARD_ADDITIONS = {
    **TASK_LOAD_RETENTION_REWARD_ADDITIONS,
    "standTeacherActionCost": 1.0,
    "settleTeacherActionCost": 1.0,
    "terminationPenalty": 25.0,
}
TASK_LOAD_HORIZON_REWARD_ADDITIONS = {
    **TASK_LOAD_SURVIVAL_REWARD_ADDITIONS,
    "terminationPenalty": 100.0,
}
TASK_LOAD_SURVIVAL_QUALITY_GATES = {
    **TRANSITION_QUALITY_GATES,
    "settleMeasurementWindowSeconds": 0.2,
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


def validate_task_load_profile(
    base_profile: dict[str, Any],
    profile: dict[str, Any],
) -> None:
    """Validate the task-load-aware lower-body calibration contract."""

    validate_profile(base_profile)
    if (
        profile.get("profileVersion") != "0.1.0"
        or profile.get("status") != "research"
        or profile.get("stage") != "loaded_track_settle_task_load"
    ):
        raise TrainingError(
            "TASK_LOAD_PROFILE_UNSUPPORTED",
            "Task-load calibration must use loaded_track_settle_task_load v0.1.",
        )
    if profile.get("baseTrainingProfileDigest") != digest_json(base_profile):
        raise TrainingError(
            "TASK_LOAD_BASE_PROFILE_MISMATCH",
            "Task-load calibration is not bound to the exact base training Profile.",
        )
    if profile.get("a5ckEvidence") != A5CK_FAILURE_EVIDENCE:
        raise TrainingError(
            "TASK_LOAD_FAILURE_EVIDENCE_MISMATCH",
            "Task-load calibration must bind the archived A5-CK in-domain recovery failure.",
        )
    source = profile.get("warmStart", {})
    if (
        source.get("sourceStage") != "loaded-track-settle-transition-v2-failed"
        or source.get("sourceReportDigest") != FAILED_TRANSITION_REPORT_DIGEST
        or source.get("checkpointDigest") != FAILED_TRANSITION_CHECKPOINT_DIGEST
        or source.get("checkpointSizeBytes") != FAILED_TRANSITION_CHECKPOINT_SIZE
    ):
        raise TrainingError(
            "TASK_LOAD_WARM_START_EVIDENCE_MISMATCH",
            "Task-load calibration must warm-start from the frozen transition-v2 policy.",
        )
    if source.get("optimizerState") != "reset" or source.get("restore") != {
        "normalizer": True,
        "policy": True,
        "value": True,
    }:
        raise TrainingError(
            "TASK_LOAD_WARM_START_INVALID",
            "Task-load calibration must restore normalizer/policy/value and reset optimizer.",
        )
    if source.get("distribution") != "internal_only":
        raise TrainingError(
            "TASK_LOAD_WARM_START_DISTRIBUTION_INVALID",
            "Task-load warm-start input must remain internal-only.",
        )
    if profile.get("trainingOverrides") != TASK_LOAD_TRAINING_OVERRIDES:
        raise TrainingError(
            "TASK_LOAD_TRAINING_OVERRIDES_INVALID",
            "Task-load calibration budget and topology are frozen.",
        )
    environment = profile.get("environment", {})
    if environment.get("commandDistribution") != TRANSITION_COMMAND:
        raise TrainingError(
            "TASK_LOAD_COMMAND_INVALID",
            "Task-load calibration must preserve the kitchen command range.",
        )
    if environment.get("transitionCurriculum") != TRANSITION_CURRICULUM:
        raise TrainingError(
            "TASK_LOAD_TRANSITION_CURRICULUM_INVALID",
            "Task-load calibration must preserve the move-to-zero curriculum.",
        )
    if environment.get("taskLoadCurriculum") != TASK_LOAD_CURRICULUM:
        raise TrainingError(
            "TASK_LOAD_CURRICULUM_INVALID",
            "Task-load calibration must use the frozen A5-CK arm-load curriculum.",
        )
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
    if environment.get("reward") != expected_reward:
        raise TrainingError(
            "TASK_LOAD_REWARD_INVALID",
            "Task-load calibration must preserve the transition reward contract.",
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
            "TASK_LOAD_TIMING_INVALID",
            "Task-load timing, termination, and reward targets are frozen.",
        )
    if profile.get("qualityGates") != TRANSITION_QUALITY_GATES:
        raise TrainingError(
            "TASK_LOAD_QUALITY_GATES_INVALID",
            "Task-load calibration must preserve the existing quality gates.",
        )
    runtime = profile.get("runtime", {})
    if runtime.get("ccdIterations") != 50:
        raise TrainingError(
            "TASK_LOAD_CCD_ITERATIONS_INVALID",
            "Task-load calibration requires CCD=50.",
        )
    if (
        runtime.get("containerDigest")
        != (runtime.get("containerImage", "").rsplit("@", maxsplit=1)[-1])
    ):
        raise TrainingError(
            "TASK_LOAD_CONTAINER_BINDING_MISMATCH",
            "Task-load containerImage and containerDigest must identify one OCI image.",
        )
    if runtime.get("packageLockDigest") != base_profile["runtime"]["packageLockDigest"]:
        raise TrainingError(
            "TASK_LOAD_PACKAGE_LOCK_MISMATCH",
            "Task-load calibration must use the base Profile package lock.",
        )
    if profile.get("artifactPolicy") != {
        "checkpoint": "research_only",
        "distribution": "internal_only",
    }:
        raise TrainingError(
            "TASK_LOAD_ARTIFACT_POLICY_INVALID",
            "Task-load outputs must remain internal research artifacts.",
        )


def validate_task_load_retention_profile(
    base_profile: dict[str, Any],
    profile: dict[str, Any],
) -> None:
    """Validate full arm-load training with stand and settle retention teachers."""

    validate_profile(base_profile)
    stage = profile.get("stage")
    survival_stage = stage == "loaded_track_settle_task_load_survival"
    deployment_eval_stage = stage == "loaded_track_settle_task_load_deployment_eval"
    horizon_stage = stage == "loaded_track_settle_task_load_horizon"
    formal_stage = stage == "loaded_track_settle_task_load_formal"
    if (
        profile.get("profileVersion") != "0.1.0"
        or profile.get("status") != "research"
        or stage
        not in {
            "loaded_track_settle_task_load_retention",
            "loaded_track_settle_task_load_survival",
            "loaded_track_settle_task_load_deployment_eval",
            "loaded_track_settle_task_load_horizon",
            "loaded_track_settle_task_load_formal",
        }
    ):
        raise TrainingError(
            "TASK_LOAD_RETENTION_PROFILE_UNSUPPORTED",
            "Task-load retention/survival/deployment evaluation must use an accepted v0.1 stage.",
        )
    if profile.get("baseTrainingProfileDigest") != digest_json(base_profile):
        raise TrainingError(
            "TASK_LOAD_RETENTION_BASE_PROFILE_MISMATCH",
            "Task-load retention is not bound to the exact base training Profile.",
        )
    if profile.get("a5ckEvidence") != A5CK_FAILURE_EVIDENCE:
        raise TrainingError(
            "TASK_LOAD_RETENTION_FAILURE_EVIDENCE_MISMATCH",
            "Task-load retention must preserve the archived A5-CK failure lineage.",
        )
    if survival_stage:
        if profile.get("priorAttempt") != TASK_LOAD_SURVIVAL_PRIOR_ATTEMPT:
            raise TrainingError(
                "TASK_LOAD_SURVIVAL_PRIOR_ATTEMPT_MISMATCH",
                "Task-load survival must bind the frozen failed retention attempt.",
            )
    elif deployment_eval_stage:
        if profile.get("priorAttempt") != TASK_LOAD_DEPLOYMENT_EVAL_PRIOR_ATTEMPT:
            raise TrainingError(
                "TASK_LOAD_DEPLOYMENT_EVAL_PRIOR_ATTEMPT_MISMATCH",
                "Task-load deployment evaluation must bind the frozen failed survival attempt.",
            )
    elif horizon_stage:
        if profile.get("priorAttempt") != TASK_LOAD_HORIZON_PRIOR_ATTEMPT:
            raise TrainingError(
                "TASK_LOAD_HORIZON_PRIOR_ATTEMPT_MISMATCH",
                "Task-load horizon calibration must bind the frozen failed deployment evaluation.",
            )
    elif formal_stage:
        if profile.get("priorAttempt") != TASK_LOAD_FORMAL_PRIOR_ATTEMPT:
            raise TrainingError(
                "TASK_LOAD_FORMAL_PRIOR_ATTEMPT_MISMATCH",
                "Formal task-load training must bind the passing horizon evidence.",
            )
    elif "priorAttempt" in profile:
        raise TrainingError(
            "TASK_LOAD_RETENTION_PRIOR_ATTEMPT_FORBIDDEN",
            "The historical retention v2 Profile cannot acquire later evidence.",
        )
    source = profile.get("warmStart", {})
    expected_source = (
        {
            "sourceStage": "loaded-track-settle-task-load-horizon-v5-passed",
            "sourceReportDigest": PASSED_TASK_LOAD_HORIZON_REPORT_DIGEST,
            "checkpointDigest": PASSED_TASK_LOAD_HORIZON_CHECKPOINT_DIGEST,
            "checkpointSizeBytes": PASSED_TASK_LOAD_HORIZON_CHECKPOINT_SIZE,
        }
        if formal_stage
        else (
        {
            "sourceStage": "loaded-track-settle-task-load-deployment-eval-v4-failed",
            "sourceReportDigest": FAILED_TASK_LOAD_DEPLOYMENT_EVAL_REPORT_DIGEST,
            "checkpointDigest": FAILED_TASK_LOAD_DEPLOYMENT_EVAL_CHECKPOINT_DIGEST,
            "checkpointSizeBytes": FAILED_TASK_LOAD_DEPLOYMENT_EVAL_CHECKPOINT_SIZE,
        }
        if horizon_stage
        else (
            {
                "sourceStage": "loaded-track-settle-task-load-survival-v3-failed",
                "sourceReportDigest": FAILED_TASK_LOAD_SURVIVAL_REPORT_DIGEST,
                "checkpointDigest": FAILED_TASK_LOAD_SURVIVAL_CHECKPOINT_DIGEST,
                "checkpointSizeBytes": FAILED_TASK_LOAD_SURVIVAL_CHECKPOINT_SIZE,
            }
            if deployment_eval_stage
            else {
                "sourceStage": "loaded-track-settle-retention-v3-failed",
                "sourceReportDigest": FAILED_RETENTION_REPORT_DIGEST,
                "checkpointDigest": FAILED_RETENTION_CHECKPOINT_DIGEST,
                "checkpointSizeBytes": FAILED_RETENTION_CHECKPOINT_SIZE,
            }
        ))
    )
    if any(source.get(key) != value for key, value in expected_source.items()):
        raise TrainingError(
            "TASK_LOAD_RETENTION_WARM_START_EVIDENCE_MISMATCH",
            "Task-load calibration must warm-start from its frozen predecessor evidence.",
        )
    if source.get("optimizerState") != "reset" or source.get("restore") != {
        "normalizer": True,
        "policy": True,
        "value": True,
    }:
        raise TrainingError(
            "TASK_LOAD_RETENTION_WARM_START_INVALID",
            "Task-load retention must restore normalizer/policy/value and reset optimizer.",
        )
    if source.get("distribution") != "internal_only":
        raise TrainingError(
            "TASK_LOAD_RETENTION_WARM_START_DISTRIBUTION_INVALID",
            "Task-load retention warm-start input must remain internal-only.",
        )
    if profile.get("standTeacher") != TASK_LOAD_RETENTION_STAND_TEACHER:
        raise TrainingError(
            "TASK_LOAD_RETENTION_STAND_TEACHER_INVALID",
            "Task-load retention must bind stand-v2.1 as the stand teacher.",
        )
    if profile.get("settleTeacher") != TASK_LOAD_RETENTION_SETTLE_TEACHER:
        raise TrainingError(
            "TASK_LOAD_RETENTION_SETTLE_TEACHER_INVALID",
            "Task-load retention must bind the passing capture policy as settle teacher.",
        )
    expected_training = (
        TASK_LOAD_FORMAL_TRAINING_OVERRIDES
        if formal_stage
        else (
            TASK_LOAD_HORIZON_TRAINING_OVERRIDES
            if horizon_stage
            else (
            TASK_LOAD_DEPLOYMENT_EVAL_TRAINING_OVERRIDES
            if deployment_eval_stage
            else (
                TASK_LOAD_SURVIVAL_TRAINING_OVERRIDES
                if survival_stage
                else TASK_LOAD_RETENTION_TRAINING_OVERRIDES
            )
        ))
    )
    if profile.get("trainingOverrides") != expected_training:
        raise TrainingError(
            "TASK_LOAD_RETENTION_TRAINING_OVERRIDES_INVALID",
            "Task-load retention budget, optimizer, and topology are frozen.",
        )
    expected_checkpoint_selection = {
        "mode": "deterministic_gate_rank_v1",
        "evaluateAllSavedCheckpoints": True,
        "packageSelectedOnly": True,
    }
    if deployment_eval_stage or horizon_stage or formal_stage:
        expected_checkpoint_selection["includeWarmStart"] = True
    if profile.get("checkpointSelection") != expected_checkpoint_selection:
        raise TrainingError(
            "TASK_LOAD_RETENTION_SELECTION_INVALID",
            "Task-load retention must evaluate every saved checkpoint and package one.",
        )
    environment = profile.get("environment", {})
    expected_command = TASK_LOAD_FORMAL_COMMAND if formal_stage else TRANSITION_COMMAND
    if environment.get("commandDistribution") != expected_command:
        raise TrainingError(
            "TASK_LOAD_RETENTION_COMMAND_INVALID",
            "Task-load retention must preserve the kitchen command range.",
        )
    if environment.get("transitionCurriculum") != TASK_LOAD_RETENTION_CURRICULUM:
        raise TrainingError(
            "TASK_LOAD_RETENTION_CURRICULUM_INVALID",
            "Task-load retention must use 75% transition and 25% stand replay.",
        )
    if environment.get("taskLoadCurriculum") != TASK_LOAD_RETENTION_LOAD:
        raise TrainingError(
            "TASK_LOAD_RETENTION_LOAD_INVALID",
            "Task-load retention must train and evaluate the full A5-CK right-arm load.",
        )
    expected_reward_additions = (
        TASK_LOAD_HORIZON_REWARD_ADDITIONS
        if horizon_stage or formal_stage
        else (
            TASK_LOAD_SURVIVAL_REWARD_ADDITIONS
            if survival_stage or deployment_eval_stage
            else TASK_LOAD_RETENTION_REWARD_ADDITIONS
        )
    )
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
        **expected_reward_additions,
    }
    if environment.get("reward") != expected_reward:
        raise TrainingError(
            "TASK_LOAD_RETENTION_REWARD_INVALID",
            "Task-load retention must preserve the dual-teacher braking reward.",
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
            "settleDistillation": 0.05,
        }
        or environment.get("commandResampleSteps") != 200
    ):
        raise TrainingError(
            "TASK_LOAD_RETENTION_TIMING_INVALID",
            "Task-load retention timing, termination, and distillation sigmas are frozen.",
        )
    expected_quality_gates = (
        TASK_LOAD_SURVIVAL_QUALITY_GATES
        if survival_stage or deployment_eval_stage or horizon_stage or formal_stage
        else TRANSITION_QUALITY_GATES
    )
    if profile.get("qualityGates") != expected_quality_gates:
        raise TrainingError(
            "TASK_LOAD_RETENTION_QUALITY_GATES_INVALID",
            "Task-load retention cannot relax the accepted quality gates.",
        )
    runtime = profile.get("runtime", {})
    if runtime.get("ccdIterations") != 50:
        raise TrainingError(
            "TASK_LOAD_RETENTION_CCD_ITERATIONS_INVALID",
            "Task-load retention requires CCD=50.",
        )
    if (
        runtime.get("containerDigest")
        != (runtime.get("containerImage", "").rsplit("@", maxsplit=1)[-1])
    ):
        raise TrainingError(
            "TASK_LOAD_RETENTION_CONTAINER_BINDING_MISMATCH",
            "Task-load retention containerImage and containerDigest must match.",
        )
    if runtime.get("packageLockDigest") != base_profile["runtime"]["packageLockDigest"]:
        raise TrainingError(
            "TASK_LOAD_RETENTION_PACKAGE_LOCK_MISMATCH",
            "Task-load retention must use the base Profile package lock.",
        )
    expected_artifact_policy = {
        "checkpoint": (
            "policy_candidate_if_passed" if formal_stage else "research_only"
        ),
        "distribution": "internal_only",
    }
    if profile.get("artifactPolicy") != expected_artifact_policy:
        raise TrainingError(
            "TASK_LOAD_RETENTION_ARTIFACT_POLICY_INVALID",
            "Task-load retention outputs must remain internal research artifacts.",
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


def make_task_load_training_profile(
    base_profile: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    validate_task_load_profile(base_profile, profile)
    effective = copy.deepcopy(base_profile)
    effective["runtime"]["containerDigest"] = profile["runtime"]["containerDigest"]
    effective["runtime"]["packageLockDigest"] = profile["runtime"]["packageLockDigest"]
    effective["runtime"]["ccdIterations"] = profile["runtime"]["ccdIterations"]
    effective["training"].update(profile["trainingOverrides"])
    effective["training"]["hyperparameterStatus"] = "research_task_load_override"
    effective["training"]["commandDistribution"] = copy.deepcopy(
        profile["environment"]["commandDistribution"]
    )
    effective["trainingEnvironment"] = copy.deepcopy(profile["environment"])
    effective["validation"] = copy.deepcopy(profile["qualityGates"])
    return effective


def make_task_load_retention_training_profile(
    base_profile: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    """Build the full-load, dual-teacher effective training Profile."""

    validate_task_load_retention_profile(base_profile, profile)
    effective = copy.deepcopy(base_profile)
    effective["runtime"]["containerDigest"] = profile["runtime"]["containerDigest"]
    effective["runtime"]["packageLockDigest"] = profile["runtime"]["packageLockDigest"]
    effective["runtime"]["ccdIterations"] = profile["runtime"]["ccdIterations"]
    effective["training"].update(profile["trainingOverrides"])
    effective["training"]["hyperparameterStatus"] = (
        "formal_task_load_override"
        if profile["stage"] == "loaded_track_settle_task_load_formal"
        else (
            "research_task_load_horizon_override"
            if profile["stage"] == "loaded_track_settle_task_load_horizon"
            else (
            "research_task_load_deployment_eval_override"
            if profile["stage"] == "loaded_track_settle_task_load_deployment_eval"
            else (
                "research_task_load_survival_override"
                if profile["stage"] == "loaded_track_settle_task_load_survival"
                else "research_task_load_retention_override"
            )
        ))
    )
    effective["training"]["commandDistribution"] = copy.deepcopy(
        profile["environment"]["commandDistribution"]
    )
    effective["trainingEnvironment"] = copy.deepcopy(profile["environment"])
    effective["validation"] = copy.deepcopy(profile["qualityGates"])
    return effective


def assess_checkpoint_candidate(
    step: int,
    mean_episode_length: float,
    tests: list[dict[str, Any]],
    gates: dict[str, Any],
) -> dict[str, Any]:
    """Score one saved checkpoint without weakening any formal gate."""

    passed_tests = sum(item.get("result") == "pass" for item in tests)
    expected_tests = gates["requiredConsecutivePasses"] * 2
    deterministic_gate = len(tests) == expected_tests and passed_tests == expected_tests
    episode_gate = mean_episode_length >= gates["minimumFinalMeanEpisodeLength"]
    violation = 0.0
    for item in tests:
        metrics = item["metrics"]
        if metrics["doneSeen"]:
            violation += 10.0
        violation += 10.0 * float(metrics["nonFiniteSamples"])
        violation += max(
            0.0,
            (gates["minimumBaseHeight"] - metrics["minimumBaseHeight"])
            / gates["minimumBaseHeight"],
        )
        violation += max(
            0.0,
            (gates["minimumUprightCosine"] - metrics["minimumUprightCosine"])
            / gates["minimumUprightCosine"],
        )
        if item["suite"] == "walk_settle":
            violation += max(
                0.0,
                (gates["minimumForwardDisplacement"] - metrics["forwardDisplacement"])
                / gates["minimumForwardDisplacement"],
            )
            violation += max(
                0.0,
                (metrics["forwardDisplacement"] - gates["maximumForwardDisplacement"])
                / gates["maximumForwardDisplacement"],
            )
            violation += max(
                0.0,
                (metrics["lateralDrift"] - gates["maximumLateralDrift"])
                / gates["maximumLateralDrift"],
            )
            violation += max(
                0.0,
                (metrics["trackingRmse"] - gates["maximumTrackingRmse"])
                / gates["maximumTrackingRmse"],
            )
            violation += max(
                0.0,
                (metrics["maximumSettleLinearSpeed"] - gates["maximumSettleLinearSpeed"])
                / gates["maximumSettleLinearSpeed"],
            )
            violation += max(
                0.0,
                (metrics["maximumSettleAngularSpeed"] - gates["maximumSettleAngularSpeed"])
                / gates["maximumSettleAngularSpeed"],
            )
        else:
            violation += max(
                0.0,
                (metrics["maximumPlanarDrift"] - gates["maximumStandPlanarDrift"])
                / gates["maximumStandPlanarDrift"],
            )
    return {
        "step": int(step),
        "meanEpisodeLength": float(mean_episode_length),
        "meanEpisodeLengthGate": episode_gate,
        "deterministicSuiteGate": deterministic_gate,
        "passedTestCount": passed_tests,
        "expectedTestCount": expected_tests,
        "normalizedViolationScore": float(violation),
        "formalGate": episode_gate and deterministic_gate,
    }


def select_checkpoint_candidate(
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Choose the strongest candidate with a deterministic, fail-closed rank."""

    if not candidates:
        raise TrainingError(
            "MIDTERM_CHECKPOINT_CANDIDATES_MISSING",
            "PPO did not produce any checkpoint candidate.",
        )
    return max(
        candidates,
        key=lambda item: (
            bool(item["formalGate"]),
            int(item["passedTestCount"]),
            bool(item["meanEpisodeLengthGate"]),
            -float(item["normalizedViolationScore"]),
            float(item["meanEpisodeLength"]),
            -int(item["step"]),
        ),
    )


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
    settle_teacher_archive: Path | None = None,
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
    elif profile.get("stage") == "loaded_track_settle_task_load":
        effective = make_task_load_training_profile(base_profile, profile)
    elif profile.get("stage") in {
        "loaded_track_settle_task_load_retention",
        "loaded_track_settle_task_load_survival",
        "loaded_track_settle_task_load_deployment_eval",
        "loaded_track_settle_task_load_horizon",
        "loaded_track_settle_task_load_formal",
    }:
        effective = make_task_load_retention_training_profile(base_profile, profile)
        if retention_teacher_archive is None or settle_teacher_archive is None:
            raise TrainingError(
                "TASK_LOAD_RETENTION_TEACHER_ARCHIVE_MISSING",
                "Task-load retention requires both stand and settle teacher archives.",
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
    settle_teacher_initialization: dict[str, Any] | None = None
    selected_tests: list[dict[str, Any]] = []
    selected_traces: list[dict[str, Any]] = []
    checkpoint_assessments: list[dict[str, Any]] = []
    selected_checkpoint_step = 0
    selected_mean_episode_length = 0.0
    with tempfile.TemporaryDirectory(prefix="worldspec-h1-warm-start-") as temporary:
        selected_step, initialization = materialize_warm_start(
            warm_start_archive,
            Path(temporary) / "checkpoint",
            profile["warmStart"]["checkpointDigest"],
            profile["warmStart"]["checkpointSizeBytes"],
        )
        teacher_policy = None
        if retention_teacher_archive is not None:
            teacher_spec = profile.get("retentionTeacher", profile.get("standTeacher"))
            if teacher_spec is None:
                raise TrainingError(
                    "MIDTERM_TEACHER_SPEC_MISSING",
                    "A teacher archive was supplied without a matching teacher spec.",
                )
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
        settle_teacher_policy = None
        if settle_teacher_archive is not None:
            settle_teacher_spec = profile.get("settleTeacher")
            if settle_teacher_spec is None:
                raise TrainingError(
                    "MIDTERM_SETTLE_TEACHER_SPEC_MISSING",
                    "A settle teacher archive was supplied without a settleTeacher spec.",
                )
            settle_teacher_step, settle_teacher_initialization = materialize_warm_start(
                settle_teacher_archive,
                Path(temporary) / "settle-teacher",
                settle_teacher_spec["checkpointDigest"],
                settle_teacher_spec["checkpointSizeBytes"],
            )
            settle_teacher_policy = _load_deterministic_teacher_policy(
                settle_teacher_step,
                settle_teacher_initialization,
                network_factory,
            )
            settle_teacher_initialization = {
                **settle_teacher_initialization,
                "mode": settle_teacher_spec["mode"],
                "scope": settle_teacher_spec["scope"],
            }
        environment = make_environment(
            effective,
            training_model,
            stand_teacher_policy=teacher_policy,
            settle_teacher_policy=settle_teacher_policy,
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
        if settle_teacher_initialization is not None:
            validate_network_compatibility(
                settle_teacher_initialization,
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
            gae_lambda=training.get("gaeLambda", 0.95),
            learning_rate=training["learningRate"],
            entropy_cost=training["entropyCost"],
            clipping_epsilon=training.get("clippingEpsilon", 0.3),
            desired_kl=training.get("desiredKl", 0.01),
            learning_rate_schedule=training.get("learningRateSchedule"),
            learning_rate_schedule_min_lr=training.get(
                "learningRateScheduleMin",
                0.00001,
            ),
            learning_rate_schedule_max_lr=training.get(
                "learningRateScheduleMax",
                0.01,
            ),
            normalize_until_count=training.get("normalizeUntilCount"),
            deterministic_eval=training.get("deterministicEval", False),
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
        if profile.get("stage") in {
            "loaded_track_settle_task_load_retention",
            "loaded_track_settle_task_load_survival",
            "loaded_track_settle_task_load_deployment_eval",
            "loaded_track_settle_task_load_horizon",
            "loaded_track_settle_task_load_formal",
        }:
            from brax.training.agents.ppo import checkpoint as ppo_checkpoint

            checkpoint_steps = sorted(
                (
                    path
                    for path in checkpoint_dir.iterdir()
                    if path.is_dir() and path.name.isdigit()
                ),
                key=lambda path: int(path.name),
            )
            candidate_details: list[dict[str, Any]] = []
            if profile.get("checkpointSelection", {}).get("includeWarmStart") is True:
                warm_mean_episode_length = progress_records[0]["metrics"].get(
                    "eval/avg_episode_length"
                )
                if warm_mean_episode_length is None:
                    raise TrainingError(
                        "MIDTERM_WARM_CANDIDATE_EPISODE_METRIC_MISSING",
                        "The deployment-evaluation Warm Start has no episode metric.",
                    )
                warm_params = ppo_checkpoint.load(selected_step)
                warm_tests, warm_traces = evaluate_policy_suite(
                    effective,
                    environment,
                    make_inference_fn,
                    warm_params,
                )
                warm_assessment = assess_checkpoint_candidate(
                    0,
                    float(warm_mean_episode_length),
                    warm_tests,
                    profile["qualityGates"],
                )
                checkpoint_assessments.append(warm_assessment)
                candidate_details.append(
                    {
                        "assessment": warm_assessment,
                        "tests": warm_tests,
                        "traces": warm_traces,
                        "path": selected_step,
                    }
                )
            for checkpoint_step in checkpoint_steps:
                step = int(checkpoint_step.name)
                matching_progress = min(
                    progress_records,
                    key=lambda item: abs(int(item["step"]) - step),
                )
                mean_episode_length = matching_progress["metrics"].get("eval/avg_episode_length")
                if mean_episode_length is None:
                    raise TrainingError(
                        "MIDTERM_CANDIDATE_EPISODE_METRIC_MISSING",
                        "A saved PPO checkpoint has no associated episode metric.",
                        {"step": step},
                    )
                candidate_params = ppo_checkpoint.load(checkpoint_step)
                candidate_tests, candidate_traces = evaluate_policy_suite(
                    effective,
                    environment,
                    make_inference_fn,
                    candidate_params,
                )
                assessment = assess_checkpoint_candidate(
                    step,
                    float(mean_episode_length),
                    candidate_tests,
                    profile["qualityGates"],
                )
                checkpoint_assessments.append(assessment)
                candidate_details.append(
                    {
                        "assessment": assessment,
                        "tests": candidate_tests,
                        "traces": candidate_traces,
                        "path": checkpoint_step,
                    }
                )
            selected_assessment = select_checkpoint_candidate(checkpoint_assessments)
            selected_detail = next(
                item
                for item in candidate_details
                if item["assessment"]["step"] == selected_assessment["step"]
            )
            selected_tests = selected_detail["tests"]
            selected_traces = selected_detail["traces"]
            selected_checkpoint_step = selected_assessment["step"]
            selected_mean_episode_length = selected_assessment["meanEpisodeLength"]
            selected_checkpoint_root = output_dir / "selected-checkpoint"
            selected_checkpoint_root.mkdir()
            shutil.copytree(
                selected_detail["path"],
                selected_checkpoint_root / str(selected_checkpoint_step),
            )
            checkpoint_archive = output_dir / "midterm-checkpoint.zip"
            _deterministic_zip(selected_checkpoint_root, checkpoint_archive)
        else:
            selected_tests, selected_traces = evaluate_policy_suite(
                effective,
                environment,
                make_inference_fn,
                params,
            )
            selected_mean_episode_length = float(final_mean_episode_length)
            checkpoint_steps = sorted(
                (
                    path
                    for path in checkpoint_dir.iterdir()
                    if path.is_dir() and path.name.isdigit()
                ),
                key=lambda path: int(path.name),
            )
            selected_checkpoint_step = int(checkpoint_steps[-1].name) if checkpoint_steps else 0
            checkpoint_archive = output_dir / "midterm-checkpoint.zip"
            _deterministic_zip(checkpoint_dir, checkpoint_archive)
    with (output_dir / "evaluation-traces.jsonl").open("w", encoding="utf-8") as stream:
        import json

        for record in selected_traces:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
    expected_tests = profile["qualityGates"]["requiredConsecutivePasses"] * 2
    tests_gate = len(selected_tests) == expected_tests and all(
        item["result"] == "pass" for item in selected_tests
    )
    episode_gate = (
        float(selected_mean_episode_length)
        >= profile["qualityGates"]["minimumFinalMeanEpisodeLength"]
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
            "finalMeanEpisodeLength": float(selected_mean_episode_length),
            "assessmentBasis": (
                "selected_saved_checkpoint"
                if checkpoint_assessments
                else "terminal_training_checkpoint"
            ),
            "terminalMeanEpisodeLength": float(final_mean_episode_length),
            "minimumFinalMeanEpisodeLength": profile["qualityGates"][
                "minimumFinalMeanEpisodeLength"
            ],
            "meanEpisodeLengthGate": episode_gate,
            "deterministicSuiteGate": tests_gate,
            "tests": selected_tests,
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
        if profile.get("stage") in {
            "loaded_track_settle_task_load_retention",
            "loaded_track_settle_task_load_survival",
            "loaded_track_settle_task_load_deployment_eval",
            "loaded_track_settle_task_load_horizon",
            "loaded_track_settle_task_load_formal",
        }:
            result["standTeacher"] = teacher_initialization
        else:
            result["retentionTeacher"] = teacher_initialization
    if settle_teacher_initialization is not None:
        result["settleTeacher"] = settle_teacher_initialization
    if checkpoint_assessments:
        result["checkpointSelection"] = {
            "mode": profile["checkpointSelection"]["mode"],
            "selectedStep": selected_checkpoint_step,
            "candidateCount": len(checkpoint_assessments),
            "selectedFormalGate": quality_passed,
            "candidates": checkpoint_assessments,
        }
    if profile.get("stage") == "loaded_track_settle_task_load":
        result["taskLoadCurriculum"] = copy.deepcopy(profile["environment"]["taskLoadCurriculum"])
    if profile.get("stage") in {
        "loaded_track_settle_task_load_retention",
        "loaded_track_settle_task_load_survival",
        "loaded_track_settle_task_load_deployment_eval",
        "loaded_track_settle_task_load_horizon",
        "loaded_track_settle_task_load_formal",
    }:
        result["taskLoadCurriculum"] = copy.deepcopy(profile["environment"]["taskLoadCurriculum"])
    return result
