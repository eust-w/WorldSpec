"""Post-walk manipulation-balance calibration for H1.

This stage is intentionally separate from the historical locomotion and capture
profiles.  It keeps the ten-action leg ABI, biases training toward the remaining
post-walk failure distribution while retaining rest-state regression coverage,
and exposes the policy to an evidence-bound right-arm trajectory.
"""

from __future__ import annotations

import copy
import functools
import json
import tempfile
import time
from pathlib import Path
from typing import Any

from .capture import _with_command
from .contract import digest_bytes, digest_json, validate_profile
from .errors import TrainingError
from .midterm import (
    TASK_LOAD_RETENTION_LOAD,
    _load_deterministic_teacher_policy,
)
from .model import prepare_training_model
from .preflight import runtime_preflight, static_preflight
from .trainer import _deterministic_zip, _flat_observation_size, _host_float
from .warm_start import materialize_warm_start, validate_network_compatibility

CAPTURE_WARM_START = {
    "sourceStage": "loaded-track-settle-capture-v1-passed",
    "sourceReportDigest": "sha256:8261f863d71cb66de46facb37b3c5ed121811e80fdabac057629ed366a52666f",
    "checkpointDigest": "sha256:7f8c45e7c0bf1d485706ca694c44e74bfd351ab4f753bfacff947e9f7e75cfbe",
    "checkpointSizeBytes": 6_280_278,
    "distribution": "internal_only",
    "restore": {"normalizer": True, "policy": True, "value": True},
    "optimizerState": "reset",
}

MOTION_TEACHER = {
    "sourceStage": "loaded-track-settle-task-load-formal-v1-failed",
    "sourceReportDigest": "sha256:31e4991a33721928df2b2887f00dccd339dfe261dfbf1aaec4597579c6c784d9",
    "checkpointDigest": "sha256:61ebfa89d0fa5e7d7fc6488c524cf21c742c6a25efb5854a2bd689a61c895016",
    "checkpointSizeBytes": 1_260_210,
    "distribution": "internal_only",
    "selectedRole": "motion",
    "mode": "deterministic_motion_to_capture_snapshot_generation",
}

A6K1_CAPTURE_FAILURE = {
    "job": "worldspec-h1-midterm-dct4w",
    "probeRevision": "06edd7ca1132fcf46536b3048f645c2a551e835c",
    "reportDigest": "sha256:45e91743b7ee4e7d36a960c03be72c0cc547b9f2beede2b980a763d967820358",
    "reportSizeBytes": 19_361,
    "traceDigest": "sha256:45b859d08f12d2940b7065ad63684141dee60d030807466cc291916afe2f6b94",
    "traceSizeBytes": 2_224_266,
    "controllerDigest": "sha256:3fd09437d407edceaece3f1827ccd124b45d8fb3947646290e8f07d00257fdf8",
    "controllerSizeBytes": 7_549,
    "activePolicy": "capture",
    "terminalReason": "fall_height",
    "completedPhase": "reach_handle",
    "taskBaseTranslation": 0.9462899017731613,
    "taskBaseLateralDrift": 0.4680730141699314,
    "qualityGatesChanged": False,
}

PREVIOUS_ATTEMPT = {
    "job": "worldspec-h1-midterm-hl78d",
    "probeRevision": "ca4a73e9006435b37a79152f47caeb4969d4f4f0",
    "reportDigest": "sha256:a5c40535c3a863a6012ba1acb98200ba4d96c0b991d7169a9f023459015483d7",
    "reportSizeBytes": 31_592,
    "checkpointDigest": "sha256:89618f878a8aee343bde51ba36fc1271d18de732896ba9c2dffac981ba8b936e",
    "checkpointSizeBytes": 8_796_941,
    "traceDigest": "sha256:4021670994c205d4e54538be1966b34a8a273f474b867c6c9ef6c52a3dddd9ef",
    "traceSizeBytes": 437_686,
    "snapshotBankDigest": "sha256:931ea17b908fffc8bfcbdaffc95c98f246915a1154b26d21a1c521e79b71357f",
    "snapshotBankSizeBytes": 1_189_923,
    "formalGate": "failed",
    "finalMeanEpisodeLength": 94.359375,
    "deterministicTestsPassed": 9,
    "fromRestMaximumBaseTranslation": 0.018160735424661872,
    "fromRestMaximumTerminalLinearSpeed": 0.0034309549556142036,
    "postWalkMaximumBaseTranslation": 0.33074650083223095,
    "postWalkMaximumTerminalLinearSpeed": 0.9128383722959879,
    "trainingFromRestProbability": 0.5,
    "evaluationSnapshotFromRestProbability": 0.5,
    "qualityGatesChanged": False,
}

