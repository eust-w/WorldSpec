"""Constructive recoverability diagnosis for the fixed H1 manipulation state.

The diagnostic searches for a bounded, finite-horizon residual action sequence
around the frozen v14 policy.  Finding a sequence is a constructive witness.
Failure to find one is reported as unknown and is never treated as an
infeasibility proof.
"""

from __future__ import annotations

import copy
import functools
import json
from pathlib import Path
from typing import Any

from .contract import canonical_bytes, digest_bytes, digest_json, validate_profile
from .errors import TrainingError
from .manipulation_balance import (
    QUALITY_GATES,
    _set_dynamic_scale,
    make_manipulation_balance_training_profile,
)
from .model import prepare_training_model
from .preflight import runtime_preflight, static_preflight
from .trainer import _flat_observation_size
from .warm_start import materialize_warm_start, validate_network_compatibility

SOURCE_MANIPULATION_PROFILE_DIGEST = (
    "sha256:7987a974551ddf4de019c04e7fefaae3b433cdd47cca20692db031db4f459a44"
)
SOURCE_FAILURE = {
    "job": "worldspec-h1-midterm-2pn45",
    "probeRevision": "154b3e6b1da0b99acef517336d511bbde8e3b0f2",
    "sourceReportDigest": (
        "sha256:83b063ac28c0174beab24ff94e1f4a9b67cf7b0ffd464101af32405c8207f542"
    ),
    "runtimeReportDigest": (
        "sha256:1757154e2d4eae03dac11b39b803f3a31d3f5ff5bd91328ed854b148878381ac"
    ),
    "checkpointDigest": (
        "sha256:b40d6287440f3a0761fe4b3fedc15da21e53d881ada3f0931f2b34a9f59b7fae"
    ),
    "checkpointSizeBytes": 1_254_893,
    "checkpointStep": 7_372_800,
    "traceDigest": (
        "sha256:2b29a5bed65fee7073fefd7621ae5bd961d9247b2fe3d15306c86ca5815782b0"
    ),
    "snapshotBankDigest": (
        "sha256:d4090fe9b437084dcc6610da3028d46500151437d7bf22a3cb7431b8ef38cec0"
    ),
    "snapshotBankSizeBytes": 1_192_118,
    "criticalSnapshotIndex": 565,
    "evaluationRun": 2,
    "evaluationSeed": 2,
    "formalGate": "failed",
    "qualityGatesChanged": False,
}
SEARCH = {
    "algorithm": "cem_closed_loop_policy_residual_shooting_v1",
    "searchSeed": 20260731,
    "population": 4096,
    "eliteCount": 128,
    "maximumIterations": 12,
    "horizonSteps": 100,
    "residualKnots": 10,
    "initialStddev": 0.2,
    "minimumStddev": 0.02,
    "maximumResidual": 0.5,
    "actionMinimum": -1.0,
    "actionMaximum": 1.0,
    "baselineCandidateIncluded": True,
}
BASELINE_METRICS = {
    "completedSteps": 100,
    "requiredSteps": 100,
    "minimumBaseHeight": 0.7160465121269226,
    "minimumUprightCosine": 0.7536250352859497,
    "maximumBaseTranslation": 0.8543086872960323,
    "maximumBaseLateralDrift": 0.5395923405885696,
    "maximumTerminalLinearSpeed": 2.8207999699295074,
    "maximumTerminalAngularSpeed": 2.125552847801331,
    "nonFiniteSamples": 0,
    "doneSeen": False,
}


