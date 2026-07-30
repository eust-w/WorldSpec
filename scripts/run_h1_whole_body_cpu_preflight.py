#!/usr/bin/env python3
"""Run the A5-C fixed-base MuJoCo torque-tracking preflight."""

from __future__ import annotations

import argparse
import json
import platform
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import mujoco
import numpy as np
from worldspec_h1_training.contract import canonical_bytes, digest_bytes, digest_json
from worldspec_h1_training.whole_body import (
    WHOLE_BODY_GATES,
    WholeBodyTaskSpaceController,
    validate_whole_body_profile,
)


def _ids(model, object_type, names: list[str]) -> np.ndarray:
    return np.asarray(
        [mujoco.mj_name2id(model, object_type, name) for name in names],
        dtype=int,
    )


def _fixed_model(source: Path, destination: Path) -> Path:
    tree = ET.parse(source)
    root = tree.getroot()
    equality = root.find("equality")
    if equality is None:
        equality = ET.SubElement(root, "equality")
    ET.SubElement(
        equality,
        "weld",
        {"name": "worldspec_cpu_fixed_base", "body1": "pelvis"},
    )
    compiler = root.find("compiler")
    meshdir = compiler.get("meshdir") if compiler is not None else None
    if compiler is not None and meshdir:
        compiler.set("meshdir", str((source.parent / meshdir).resolve()))
    tree.write(destination, encoding="utf-8", xml_declaration=True)
    return destination


