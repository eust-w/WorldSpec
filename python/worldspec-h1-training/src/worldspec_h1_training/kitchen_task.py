"""A5 fixed-kitchen integration probe for the frozen H1 locomotion supervisor.

The probe deliberately uses a self-authored primitive scene and physical
contacts only.  It does not create a hidden weld or teleport the drawer/cup.
"""

from __future__ import annotations

import copy
import functools
import json
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contract import canonical_bytes, digest_bytes, digest_json, validate_profile
from .errors import TrainingError
from .midterm import _load_deterministic_teacher_policy
from .model import prepare_training_model
from .preflight import runtime_preflight, static_preflight
from .supervisor import (
    SUPERVISOR,
    SupervisorState,
    make_supervisor_evaluation_profile,
)
from .trainer import _flat_observation_size
from .warm_start import materialize_warm_start, validate_network_compatibility

TASK_SCENE = {
    "sceneId": "scene://worldspec/h1-kitchen/primitive-drawer-cup-v1",
    "evidenceStatus": "generated",
    "distribution": "internal_only",
    "drawer": {
        "closedCenter": [2.06, -0.21, 1.02],
        "slideAxis": [-1.0, 0.0, 0.0],
        "range": [0.0, 0.24],
        "openThreshold": 0.18,
        "closedThreshold": 0.03,
    },
    "cup": {
        "initialCenter": [1.88, -0.21, 1.195],
        "proxy": "short_cylinder",
        "massKg": 0.18,
    },
    "graspModel": "physical_contact_only",
    "hiddenAttachment": False,
}

PHASES = [
    "stand_ready",
    "reach_handle",
    "close_handle",
    "pull_drawer",
    "release_handle",
    "reach_cup",
    "close_cup",
    "lift_cup",
    "insert_cup",
    "release_cup",
    "retract",
    "push_drawer",
    "final_hold",
]

TASK_CONTROLLER = {
    "mode": "frozen_locomotion_plus_jacobian_impedance",
    "controlledJoints": [
        "right_shoulder_pitch",
        "right_shoulder_roll",
        "right_shoulder_yaw",
        "right_elbow",
    ],
    "damping": 0.04,
    "maximumJointTargetStep": 0.04,
    "positionToleranceMeters": 0.035,
    "openGripperCommand": 0.0,
    "closedGripperCommand": 255.0,
    "phaseMinimumSteps": {
        "stand_ready": 25,
        "reach_handle": 5,
        "close_handle": 30,
        "pull_drawer": 5,
        "release_handle": 20,
        "reach_cup": 5,
        "close_cup": 40,
        "lift_cup": 5,
        "insert_cup": 5,
        "release_cup": 30,
        "retract": 5,
        "push_drawer": 5,
        "final_hold": 25,
    },
    "phaseMaximumSteps": {
        "stand_ready": 25,
        "reach_handle": 100,
        "close_handle": 30,
        "pull_drawer": 120,
        "release_handle": 20,
        "reach_cup": 120,
        "close_cup": 40,
        "lift_cup": 120,
        "insert_cup": 140,
        "release_cup": 30,
        "retract": 100,
        "push_drawer": 140,
        "final_hold": 25,
    },
}

TASK_GATES = {
    "probeRuns": 1,
    "acceptanceRuns": 5,
    "minimumForwardDisplacement": 1.0,
    "maximumForwardDisplacement": 2.2,
    "minimumBaseHeight": 0.8,
    "minimumUprightCosine": 0.8,
    "drawerOpenThreshold": 0.18,
    "drawerClosedThreshold": 0.03,
    "cupInsideMargin": 0.015,
    "maximumCupLinearSpeed": 0.08,
    "maximumCupAngularSpeed": 0.20,
    "minimumStableSteps": 20,
    "maximumNonFiniteSamples": 0,
}


