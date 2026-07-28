"""Derive a training-only MJCF without mutating the composition bundle."""

from __future__ import annotations

import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .contract import digest_bytes, digest_json, safe_artifact, validate_bundle
from .errors import TrainingError


def _child(root: ET.Element, tag: str) -> ET.Element:
    value = root.find(tag)
    if value is None:
        value = ET.SubElement(root, tag)
    return value


def _body(root: ET.Element, name: str) -> ET.Element:
    for value in root.findall(".//body"):
        if value.get("name") == name:
            return value
    raise TrainingError("TRAINING_MODEL_BINDING_MISSING", f"Required body is absent: {name}")


def _ensure_foot_geometry(root: ET.Element, side: str) -> None:
    ankle = _body(root, f"{side}_ankle_link")
    by_class = {
        geom.get("class"): geom
        for geom in ankle.findall("geom")
        if geom.get("class") in {"foot1", "foot2", "foot3"}
    }
    if set(by_class) != {"foot1", "foot2", "foot3"}:
        raise TrainingError(
            "TRAINING_MODEL_BINDING_MISSING",
            f"{side} ankle does not expose the three Menagerie foot geoms.",
        )
    for suffix, geom in by_class.items():
        expected = f"{side}_{suffix}"
        current = geom.get("name")
        if current not in {None, expected}:
            raise TrainingError(
                "TRAINING_MODEL_NAME_CONFLICT",
                f"Foot geom name conflicts with the training adapter: {current}",
            )
        geom.set("name", expected)
    site_name = f"{side}_foot"
    sites = [site for site in ankle.findall("site") if site.get("name") == site_name]
    if not sites:
        ET.SubElement(
            ankle,
            "site",
            {
                "name": site_name,
                "pos": "0.02 0 -0.045",
                "size": "0.015",
            },
        )


def _ensure_floor(root: ET.Element) -> None:
    worldbody = _child(root, "worldbody")
    named = [geom for geom in worldbody.findall("geom") if geom.get("name") == "floor"]
    if named:
        return
    ET.SubElement(
        worldbody,
        "geom",
        {
            "name": "floor",
            "type": "plane",
            "size": "0 0 0.05",
            "material": "worldspec_training_ground",
            "contype": "1",
            "conaffinity": "1",
        },
    )
    asset = _child(root, "asset")
    if not any(
        value.get("name") == "worldspec_training_ground" for value in asset.findall("material")
    ):
        ET.SubElement(
            asset,
            "material",
            {
                "name": "worldspec_training_ground",
                "rgba": "0.35 0.35 0.35 1",
            },
        )


def _ensure_sensor(sensor: ET.Element, tag: str, name: str, attributes: dict[str, str]) -> None:
    existing = [value for value in sensor.findall(tag) if value.get("name") == name]
    if existing:
        return
    ET.SubElement(sensor, tag, {"name": name, **attributes})


def _ensure_sensors(root: ET.Element) -> None:
    sensor = _child(root, "sensor")
    _ensure_sensor(sensor, "gyro", "gyro", {"site": "imu"})
    _ensure_sensor(sensor, "velocimeter", "local_linvel", {"site": "imu"})
    _ensure_sensor(
        sensor,
        "framezaxis",
        "upvector",
        {"objtype": "site", "objname": "imu"},
    )
    _ensure_sensor(
        sensor,
        "framelinvel",
        "global_linvel",
        {"objtype": "site", "objname": "imu"},
    )
    _ensure_sensor(
        sensor,
        "frameangvel",
        "global_angvel",
        {"objtype": "site", "objname": "imu"},
    )
    for side in ("left", "right"):
        _ensure_sensor(
            sensor,
            "framelinvel",
            f"{side}_foot_global_linvel",
            {"objtype": "site", "objname": f"{side}_foot"},
        )
        for index in range(1, 4):
            _ensure_sensor(
                sensor,
                "contact",
                f"{side}_foot{index}_floor_found",
                {
                    "geom1": f"{side}_foot{index}",
                    "geom2": "floor",
                    "reduce": "mindist",
                    "num": "1",
                    "data": "found",
                },
            )


def _copy_inventory(bundle_dir: Path, destination: Path, manifest: dict[str, Any]) -> None:
    for item in manifest["artifacts"]:
        source = safe_artifact(bundle_dir, item["path"])
        target = destination / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def prepare_training_model(
    profile: dict[str, Any], bundle_dir: Path, work_dir: Path
) -> tuple[Path, dict[str, Any]]:
    """Copy a verified bundle and add deterministic, non-dynamic instrumentation."""

    manifest = validate_bundle(profile, bundle_dir)
    destination = (work_dir / "target-bundle").resolve()
    if destination.exists():
        raise TrainingError("TRAINING_WORKDIR_NOT_EMPTY", f"Refusing to overwrite {destination}")
    destination.mkdir(parents=True)
    _copy_inventory(bundle_dir.resolve(), destination, manifest)
    source_model = safe_artifact(destination, manifest["model"])
    head = source_model.read_bytes()[:8192].upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in head:
        raise TrainingError("TRAINING_XML_UNSAFE", "DTD and entity declarations are forbidden.")
    try:
        tree = ET.parse(source_model)
    except ET.ParseError as error:
        raise TrainingError(
            "TRAINING_XML_INVALID", "Composition model is not valid XML."
        ) from error
    root = tree.getroot()
    option = _child(root, "option")
    option.set("timestep", format(profile["training"]["simulationTimestepSeconds"], ".17g"))
    _ensure_foot_geometry(root, "left")
    _ensure_foot_geometry(root, "right")
    _ensure_floor(root)
    _ensure_sensors(root)
    ET.indent(tree, space="  ")
    training_model = destination / "training-model.xml"
    tree.write(training_model, encoding="utf-8", xml_declaration=True)
    derived = {
        "manifestVersion": "0.1.0",
        "sourceBundleDigest": manifest["bundleDigest"],
        "sourceModel": manifest["model"],
        "derivedModel": "training-model.xml",
        "derivedModelDigest": digest_bytes(training_model.read_bytes()),
        "profileDigest": digest_json(profile),
        "transformations": [
            "set_simulation_timestep",
            "assign_stable_foot_geom_names",
            "add_foot_sites",
            "add_training_floor",
            "add_observation_and_contact_sensors",
        ],
        "dynamicsStatement": (
            "Sensors and geom names do not change robot dynamics; the training floor "
            "adds the declared environment contact surface."
        ),
        "evidenceStatus": "derived",
    }
    (destination / "training-model-derivation.json").write_text(
        json.dumps(derived, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return training_model, derived
