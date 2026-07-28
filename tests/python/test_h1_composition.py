from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from compose_h1_robotiq import (  # noqa: E402
    CompositionError,
    component_file,
    file_inventory,
    namespace_tree,
)
from fetch_h1_kitchen_sources import tree_digest  # noqa: E402
from validate_h1_locomotion_policy import (  # noqa: E402
    PolicyValidationError,
    gravity_orientation,
    validate_profile,
)


def test_namespace_tree_resolves_implicit_mesh_and_references() -> None:
    root = ET.fromstring(
        """
        <mujoco>
          <asset>
            <material name="black"/>
            <mesh class="2f85" file="base.stl"/>
          </asset>
          <default><default class="2f85"><geom material="black"/></default></default>
          <worldbody>
            <body name="base" childclass="2f85">
              <geom mesh="base" material="black"/>
              <site name="pinch"/>
            </body>
          </worldbody>
        </mujoco>
        """
    )
    namespace_tree(root, "right_gripper_")
    mesh = root.find("./asset/mesh")
    body = root.find("./worldbody/body")
    geom = root.find("./worldbody/body/geom")
    assert mesh is not None and mesh.get("name") == "right_gripper_base"
    assert mesh.get("class") == "right_gripper_2f85"
    assert body is not None and body.get("name") == "right_gripper_base"
    assert body.get("childclass") == "right_gripper_2f85"
    assert geom is not None and geom.get("mesh") == "right_gripper_base"
    assert geom.get("material") == "right_gripper_black"


def test_component_file_requires_locked_component_prefix(tmp_path: Path) -> None:
    model = tmp_path / "h1.xml"
    model.write_text("<mujoco/>", encoding="utf-8")
    component = {"path": "unitree_h1"}
    assert component_file(tmp_path, component, "unitree_h1/h1.xml") == model
    with pytest.raises(CompositionError):
        component_file(tmp_path, component, "other/h1.xml")
    with pytest.raises(CompositionError):
        component_file(tmp_path, component, "unitree_h1/../h1.xml")


def test_inventory_excludes_self_referential_manifest(tmp_path: Path) -> None:
    (tmp_path / "model.xml").write_text("<mujoco/>", encoding="utf-8")
    (tmp_path / "composition-manifest.json").write_text("{}", encoding="utf-8")
    inventory = file_inventory(tmp_path)
    assert [item["path"] for item in inventory] == ["model.xml"]


def test_tree_digest_accepts_a_repository_reached_through_a_symlink(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    component = repository / "component"
    component.mkdir(parents=True)
    (component / "asset.txt").write_text("locked\n", encoding="utf-8")
    alias = tmp_path / "repository-alias"
    alias.symlink_to(repository, target_is_directory=True)
    digest, count = tree_digest(alias, "component")
    assert digest.startswith("sha256:")
    assert count == 1


def test_locomotion_profile_rejects_implicit_joint_slicing() -> None:
    profile = {
        "profileVersion": "0.1.0",
        "sourceLockDigest": "sha256:" + "a" * 64,
        "legControl": {
            "joints": ["left_hip"],
            "actuators": ["left_hip"],
            "kps": [100],
            "kds": [2],
            "defaultAngles": [0],
        },
        "observation": {"actions": 2, "dimensions": 17},
        "upperBodyHold": {
            "joints": ["torso"],
            "actuators": ["torso"],
            "targets": [0],
            "kps": [10],
            "kds": [1],
        },
        "simulation": {
            "timestepSeconds": 0.002,
            "controlDecimation": 10,
            "durationSeconds": 1,
        },
    }
    with pytest.raises(PolicyValidationError):
        validate_profile(profile, "sha256:" + "a" * 64)


def test_projected_gravity_is_upright_for_identity_quaternion() -> None:
    np = pytest.importorskip("numpy")
    value = gravity_orientation([1.0, 0.0, 0.0, 0.0], np)
    assert value.tolist() == [0.0, -0.0, -1.0]
