import copy
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from worldspec_h1_training.contract import digest_json
from worldspec_h1_training.model import prepare_training_model

ROOT = Path(__file__).resolve().parents[3]
PROFILE = ROOT / "examples" / "h1-kitchen" / "locomotion-training-profile.json"


def _digest(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _fixture_bundle(tmp_path: Path) -> tuple[dict, Path]:
    profile = copy.deepcopy(json.loads(PROFILE.read_text(encoding="utf-8")))
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    joints = [
        *profile["control"]["policyJoints"],
        *profile["control"]["heldJoints"],
    ]
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
    inventory = [
        {
            "path": "model.xml",
            "sizeBytes": len(model),
            "digest": _digest(model),
        }
    ]
    manifest = {
        "model": "model.xml",
        "artifacts": inventory,
        "sourceLockDigest": profile["target"]["sourceLockDigest"],
        "compositionProfileDigest": profile["target"]["compositionProfileDigest"],
        "bundleDigest": digest_json(inventory),
    }
    profile["target"]["bundleDigest"] = manifest["bundleDigest"]
    (bundle / "composition-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return profile, bundle


def test_training_model_is_derived_without_mutating_source(tmp_path: Path) -> None:
    profile, bundle = _fixture_bundle(tmp_path)
    source = (bundle / "model.xml").read_bytes()
    model, derivation = prepare_training_model(profile, bundle, tmp_path / "work")
    assert (bundle / "model.xml").read_bytes() == source
    assert derivation["sourceBundleDigest"] == profile["target"]["bundleDigest"]
    root = ET.parse(model).getroot()
    assert root.find(".//geom[@name='floor']") is not None
    assert root.find(".//geom[@name='left_foot1']") is not None
    assert root.find(".//sensor/gyro[@name='gyro']") is not None
    assert root.find(".//sensor/contact[@name='right_foot3_floor_found']") is not None


def test_training_model_derivation_is_deterministic(tmp_path: Path) -> None:
    profile, bundle = _fixture_bundle(tmp_path)
    model_a, derivation_a = prepare_training_model(profile, bundle, tmp_path / "work-a")
    model_b, derivation_b = prepare_training_model(profile, bundle, tmp_path / "work-b")
    assert model_a.read_bytes() == model_b.read_bytes()
    assert derivation_a == derivation_b


def test_training_model_accepts_a_workdir_reached_through_a_symlink(
    tmp_path: Path,
) -> None:
    profile, bundle = _fixture_bundle(tmp_path)
    actual_work = tmp_path / "actual-work"
    actual_work.mkdir()
    work_alias = tmp_path / "work-alias"
    work_alias.symlink_to(actual_work, target_is_directory=True)
    model, _ = prepare_training_model(profile, bundle, work_alias)
    assert model.is_file()
