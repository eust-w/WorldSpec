"""Deterministic H1 walk/settle and stand-regression policy evaluation."""

from __future__ import annotations

from typing import Any


def evaluate_policy_suite(
    profile: dict[str, Any],
    env,
    make_inference_fn,
    params,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run five walk/settle and five zero-command regression tests."""

    import jax
    import jax.numpy as jp
    import numpy as np

    inference = jax.jit(make_inference_fn(params, deterministic=True))
    reset = jax.jit(env.reset)
    step = jax.jit(env.step)
    validation = profile["validation"]
    dt = profile["training"]["simulationTimestepSeconds"] * profile["control"]["controlDecimation"]
    duration_steps = max(1, round(validation["nominalDurationSeconds"] / dt))
    move_steps = max(1, round(validation["moveDurationSeconds"] / dt))
    settle_steps = max(1, round(validation["settleWindowSeconds"] / dt))
    settle_measurement_seconds = validation.get(
        "settleMeasurementWindowSeconds",
        validation["settleWindowSeconds"],
    )
    settle_measurement_steps = max(1, round(settle_measurement_seconds / dt))
    if settle_measurement_steps > settle_steps:
        raise ValueError("settle measurement window cannot exceed the settle phase")
    required = validation["requiredConsecutivePasses"]
    tests: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []

    def run(run_index: int, mode: str) -> dict[str, Any]:
        rng = jax.random.PRNGKey(profile["training"]["seed"] + run_index)
        state = reset(rng)
        start_xy = np.asarray(state.data.qpos[:2], dtype=float)
        minimum_height = float("inf")
        minimum_upright = float("inf")
        maximum_planar_drift = 0.0
        maximum_settle_linear_speed = 0.0
        maximum_settle_angular_speed = 0.0
        maximum_teacher_action_mse = 0.0
        maximum_stand_teacher_action_mse = 0.0
        maximum_settle_teacher_action_mse = 0.0
        squared_tracking_error = 0.0
        tracking_samples = 0
        nonfinite = 0
        done_seen = False
        terminal_reasons: set[str] = set()
        completed_steps = 0
        for index in range(duration_steps):
            moving = mode == "walk_settle" and index < move_steps
            command = jp.asarray([0.5, 0.0, 0.0]) if moving else jp.zeros(3)
            info = dict(state.info)
            info["command"] = command
            info["transition_active"] = jp.asarray(mode == "walk_settle")
            info["stand_replay_active"] = jp.asarray(mode == "stand_regression")
            state = state.replace(info=info)
            rng, action_rng = jax.random.split(rng)
            action, _ = inference(state.obs, action_rng)
            state = step(state, action)
            jax.block_until_ready(state.reward)
            qpos = np.asarray(state.data.qpos)
            qvel = np.asarray(state.data.qvel)
            local_velocity = np.asarray(env.local_velocity(state.data), dtype=float)
            angular_velocity = np.asarray(env.angular_velocity(state.data), dtype=float)
            height = float(np.asarray(state.data.xpos[env.pelvis_body_id, 2]))
            upright = float(np.asarray(env.upvector(state.data)[2]))
            finite = bool(np.isfinite(qpos).all() and np.isfinite(qvel).all())
            done = bool(np.asarray(state.done))
            teacher_action_mse = float(
                np.asarray(state.metrics.get("cost/teacher_action_mse", 0.0))
            )
            stand_teacher_action_mse = float(
                np.asarray(state.metrics.get("cost/stand_teacher_action_mse", 0.0))
            )
            settle_teacher_action_mse = float(
                np.asarray(state.metrics.get("cost/settle_teacher_action_mse", 0.0))
            )
            position = np.asarray(qpos[:2], dtype=float)
            minimum_height = min(minimum_height, height)
            minimum_upright = min(minimum_upright, upright)
            maximum_planar_drift = max(
                maximum_planar_drift,
                float(np.linalg.norm(position - start_xy)),
            )
            maximum_teacher_action_mse = max(
                maximum_teacher_action_mse,
                teacher_action_mse,
            )
            maximum_stand_teacher_action_mse = max(
                maximum_stand_teacher_action_mse,
                stand_teacher_action_mse,
            )
            maximum_settle_teacher_action_mse = max(
                maximum_settle_teacher_action_mse,
                settle_teacher_action_mse,
            )
            nonfinite += 0 if finite else 1
            completed_steps += 1
            if moving:
                squared_tracking_error += float((local_velocity[0] - 0.5) ** 2)
                tracking_samples += 1
            if index >= duration_steps - settle_measurement_steps:
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
                    "basePosition": [float(qpos[0]), float(qpos[1]), height],
                    "uprightCosine": upright,
                    "localVelocity": [float(value) for value in local_velocity],
                    "angularVelocity": [float(value) for value in angular_velocity],
                    "teacherActionMse": teacher_action_mse,
                    "standTeacherActionMse": stand_teacher_action_mse,
                    "settleTeacherActionMse": settle_teacher_action_mse,
                    "taskLoadScale": float(np.asarray(state.info.get("task_load_scale", 0.0))),
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
            "id": (f"test://worldspec/h1-policy/{mode}/{run_index + 1}"),
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
                "settleMeasurementWindowSeconds": settle_measurement_seconds,
                "maximumTeacherActionMse": maximum_teacher_action_mse,
                "maximumStandTeacherActionMse": (maximum_stand_teacher_action_mse),
                "maximumSettleTeacherActionMse": (maximum_settle_teacher_action_mse),
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