def validate_viability_profile(
    base_profile: dict[str, Any],
    manipulation_profile: dict[str, Any],
    profile: dict[str, Any],
) -> None:
    """Reject lineage, search, action-envelope, or gate drift."""

    validate_profile(base_profile)
    expected = {
        "profileVersion": "0.1.0",
        "status": "research",
        "stage": "loaded_track_settle_manipulation_viability",
        "baseTrainingProfileDigest": digest_json(base_profile),
        "sourceManipulationProfileDigest": SOURCE_MANIPULATION_PROFILE_DIGEST,
        "sourceFailure": SOURCE_FAILURE,
        "warmStart": {
            "sourceStage": (
                "loaded-track-settle-manipulation-hard-negative-replay-v14-failed"
            ),
            "sourceReportDigest": SOURCE_FAILURE["sourceReportDigest"],
            "checkpointDigest": SOURCE_FAILURE["checkpointDigest"],
            "checkpointSizeBytes": SOURCE_FAILURE["checkpointSizeBytes"],
            "checkpointStep": SOURCE_FAILURE["checkpointStep"],
            "distribution": "internal_only",
        },
        "snapshotBank": {
            "digest": SOURCE_FAILURE["snapshotBankDigest"],
            "sizeBytes": SOURCE_FAILURE["snapshotBankSizeBytes"],
            "snapshotCount": 4096,
            "criticalSnapshotIndex": SOURCE_FAILURE["criticalSnapshotIndex"],
        },
        "search": SEARCH,
        "baselineReproduction": {
            "metrics": BASELINE_METRICS,
            "absoluteTolerance": 0.001,
        },
        "qualityGates": QUALITY_GATES,
        "claimBoundary": {
            "witnessFoundProvesRecoverableUnderFrozenContract": True,
            "witnessNotFoundProvesUnrecoverable": False,
            "policyCandidateAllowed": False,
            "fullKitchenSingleAllowed": False,
            "fiveOfFiveAllowed": False,
            "hundredMillionTrainingAllowed": False,
            "automaticRetryAllowed": False,
        },
    }
    actual = {key: profile.get(key) for key in expected}
    if actual != expected:
        raise TrainingError(
            "MANIPULATION_VIABILITY_PROFILE_DRIFT",
            "Manipulation viability Profile changed a frozen diagnostic contract.",
        )
    runtime = profile.get("runtime", {})
    image = runtime.get("containerImage")
    digest = runtime.get("containerDigest")
    if (
        not isinstance(image, str)
        or "@sha256:" not in image
        or digest != image.rsplit("@", 1)[1]
        or runtime.get("packageLockDigest")
        != "sha256:7cc88f20b2c608d6fe673f3b994b879db69d75361206bf25f949d7acc5ed3a41"
        or runtime.get("ccdIterations") != 50
    ):
        raise TrainingError(
            "MANIPULATION_VIABILITY_RUNTIME_DRIFT",
            "Manipulation viability runtime must be immutable and package-locked.",
        )
    if digest_json(manipulation_profile) != SOURCE_MANIPULATION_PROFILE_DIGEST:
        raise TrainingError(
            "MANIPULATION_VIABILITY_SOURCE_PROFILE_MISMATCH",
            "The source manipulation Profile does not match the v14 evidence.",
        )


def assess_viability_metrics(
    metrics: dict[str, Any],
    gates: dict[str, Any],
) -> dict[str, Any]:
    """Apply the unchanged manipulation gate to one candidate trajectory."""

    passed = (
        metrics["completedSteps"] == gates["episodeSteps"]
        and not metrics["doneSeen"]
        and metrics["nonFiniteSamples"] <= gates["maximumNonFiniteSamples"]
        and metrics["minimumBaseHeight"] >= gates["minimumBaseHeight"]
        and metrics["minimumUprightCosine"] >= gates["minimumUprightCosine"]
        and metrics["maximumBaseTranslation"] <= gates["maximumBaseTranslation"]
        and metrics["maximumBaseLateralDrift"] <= gates["maximumBaseLateralDrift"]
        and metrics["maximumTerminalLinearSpeed"]
        <= gates["maximumTerminalLinearSpeed"]
        and metrics["maximumTerminalAngularSpeed"]
        <= gates["maximumTerminalAngularSpeed"]
    )
    return {
        "result": "pass" if passed else "fail",
        "metrics": metrics,
    }