@dataclass
class KitchenTaskState:
    """Fail-closed ordered task state machine."""

    phase_index: int = 0
    phase_steps: int = 0
    failed_reason: str | None = None
    maximum_drawer_opening: float = 0.0
    cup_stable_steps: int = 0

    @property
    def phase(self) -> str:
        return PHASES[self.phase_index]

    @property
    def completed(self) -> bool:
        return self.phase == "final_hold" and self.phase_steps >= TASK_CONTROLLER[
            "phaseMinimumSteps"
        ]["final_hold"]

    def _advance(self) -> None:
        if self.phase_index < len(PHASES) - 1:
            self.phase_index += 1
            self.phase_steps = 0

    def observe(
        self,
        *,
        target_error: float,
        drawer_position: float,
        cup_inside: bool,
        cup_linear_speed: float,
        cup_angular_speed: float,
    ) -> None:
        if self.failed_reason is not None:
            return
        self.phase_steps += 1
        self.maximum_drawer_opening = max(self.maximum_drawer_opening, drawer_position)
        minimum = TASK_CONTROLLER["phaseMinimumSteps"][self.phase]
        maximum = TASK_CONTROLLER["phaseMaximumSteps"][self.phase]
        ready = False
        if self.phase in {"stand_ready", "close_handle", "release_handle", "close_cup"}:
            ready = self.phase_steps >= minimum
        elif self.phase in {"reach_handle", "reach_cup", "lift_cup", "retract"}:
            ready = self.phase_steps >= minimum and target_error <= TASK_CONTROLLER[
                "positionToleranceMeters"
            ]
        elif self.phase == "pull_drawer":
            ready = self.phase_steps >= minimum and drawer_position >= TASK_GATES[
                "drawerOpenThreshold"
            ]
        elif self.phase == "insert_cup":
            ready = self.phase_steps >= minimum and cup_inside
        elif self.phase == "release_cup":
            stable = (
                cup_inside
                and cup_linear_speed <= TASK_GATES["maximumCupLinearSpeed"]
                and cup_angular_speed <= TASK_GATES["maximumCupAngularSpeed"]
            )
            self.cup_stable_steps = self.cup_stable_steps + 1 if stable else 0
            ready = (
                self.phase_steps >= minimum
                and self.cup_stable_steps >= TASK_GATES["minimumStableSteps"]
            )
        elif self.phase == "push_drawer":
            ready = self.phase_steps >= minimum and drawer_position <= TASK_GATES[
                "drawerClosedThreshold"
            ]
        elif self.phase == "final_hold":
            return
        if ready:
            self._advance()
        elif self.phase_steps >= maximum:
            self.failed_reason = f"{self.phase}_timeout"


def validate_kitchen_task_profile(
    base_profile: dict[str, Any],
    supervisor_profile: dict[str, Any],
    profile: dict[str, Any],
) -> None:
    """Validate A5 without weakening the frozen A4 policy lineage."""

    validate_profile(base_profile)
    make_supervisor_evaluation_profile(base_profile, supervisor_profile)
    if (
        profile.get("profileVersion") != "0.1.0"
        or profile.get("status") != "research"
        or profile.get("stage") != "fixed_kitchen_full_loop_probe"
    ):
        raise TrainingError(
            "KITCHEN_TASK_PROFILE_UNSUPPORTED",
            "A5 must use fixed_kitchen_full_loop_probe v0.1.",
        )
    if profile.get("baseTrainingProfileDigest") != digest_json(base_profile):
        raise TrainingError(
            "KITCHEN_TASK_BASE_PROFILE_MISMATCH",
            "A5 is not bound to the exact base training Profile.",
        )
    if profile.get("supervisorProfileDigest") != digest_json(supervisor_profile):
        raise TrainingError(
            "KITCHEN_TASK_SUPERVISOR_MISMATCH",
            "A5 is not bound to the passing A4 supervisor Profile.",
        )
    for key in ("motionPolicy", "capturePolicy", "standPolicy"):
        if profile.get(key) != supervisor_profile[key]:
            raise TrainingError(
                "KITCHEN_TASK_POLICY_LINEAGE_MISMATCH",
                "A5 must reuse the frozen A4 policy identities.",
            )
    if profile.get("scene") != TASK_SCENE:
        raise TrainingError(
            "KITCHEN_TASK_SCENE_INVALID",
            "A5 must use the self-authored primitive fixed kitchen scene.",
        )
    if profile.get("controller") != TASK_CONTROLLER:
        raise TrainingError(
            "KITCHEN_TASK_CONTROLLER_INVALID",
            "A5 controller contract or ordered phase graph changed.",
        )
    if profile.get("qualityGates") != TASK_GATES:
        raise TrainingError(
            "KITCHEN_TASK_GATES_INVALID",
            "A5 quality gates cannot be relaxed.",
        )
    if profile.get("artifactPolicy") != {
        "controller": "research_only",
        "distribution": "internal_only",
        "l3Claim": "forbidden",
    }:
        raise TrainingError(
            "KITCHEN_TASK_ARTIFACT_POLICY_INVALID",
            "A5 remains internal research evidence and cannot claim L3.",
        )
    runtime = profile.get("runtime", {})
    if runtime.get("ccdIterations") != 50 or runtime.get("evaluationEnvironments") != 1:
        raise TrainingError(
            "KITCHEN_TASK_RUNTIME_INVALID",
            "A5 requires CCD=50 and one deterministic environment.",
        )
    if (
        runtime.get("containerDigest")
        != runtime.get("containerImage", "").rsplit("@", maxsplit=1)[-1]
    ):
        raise TrainingError(
            "KITCHEN_TASK_CONTAINER_BINDING_MISMATCH",
            "A5 containerImage and containerDigest must identify one OCI image.",
        )


