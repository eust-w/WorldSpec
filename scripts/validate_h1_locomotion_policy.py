#!/usr/bin/env python3
"""Execute the locked Unitree H1 policy against a composed H1 bundle.

The adapter maps the policy's ten leg joints by stable MuJoCo names instead of
assuming every qpos after the floating base belongs to the policy. Upper-body
PD hold and gripper commands are separate, explicit control channels.
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = ROOT / "third_party" / "h1-kitchen.lock.json"
DEFAULT_PROFILE = ROOT / "examples" / "h1-kitchen" / "locomotion-adapter-profile.json"

sys.path.insert(0, str(ROOT / "scripts"))
from compose_h1_robotiq import (
    CompositionError,
    canonical_bytes,
    digest_json,
    find_source,
    parse_xml,
    repository_path,
    verify_cache,
)
from fetch_h1_kitchen_sources import digest_file, read_lock, safe_relative
from validate_h1_composition import safe_file, validate_inventory


class PolicyValidationError(RuntimeError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PolicyValidationError(f"expected JSON object: {path}")
    return value


def locked_file(
    cache: Path,
    lock: dict[str, Any],
    reference: dict[str, Any],
) -> Path:
    index, _source, component = find_source(lock, reference["componentId"])
    if component["kind"] != "files":
        raise PolicyValidationError("policy references must use a locked files component")
    locked = next(
        (item for item in component["files"] if item["path"] == reference["path"]),
        None,
    )
    if locked is None:
        raise PolicyValidationError(f"file is absent from source lock: {reference['path']}")
    if locked["digest"] != reference["digest"]:
        raise PolicyValidationError(f"profile digest differs from source lock: {reference['path']}")
    path = safe_relative(repository_path(cache, index), reference["path"])
    if digest_file(path) != locked["digest"]:
        raise PolicyValidationError(f"cached file digest mismatch: {reference['path']}")
    return path


def equal_lengths(label: str, values: list[list[Any]]) -> int:
    lengths = {len(value) for value in values}
    if len(lengths) != 1:
        raise PolicyValidationError(f"{label} arrays have inconsistent lengths: {lengths}")
    return next(iter(lengths))


def validate_profile(profile: dict[str, Any], lock_digest: str) -> None:
    if profile.get("profileVersion") != "0.1.0":
        raise PolicyValidationError("unsupported locomotion profileVersion")
    if profile.get("sourceLockDigest") != lock_digest:
        raise PolicyValidationError("locomotion profile does not bind the selected source lock")
    leg = profile["legControl"]
    count = equal_lengths(
        "legControl",
        [
            leg["joints"],
            leg["actuators"],
            leg["kps"],
            leg["kds"],
            leg["defaultAngles"],
        ],
    )
    observation = profile["observation"]
    if count != observation["actions"]:
        raise PolicyValidationError("leg count differs from observation.actions")
    if observation["dimensions"] != 9 + 3 * count + 2:
        raise PolicyValidationError("observation dimensions do not match adapter layout")
    upper = profile["upperBodyHold"]
    equal_lengths(
        "upperBodyHold",
        [
            upper["joints"],
            upper["actuators"],
            upper["targets"],
            upper["kps"],
            upper["kds"],
        ],
    )
    simulation = profile["simulation"]
    if (
        simulation["timestepSeconds"] <= 0
        or simulation["controlDecimation"] < 1
        or simulation["durationSeconds"] <= 0
    ):
        raise PolicyValidationError("simulation parameters must be positive")


def gravity_orientation(quaternion: Any, np: Any) -> Any:
    qw, qx, qy, qz = quaternion
    return np.array(
        [
            2 * (-qz * qx + qw * qy),
            -2 * (qz * qy + qw * qx),
            1 - 2 * (qw * qw + qz * qz),
        ],
        dtype=np.float32,
    )


def diagnostic(code: str, message: str) -> dict[str, Any]:
    return {"code": code, "severity": "error", "message": message}


def test(
    identifier: str,
    result: str,
    metrics: dict[str, Any] | None = None,
    diagnostics: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": identifier,
        "result": result,
        "metrics": metrics or {},
        "diagnostics": diagnostics or [],
    }


def summarize(tests: list[dict[str, Any]]) -> dict[str, Any]:
    values = {
        "passed": sum(item["result"] == "pass" for item in tests),
        "failed": sum(item["result"] == "fail" for item in tests),
        "unknown": sum(item["result"] == "unknown" for item in tests),
        "notRun": sum(item["result"] == "not_run" for item in tests),
    }
    if values["failed"]:
        overall = "fail"
    elif values["unknown"] or values["notRun"]:
        overall = "incomplete"
    else:
        overall = "pass"
    return {**values, "overall": overall}


def named_indices(
    model: Any,
    mujoco: Any,
    names: list[str],
    object_type: Any,
    address: Any | None = None,
) -> list[int]:
    result = []
    missing = []
    for name in names:
        identifier = mujoco.mj_name2id(model, object_type, name)
        if identifier < 0:
            missing.append(name)
        else:
            result.append(int(address[identifier]) if address is not None else int(identifier))
    if missing:
        raise PolicyValidationError(f"model is missing named controls: {missing}")
    return result


def set_clamped_control(model: Any, data: Any, actuator: int, value: float) -> bool:
    clipped = value
    saturated = False
    if model.actuator_ctrllimited[actuator]:
        lower, upper = model.actuator_ctrlrange[actuator]
        clipped = min(max(value, float(lower)), float(upper))
        saturated = clipped != value
    data.ctrl[actuator] = clipped
    return saturated


def model_assets(bundle: Path, manifest: dict[str, Any]) -> dict[str, bytes]:
    assets: dict[str, bytes] = {}
    for artifact in manifest["artifacts"]:
        relative = artifact["path"]
        if not relative.startswith("assets/"):
            continue
        payload = safe_file(bundle, relative).read_bytes()
        assets[relative] = payload
    return assets


def evaluation_xml(bundle: Path, manifest: dict[str, Any]) -> str:
    model_path = safe_file(bundle, manifest["model"])
    tree = parse_xml(model_path)
    root = tree.getroot()
    worldbody = root.find("worldbody")
    if worldbody is None:
        raise PolicyValidationError("composed model has no worldbody")
    if any(geom.get("name") == "worldspec_policy_test_floor" for geom in worldbody.findall("geom")):
        raise PolicyValidationError("composed model already contains the reserved test floor")
    worldbody.append(
        ET.Element(
            "geom",
            {
                "name": "worldspec_policy_test_floor",
                "type": "plane",
                "size": "0 0 0.05",
                "friction": "1 0.005 0.0001",
            },
        )
    )
    return ET.tostring(root, encoding="unicode")


def run_policy(
    bundle: Path,
    manifest: dict[str, Any],
    profile: dict[str, Any],
    policy_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    tests: list[dict[str, Any]] = []
    inventory_ok, inventory_errors = validate_inventory(bundle, manifest)
    tests.append(
        test(
            "test://worldspec/h1-policy/artifact-integrity",
            "pass" if inventory_ok else "fail",
            {"artifactCount": len(manifest.get("artifacts", []))},
            [
                diagnostic("H1_POLICY_ARTIFACT_INTEGRITY_FAILED", message)
                for message in inventory_errors
            ],
        )
    )
    try:
        import mujoco
        import numpy as np
        import torch
    except (ImportError, OSError) as exc:
        tests.append(
            test(
                "test://worldspec/h1-policy/runtime",
                "not_run",
                diagnostics=[diagnostic("H1_POLICY_RUNTIME_UNAVAILABLE", str(exc))],
            )
        )
        return tests, {"mujoco": "unavailable", "torch": "unavailable", "numpy": "unavailable"}
    versions = {"mujoco": mujoco.__version__, "torch": torch.__version__, "numpy": np.__version__}
    if not inventory_ok:
        tests.append(
            test(
                "test://worldspec/h1-policy/runtime",
                "not_run",
                diagnostics=[
                    diagnostic(
                        "H1_POLICY_INTEGRITY_REQUIRED",
                        "policy execution is blocked until bundle integrity passes",
                    )
                ],
            )
        )
        return tests, versions

    model = mujoco.MjModel.from_xml_string(
        evaluation_xml(bundle, manifest),
        assets=model_assets(bundle, manifest),
    )
    simulation = profile["simulation"]
    model.opt.timestep = simulation["timestepSeconds"]
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)

    leg = profile["legControl"]
    upper = profile["upperBodyHold"]
    leg_qpos = named_indices(
        model, mujoco, leg["joints"], mujoco.mjtObj.mjOBJ_JOINT, model.jnt_qposadr
    )
    leg_qvel = named_indices(
        model, mujoco, leg["joints"], mujoco.mjtObj.mjOBJ_JOINT, model.jnt_dofadr
    )
    leg_actuators = named_indices(
        model, mujoco, leg["actuators"], mujoco.mjtObj.mjOBJ_ACTUATOR
    )
    upper_qpos = named_indices(
        model, mujoco, upper["joints"], mujoco.mjtObj.mjOBJ_JOINT, model.jnt_qposadr
    )
    upper_qvel = named_indices(
        model, mujoco, upper["joints"], mujoco.mjtObj.mjOBJ_JOINT, model.jnt_dofadr
    )
    upper_actuators = named_indices(
        model, mujoco, upper["actuators"], mujoco.mjtObj.mjOBJ_ACTUATOR
    )
    gripper_actuators = [
        (
            named_indices(
                model,
                mujoco,
                [command["actuator"]],
                mujoco.mjtObj.mjOBJ_ACTUATOR,
            )[0],
            float(command["value"]),
        )
        for command in profile["gripperControls"]
    ]
    free_joints = [
        index
        for index in range(model.njnt)
        if model.jnt_type[index] == mujoco.mjtJoint.mjJNT_FREE
    ]
    if len(free_joints) != 1:
        raise PolicyValidationError("policy adapter requires exactly one floating base")
    free_qpos = int(model.jnt_qposadr[free_joints[0]])
    free_qvel = int(model.jnt_dofadr[free_joints[0]])

    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    policy = torch.jit.load(str(policy_path), map_location="cpu")
    if hasattr(policy, "reset_memory"):
        policy.reset_memory()
    observation = profile["observation"]
    action_count = observation["actions"]
    action = np.zeros(action_count, dtype=np.float32)
    target = np.asarray(leg["defaultAngles"], dtype=np.float64)
    obs = np.zeros(observation["dimensions"], dtype=np.float32)
    with torch.no_grad():
        initial_action = policy(torch.from_numpy(obs).unsqueeze(0))
    inference_ok = (
        tuple(initial_action.shape) == (1, action_count)
        and bool(torch.isfinite(initial_action).all())
    )
    if hasattr(policy, "reset_memory"):
        policy.reset_memory()
    tests.append(
        test(
            "test://worldspec/h1-policy/binding-and-inference",
            "pass" if inference_ok else "fail",
            {
                "actions": action_count,
                "observations": observation["dimensions"],
                "legJointCount": len(leg_qpos),
                "upperBodyJointCount": len(upper_qpos),
                "gripperActuatorCount": len(gripper_actuators),
                "outputShape": list(initial_action.shape),
                "outputFinite": bool(torch.isfinite(initial_action).all()),
            },
            []
            if inference_ok
            else [
                diagnostic(
                    "H1_POLICY_INTERFACE_MISMATCH",
                    "policy output shape or finite-value contract does not match the profile",
                )
            ],
        )
    )
    if not inference_ok:
        return tests, versions

    dt = float(simulation["timestepSeconds"])
    decimation = int(simulation["controlDecimation"])
    total_steps = round(float(simulation["durationSeconds"]) / dt)
    if not math.isclose(total_steps * dt, float(simulation["durationSeconds"]), abs_tol=1e-12):
        raise PolicyValidationError("duration must be an integer number of simulation steps")
    kps = np.asarray(leg["kps"], dtype=np.float64)
    kds = np.asarray(leg["kds"], dtype=np.float64)
    upper_targets = np.asarray(upper["targets"], dtype=np.float64)
    upper_kps = np.asarray(upper["kps"], dtype=np.float64)
    upper_kds = np.asarray(upper["kds"], dtype=np.float64)
    command = np.asarray(leg["command"], dtype=np.float32)
    command_scale = np.asarray(observation["commandScale"], dtype=np.float32)
    start_position = data.qpos[free_qpos : free_qpos + 3].copy()
    min_height = float(start_position[2])
    min_upright = 1.0
    max_abs_control = 0.0
    control_saturation_count = 0
    finite = True
    joint_limit_violation_samples = 0

    for counter in range(1, total_steps + 1):
        data.ctrl[:] = 0
        q = data.qpos[leg_qpos]
        dq = data.qvel[leg_qvel]
        torques = (target - q) * kps - dq * kds
        for actuator, torque in zip(leg_actuators, torques, strict=True):
            control_saturation_count += set_clamped_control(
                model, data, actuator, float(torque)
            )
        upper_q = data.qpos[upper_qpos]
        upper_dq = data.qvel[upper_qvel]
        upper_torque = (upper_targets - upper_q) * upper_kps - upper_dq * upper_kds
        for actuator, torque in zip(upper_actuators, upper_torque, strict=True):
            control_saturation_count += set_clamped_control(
                model, data, actuator, float(torque)
            )
        for actuator, value in gripper_actuators:
            control_saturation_count += set_clamped_control(model, data, actuator, value)
        max_abs_control = max(max_abs_control, float(np.max(np.abs(data.ctrl))))
        mujoco.mj_step(model, data)

        position = data.qpos[free_qpos : free_qpos + 3]
        quaternion = data.qpos[free_qpos + 3 : free_qpos + 7]
        projected_gravity = gravity_orientation(quaternion, np)
        min_height = min(min_height, float(position[2]))
        min_upright = min(min_upright, float(-projected_gravity[2]))
        finite = finite and bool(
            np.isfinite(data.qpos).all()
            and np.isfinite(data.qvel).all()
            and np.isfinite(data.qacc).all()
            and np.isfinite(data.ctrl).all()
        )
        for joint_name in [*leg["joints"], *upper["joints"]]:
            joint_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, joint_name)
            if model.jnt_limited[joint_id]:
                qpos = data.qpos[model.jnt_qposadr[joint_id]]
                lower, upper_limit = model.jnt_range[joint_id]
                if qpos < lower - 1e-6 or qpos > upper_limit + 1e-6:
                    joint_limit_violation_samples += 1

        if counter % decimation == 0:
            qj = (data.qpos[leg_qpos] - np.asarray(leg["defaultAngles"])) * observation[
                "jointPositionScale"
            ]
            dqj = data.qvel[leg_qvel] * observation["jointVelocityScale"]
            quaternion = data.qpos[free_qpos + 3 : free_qpos + 7]
            omega = data.qvel[free_qvel + 3 : free_qvel + 6] * observation[
                "angularVelocityScale"
            ]
            phase = (counter * dt) % observation["phasePeriodSeconds"] / observation[
                "phasePeriodSeconds"
            ]
            obs[:3] = omega
            obs[3:6] = gravity_orientation(quaternion, np)
            obs[6:9] = command * command_scale
            obs[9 : 9 + action_count] = qj
            obs[9 + action_count : 9 + 2 * action_count] = dqj
            obs[9 + 2 * action_count : 9 + 3 * action_count] = action
            obs[9 + 3 * action_count :] = np.array(
                [np.sin(2 * np.pi * phase), np.cos(2 * np.pi * phase)],
                dtype=np.float32,
            )
            with torch.no_grad():
                output = policy(torch.from_numpy(obs).unsqueeze(0))
            action = output.detach().cpu().numpy().squeeze().astype(np.float32)
            if action.shape != (action_count,) or not np.isfinite(action).all():
                finite = False
                break
            target = action.astype(np.float64) * leg["actionScale"] + np.asarray(
                leg["defaultAngles"], dtype=np.float64
            )

    final_position = data.qpos[free_qpos : free_qpos + 3].copy()
    forward_displacement = float(final_position[0] - start_position[0])
    lateral_drift = abs(float(final_position[1] - start_position[1]))
    tests.append(
        test(
            "test://worldspec/h1-policy/finite-execution",
            "pass" if finite and joint_limit_violation_samples == 0 else "fail",
            {
                "stepsRequested": total_steps,
                "stepsExecuted": counter,
                "simulationTimeSeconds": float(data.time),
                "finite": finite,
                "jointLimitViolationSamples": joint_limit_violation_samples,
                "controlSaturationCount": control_saturation_count,
                "maximumAbsoluteControl": max_abs_control,
            },
            []
            if finite and joint_limit_violation_samples == 0
            else [
                diagnostic(
                    "H1_POLICY_EXECUTION_INVALID",
                    "execution produced non-finite state or exceeded a joint limit",
                )
            ],
        )
    )
    thresholds = profile["validation"]
    behavior_ok = (
        finite
        and min_height >= thresholds["minimumBaseHeight"]
        and min_upright >= thresholds["minimumUprightCosine"]
        and forward_displacement >= thresholds["minimumForwardDisplacement"]
        and lateral_drift <= thresholds["maximumLateralDrift"]
    )
    tests.append(
        test(
            "test://worldspec/h1-policy/short-horizon-locomotion",
            "pass" if behavior_ok else "fail",
            {
                "startPosition": start_position.tolist(),
                "finalPosition": final_position.tolist(),
                "forwardDisplacement": forward_displacement,
                "lateralDrift": lateral_drift,
                "minimumBaseHeight": min_height,
                "minimumUprightCosine": min_upright,
            },
            []
            if behavior_ok
            else [
                diagnostic(
                    "H1_POLICY_BEHAVIOR_OUTSIDE_PROFILE",
                    "short-horizon balance or locomotion fell outside profile thresholds",
                )
            ],
        )
    )
    return tests, versions


def validate(
    bundle: Path,
    cache: Path,
    lock_path: Path,
    profile_path: Path,
) -> dict[str, Any]:
    lock = read_lock(lock_path)
    lock_digest = digest_file(lock_path)
    profile = read_json(profile_path)
    validate_profile(profile, lock_digest)
    try:
        verify_cache(cache, lock, lock_digest)
    except CompositionError as exc:
        raise PolicyValidationError(str(exc)) from exc
    policy_path = locked_file(cache, lock, profile["policy"])
    locked_file(cache, lock, profile["sourceConfig"])
    manifest = read_json(safe_file(bundle, "composition-manifest.json"))
    tests, versions = run_policy(bundle, manifest, profile, policy_path)
    return {
        "id": "conformance://worldspec/h1-locomotion-policy/short-horizon",
        "reportVersion": "0.1.0",
        "bundleDigest": manifest["bundleDigest"],
        "sourceLockDigest": lock_digest,
        "adapterProfileDigest": digest_json(profile),
        "policyDigest": profile["policy"]["digest"],
        "executionEvidence": "executed"
        if versions["mujoco"] != "unavailable"
        else "not_executed",
        "environment": {
            "os": platform.system().lower(),
            "architecture": platform.machine().lower(),
            "python": platform.python_version(),
            **versions,
        },
        "tests": tests,
        "summary": summarize(tests),
        "generatedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite output: {args.output}")
    try:
        report = validate(
            args.bundle.resolve(strict=True),
            args.cache.resolve(strict=True),
            args.lock,
            args.profile,
        )
    except (
        CompositionError,
        PolicyValidationError,
        OSError,
        KeyError,
        json.JSONDecodeError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_bytes(report) + b"\n")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["summary"]["overall"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