def _baseline_matches(
    actual: dict[str, Any],
    expected: dict[str, Any],
    tolerance: float,
) -> tuple[bool, dict[str, float]]:
    deltas: dict[str, float] = {}
    for key, value in expected.items():
        if isinstance(value, (bool, int)):
            if actual[key] != value:
                return False, deltas
        else:
            delta = abs(float(actual[key]) - float(value))
            deltas[key] = delta
            if delta > tolerance:
                return False, deltas
    return True, deltas


def run_manipulation_viability_diagnostic(
    base_profile: dict[str, Any],
    manipulation_profile: dict[str, Any],
    profile: dict[str, Any],
    bundle_dir: Path,
    model_dir: Path,
    output_dir: Path,
    checkpoint_archive: Path,
    snapshot_bank_archive: Path,
) -> dict[str, Any]:
    """Search for a constructive recovery witness on the exact hard state."""

    import jax
    import jax.numpy as jp
    import numpy as np
    from brax.training.acme import running_statistics
    from brax.training.agents.ppo import checkpoint as ppo_checkpoint
    from brax.training.agents.ppo import networks as ppo_networks

    from .environment import make_environment

    validate_viability_profile(base_profile, manipulation_profile, profile)
    static = static_preflight(base_profile, bundle_dir)
    effective = make_manipulation_balance_training_profile(
        base_profile,
        manipulation_profile,
    )
    evaluation_profile = copy.deepcopy(effective)
    snapshot = evaluation_profile["trainingEnvironment"]["snapshotCurriculum"]
    snapshot["fromRestProbability"] = 0.0
    snapshot["criticalSnapshotProbability"] = 0.0
    snapshot["uniformSnapshotProbability"] = 1.0

    training_model, derivation = prepare_training_model(
        base_profile,
        bundle_dir,
        model_dir,
    )
    runtime = runtime_preflight(effective, training_model)
    bank_payload = snapshot_bank_archive.read_bytes()
    if (
        digest_bytes(bank_payload) != profile["snapshotBank"]["digest"]
        or len(bank_payload) != profile["snapshotBank"]["sizeBytes"]
    ):
        raise TrainingError(
            "MANIPULATION_VIABILITY_BANK_MISMATCH",
            "The frozen state bank does not match the viability Profile.",
        )
    with np.load(snapshot_bank_archive, allow_pickle=False) as archive:
        bank = {key: archive[key] for key in archive.files}
    if any(key not in bank for key in ("qpos", "qvel", "last_action")):
        raise TrainingError(
            "MANIPULATION_VIABILITY_BANK_INVALID",
            "The frozen state bank is missing required arrays.",
        )
    if bank["qpos"].shape[0] != profile["snapshotBank"]["snapshotCount"]:
        raise TrainingError(
            "MANIPULATION_VIABILITY_BANK_INVALID",
            "The frozen state bank count changed.",
        )

    env = make_environment(
        evaluation_profile,
        training_model,
        capture_state_bank=bank,
    )
    observation_size = _flat_observation_size(env.observation_size["state"])
    action_size = int(env.action_size)
    checkpoint_path, checkpoint_metadata = materialize_warm_start(
        checkpoint_archive,
        output_dir / "source-checkpoint",
        profile["warmStart"]["checkpointDigest"],
        profile["warmStart"]["checkpointSizeBytes"],
    )
    if checkpoint_metadata["selectedStep"] != profile["warmStart"]["checkpointStep"]:
        raise TrainingError(
            "MANIPULATION_VIABILITY_CHECKPOINT_STEP_MISMATCH",
            "The selected v14 Checkpoint step changed.",
        )
    validate_network_compatibility(
        checkpoint_metadata,
        observation_size,
        action_size,
    )

    network_factory = functools.partial(
        ppo_networks.make_ppo_networks,
        policy_hidden_layer_sizes=(128, 128, 128, 128),
        value_hidden_layer_sizes=(256, 256, 256, 256, 256),
        policy_obs_key="state",
        value_obs_key="state",
    )
    policy_network = network_factory(
        {"state": observation_size},
        action_size,
        preprocess_observations_fn=running_statistics.normalize,
    )
    policy = ppo_networks.make_inference_fn(policy_network)(
        ppo_checkpoint.load(checkpoint_path),
        deterministic=True,
    )

    initial_rng = jax.random.PRNGKey(profile["sourceFailure"]["evaluationSeed"])
    initial_state = jax.jit(env.reset)(initial_rng)
    initial_state = _set_dynamic_scale(env, initial_state, 1.0)
    actual_index = int(np.asarray(initial_state.info["snapshot_bank_index"]))
    if actual_index != profile["snapshotBank"]["criticalSnapshotIndex"]:
        raise TrainingError(
            "MANIPULATION_VIABILITY_INITIAL_STATE_MISMATCH",
            "The frozen evaluation seed no longer maps to hard state 565.",
            {"actualIndex": actual_index},
        )
    bank_index = profile["snapshotBank"]["criticalSnapshotIndex"]
    actual_qpos = np.asarray(initial_state.data.qpos)
    bank_qpos = bank["qpos"][bank_index]
    non_held_qpos = np.ones((actual_qpos.shape[0],), dtype=bool)
    non_held_qpos[np.asarray(env._held_qpos, dtype=int)] = False
    held_targets = np.asarray(initial_state.info["held_targets"])
    if (
        not np.array_equal(actual_qpos[non_held_qpos], bank_qpos[non_held_qpos])
        or not np.array_equal(
            actual_qpos[np.asarray(env._held_qpos, dtype=int)],
            held_targets,
        )
        or not np.array_equal(np.asarray(initial_state.data.qvel), bank["qvel"][bank_index])
        or not np.array_equal(
            np.asarray(initial_state.info["last_action"]),
            bank["last_action"][bank_index],
        )
    ):
        raise TrainingError(
            "MANIPULATION_VIABILITY_INITIAL_STATE_MISMATCH",
            "The materialized evaluation state differs from state-bank index 565 "
            "plus the frozen dynamic-arm start target.",
        )

    search = profile["search"]
    population = int(search["population"])
    elite_count = int(search["eliteCount"])
    horizon = int(search["horizonSteps"])
    knot_count = int(search["residualKnots"])
    action_minimum = float(search["actionMinimum"])
    action_maximum = float(search["actionMaximum"])
    maximum_residual = float(search["maximumResidual"])
    policy_keys = jax.random.split(jax.random.PRNGKey(0), population)
    batched_initial = jax.tree_util.tree_map(
        lambda value: jp.broadcast_to(value, (population,) + value.shape),
        initial_state,
    )
    start_xy = batched_initial.data.qpos[:, :2]
    batched_step = jax.vmap(env.step)
    batched_policy = jax.vmap(policy)
    gates = profile["qualityGates"]

    def rollout_batch(residual_knots):
        def scan_step(carry, step_index):
            state, minimum_height, minimum_upright, maximum_translation, maximum_lateral, terminal_linear, terminal_angular, nonfinite, done_seen = carry
            policy_action, _ = batched_policy(state.obs, policy_keys)
            knot_position = (
                step_index.astype(jp.float32)
                * float(knot_count - 1)
                / float(horizon - 1)
            )
            lower = jp.floor(knot_position).astype(jp.int32)
            upper = jp.minimum(lower + 1, knot_count - 1)
            alpha = knot_position - lower.astype(jp.float32)
            residual = (
                residual_knots[:, lower, :] * (1.0 - alpha)
                + residual_knots[:, upper, :] * alpha
            )
            action = jp.clip(policy_action + residual, action_minimum, action_maximum)
            next_state = batched_step(state, action)
            position = next_state.data.qpos[:, :2]
            displacement = position - start_xy
            translation = jp.linalg.norm(displacement, axis=-1)
            lateral = jp.abs(displacement[:, 1])
            height = next_state.data.xpos[:, env.pelvis_body_id, 2]
            upright = jax.vmap(env.upvector)(next_state.data)[:, 2]
            linear_speed = jp.linalg.norm(
                jax.vmap(env.local_velocity)(next_state.data),
                axis=-1,
            )
            angular_speed = jp.linalg.norm(
                jax.vmap(env.angular_velocity)(next_state.data),
                axis=-1,
            )
            terminal = step_index >= horizon - 10
            finite = jp.all(jp.isfinite(next_state.data.qpos), axis=-1) & jp.all(
                jp.isfinite(next_state.data.qvel),
                axis=-1,
            )
            return (
                next_state,
                jp.minimum(minimum_height, height),
                jp.minimum(minimum_upright, upright),
                jp.maximum(maximum_translation, translation),
                jp.maximum(maximum_lateral, lateral),
                jp.where(terminal, jp.maximum(terminal_linear, linear_speed), terminal_linear),
                jp.where(
                    terminal,
                    jp.maximum(terminal_angular, angular_speed),
                    terminal_angular,
                ),
                nonfinite + (~finite).astype(jp.int32),
                done_seen | (next_state.done > 0),
            ), None

        zeros = jp.zeros((population,), dtype=jp.float32)
        initial_carry = (
            batched_initial,
            jp.full((population,), jp.inf),
            jp.full((population,), jp.inf),
            zeros,
            zeros,
            zeros,
            zeros,
            jp.zeros((population,), dtype=jp.int32),
            jp.zeros((population,), dtype=bool),
        )
        final, _ = jax.lax.scan(scan_step, initial_carry, jp.arange(horizon))
        (
            _,
            minimum_height,
            minimum_upright,
            maximum_translation,
            maximum_lateral,
            terminal_linear,
            terminal_angular,
            nonfinite,
            done_seen,
        ) = final
        height_violation = jp.maximum(
            0.0,
            (float(gates["minimumBaseHeight"]) - minimum_height) / 0.1,
        )
        upright_violation = jp.maximum(
            0.0,
            (float(gates["minimumUprightCosine"]) - minimum_upright) / 0.1,
        )
        translation_violation = jp.maximum(
            0.0,
            (maximum_translation - float(gates["maximumBaseTranslation"]))
            / float(gates["maximumBaseTranslation"]),
        )
        lateral_violation = jp.maximum(
            0.0,
            (maximum_lateral - float(gates["maximumBaseLateralDrift"]))
            / float(gates["maximumBaseLateralDrift"]),
        )
        terminal_linear_violation = jp.maximum(
            0.0,
            (terminal_linear - float(gates["maximumTerminalLinearSpeed"]))
            / float(gates["maximumTerminalLinearSpeed"]),
        )
        terminal_angular_violation = jp.maximum(
            0.0,
            (terminal_angular - float(gates["maximumTerminalAngularSpeed"]))
            / float(gates["maximumTerminalAngularSpeed"]),
        )
        violation = (
            height_violation**2
            + upright_violation**2
            + translation_violation**2
            + lateral_violation**2
            + terminal_linear_violation**2
            + terminal_angular_violation**2
            + done_seen.astype(jp.float32) * 100.0
            + nonfinite.astype(jp.float32) * 100.0
        )
        action_cost = jp.mean(residual_knots**2, axis=(1, 2))
        success = (
            ~done_seen
            & (nonfinite == 0)
            & (minimum_height >= float(gates["minimumBaseHeight"]))
            & (minimum_upright >= float(gates["minimumUprightCosine"]))
            & (maximum_translation <= float(gates["maximumBaseTranslation"]))
            & (maximum_lateral <= float(gates["maximumBaseLateralDrift"]))
            & (terminal_linear <= float(gates["maximumTerminalLinearSpeed"]))
            & (terminal_angular <= float(gates["maximumTerminalAngularSpeed"]))
        )
        score = -violation - 0.01 * action_cost + success.astype(jp.float32) * 1_000_000.0
        return score, success, {
            "minimumBaseHeight": minimum_height,
            "minimumUprightCosine": minimum_upright,
            "maximumBaseTranslation": maximum_translation,
            "maximumBaseLateralDrift": maximum_lateral,
            "maximumTerminalLinearSpeed": terminal_linear,
            "maximumTerminalAngularSpeed": terminal_angular,
            "nonFiniteSamples": nonfinite,
            "doneSeen": done_seen,
        }

    @jax.jit
    def search_iteration(key, mean, stddev):
        residuals = jp.clip(
            mean
            + jax.random.normal(
                key,
                (population, knot_count, action_size),
            )
            * stddev,
            -maximum_residual,
            maximum_residual,
        )
        residuals = residuals.at[0].set(jp.zeros((knot_count, action_size)))
        scores, success, metrics = rollout_batch(residuals)
        _, elite_indices = jax.lax.top_k(scores, elite_count)
        elites = residuals[elite_indices]
        best_index = jp.argmax(scores)
        return (
            jp.mean(elites, axis=0),
            jp.maximum(
                jp.std(elites, axis=0),
                float(search["minimumStddev"]),
            ),
            residuals[best_index],
            scores[best_index],
            success[best_index],
            jax.tree_util.tree_map(lambda value: value[best_index], metrics),
            jp.sum(success.astype(jp.int32)),
        )

    def detailed_rollout(label: str, residual_knots: np.ndarray):
        state = initial_state
        start = np.asarray(state.data.qpos[:2], dtype=float)
        minimum_height = float("inf")
        minimum_upright = float("inf")
        maximum_translation = 0.0
        maximum_lateral = 0.0
        terminal_linear = 0.0
        terminal_angular = 0.0
        nonfinite = 0
        done_seen = False
        completed = 0
        trace: list[dict[str, Any]] = []
        actions: list[list[float]] = []
        step_fn = jax.jit(env.step)
        inference = jax.jit(policy)
        for step_index in range(horizon):
            policy_action, _ = inference(state.obs, jax.random.PRNGKey(0))
            knot_position = step_index * (knot_count - 1) / (horizon - 1)
            lower = int(np.floor(knot_position))
            upper = min(lower + 1, knot_count - 1)
            alpha = knot_position - lower
            residual = (
                residual_knots[lower] * (1.0 - alpha)
                + residual_knots[upper] * alpha
            )
            action = np.clip(
                np.asarray(policy_action, dtype=float) + residual,
                action_minimum,
                action_maximum,
            )
            state = step_fn(state, jp.asarray(action))
            jax.block_until_ready(state.reward)
            qpos = np.asarray(state.data.qpos)
            qvel = np.asarray(state.data.qvel)
            displacement = np.asarray(qpos[:2], dtype=float) - start
            linear_velocity = np.asarray(env.local_velocity(state.data), dtype=float)
            angular_velocity = np.asarray(env.angular_velocity(state.data), dtype=float)
            height = float(np.asarray(state.data.xpos[env.pelvis_body_id, 2]))
            upright = float(np.asarray(env.upvector(state.data)[2]))
            finite = bool(np.isfinite(qpos).all() and np.isfinite(qvel).all())
            done = bool(np.asarray(state.done))
            minimum_height = min(minimum_height, height)
            minimum_upright = min(minimum_upright, upright)
            maximum_translation = max(
                maximum_translation,
                float(np.linalg.norm(displacement)),
            )
            maximum_lateral = max(maximum_lateral, abs(float(displacement[1])))
            if step_index >= horizon - 10:
                terminal_linear = max(
                    terminal_linear,
                    float(np.linalg.norm(linear_velocity)),
                )
                terminal_angular = max(
                    terminal_angular,
                    float(np.linalg.norm(angular_velocity)),
                )
            nonfinite += 0 if finite else 1
            done_seen = done_seen or done
            completed += 1
            action_values = [float(value) for value in action]
            actions.append(action_values)
            trace.append(
                {
                    "trajectory": label,
                    "step": step_index,
                    "snapshotBankIndex": actual_index,
                    "basePosition": [float(qpos[0]), float(qpos[1]), height],
                    "uprightCosine": upright,
                    "localVelocity": [float(value) for value in linear_velocity],
                    "angularVelocity": [float(value) for value in angular_velocity],
                    "action": action_values,
                    "done": done,
                    "finite": finite,
                }
            )
            if done:
                break
        metrics = {
            "completedSteps": completed,
            "requiredSteps": horizon,
            "minimumBaseHeight": minimum_height,
            "minimumUprightCosine": minimum_upright,
            "maximumBaseTranslation": maximum_translation,
            "maximumBaseLateralDrift": maximum_lateral,
            "maximumTerminalLinearSpeed": terminal_linear,
            "maximumTerminalAngularSpeed": terminal_angular,
            "nonFiniteSamples": nonfinite,
            "doneSeen": done_seen,
        }
        return assess_viability_metrics(metrics, gates), actions, trace

    baseline_residual = np.zeros((knot_count, action_size), dtype=np.float32)
    baseline_assessment, _baseline_actions, baseline_trace = detailed_rollout(
        "frozen_policy_baseline",
        baseline_residual,
    )
    baseline_matches, baseline_deltas = _baseline_matches(
        baseline_assessment["metrics"],
        profile["baselineReproduction"]["metrics"],
        float(profile["baselineReproduction"]["absoluteTolerance"]),
    )
    if not baseline_matches:
        raise TrainingError(
            "MANIPULATION_VIABILITY_BASELINE_MISMATCH",
            "The diagnostic did not reproduce the archived v14 failed trajectory.",
            {"deltas": baseline_deltas},
        )

    mean = jp.zeros((knot_count, action_size))
    stddev = jp.full((knot_count, action_size), float(search["initialStddev"]))
    best_score = float("-inf")
    best_residual = baseline_residual
    progress: list[dict[str, Any]] = []
    for iteration in range(int(search["maximumIterations"])):
        (
            mean,
            stddev,
            candidate_residual,
            candidate_score,
            candidate_success,
            candidate_metrics,
            success_count,
        ) = search_iteration(
            jax.random.fold_in(
                jax.random.PRNGKey(int(search["searchSeed"])),
                iteration,
            ),
            mean,
            stddev,
        )
        jax.block_until_ready(candidate_score)
        score = float(np.asarray(candidate_score))
        if score > best_score:
            best_score = score
            best_residual = np.asarray(candidate_residual, dtype=np.float32)
        progress.append(
            {
                "iteration": iteration + 1,
                "bestScore": score,
                "successfulCandidates": int(np.asarray(success_count)),
                "bestCandidateSuccess": bool(np.asarray(candidate_success)),
                "bestCandidateMetrics": {
                    key: (
                        bool(np.asarray(value))
                        if getattr(value, "dtype", None) == np.dtype(bool)
                        else float(np.asarray(value))
                    )
                    for key, value in candidate_metrics.items()
                },
                "meanStddev": float(np.asarray(jp.mean(stddev))),
            }
        )

    candidate_assessment, candidate_actions, candidate_trace = detailed_rollout(
        "best_search_candidate",
        best_residual,
    )
    witness_found = candidate_assessment["result"] == "pass"
    witness_status = "found" if witness_found else "not_found"
    conclusion = "constructive_witness" if witness_found else "unknown"
    output_dir.mkdir(parents=True, exist_ok=True)

    candidate = {
        "artifactVersion": "0.1.0",
        "status": "witness" if witness_found else "best_candidate_not_witness",
        "method": search["algorithm"],
        "snapshotBankIndex": actual_index,
        "evaluationSeed": profile["sourceFailure"]["evaluationSeed"],
        "actionEnvelope": [action_minimum, action_maximum],
        "residualKnots": best_residual.tolist(),
        "actions": candidate_actions,
        "assessment": candidate_assessment,
        "claimBoundary": {
            "constructiveWitness": witness_found,
            "notFoundIsInfeasibilityProof": False,
        },
    }
    candidate_path = output_dir / "viability-witness.json"
    candidate_path.write_bytes(canonical_bytes(candidate))
    progress_path = output_dir / "viability-search-progress.json"
    progress_path.write_bytes(
        canonical_bytes(
            {
                "progressVersion": "0.1.0",
                "algorithm": search["algorithm"],
                "iterations": progress,
            }
        )
    )
    trace_path = output_dir / "evaluation-traces.jsonl"
    with trace_path.open("w", encoding="utf-8") as stream:
        for record in [*baseline_trace, *candidate_trace]:
            stream.write(
                json.dumps(
                    record,
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n"
            )

    diagnostic_passed = (
        baseline_matches
        and actual_index == profile["snapshotBank"]["criticalSnapshotIndex"]
        and len(progress) == search["maximumIterations"]
        and all(item["successfulCandidates"] >= 0 for item in progress)
    )
    return {
        "profileDigest": digest_json(profile),
        "sourceManipulationProfileDigest": digest_json(manipulation_profile),
        "sourceFailure": profile["sourceFailure"],
        "staticPreflight": static,
        "runtimePreflight": runtime,
        "target": {
            **derivation,
            "observationSize": observation_size,
            "actionSize": action_size,
        },
        "checkpoint": checkpoint_metadata,
        "snapshotBank": {
            **profile["snapshotBank"],
            "materializedInitialIndex": actual_index,
        },
        "search": {
            **search,
            "iterationsExecuted": len(progress),
            "bestScore": best_score,
        },
        "diagnosticAssessment": {
            "status": "passed" if diagnostic_passed else "failed",
            "baselineReproduced": baseline_matches,
            "baselineMetricAbsoluteDeltas": baseline_deltas,
            "searchCompleted": len(progress) == search["maximumIterations"],
        },
        "witnessAssessment": {
            "status": witness_status,
            "recoverabilityConclusion": conclusion,
            "formalWitnessGate": "passed" if witness_found else "failed",
            "notFoundIsInfeasibilityProof": False,
        },
        "qualityAssessment": {
            "status": "passed" if witness_found else "failed",
            "tests": [
                {
                    "id": "test://worldspec/h1/manipulation-viability/baseline",
                    **baseline_assessment,
                },
                {
                    "id": "test://worldspec/h1/manipulation-viability/best-candidate",
                    **candidate_assessment,
                },
            ],
        },
        "candidateArtifact": {
            "path": candidate_path.name,
            "digest": digest_bytes(candidate_path.read_bytes()),
            "sizeBytes": candidate_path.stat().st_size,
            "distribution": "internal_only",
        },
        "searchProgressArtifact": {
            "path": progress_path.name,
            "digest": digest_bytes(progress_path.read_bytes()),
            "sizeBytes": progress_path.stat().st_size,
            "distribution": "internal_only",
        },
        "traceArtifact": {
            "path": trace_path.name,
            "digest": digest_bytes(trace_path.read_bytes()),
            "sizeBytes": trace_path.stat().st_size,
            "recordCount": len(baseline_trace) + len(candidate_trace),
            "distribution": "internal_only",
        },
        "controllerStatus": "non_publishable",
        "claimBoundary": profile["claimBoundary"],
    }