def _child(root: ET.Element, tag: str) -> ET.Element:
    value = root.find(tag)
    return value if value is not None else ET.SubElement(root, tag)


def prepare_kitchen_task_model(
    base_profile: dict[str, Any],
    bundle_dir: Path,
    work_dir: Path,
) -> tuple[Path, dict[str, Any]]:
    """Add a deterministic, distributable drawer/cup task scene."""

    training_model, parent_derivation = prepare_training_model(
        base_profile,
        bundle_dir,
        work_dir,
    )
    tree = ET.parse(training_model)
    root = tree.getroot()
    worldbody = _child(root, "worldbody")
    if any(body.get("name") == "worldspec_task_drawer" for body in worldbody.findall("body")):
        raise TrainingError("KITCHEN_TASK_SCENE_CONFLICT", "Task scene is already present.")

    cabinet = ET.SubElement(worldbody, "body", {"name": "worldspec_task_cabinet"})
    for name, pos, size in (
        ("worldspec_cabinet_back", "2.25 -0.21 1.08", "0.02 0.24 0.28"),
        ("worldspec_cabinet_left", "2.06 -0.45 1.08", "0.21 0.02 0.28"),
        ("worldspec_cabinet_right", "2.06 0.03 1.08", "0.21 0.02 0.28"),
    ):
        ET.SubElement(
            cabinet,
            "geom",
            {
                "name": name,
                "type": "box",
                "pos": pos,
                "size": size,
                "rgba": "0.45 0.32 0.20 1",
                "friction": "0.8 0.01 0.001",
            },
        )
    for side, y in (("left", -0.275), ("right", -0.145)):
        ET.SubElement(
            cabinet,
            "geom",
            {
                "name": f"worldspec_cup_rail_{side}",
                "type": "box",
                "pos": f"1.88 {y} 1.155",
                "size": "0.08 0.02 0.012",
                "rgba": "0.35 0.35 0.35 1",
                "friction": "1.0 0.01 0.001",
            },
        )

    drawer = ET.SubElement(
        worldbody,
        "body",
        {"name": "worldspec_task_drawer", "pos": "2.06 -0.21 1.02"},
    )
    ET.SubElement(
        drawer,
        "joint",
        {
            "name": "worldspec_drawer_slide",
            "type": "slide",
            "axis": "-1 0 0",
            "range": "0 0.24",
            "damping": "5",
            "frictionloss": "0.5",
            "armature": "0.02",
        },
    )
    ET.SubElement(
        drawer,
        "inertial",
        {"pos": "0 0 0.035", "mass": "2.0", "diaginertia": "0.05 0.08 0.08"},
    )
    for name, pos, size in (
        ("worldspec_drawer_bottom", "0 0 0", "0.16 0.18 0.015"),
        ("worldspec_drawer_left", "0 -0.165 0.06", "0.16 0.015 0.06"),
        ("worldspec_drawer_right", "0 0.165 0.06", "0.16 0.015 0.06"),
        ("worldspec_drawer_back", "0.145 0 0.06", "0.015 0.18 0.06"),
        ("worldspec_drawer_front", "-0.145 0 0.06", "0.015 0.18 0.06"),
    ):
        ET.SubElement(
            drawer,
            "geom",
            {
                "name": name,
                "type": "box",
                "pos": pos,
                "size": size,
                "rgba": "0.62 0.42 0.24 1",
                "friction": "1.0 0.01 0.001",
            },
        )
    ET.SubElement(
        drawer,
        "geom",
        {
            "name": "worldspec_drawer_handle",
            "type": "cylinder",
            "pos": "-0.19 0 0.055",
            "size": "0.012 0.09",
            "quat": "0.7071067811865476 0.7071067811865476 0 0",
            "rgba": "0.18 0.18 0.18 1",
            "friction": "1.5 0.02 0.002",
        },
    )
    ET.SubElement(
        drawer,
        "site",
        {
            "name": "worldspec_drawer_handle_site",
            "pos": "-0.19 0 0.055",
            "size": "0.012",
        },
    )
    ET.SubElement(
        drawer,
        "site",
        {
            "name": "worldspec_drawer_inside_site",
            "pos": "0 0 0.055",
            "size": "0.012",
        },
    )

    cup = ET.SubElement(
        worldbody,
        "body",
        {"name": "worldspec_task_cup", "pos": "1.88 -0.21 1.195"},
    )
    ET.SubElement(cup, "freejoint", {"name": "worldspec_cup_free"})
    ET.SubElement(
        cup,
        "inertial",
        {
            "pos": "0 0 0",
            "mass": "0.18",
            "diaginertia": "0.00009 0.00009 0.00012",
        },
    )
    ET.SubElement(
        cup,
        "geom",
        {
            "name": "worldspec_cup_collision",
            "type": "cylinder",
            "size": "0.035 0.025",
            "rgba": "0.84 0.84 0.88 1",
            "friction": "1.6 0.02 0.002",
            "solref": "0.003 1",
        },
    )
    ET.SubElement(cup, "site", {"name": "worldspec_cup_site", "size": "0.012"})

    ET.indent(tree, space="  ")
    task_model = training_model.with_name("kitchen-task-model.xml")
    tree.write(task_model, encoding="utf-8", xml_declaration=True)
    derivation = {
        "manifestVersion": "0.1.0",
        "parentDerivation": parent_derivation,
        "derivedModel": task_model.name,
        "derivedModelDigest": digest_bytes(task_model.read_bytes()),
        "taskScene": copy.deepcopy(TASK_SCENE),
        "transformations": [
            "add_self_authored_static_cabinet",
            "add_prismatic_drawer_and_handle",
            "add_dynamic_short_cylinder_cup",
        ],
        "dynamicsStatement": (
            "The A5 task scene adds physical contacts and one drawer articulation. "
            "No weld, mocap attachment, teleport, or hidden grasp constraint is present."
        ),
        "evidenceStatus": "derived",
    }
    task_model.with_name("kitchen-task-model-derivation.json").write_text(
        json.dumps(derivation, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return task_model, derivation


class JacobianImpedanceController:
    """Host-side position IK that writes declared held-joint impedance targets."""

    def __init__(self, model) -> None:
        import mujoco
        import numpy as np

        self._mujoco = mujoco
        self._np = np
        self._model = model
        self._data = mujoco.MjData(model)
        self._site = mujoco.mj_name2id(
            model,
            mujoco.mjtObj.mjOBJ_SITE,
            "right_gripper_pinch",
        )
        names = TASK_CONTROLLER["controlledJoints"]
        self._joint_ids = np.asarray(
            [
                mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name)
                for name in names
            ],
            dtype=int,
        )
        if self._site < 0 or (self._joint_ids < 0).any():
            raise TrainingError(
                "KITCHEN_TASK_CONTROL_BINDING_MISSING",
                "Right arm or pinch site is missing from the target model.",
            )
        self._qpos = model.jnt_qposadr[self._joint_ids]
        self._dofs = model.jnt_dofadr[self._joint_ids]
        self._ranges = model.jnt_range[self._joint_ids]

    def solve(self, qpos, qvel, target) -> tuple[list[float], float, list[float]]:
        np = self._np
        self._data.qpos[:] = np.asarray(qpos)
        self._data.qvel[:] = np.asarray(qvel)
        self._mujoco.mj_forward(self._model, self._data)
        jacp = np.zeros((3, self._model.nv))
        jacr = np.zeros((3, self._model.nv))
        self._mujoco.mj_jacSite(
            self._model,
            self._data,
            jacp,
            jacr,
            self._site,
        )
        current = self._data.site_xpos[self._site].copy()
        error = np.asarray(target, dtype=float) - current
        jac = jacp[:, self._dofs]
        damping = float(TASK_CONTROLLER["damping"])
        delta = jac.T @ np.linalg.solve(jac @ jac.T + damping**2 * np.eye(3), error)
        limit = float(TASK_CONTROLLER["maximumJointTargetStep"])
        delta = np.clip(delta, -limit, limit)
        values = np.clip(
            self._data.qpos[self._qpos] + delta,
            self._ranges[:, 0] + 0.01,
            self._ranges[:, 1] - 0.01,
        )
        held = [0.0] * 9
        held[5:9] = [float(value) for value in values]
        return held, float(np.linalg.norm(error)), [float(value) for value in current]


def _task_metrics(env, state) -> dict[str, Any]:
    import mujoco
    import numpy as np

    model = env.mj_model
    qpos = np.asarray(state.data.qpos)
    qvel = np.asarray(state.data.qvel)
    drawer_joint = mujoco.mj_name2id(
        model,
        mujoco.mjtObj.mjOBJ_JOINT,
        "worldspec_drawer_slide",
    )
    cup_joint = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, "worldspec_cup_free")
    drawer_qpos = int(model.jnt_qposadr[drawer_joint])
    cup_qpos = int(model.jnt_qposadr[cup_joint])
    cup_dof = int(model.jnt_dofadr[cup_joint])
    drawer_position = float(qpos[drawer_qpos])
    cup_position = qpos[cup_qpos : cup_qpos + 3]
    drawer_center = np.asarray(TASK_SCENE["drawer"]["closedCenter"], dtype=float)
    drawer_center[0] -= drawer_position
    margin = TASK_GATES["cupInsideMargin"]
    inside = bool(
        drawer_center[0] - 0.145 + margin
        <= cup_position[0]
        <= drawer_center[0] + 0.145 - margin
        and drawer_center[1] - 0.165 + margin
        <= cup_position[1]
        <= drawer_center[1] + 0.165 - margin
        and drawer_center[2] + 0.02
        <= cup_position[2]
        <= drawer_center[2] + 0.115
    )
    return {
        "drawerPosition": drawer_position,
        "cupPosition": [float(value) for value in cup_position],
        "cupInside": inside,
        "cupLinearSpeed": float(np.linalg.norm(qvel[cup_dof : cup_dof + 3])),
        "cupAngularSpeed": float(np.linalg.norm(qvel[cup_dof + 3 : cup_dof + 6])),
    }