ANCHOR_RECOVERY = {
    "mode": "pelvis_yaw_local_velocity_command_v1",
    "frame": "pelvis_yaw_local",
    "linearGain": 2.0,
    "yawGain": 2.0,
    "maximumLinearVelocityX": 0.6,
    "maximumLinearVelocityY": 0.3,
    "maximumAngularVelocityYaw": 0.4,
}

ZERO_COMMAND = {
    "linearVelocityX": [0.0, 0.0],
    "linearVelocityY": [0.0, 0.0],
    "angularVelocityYaw": [0.0, 0.0],
    "zeroCommandProbability": 1.0,
}

SNAPSHOT_CURRICULUM = {
    "mode": "loaded_motion_capture_biased_mixture",
    "snapshotCount": 4096,
    "fromRestProbability": 0.25,
    "motionSteps": 150,
    "captureStepRange": [35, 50],
    "motionCommandDistribution": {
        "linearVelocityX": [0.4, 0.6],
        "linearVelocityY": [-0.05, 0.05],
        "angularVelocityYaw": [-0.1, 0.1],
    },
}

# The knots are a bounded projection of the dct4w controller Trace.  The last
# knot precedes the positive-feedback divergence, so training sees the intended
# reach load without learning from the already-fallen base state.
DYNAMIC_ARM_CURRICULUM = {
    "mode": "evidence_bound_right_arm_reach_v1",
    "sourceTraceDigest": A6K1_CAPTURE_FAILURE["traceDigest"],
    "episodeSteps": 100,
    "trajectoryScale": [0.75, 1.0],
    "anchorRecovery": ANCHOR_RECOVERY,
    "trajectoryKnots": [
        {
            "step": 0,
            "heldTargets": TASK_LOAD_RETENTION_LOAD["heldTargets"],
            "heldFeedforward": TASK_LOAD_RETENTION_LOAD["heldFeedforward"],
        },
        {
            "step": 5,
            "heldTargets": [
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                -0.09965808987617492,
                0.028872416728217234,
                -0.12167143662028922,
                0.009739961959215448,
            ],
            "heldFeedforward": [
                0.1680696747004276,
                -1.1976452358824279,
                0.18025528145452352,
                0.03468204546459902,
                -1.0455716430862962,
                -2.971125293979,
                0.9348745896661494,
                0.5760253329945153,
                -4.390410456315016,
            ],
        },
        {
            "step": 15,
            "heldTargets": [
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                -0.5035227378799308,
                -0.11494406030366155,
                -0.18123974089336659,
                0.4604156196117401,
            ],
            "heldFeedforward": [
                0.2706931324063241,
                -1.2807947720821096,
                0.11847126498638527,
                0.019756445082189822,
                -1.0468542988132297,
                -8.86953962193507,
                -0.6851127323639048,
                0.09892613004358708,
                -6.236283393464163,
            ],
        },
        {
            "step": 25,
            "heldTargets": [
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                -0.6864341108398805,
                -0.15760063317480932,
                -0.20137286481171396,
                0.7752665891538756,
            ],
            "heldFeedforward": [
                0.15884798470550893,
                -1.3692005635435809,
                0.20766792465892703,
                0.03957326203048639,
                -1.0458039394642151,
                -10.768232067572505,
                -3.3756956180844444,
                -0.3438746830214372,
                -4.711641829904508,
            ],
        },
        {
            "step": 30,
            "heldTargets": [
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                -0.8783807639104484,
                -0.2135736363672297,
                -0.22131405366572254,
                0.9845652461051941,
            ],
            "heldFeedforward": [
                0.6398647991487194,
                -1.455280253508255,
                0.277696297026198,
                0.05503073351652549,
                -1.0478031838393067,
                -11.055074955449417,
                -3.3823736684530052,
                -0.27764824651269127,
                -4.392885623670252,
            ],
        },
        {
            "step": 45,
            "heldTargets": [
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                -1.147033125595145,
                -0.22617855939133252,
                -0.21083969044251988,
                1.4936201707446037,
            ],
            "heldFeedforward": [
                0.4601545329644471,
                -1.60370468229885,
                0.3163013461889479,
                0.06409719139713749,
                -1.0472194346579262,
                -12.111874935635354,
                -4.110418722734953,
                -0.12760540258622655,
                -4.307221465824047,
            ],
        },
        {
            "step": 100,
            "heldTargets": [
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                -1.147033125595145,
                -0.22617855939133252,
                -0.21083969044251988,
                1.4936201707446037,
            ],
            "heldFeedforward": [
                0.4601545329644471,
                -1.60370468229885,
                0.3163013461889479,
                0.06409719139713749,
                -1.0472194346579262,
                -12.111874935635354,
                -4.110418722734953,
                -0.12760540258622655,
                -4.307221465824047,
            ],
        },
    ],
}

