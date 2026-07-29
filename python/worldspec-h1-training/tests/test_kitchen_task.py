from __future__ import annotations

import copy
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from worldspec_h1_training.contract import digest_json
from worldspec_h1_training.errors import TrainingError
from worldspec_h1_training.kitchen_task import (
    PHASES,
    TASK_CONTROLLER,
    KitchenTaskState,
    make_kitchen_task_evaluation_profile,
    prepare_kitchen_task_model,
    validate_kitchen_task_profile,
)

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "examples" / "h1-kitchen" / "locomotion-training-profile.json"
SUPERVISOR = ROOT / "examples" / "h1-kitchen" / "locomotion-supervisor-profile.json"
TASK = ROOT / "examples" / "h1-kitchen" / "kitchen-task-profile.json"


def _profiles() -> tuple[dict, dict, dict]:
    return tuple(
        json.loads(path.read_text(encoding="utf-8"))
        for path in (BASE, SUPERVISOR, TASK)
    )


def _digest(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _fixture_bundle(tmp_path: Path) -> tuple[dict, Path]:
    profile, _, _ = _profiles()
    profile = copy.deepcopy(profile)
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    joints = [*profile["control"]["policyJoints"], *profile["control"]["heldJoints"]]
    actuators = [
        *profile["control"]["policyActuators"],
        *profile["control"]["heldActuators"],
        *profile["control"]["gripperActuators"],
    ]
    joint_xml = "".join(
        f'<body name="{name}_control_body"><joint name="{name}" range="-3 3"/></body>'
        for name in joints
    )
    actuator_xml = "".join(
        f'<motor name="{name}" joint="{joints[min(index, len(joints) - 1)]}"/>'
        for index, name in enumerate(actuators)
    )
    model = f"""<mujoco>
  <default>
    <default class="foot1"><geom type="capsule" size="0.01"/></default>
    <default class="foot2"><geom type="capsule" size="0.01"/></default>
    <default class="foot3"><geom type="capsule" size="0.01"/></default>
  </default>
  <worldbody>
    <body name="pelvis"><freejoint/>{joint_xml}
      <body name="torso_link"><site name="imu"/></body>
      <body name="right_elbow_link"><site name="right_gripper_pinch"/></body>
      <body name="left_ankle_link">
        <geom class="foot1"/><geom class="foot2"/><geom class="foot3"/>
      </body>
      <body name="right_ankle_link">
        <geom class="foot1"/><geom class="foot2"/><geom class="foot3"/>
      </body>
    </body>
  </worldbody>
  <actuator>{actuator_xml}</actuator>
</mujoco>""".encode()
    (bundle / "model.xml").write_bytes(model)
    inventory = [{"path": "model.xml", "sizeBytes": len(model), "digest": _digest(model)}]
    manifest = {
        "model": "model.xml",
        "artifacts": inventory,
        "sourceLockDigest": profile["target"]["sourceLockDigest"],
        "compositionProfileDigest": profile["target"]["compositionProfileDigest"],
        "bundleDigest": digest_json(inventory),
    }
    profile["target"]["bundleDigest"] = manifest["bundleDigest"]
    (bundle / "composition-manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    return profile, bundle


def test_a5_profile_binds_a4_and_forbids_l3() -> None:
    base, supervisor, task = _profiles()

    validate_kitchen_task_profile(base, supervisor, task)

    assert task["supervisorProfileDigest"] == digest_json(supervisor)
    assert task["scene"]["hiddenAttachment"] is False
    assert task["scene"]["graspModel"] == "physical_contact_only"
    assert task["artifactPolicy"]["l3Claim"] == "forbidden"


def test_a5_effective_profile_uses_task_seed_and_runtime() -> None:
    base, supervisor, task = _profiles()

    effective = make_kitchen_task_evaluation_profile(base, supervisor, task)

    assert effective["training"]["seed"] == task["seed"]
    assert effective["training"]["numEnvs"] == 1
    assert effective["runtime"]["containerDigest"] == task["runtime"]["containerDigest"]
    assert effective["runtime"]["ccdIterations"] == task["runtime"]["ccdIterations"]


def test_a5_rejects_hidden_attachment_and_policy_drift() -> None:
    base, supervisor, task = _profiles()
    task["scene"]["hiddenAttachment"] = True

    with pytest.raises(TrainingError, match="primitive fixed kitchen"):
        validate_kitchen_task_profile(base, supervisor, task)

    _, _, task = _profiles()
    task["standPolicy"]["checkpointDigest"] = "sha256:" + ("0" * 64)
    with pytest.raises(TrainingError, match="frozen A4"):
        validate_kitchen_task_profile(base, supervisor, task)


def test_task_state_machine_is_ordered_and_fail_closed() -> None:
    state = KitchenTaskState()
    observed = [state.phase]
    while not state.completed:
        phase = state.phase
        minimum = TASK_CONTROLLER["phaseMinimumSteps"][phase]
        for _ in range(minimum):
            state.observe(
                target_error=0.0,
                drawer_position=0.2 if phase != "push_drawer" else 0.0,
                cup_inside=phase in {"insert_cup", "release_cup", "retract", "push_drawer", "final_hold"},
                cup_linear_speed=0.0,
                cup_angular_speed=0.0,
            )
        if state.phase != observed[-1]:
            observed.append(state.phase)
    assert observed == PHASES
    assert state.failed_reason is None

    failed = KitchenTaskState(phase_index=PHASES.index("pull_drawer"))
    for _ in range(TASK_CONTROLLER["phaseMaximumSteps"]["pull_drawer"]):
        failed.observe(
            target_error=0.0,
            drawer_position=0.0,
            cup_inside=False,
            cup_linear_speed=0.0,
            cup_angular_speed=0.0,
        )
    assert failed.failed_reason == "pull_drawer_timeout"


def test_task_scene_is_derived_without_hidden_constraint(tmp_path: Path) -> None:
    profile, bundle = _fixture_bundle(tmp_path)

    model, derivation = prepare_kitchen_task_model(profile, bundle, tmp_path / "work")
    root = ET.parse(model).getroot()

    assert root.find(".//joint[@name='worldspec_drawer_slide']") is not None
    assert root.find(".//freejoint[@name='worldspec_cup_free']") is not None
    assert root.find(".//site[@name='worldspec_drawer_handle_site']") is not None
    assert root.find(".//equality") is None
    assert root.find(".//body[@mocap='true']") is None
    assert "No weld" in derivation["dynamicsStatement"]


def test_a800_a5_launcher_is_gated_and_does_not_start_training() -> None:
    entrypoint = (
        ROOT / "ops" / "a800" / "h1-locomotion-midterm-entrypoint.sh"
    ).read_text(encoding="utf-8")
    launcher = (
        ROOT / "scripts" / "run_a800_h1_locomotion_midterm.sh"
    ).read_text(encoding="utf-8")
    wrapper = (
        ROOT / "scripts" / "run_a800_h1_fixed_kitchen_task_probe.sh"
    ).read_text(encoding="utf-8")

    assert "run_fixed_kitchen_task_probe" in entrypoint
    assert "WORLDSPEC_A800_KITCHEN_TASK_RESULT=" in entrypoint
    assert "formalTaskGate" in launcher
    assert "h1-kitchen-task-report.schema.json" in launcher
    assert "kitchen-task-controller.json" in launcher
    assert "kitchen-task-profile.json" in wrapper
    assert "100000000" not in wrapper
