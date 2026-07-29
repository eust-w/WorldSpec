"""Zero-training H1 motion-to-stand dual-policy switch probe."""

from __future__ import annotations

import copy
import functools
import json
import tempfile
from pathlib import Path
from typing import Any

from .contract import canonical_bytes, digest_bytes, digest_json, validate_profile
from .errors import TrainingError
from .midterm import _load_deterministic_teacher_policy
from .model import prepare_training_model
from .preflight import runtime_preflight, static_preflight
from .trainer import _flat_observation_size
from .warm_start import materialize_warm_start, validate_network_compatibility

MOTION_POLICY_SOURCE = {
    "sourceStage": "loaded-track-settle-transition-v2-failed",
    "sourceReportDigest": (
        "sha256:1d7310274a58e78e21570fe0916c23af49573f41d769037393967d41ce89705d"
    ),
    "checkpointDigest": ("sha256:2e4590c9291c81581205aee02c4bf168b9532790a14aecac839faee68954d356"),
    "checkpointSizeBytes": 8_838_595,
    "distribution": "internal_only",
    "selectedRole": "motion",
}
STAND_POLICY_SOURCE = {
    "sourceStage": "stand-v2.1",
    "sourceReportDigest": (
        "sha256:8a92a910ca52540fff50bab37e20e7e28d4ea06ae0acd20d0079e8b45e65f660"
    ),
    "checkpointDigest": ("sha256:fc91edb936de7391b7e075596e5aaa944acc656664cdb820dbb21c149cf7921c"),
    "checkpointSizeBytes": 6_280_684,
    "distribution": "internal_only",
    "selectedRole": "zero_velocity_and_stand",
}
SUPERVISOR = {
    "mode": "command_state_machine",
    "motionCommandThreshold": 0.05,
    "moveSteps": 150,
    "settleSteps": 50,
    "handoff": {
        "mode": "linear_action_blend",
        "blendSteps": 5,
        "durationSeconds": 0.1,
        "observationCommand": [0.0, 0.0, 0.0],
    },
    "standRegressionPolicy": "standPolicy",
}
QUALITY_GATES = {
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


def validate_dual_policy_profile(
    base_profile: dict[str, Any],
    profile: dict[str, Any],
) -> None:
    """Validate the immutable A2 probe contract and both policy lineages."""

    validate_profile(base_profile)
    if (
        profile.get("profileVersion") != "0.1.0"
        or profile.get("status") != "research"
        or profile.get("stage") != "dual_policy_switch_probe"
    ):
        raise TrainingError(
            "DUAL_POLICY_PROFILE_UNSUPPORTED",
            "A2 must use the dual_policy_switch_probe research profile v0.1.",
        )
    if profile.get("baseTrainingProfileDigest") != digest_json(base_profile):
        raise TrainingError(
            "DUAL_POLICY_BASE_PROFILE_MISMATCH",
            "A2 is not bound to the exact base training Profile.",
        )
    if profile.get("motionPolicy") != MOTION_POLICY_SOURCE:
        raise TrainingError(
            "DUAL_POLICY_MOTION_SOURCE_MISMATCH",
            "A2 must bind the frozen transition-v2 motion checkpoint.",
        )
    if profile.get("standPolicy") != STAND_POLICY_SOURCE:
        raise TrainingError(
            "DUAL_POLICY_STAND_SOURCE_MISMATCH",
            "A2 must bind the passing stand-v2.1 checkpoint.",
        )
    if profile.get("supervisor") != SUPERVISOR:
        raise TrainingError(
            "DUAL_POLICY_SUPERVISOR_INVALID",
            "A2 must use the frozen five-step linear action handoff.",
        )
    if profile.get("qualityGates") != QUALITY_GATES:
        raise TrainingError(
            "DUAL_POLICY_QUALITY_GATES_INVALID",
            "A2 cannot relax the existing walk/settle or stand gates.",
        )
    runtime = profile.get("runtime", {})
    if runtime.get("ccdIterations") != 50:
        raise TrainingError(
            "DUAL_POLICY_CCD_ITERATIONS_INVALID",
            "A2 requires the passing bounded CCD=50 setting.",
        )
    if runtime.get("evaluationEnvironments") != 1:
        raise TrainingError(
            "DUAL_POLICY_ENVIRONMENT_COUNT_INVALID",
            "A2 evaluates one deterministic environment at a time.",
        )
    if (
        runtime.get("containerDigest")
        != (runtime.get("containerImage", "").rsplit("@", maxsplit=1)[-1])
    ):
        raise TrainingError(
            "DUAL_POLICY_CONTAINER_BINDING_MISMATCH",
            "A2 containerImage and containerDigest must identify one OCI image.",
        )
    if runtime.get("packageLockDigest") != base_profile["runtime"]["packageLockDigest"]:
        raise TrainingError(
            "DUAL_POLICY_PACKAGE_LOCK_MISMATCH",
            "A2 must use the base Profile package lock.",
        )
    if profile.get("artifactPolicy") != {
        "controller": "research_only",
        "distribution": "internal_only",
    }:
        raise TrainingError(
            "DUAL_POLICY_ARTIFACT_POLICY_INVALID",
            "A2 controller evidence must remain internal research material.",
        )


def make_dual_policy_evaluation_profile(
    base_profile: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    """Build an evaluation-only effective Profile without training overrides."""

    validate_dual_policy_profile(base_profile, profile)
    effective = copy.deepcopy(base_profile)
    effective["runtime"]["containerDigest"] = profile["runtime"]["containerDigest"]
    effective["runtime"]["packageLockDigest"] = profile["runtime"]["packageLockDigest"]
    effective["runtime"]["ccdIterations"] = profile["runtime"]["ccdIterations"]
    effective["training"]["numEnvs"] = profile["runtime"]["evaluationEnvironments"]
    effective["validation"] = copy.deepcopy(profile["qualityGates"])
    return effective


def action_handoff(
    motion_action,
    stand_action,
    step_index: int,
    move_steps: int = 150,
    blend_steps: int = 5,
):
    """Select or blend actions according to the frozen supervisor."""

    if step_index < move_steps:
        return motion_action, "motion", 0.0
    if step_index < move_steps + blend_steps:
        alpha = (step_index - move_steps + 1) / blend_steps
        return (1.0 - alpha) * motion_action + alpha * stand_action, "blend", alpha
    return stand_action, "stand", 1.0


def evaluate_dual_policy_suite(
    profile: dict[str, Any],
    env,
    motion_policy,
    stand_policy,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run five switched walk/settle and five stand-only regression episodes."""

    import jax
    import jax.numpy as jp
    import numpy as np

    motion_inference = jax.jit(motion_policy)
    stand_inference = jax.jit(stand_policy)
    reset = jax.jit(env.reset)
    step = jax.jit(env.step)
    validation = profile["validation"]
    dt = profile["training"]["simulationTimestepSeconds"] * profile["control"]["controlDecimation"]
    duration_steps = max(1, round(validation["nominalDurationSeconds"] / dt))
    move_steps = SUPERVISOR["moveSteps"]
    settle_steps = SUPERVISOR["settleSteps"]
    blend_steps = SUPERVISOR["handoff"]["blendSteps"]
    required = validation["requiredConsecutivePasses"]
    if duration_steps != move_steps + settle_steps:
        raise TrainingError(
            "DUAL_POLICY_TIMING_MISMATCH",
            "A2 duration must resolve to exactly 150 move and 50 settle steps.",
            {"durationSteps": duration_steps},
        )
    tests: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []

    def with_command(state, command):
        info = dict(state.info)
        info["command"] = command
        info["transition_active"] = jp.asarray(False)
        info["stand_replay_active"] = jp.asarray(False)
        observation = {
            "state": env._observation(
                state.data,
                info["last_action"],
                command,
            )
        }
        return state.replace(info=info, obs=observation)

    def run(run_index: int, mode: str) -> dict[str, Any]:
        rng = jax.random.PRNGKey(profile["training"]["seed"] + run_index)
        state = reset(rng)
        start_xy = np.asarray(state.data.qpos[:2], dtype=float)
        minimum_height = float("inf")
        minimum_upright = float("inf")
        maximum_planar_drift = 0.0
        maximum_settle_linear_speed = 0.0
        maximum_settle_angular_speed = 0.0
        maximum_action_jump_norm = 0.0
        squared_tracking_error = 0.0
        tracking_samples = 0
        nonfinite = 0
        done_seen = False
        terminal_reasons: set[str] = set()
        completed_steps = 0
        previous_action = None
        for index in range(duration_steps):
            moving = mode == "walk_settle" and index < move_steps
            command = jp.asarray([0.5, 0.0, 0.0]) if moving else jp.zeros(3)
            state = with_command(state, command)
            rng, motion_rng, stand_rng = jax.random.split(rng, 3)
            if mode == "stand_regression":
                action, _ = stand_inference(state.obs, stand_rng)
                active_policy = "stand"
                blend_alpha = 1.0
            elif moving:
                action, _ = motion_inference(state.obs, motion_rng)
                active_policy = "motion"
                blend_alpha = 0.0
            else:
                motion_action, _ = motion_inference(state.obs, motion_rng)
                stand_action, _ = stand_inference(state.obs, stand_rng)
                action, active_policy, blend_alpha = action_handoff(
                    motion_action,
                    stand_action,
                    index,
                    move_steps,
                    blend_steps,
                )
            action_array = np.asarray(action, dtype=float)
            action_jump_norm = (
                0.0
                if previous_action is None
                else float(np.linalg.norm(action_array - previous_action))
            )
            maximum_action_jump_norm = max(maximum_action_jump_norm, action_jump_norm)
            previous_action = action_array
            state = step(state, action)
            jax.block_until_ready(state.reward)
            qpos = np.asarray(state.data.qpos)
            qvel = np.asarray(state.data.qvel)
            local_velocity = np.asarray(env.local_velocity(state.data), dtype=float)
            angular_velocity = np.asarray(env.angular_velocity(state.data), dtype=float)
            height = float(np.asarray(state.data.xpos[env.pelvis_body_id, 2]))
            upright = float(np.asarray(env.upvector(state.data)[2]))
            finite = bool(
                np.isfinite(qpos).all()
                and np.isfinite(qvel).all()
                and np.isfinite(action_array).all()
            )
            done = bool(np.asarray(state.done))
            position = np.asarray(qpos[:2], dtype=float)
            minimum_height = min(minimum_height, height)
            minimum_upright = min(minimum_upright, upright)
            maximum_planar_drift = max(
                maximum_planar_drift,
                float(np.linalg.norm(position - start_xy)),
            )
            nonfinite += 0 if finite else 1
            completed_steps += 1
            if moving:
                squared_tracking_error += float((local_velocity[0] - 0.5) ** 2)
                tracking_samples += 1
            if index >= duration_steps - settle_steps:
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
                    "suite": mode,
                    "run": run_index,
                    "step": index,
                    "timeSeconds": (index + 1) * dt,
                    "command": [float(value) for value in np.asarray(command)],
                    "activePolicy": active_policy,
                    "blendAlpha": blend_alpha,
                    "actionJumpNorm": action_jump_norm,
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
                and maximum_settle_linear_speed <= validation["maximumSettleLinearSpeed"]
                and maximum_settle_angular_speed <= validation["maximumSettleAngularSpeed"]
            )
        else:
            passed = common and maximum_planar_drift <= validation["maximumStandPlanarDrift"]
        return {
            "id": f"test://worldspec/h1-dual-policy/{mode}/{run_index + 1}",
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
                "maximumSettleLinearSpeed": maximum_settle_linear_speed,
                "maximumSettleAngularSpeed": maximum_settle_angular_speed,
                "maximumActionJumpNorm": maximum_action_jump_norm,
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


def run_dual_policy_probe(
    base_profile: dict[str, Any],
    profile: dict[str, Any],
    bundle_dir: Path,
    model_dir: Path,
    output_dir: Path,
    motion_archive: Path,
    stand_archive: Path,
) -> dict[str, Any]:
    """Load two frozen policies and evaluate their deterministic supervisor."""

    from brax.training.agents.ppo import networks as ppo_networks

    from .environment import make_environment

    effective = make_dual_policy_evaluation_profile(base_profile, profile)
    static = static_preflight(base_profile, bundle_dir)
    training_model, derivation = prepare_training_model(base_profile, bundle_dir, model_dir)
    runtime = runtime_preflight(effective, training_model)
    output_dir.mkdir(parents=True, exist_ok=True)
    network_factory = functools.partial(
        ppo_networks.make_ppo_networks,
        policy_hidden_layer_sizes=(128, 128, 128, 128),
        value_hidden_layer_sizes=(256, 256, 256, 256, 256),
        policy_obs_key="state",
        value_obs_key="state",
    )
    environment = make_environment(effective, training_model)
    observation_size = _flat_observation_size(environment.observation_size["state"])
    action_size = int(environment.action_size)
    with tempfile.TemporaryDirectory(prefix="worldspec-h1-dual-policy-") as temporary:
        root = Path(temporary)
        motion_step, motion_initialization = materialize_warm_start(
            motion_archive,
            root / "motion",
            profile["motionPolicy"]["checkpointDigest"],
            profile["motionPolicy"]["checkpointSizeBytes"],
        )
        stand_step, stand_initialization = materialize_warm_start(
            stand_archive,
            root / "stand",
            profile["standPolicy"]["checkpointDigest"],
            profile["standPolicy"]["checkpointSizeBytes"],
        )
        validate_network_compatibility(
            motion_initialization,
            observation_size,
            action_size,
        )
        validate_network_compatibility(
            stand_initialization,
            observation_size,
            action_size,
        )
        motion_policy = _load_deterministic_teacher_policy(
            motion_step,
            motion_initialization,
            network_factory,
        )
        stand_policy = _load_deterministic_teacher_policy(
            stand_step,
            stand_initialization,
            network_factory,
        )
        tests, traces = evaluate_dual_policy_suite(
            effective,
            environment,
            motion_policy,
            stand_policy,
        )
    motion_initialization["role"] = "motion"
    stand_initialization["role"] = "zero_velocity_and_stand"
    controller = {
        "controllerVersion": "0.1.0",
        "status": "research_only",
        "dualPolicyProfileDigest": digest_json(profile),
        "baseTrainingProfileDigest": digest_json(base_profile),
        "motionPolicy": {
            "checkpointDigest": motion_initialization["archiveDigest"],
            "selectedStep": motion_initialization["selectedStep"],
        },
        "standPolicy": {
            "checkpointDigest": stand_initialization["archiveDigest"],
            "selectedStep": stand_initialization["selectedStep"],
        },
        "supervisor": copy.deepcopy(profile["supervisor"]),
        "distribution": "internal_only",
    }
    controller_path = output_dir / "dual-policy-controller.json"
    controller_path.write_bytes(canonical_bytes(controller))
    trace_path = output_dir / "evaluation-traces.jsonl"
    with trace_path.open("w", encoding="utf-8") as stream:
        for record in traces:
            stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    expected_tests = profile["qualityGates"]["requiredConsecutivePasses"] * 2
    tests_gate = len(tests) == expected_tests and all(item["result"] == "pass" for item in tests)
    return {
        "baseTrainingProfileDigest": digest_json(base_profile),
        "dualPolicyProfileDigest": digest_json(profile),
        "motionPolicy": motion_initialization,
        "standPolicy": stand_initialization,
        "runtimeCapacity": {
            **base_profile["runtime"]["mjxCapacity"],
            "effectiveNaconmax": (
                base_profile["runtime"]["mjxCapacity"]["activeContactsPerEnvironment"]
                * effective["training"]["numEnvs"]
            ),
            "effectiveNaccdmax": (
                base_profile["runtime"]["mjxCapacity"]["ccdContactsPerEnvironment"]
                * effective["training"]["numEnvs"]
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
        "supervisor": copy.deepcopy(profile["supervisor"]),
        "qualityAssessment": {
            "status": "passed" if tests_gate else "failed",
            "deterministicSuiteGate": tests_gate,
            "tests": tests,
        },
        "controllerArtifact": {
            "path": controller_path.name,
            "digest": digest_bytes(controller_path.read_bytes()),
            "sizeBytes": controller_path.stat().st_size,
            "distribution": "internal_only",
        },
        "traceArtifact": {
            "path": trace_path.name,
            "digest": digest_bytes(trace_path.read_bytes()),
            "sizeBytes": trace_path.stat().st_size,
            "distribution": "internal_only",
        },
    }