def run(args: argparse.Namespace) -> dict:
    base = json.loads(args.base_profile.read_text(encoding="utf-8"))
    supervisor = json.loads(args.supervisor_profile.read_text(encoding="utf-8"))
    profile = json.loads(args.control_profile.read_text(encoding="utf-8"))
    validate_whole_body_profile(base, supervisor, profile)
    control = base["control"]
    with tempfile.TemporaryDirectory(prefix="worldspec-h1-a5c-cpu-") as temporary:
        model_path = _fixed_model(args.model.resolve(), Path(temporary) / "model.xml")
        model = mujoco.MjModel.from_xml_path(str(model_path))
        data = mujoco.MjData(model)
        policy_joints = _ids(
            model,
            mujoco.mjtObj.mjOBJ_JOINT,
            control["policyJoints"],
        )
        held_joints = _ids(
            model,
            mujoco.mjtObj.mjOBJ_JOINT,
            control["heldJoints"],
        )
        policy_actuators = _ids(
            model,
            mujoco.mjtObj.mjOBJ_ACTUATOR,
            control["policyActuators"],
        )
        held_actuators = _ids(
            model,
            mujoco.mjtObj.mjOBJ_ACTUATOR,
            control["heldActuators"],
        )
        gripper_actuators = _ids(
            model,
            mujoco.mjtObj.mjOBJ_ACTUATOR,
            control["gripperActuators"],
        )
        policy_qpos = model.jnt_qposadr[policy_joints]
        policy_dofs = model.jnt_dofadr[policy_joints]
        held_qpos = model.jnt_qposadr[held_joints]
        held_dofs = model.jnt_dofadr[held_joints]
        data.qpos[:] = model.qpos0
        data.qpos[policy_qpos] = np.asarray(control["defaultAngles"])
        data.qpos[held_qpos] = np.asarray(control["heldTargets"])
        mujoco.mj_forward(model, data)
        controller = WholeBodyTaskSpaceController(
            model,
            control,
            profile.get("dynamicArmTracking"),
        )
        settled_base = np.asarray(args.settled_base, dtype=float)
        drawer_center = np.asarray(profile["scene"]["drawer"]["closedCenter"], dtype=float)
        handle_target = drawer_center + np.asarray([-0.19, 0.0, 0.055], dtype=float)
        target = handle_target - settled_base + np.asarray(model.qpos0[:3], dtype=float)
        samples: list[dict] = []
        for step in range(args.steps):
            solution = controller.solve(
                data.qpos,
                data.qvel,
                target,
                allow_base=False,
            )
            held_targets = np.asarray(solution["heldTargets"])
            feedforward = np.asarray(solution["feedforwardTorque"])
            for _ in range(control["controlDecimation"]):
                mujoco.mj_forward(model, data)
                torque = np.zeros(model.nu)
                torque[policy_actuators] = (
                    (np.asarray(control["defaultAngles"]) - data.qpos[policy_qpos])
                    * np.asarray(control["policyKps"])
                    - data.qvel[policy_dofs] * np.asarray(control["policyKds"])
                )
                torque[held_actuators] = (
                    (held_targets - data.qpos[held_qpos])
                    * np.asarray(control["heldKps"])
                    - data.qvel[held_dofs] * np.asarray(control["heldKds"])
                    + feedforward
                )
                torque[gripper_actuators] = 0.0
                data.ctrl[:] = np.clip(
                    torque,
                    model.actuator_ctrlrange[:, 0],
                    model.actuator_ctrlrange[:, 1],
                )
                mujoco.mj_step(model, data)
            site = controller.site_state(data.qpos, data.qvel, target)
            samples.append(
                {
                    "step": step,
                    "targetErrorMeters": site["targetErrorMeters"],
                    "tcpSpeed": site["tcpSpeed"],
                    "qpProjectedGradient": solution["qpProjectedGradient"],
                    "finite": bool(
                        np.isfinite(data.qpos).all() and np.isfinite(data.qvel).all()
                    ),
                }
            )
    hold = samples[-int(WHOLE_BODY_GATES["holdSteps"]) :]
    metrics = {
        "steps": len(samples),
        "initialTargetErrorMeters": samples[0]["targetErrorMeters"],
        "minimumTargetErrorMeters": min(item["targetErrorMeters"] for item in samples),
        "finalTargetErrorMeters": samples[-1]["targetErrorMeters"],
        "holdMaximumTargetErrorMeters": max(
            item["targetErrorMeters"] for item in hold
        ),
        "holdMaximumTcpSpeed": max(item["tcpSpeed"] for item in hold),
        "maximumProjectedGradient": max(
            item["qpProjectedGradient"] for item in samples
        ),
        "nonFiniteSamples": sum(not item["finite"] for item in samples),
    }
    passed = (
        metrics["holdMaximumTargetErrorMeters"]
        <= WHOLE_BODY_GATES["positionToleranceMeters"]
        and metrics["holdMaximumTcpSpeed"] <= WHOLE_BODY_GATES["maximumTcpSpeed"]
        and metrics["maximumProjectedGradient"]
        <= WHOLE_BODY_GATES["maximumProjectedGradient"]
        and metrics["nonFiniteSamples"]
        <= WHOLE_BODY_GATES["maximumNonFiniteSamples"]
    )
    return {
        "id": "conformance://worldspec/h1/a5c-fixed-base-cpu",
        "reportVersion": "0.1.0",
        "status": "completed",
        "scope": "h1_whole_body_fixed_base_cpu_preflight",
        "executionEvidence": "executed",
        "formalPreflightGate": "passed" if passed else "failed",
        "controlProfileDigest": digest_json(profile),
        "sourceModel": {
            "path": args.model.name,
            "digest": digest_bytes(args.model.read_bytes()),
        },
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "mujoco": mujoco.__version__,
        },
        "method": {
            "base": "explicit_mujoco_weld",
            "controller": profile["controller"]["mode"],
            "feedforward": "mujoco_qfrc_bias",
            "hiddenGraspConstraint": False,
        },
        "metrics": metrics,
        "claimBoundary": {
            "status": "fixed_base_cpu_preflight_only",
            "a800Claim": "forbidden",
            "fullTaskClaim": "forbidden",
            "l3Claim": "forbidden",
        },
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-profile", type=Path, required=True)
    parser.add_argument("--supervisor-profile", type=Path, required=True)
    parser.add_argument("--control-profile", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=220)
    parser.add_argument(
        "--settled-base",
        type=float,
        nargs=3,
        default=[1.4032, 0.0241, 1.0398],
    )
    args = parser.parse_args()
    if args.steps < WHOLE_BODY_GATES["holdSteps"]:
        parser.error("--steps must cover the complete hold gate")
    report = run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_bytes(report))
    print(json.dumps(report, sort_keys=True))
    return 0 if report["formalPreflightGate"] == "passed" else 3


if __name__ == "__main__":
    raise SystemExit(main())