TRAINING_OVERRIDES = {
    "numTimesteps": 16_777_216,
    "numEnvs": 4096,
    "numEvals": 8,
    "episodeLength": 100,
    "unrollLength": 20,
    "numMinibatches": 16,
    "numUpdatesPerBatch": 4,
    "batchSize": 256,
    "learningRate": 0.00001,
    "entropyCost": 0.0002,
    "discounting": 0.995,
}

REWARD = {
    "survival": 3.0,
    "trackingLinear": 6.0,
    "trackingYaw": 2.0,
    "upright": 4.0,
    "baseHeight": 3.0,
    "pose": 0.5,
    "baseAnchor": 12.0,
    "verticalVelocityCost": 1.0,
    "angularVelocityXYCost": 0.5,
    "torqueCost": 0.000002,
    "actionRateCost": 0.03,
    "settleLinear": 12.0,
    "settleYaw": 5.0,
    "settleActionRateScale": 0.2,
    "terminationPenalty": 100.0,
}

QUALITY_GATES = {
    "minimumFinalMeanEpisodeLength": 90.0,
    "requiredConsecutivePasses": 5,
    "episodeSteps": 100,
    "minimumBaseHeight": 0.8,
    "minimumUprightCosine": 0.8,
    "maximumBaseTranslation": 0.2,
    "maximumBaseLateralDrift": 0.12,
    "maximumTerminalLinearSpeed": 0.2,
    "maximumTerminalAngularSpeed": 0.4,
    "maximumNonFiniteSamples": 0,
}


def validate_manipulation_balance_profile(
    base_profile: dict[str, Any],
    profile: dict[str, Any],
) -> None:
    """Validate the evidence-bound manipulation-balance calibration."""

    validate_profile(base_profile)
    expected = {
        "profileVersion": "0.1.0",
        "status": "research",
        "stage": "loaded_track_settle_manipulation_balance",
        "baseTrainingProfileDigest": digest_json(base_profile),
        "warmStart": CAPTURE_WARM_START,
        "motionTeacher": MOTION_TEACHER,
        "a6k1CaptureFailure": A6K1_CAPTURE_FAILURE,
        "previousAttempt": PREVIOUS_ATTEMPT,
        "trainingOverrides": TRAINING_OVERRIDES,
        "environment": {
            "commandDistribution": ZERO_COMMAND,
            "snapshotCurriculum": SNAPSHOT_CURRICULUM,
            "taskLoadCurriculum": TASK_LOAD_RETENTION_LOAD,
            "dynamicArmCurriculum": DYNAMIC_ARM_CURRICULUM,
            "termination": {
                "minimumBaseHeight": 0.5,
                "minimumUprightCosine": 0.25,
                "jointLimitToleranceRadians": 0.02,
            },
            "reward": REWARD,
            "targets": {"baseHeight": 0.98},
            "sigmas": {
                "tracking": 0.2,
                "upright": 0.05,
                "baseHeight": 0.02,
                "pose": 0.2,
                "settleTracking": 0.05,
                "baseAnchor": 0.04,
            },
            "commandResampleSteps": 100,
        },
        "qualityGates": QUALITY_GATES,
        "artifactPolicy": {
            "checkpoint": "research_only",
            "snapshotBank": "research_only",
            "distribution": "internal_only",
        },
        "evidenceStatus": "derived",
    }
    for key, value in expected.items():
        if profile.get(key) != value:
            raise TrainingError(
                "MANIPULATION_BALANCE_PROFILE_INVALID",
                f"Manipulation-balance Profile field is not frozen: {key}",
                {"field": key, "expected": value, "actual": profile.get(key)},
            )
    runtime = profile.get("runtime", {})
    if (
        runtime.get("ccdIterations") != 50
        or runtime.get("packageLockDigest") != base_profile["runtime"]["packageLockDigest"]
        or runtime.get("containerDigest")
        != runtime.get("containerImage", "").rsplit("@", maxsplit=1)[-1]
    ):
        raise TrainingError(
            "MANIPULATION_BALANCE_RUNTIME_INVALID",
            "Manipulation-balance runtime must retain CCD, package lock, and OCI binding.",
        )