def _target_for_phase(phase: str, metrics: dict[str, Any]) -> list[float]:
    if phase in {"stand_ready", "final_hold"}:
        return [1.72, -0.21, 1.16]
    if phase in {"reach_handle", "close_handle"}:
        return [
            1.87 - metrics["drawerPosition"],
            -0.21,
            1.075,
        ]
    if phase == "pull_drawer":
        return [1.63, -0.21, 1.075]
    if phase == "release_handle":
        return [1.58, -0.21, 1.12]
    if phase in {"reach_cup", "close_cup"}:
        return metrics["cupPosition"]
    if phase == "lift_cup":
        return [1.80, -0.21, 1.27]
    if phase in {"insert_cup", "release_cup"}:
        return [1.78, -0.21, 1.065]
    if phase == "retract":
        return [1.58, -0.21, 1.22]
    if phase == "push_drawer":
        return [1.91, -0.21, 1.075]
    raise TrainingError("KITCHEN_TASK_PHASE_INVALID", f"Unsupported task phase: {phase}")


def _gripper_for_phase(phase: str) -> float:
    if phase in {"close_handle", "pull_drawer", "close_cup", "lift_cup", "insert_cup"}:
        return TASK_CONTROLLER["closedGripperCommand"]
    return TASK_CONTROLLER["openGripperCommand"]