def make_manipulation_balance_training_profile(
    base_profile: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    validate_manipulation_balance_profile(base_profile, profile)
    effective = copy.deepcopy(base_profile)
    effective["runtime"].update(profile["runtime"])
    effective["training"].update(profile["trainingOverrides"])
    effective["training"]["hyperparameterStatus"] = "research_manipulation_balance_override"
    effective["training"]["commandDistribution"] = copy.deepcopy(ZERO_COMMAND)
    effective["trainingEnvironment"] = copy.deepcopy(profile["environment"])
    effective["validation"] = copy.deepcopy(profile["qualityGates"])
    return effective


def _roll_motion_capture_bank(
    env,
    motion_policy,
    capture_policy,
    *,
    seed: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Generate actual post-motion/capture states under the frozen loaded model."""

    import jax
    import jax.numpy as jp
    import numpy as np

    count = SNAPSHOT_CURRICULUM["snapshotCount"]
    motion_steps = SNAPSHOT_CURRICULUM["motionSteps"]
    capture_low, capture_high = SNAPSHOT_CURRICULUM["captureStepRange"]
    root = jax.random.PRNGKey(seed)
    reset_rng, command_rng, capture_rng, policy_rng = jax.random.split(root, 4)
    reset = jax.jit(jax.vmap(env.reset))
    step = jax.jit(jax.vmap(env.step))
    with_command = jax.jit(jax.vmap(functools.partial(_with_command, env)))
    states = reset(jax.random.split(reset_rng, count))
    distribution = SNAPSHOT_CURRICULUM["motionCommandDistribution"]
    low = jp.asarray(
        [
            distribution["linearVelocityX"][0],
            distribution["linearVelocityY"][0],
            distribution["angularVelocityYaw"][0],
        ]
    )
    high = jp.asarray(
        [
            distribution["linearVelocityX"][1],
            distribution["linearVelocityY"][1],
            distribution["angularVelocityYaw"][1],
        ]
    )
    commands = jax.random.uniform(command_rng, (count, 3), minval=low, maxval=high)
    capture_steps = jax.random.randint(
        capture_rng,
        (count,),
        minval=capture_low,
        maxval=capture_high + 1,
    )
    motion_inference = jax.jit(motion_policy)
    capture_inference = jax.jit(capture_policy)
    failed = jp.zeros((count,), dtype=bool)
    captured = {
        "qpos": states.data.qpos,
        "qvel": states.data.qvel,
        "last_action": states.info["last_action"],
    }
    hit_failure = jp.zeros((count,), dtype=bool)

    def select(mask, old, new):
        expanded = mask.reshape((count,) + (1,) * (new.ndim - 1))
        return jp.where(expanded, new, old)

    for index in range(motion_steps + capture_high):
        moving = index < motion_steps
        states = with_command(states, commands if moving else jp.zeros((count, 3)))
        action, _ = (
            motion_inference(states.obs, jax.random.fold_in(policy_rng, index))
            if moving
            else capture_inference(states.obs, jax.random.fold_in(policy_rng, index))
        )
        states = step(states, action)
        failed = failed | states.done.astype(bool)
        hit = (
            capture_steps == index - motion_steps + 1
            if not moving
            else jp.zeros((count,), dtype=bool)
        )
        captured = {
            key: select(hit, captured[key], value)
            for key, value in {
                "qpos": states.data.qpos,
                "qvel": states.data.qvel,
                "last_action": states.info["last_action"],
            }.items()
        }
        hit_failure = jp.where(hit, failed, hit_failure)

    jax.block_until_ready(captured["qpos"])
    failures = int(np.count_nonzero(np.asarray(hit_failure)))
    if failures:
        raise TrainingError(
            "MANIPULATION_SNAPSHOT_ROLLOUT_FAILED",
            "Frozen motion/capture teachers terminated before snapshot capture.",
            {"failedCount": failures, "snapshotCount": count},
        )
    bank = {key: np.asarray(value) for key, value in captured.items()}
    metadata = {
        "snapshotCount": count,
        "motionSteps": motion_steps,
        "captureStepMinimum": int(np.min(np.asarray(capture_steps))),
        "captureStepMaximum": int(np.max(np.asarray(capture_steps))),
        "motionCommandMinimum": [float(v) for v in np.min(np.asarray(commands), axis=0)],
        "motionCommandMaximum": [float(v) for v in np.max(np.asarray(commands), axis=0)],
        "terminatedSnapshotCount": failures,
        "seed": seed,
    }
    return bank, metadata


def _save_bank(path: Path, bank: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    import numpy as np

    np.savez_compressed(path, **bank)
    payload = path.read_bytes()
    return {
        "path": path.name,
        "digest": digest_bytes(payload),
        "sizeBytes": len(payload),
        "distribution": "internal_only",
        **metadata,
    }


def _set_dynamic_scale(env, state, scale: float):
    import jax.numpy as jp

    info = dict(state.info)
    info["dynamic_arm_scale"] = jp.asarray(scale)
    info["base_anchor_xy"] = state.data.qpos[:2]
    info["step"] = jp.zeros((), dtype=jp.int32)
    info["command"] = jp.zeros(3)
    observation = {"state": env._observation(state.data, info["last_action"], info["command"])}
    return state.replace(info=info, obs=observation)


def evaluate_manipulation_balance_suite(
    profile: dict[str, Any],
    snapshot_env,
    rest_env,
    policy,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run five post-walk snapshots and five from-rest dynamic-arm tests."""

    import jax
    import numpy as np

    inference = jax.jit(policy)
    gates = profile["validation"]
    tests: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []

    def run(run_index: int, suite: str, env) -> dict[str, Any]:
        rng = jax.random.PRNGKey(profile["training"]["seed"] + run_index)
        state = jax.jit(env.reset)(rng)
        state = _set_dynamic_scale(env, state, 1.0)
        start = np.asarray(state.data.qpos[:2], dtype=float)
        minimum_height = float("inf")
        minimum_upright = float("inf")
        maximum_translation = 0.0
        maximum_lateral = 0.0
        terminal_linear = 0.0
        terminal_angular = 0.0
        nonfinite = 0
        done_seen = False
        terminal_reasons: set[str] = set()
        completed = 0
        step_fn = jax.jit(env.step)
        for index in range(gates["episodeSteps"]):
            rng, action_rng = jax.random.split(rng)
            action, _ = inference(state.obs, action_rng)
            state = step_fn(state, action)
            jax.block_until_ready(state.reward)
            qpos = np.asarray(state.data.qpos)
            qvel = np.asarray(state.data.qvel)
            position = np.asarray(qpos[:2], dtype=float)
            linear_velocity = np.asarray(env.local_velocity(state.data), dtype=float)
            angular_velocity = np.asarray(env.angular_velocity(state.data), dtype=float)
            height = float(np.asarray(state.data.xpos[env.pelvis_body_id, 2]))
            upright = float(np.asarray(env.upvector(state.data)[2]))
            done = bool(np.asarray(state.done))
            finite = bool(np.isfinite(qpos).all() and np.isfinite(qvel).all())
            displacement = position - start
            maximum_translation = max(maximum_translation, float(np.linalg.norm(displacement)))
            maximum_lateral = max(maximum_lateral, abs(float(displacement[1])))
            minimum_height = min(minimum_height, height)
            minimum_upright = min(minimum_upright, upright)
            nonfinite += 0 if finite else 1
            completed += 1
            if index >= gates["episodeSteps"] - 10:
                terminal_linear = max(terminal_linear, float(np.linalg.norm(linear_velocity)))
                terminal_angular = max(terminal_angular, float(np.linalg.norm(angular_velocity)))
            traces.append(
                {
                    "suite": suite,
                    "run": run_index,
                    "step": index,
                    "activePolicy": "manipulation_balance",
                    "basePosition": [float(qpos[0]), float(qpos[1]), height],
                    "uprightCosine": upright,
                    "localVelocity": [float(value) for value in linear_velocity],
                    "angularVelocity": [float(value) for value in angular_velocity],
                    "dynamicArmScale": 1.0,
                    "done": done,
                    "finite": finite,
                }
            )
            if done:
                done_seen = True
                terminal_reasons.update(
                    name
                    for name, active in state.info["termination"].items()
                    if bool(np.asarray(active))
                )
                break
        passed = (
            not done_seen
            and completed == gates["episodeSteps"]
            and nonfinite <= gates["maximumNonFiniteSamples"]
            and minimum_height >= gates["minimumBaseHeight"]
            and minimum_upright >= gates["minimumUprightCosine"]
            and maximum_translation <= gates["maximumBaseTranslation"]
            and maximum_lateral <= gates["maximumBaseLateralDrift"]
            and terminal_linear <= gates["maximumTerminalLinearSpeed"]
            and terminal_angular <= gates["maximumTerminalAngularSpeed"]
        )
        return {
            "id": f"test://worldspec/h1-manipulation-balance/{suite}/{run_index + 1}",
            "suite": suite,
            "result": "pass" if passed else "fail",
            "metrics": {
                "completedSteps": completed,
                "requiredSteps": gates["episodeSteps"],
                "minimumBaseHeight": minimum_height,
                "minimumUprightCosine": minimum_upright,
                "maximumBaseTranslation": maximum_translation,
                "maximumBaseLateralDrift": maximum_lateral,
                "maximumTerminalLinearSpeed": terminal_linear,
                "maximumTerminalAngularSpeed": terminal_angular,
                "nonFiniteSamples": nonfinite,
                "doneSeen": done_seen,
                "terminalReasons": sorted(terminal_reasons),
            },
        }

    required = gates["requiredConsecutivePasses"]
    for index in range(required):
        tests.append(run(index, "post_walk_capture", snapshot_env))
    for index in range(required):
        tests.append(run(index, "from_rest", rest_env))
    return tests, traces


def run_manipulation_balance_calibration(
    base_profile: dict[str, Any],
    profile: dict[str, Any],
    bundle_dir: Path,
    model_dir: Path,
    output_dir: Path,
    warm_start_archive: Path,
    motion_teacher_archive: Path,
) -> dict[str, Any]:
    """Train and gate the dedicated manipulation-balance policy."""

    import numpy as np
    from brax.training.agents.ppo import networks as ppo_networks
    from brax.training.agents.ppo import train as ppo
    from mujoco_playground import wrapper

    from .environment import make_environment

    effective = make_manipulation_balance_training_profile(base_profile, profile)
    static = static_preflight(base_profile, bundle_dir)
    training_model, derivation = prepare_training_model(base_profile, bundle_dir, model_dir)
    runtime = runtime_preflight(effective, training_model)
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_dir = output_dir / "checkpoints"
    checkpoint_dir.mkdir()
    progress_records: list[dict[str, Any]] = []
    started = time.monotonic()

    def progress(step: int, metrics: dict[str, Any]) -> None:
        scalar = {
            key: _host_float(value)
            for key, value in metrics.items()
            if getattr(value, "size", 1) == 1
        }
        if not all(np.isfinite(value) for value in scalar.values()):
            raise TrainingError(
                "MANIPULATION_BALANCE_METRIC_NONFINITE",
                "Manipulation-balance PPO produced a non-finite metric.",
                {"step": int(step), "metrics": scalar},
            )
        progress_records.append(
            {"step": int(step), "elapsedSeconds": time.monotonic() - started, "metrics": scalar}
        )

    network_factory = functools.partial(
        ppo_networks.make_ppo_networks,
        policy_hidden_layer_sizes=(128, 128, 128, 128),
        value_hidden_layer_sizes=(256, 256, 256, 256, 256),
        policy_obs_key="state",
        value_obs_key="state",
    )
    training = effective["training"]
    with tempfile.TemporaryDirectory(prefix="worldspec-h1-manipulation-balance-") as temporary:
        temporary_root = Path(temporary)
        warm_step, initialization = materialize_warm_start(
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
        capture_teacher = _load_deterministic_teacher_policy(
            warm_step,
            initialization,
            network_factory,
        )
        motion_teacher = _load_deterministic_teacher_policy(
            motion_step,
            motion_initialization,
            network_factory,
        )
        rollout_profile = copy.deepcopy(effective)
        rollout_profile["trainingEnvironment"].pop("dynamicArmCurriculum")
        rollout_profile["trainingEnvironment"].pop("snapshotCurriculum")
        rollout_profile["training"]["commandDistribution"] = {
            **SNAPSHOT_CURRICULUM["motionCommandDistribution"],
            "zeroCommandProbability": 0.0,
        }
        rollout_env = make_environment(rollout_profile, training_model)
        observation_size = _flat_observation_size(rollout_env.observation_size["state"])
        action_size = int(rollout_env.action_size)
        validate_network_compatibility(initialization, observation_size, action_size)
        validate_network_compatibility(motion_initialization, observation_size, action_size)
        bank, bank_metadata = _roll_motion_capture_bank(
            rollout_env,
            motion_teacher,
            capture_teacher,
            seed=training["seed"] + 20_000,
        )
        snapshot_artifact = _save_bank(
            output_dir / "manipulation-state-bank.npz",
            bank,
            bank_metadata,
        )
        training_env = make_environment(
            effective,
            training_model,
            capture_state_bank=bank,
        )
        make_inference_fn, params, _ = ppo.train(
            environment=training_env,
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
            restore_checkpoint_path=str(warm_step),
            restore_value_fn=True,
            wrap_env_fn=wrapper.wrap_for_brax_training,
            num_eval_envs=min(128, training["numEnvs"]),
        )
        candidate = make_inference_fn(params, deterministic=True)
        snapshot_eval_profile = copy.deepcopy(effective)
        snapshot_eval_profile["trainingEnvironment"]["snapshotCurriculum"][
            "fromRestProbability"
        ] = 0.0
        snapshot_eval_env = make_environment(
            snapshot_eval_profile,
            training_model,
            capture_state_bank=bank,
        )
        rest_eval_env = make_environment(effective, training_model)
        tests, traces = evaluate_manipulation_balance_suite(
            effective,
            snapshot_eval_env,
            rest_eval_env,
            candidate,
        )
    if len(progress_records) < 2:
        raise TrainingError(
            "MANIPULATION_BALANCE_PROGRESS_MISSING",
            "Manipulation-balance training did not report enough progress.",
        )
    final_progress = progress_records[-1]
    mean_episode_length = final_progress["metrics"].get("eval/avg_episode_length")
    if mean_episode_length is None:
        raise TrainingError(
            "MANIPULATION_BALANCE_EPISODE_METRIC_MISSING",
            "Manipulation-balance training omitted eval/avg_episode_length.",
        )
    checkpoint_archive = output_dir / "midterm-checkpoint.zip"
    _deterministic_zip(checkpoint_dir, checkpoint_archive)
    trace_path = output_dir / "evaluation-traces.jsonl"
    with trace_path.open("w", encoding="utf-8") as stream:
        for record in traces:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
    tests_gate = len(tests) == 10 and all(test["result"] == "pass" for test in tests)
    episode_gate = float(mean_episode_length) >= QUALITY_GATES["minimumFinalMeanEpisodeLength"]
    quality_passed = tests_gate and episode_gate
    return {
        "baseTrainingProfileDigest": digest_json(base_profile),
        "manipulationBalanceProfileDigest": digest_json(profile),
        "effectiveTrainingProfileDigest": digest_json(effective),
        "warmStart": initialization,
        "motionTeacher": {
            **motion_initialization,
            "mode": MOTION_TEACHER["mode"],
            "selectedRole": MOTION_TEACHER["selectedRole"],
        },
        "a6k1CaptureFailure": copy.deepcopy(A6K1_CAPTURE_FAILURE),
        "previousAttempt": copy.deepcopy(PREVIOUS_ATTEMPT),
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
            "finalMeanEpisodeLength": float(mean_episode_length),
            "minimumFinalMeanEpisodeLength": QUALITY_GATES["minimumFinalMeanEpisodeLength"],
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
        "dynamicArmCurriculum": copy.deepcopy(DYNAMIC_ARM_CURRICULUM),
    }