def evaluate_kitchen_task_suite(
    profile: dict[str, Any],
    env,
    motion_policy,
    capture_policy,
    stand_policy,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run a one-episode gate, then four more episodes only when it passes."""

    import jax
    import jax.numpy as jp
    import numpy as np

    motion_inference = jax.jit(motion_policy)
    capture_inference = jax.jit(capture_policy)
    stand_inference = jax.jit(stand_policy)
    reset = jax.jit(env.reset)
    step = jax.jit(env.step)
    controller = JacobianImpedanceController(env.mj_model)
    dt = env.dt
    tests: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []

    def with_inputs(state, command, held_targets, gripper):
        info = dict(state.info)
        info["command"] = command
        info["held_targets"] = jp.asarray(held_targets)
        info["gripper_commands"] = jp.asarray([gripper])
        false_value = command[0] < command[0]
        info["transition_active"] = false_value
        info["stand_replay_active"] = false_value
        info["capture_active"] = false_value
        observation = {
            "state": env._observation(
                state.data,
                info["last_action"],
                command,
            )
        }
        return state.replace(info=info, obs=observation)

    def run(run_index: int) -> dict[str, Any]:
        rng = jax.random.PRNGKey(profile["seed"] + run_index)
        state = reset(rng)
        locomotion = SupervisorState()
        task = KitchenTaskState()
        start_x = float(np.asarray(state.data.qpos[0]))
        minimum_height = float("inf")
        minimum_upright = float("inf")
        nonfinite = 0
        done_seen = False
        failed_reason = None
        task_started = False
        target_error = 0.0
        tcp = [0.0, 0.0, 0.0]
        maximum_steps = 200 + sum(TASK_CONTROLLER["phaseMaximumSteps"].values())
        for index in range(maximum_steps):
            moving = index < SUPERVISOR["moveSteps"]
            command = jp.asarray([0.5, 0.0, 0.0]) if moving else jp.zeros(3)
            rng, motion_rng, capture_rng, stand_rng = jax.random.split(rng, 4)
            state = with_inputs(state, command, [0.0] * 9, 0.0)
            motion_action, _ = motion_inference(state.obs, motion_rng)
            capture_action, _ = capture_inference(state.obs, capture_rng)
            stand_action, _ = stand_inference(state.obs, stand_rng)
            if index < 200:
                action, active_policy, _ = locomotion.select(
                    moving,
                    motion_action,
                    capture_action,
                    stand_action,
                )
                phase = f"locomotion:{active_policy}"
                held_targets = [0.0] * 9
                gripper = 0.0
            else:
                if locomotion.phase != "stand":
                    failed_reason = "locomotion_supervisor_not_ready"
                    break
                task_started = True
                active_policy = "stand"
                metrics_before = _task_metrics(env, state)
                phase = task.phase
                target = _target_for_phase(phase, metrics_before)
                held_targets, target_error, tcp = controller.solve(
                    np.asarray(state.data.qpos),
                    np.asarray(state.data.qvel),
                    target,
                )
                gripper = _gripper_for_phase(phase)
                action = stand_action
            state = with_inputs(state, command, held_targets, gripper)
            state = step(state, action)
            jax.block_until_ready(state.reward)
            qpos = np.asarray(state.data.qpos)
            qvel = np.asarray(state.data.qvel)
            linear = np.asarray(env.local_velocity(state.data), dtype=float)
            angular = np.asarray(env.angular_velocity(state.data), dtype=float)
            height = float(np.asarray(state.data.xpos[env.pelvis_body_id, 2]))
            upright = float(np.asarray(env.upvector(state.data)[2]))
            finite = bool(np.isfinite(qpos).all() and np.isfinite(qvel).all())
            done = bool(np.asarray(state.done))
            minimum_height = min(minimum_height, height)
            minimum_upright = min(minimum_upright, upright)
            nonfinite += 0 if finite else 1
            task_metrics = _task_metrics(env, state)
            if index < 200:
                locomotion.observe(
                    active_policy,
                    float(np.linalg.norm(linear)),
                    float(np.linalg.norm(angular)),
                )
                if locomotion.handoff_failed:
                    failed_reason = "locomotion_handoff_timeout"
            else:
                task.observe(
                    target_error=target_error,
                    drawer_position=task_metrics["drawerPosition"],
                    cup_inside=task_metrics["cupInside"],
                    cup_linear_speed=task_metrics["cupLinearSpeed"],
                    cup_angular_speed=task_metrics["cupAngularSpeed"],
                )
                if task.failed_reason:
                    failed_reason = task.failed_reason
            traces.append(
                {
                    "run": run_index,
                    "step": index,
                    "timeSeconds": (index + 1) * dt,
                    "phase": phase,
                    "activePolicy": active_policy,
                    "targetError": target_error,
                    "tcpPosition": tcp,
                    "gripperCommand": gripper,
                    "basePosition": [float(qpos[0]), float(qpos[1]), height],
                    "minimumUprightCosine": minimum_upright,
                    **task_metrics,
                    "done": done,
                    "finite": finite,
                }
            )
            if done:
                done_seen = True
                failed_reason = failed_reason or "robot_termination"
            if failed_reason or (task_started and task.completed):
                break
        final = _task_metrics(env, state)
        displacement = float(np.asarray(state.data.qpos[0])) - start_x
        released = float(np.asarray(state.info["gripper_commands"])[0]) == 0.0
        passed = (
            failed_reason is None
            and task.completed
            and displacement >= TASK_GATES["minimumForwardDisplacement"]
            and displacement <= TASK_GATES["maximumForwardDisplacement"]
            and minimum_height >= TASK_GATES["minimumBaseHeight"]
            and minimum_upright >= TASK_GATES["minimumUprightCosine"]
            and task.maximum_drawer_opening >= TASK_GATES["drawerOpenThreshold"]
            and final["drawerPosition"] <= TASK_GATES["drawerClosedThreshold"]
            and final["cupInside"]
            and final["cupLinearSpeed"] <= TASK_GATES["maximumCupLinearSpeed"]
            and final["cupAngularSpeed"] <= TASK_GATES["maximumCupAngularSpeed"]
            and released
            and nonfinite <= TASK_GATES["maximumNonFiniteSamples"]
            and not done_seen
        )
        return {
            "id": f"test://worldspec/h1-kitchen/full-loop/{run_index + 1}",
            "result": "pass" if passed else "fail",
            "metrics": {
                "completedPhase": task.phase,
                "failedReason": failed_reason,
                "forwardDisplacement": displacement,
                "minimumBaseHeight": minimum_height,
                "minimumUprightCosine": minimum_upright,
                "maximumDrawerOpening": task.maximum_drawer_opening,
                "finalDrawerPosition": final["drawerPosition"],
                "cupInside": final["cupInside"],
                "cupReleased": released,
                "cupLinearSpeed": final["cupLinearSpeed"],
                "cupAngularSpeed": final["cupAngularSpeed"],
                "nonFiniteSamples": nonfinite,
                "doneSeen": done_seen,
            },
        }

    first = run(0)
    tests.append(first)
    if first["result"] == "pass":
        for run_index in range(1, TASK_GATES["acceptanceRuns"]):
            tests.append(run(run_index))
    return tests, traces


def run_fixed_kitchen_task_probe(
    base_profile: dict[str, Any],
    supervisor_profile: dict[str, Any],
    profile: dict[str, Any],
    bundle_dir: Path,
    model_dir: Path,
    output_dir: Path,
    motion_archive: Path,
    capture_archive: Path,
    stand_archive: Path,
) -> dict[str, Any]:
    """Run A5 and retain failed evidence without upgrading it to L3."""

    from brax.training.agents.ppo import networks as ppo_networks

    from .environment import make_environment

    validate_kitchen_task_profile(base_profile, supervisor_profile, profile)
    effective = make_supervisor_evaluation_profile(base_profile, supervisor_profile)
    effective["runtime"]["containerDigest"] = profile["runtime"]["containerDigest"]
    effective["runtime"]["ccdIterations"] = profile["runtime"]["ccdIterations"]
    effective["training"]["numEnvs"] = 1
    static = static_preflight(base_profile, bundle_dir)
    task_model, derivation = prepare_kitchen_task_model(base_profile, bundle_dir, model_dir)
    runtime = runtime_preflight(effective, task_model)
    output_dir.mkdir(parents=True, exist_ok=True)
    network_factory = functools.partial(
        ppo_networks.make_ppo_networks,
        policy_hidden_layer_sizes=(128, 128, 128, 128),
        value_hidden_layer_sizes=(256, 256, 256, 256, 256),
        policy_obs_key="state",
        value_obs_key="state",
    )
    environment = make_environment(effective, task_model)
    observation_size = _flat_observation_size(environment.observation_size["state"])
    action_size = int(environment.action_size)
    loaded: dict[str, dict[str, Any]] = {}
    policies: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="worldspec-h1-kitchen-task-") as temporary:
        root = Path(temporary)
        for role, archive, source in (
            ("motion", motion_archive, profile["motionPolicy"]),
            ("capture", capture_archive, profile["capturePolicy"]),
            ("stand", stand_archive, profile["standPolicy"]),
        ):
            step_path, initialization = materialize_warm_start(
                archive,
                root / role,
                source["checkpointDigest"],
                source["checkpointSizeBytes"],
            )
            validate_network_compatibility(initialization, observation_size, action_size)
            policies[role] = _load_deterministic_teacher_policy(
                step_path,
                initialization,
                network_factory,
            )
            initialization["role"] = source["selectedRole"]
            loaded[role] = initialization
        tests, traces = evaluate_kitchen_task_suite(
            effective,
            environment,
            policies["motion"],
            policies["capture"],
            policies["stand"],
        )
    trace_path = output_dir / "evaluation-traces.jsonl"
    with trace_path.open("w", encoding="utf-8") as stream:
        for record in traces:
            stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    controller_artifact = {
        "controllerVersion": "0.1.0",
        "status": "research_only",
        "profileDigest": digest_json(profile),
        "supervisorProfileDigest": digest_json(supervisor_profile),
        "controller": copy.deepcopy(TASK_CONTROLLER),
        "scene": copy.deepcopy(TASK_SCENE),
        "policies": {
            role: {
                "checkpointDigest": value["archiveDigest"],
                "selectedStep": value["selectedStep"],
            }
            for role, value in loaded.items()
        },
        "distribution": "internal_only",
        "l3Claim": "forbidden",
    }
    controller_path = output_dir / "kitchen-task-controller.json"
    controller_path.write_bytes(canonical_bytes(controller_artifact))
    full_gate = (
        len(tests) == TASK_GATES["acceptanceRuns"]
        and all(item["result"] == "pass" for item in tests)
    )
    return {
        "baseTrainingProfileDigest": digest_json(base_profile),
        "supervisorProfileDigest": digest_json(supervisor_profile),
        "taskProfileDigest": digest_json(profile),
        "policies": loaded,
        "staticPreflight": static,
        "runtimePreflight": runtime,
        "target": {
            "sourceBundleDigest": derivation["parentDerivation"]["sourceBundleDigest"],
            "derivedModelDigest": derivation["derivedModelDigest"],
            "observationSize": observation_size,
            "actionSize": action_size,
        },
        "scene": copy.deepcopy(TASK_SCENE),
        "controller": copy.deepcopy(TASK_CONTROLLER),
        "qualityAssessment": {
            "status": "passed" if full_gate else "failed",
            "singleRunGate": bool(tests and tests[0]["result"] == "pass"),
            "fixedSceneFiveRunGate": full_gate,
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
        "claimBoundary": {
            "status": "research_integration_only",
            "l3Claim": "forbidden",
            "reasons": [
                "right_gripper_mount_evidence_is_estimated_and_unvalidated",
                "task_scene_is_self_authored_primitive_proxy_not_real_kitchen_evidence",
                "randomized_robustness_not_evaluated",
            ],
        },
    }
