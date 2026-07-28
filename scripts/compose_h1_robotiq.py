#!/usr/bin/env python3
"""Compose locked Menagerie H1 and Robotiq sources without mutating them.

The output is a new standalone MuJoCo bundle. Mount transforms come from an
explicit profile and remain estimated until separate kinematic/dynamic evidence
upgrades them. This script verifies every locked source again before reading it.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = ROOT / "third_party" / "h1-kitchen.lock.json"
DEFAULT_PROFILE = ROOT / "examples" / "h1-kitchen" / "composition-profile.json"

sys.path.insert(0, str(ROOT / "scripts"))
from fetch_h1_kitchen_sources import (
    VerificationError,
    digest_file,
    read_lock,
    safe_relative,
    verify_repository,
)

REFERENCE_ATTRIBUTES = {
    "body",
    "body1",
    "body2",
    "childclass",
    "class",
    "joint",
    "joint1",
    "joint2",
    "material",
    "mesh",
    "site",
    "site1",
    "site2",
    "target",
    "tendon",
}
DECLARATION_TAGS = {
    "body",
    "camera",
    "default",
    "fixed",
    "general",
    "geom",
    "joint",
    "light",
    "material",
    "mesh",
    "motor",
    "position",
    "site",
    "spatial",
    "velocity",
}
KNOWN_OPTION_ATTRIBUTES = {"cone", "impratio"}


class CompositionError(RuntimeError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode()


def digest_json(value: Any) -> str:
    return f"sha256:{hashlib.sha256(canonical_bytes(value)).hexdigest()}"


def read_json(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise CompositionError(f"expected a JSON object: {path}")
    return document


def reject_unsafe_xml(path: Path) -> None:
    head = path.read_bytes()[:8192].upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in head:
        raise CompositionError(f"DTD or entity declarations are forbidden: {path}")


def parse_xml(path: Path) -> ET.ElementTree:
    reject_unsafe_xml(path)
    try:
        return ET.parse(path)
    except ET.ParseError as exc:
        raise CompositionError(f"invalid XML {path}: {exc}") from exc


def float_list(values: list[float]) -> str:
    if any(not math.isfinite(value) for value in values):
        raise CompositionError("transform contains a non-finite value")
    return " ".join(format(value, ".17g") for value in values)


def validate_transform(transform: dict[str, Any], label: str) -> None:
    translation = transform.get("translation")
    quaternion = transform.get("rotationWxyz")
    if not isinstance(translation, list) or len(translation) != 3:
        raise CompositionError(f"{label}.translation must contain three numbers")
    if not isinstance(quaternion, list) or len(quaternion) != 4:
        raise CompositionError(f"{label}.rotationWxyz must contain four numbers")
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float))
        for value in [*translation, *quaternion]
    ):
        raise CompositionError(f"{label} contains a non-number")
    norm = math.sqrt(sum(float(value) ** 2 for value in quaternion))
    if abs(norm - 1.0) > 1e-9:
        raise CompositionError(f"{label}.rotationWxyz is not normalized")


def validate_profile(profile: dict[str, Any], lock_digest: str) -> None:
    if profile.get("profileVersion") != "0.1.0":
        raise CompositionError("unsupported composition profileVersion")
    if profile.get("sourceLockDigest") != lock_digest:
        raise CompositionError("composition profile does not bind the selected source lock")
    base = profile.get("baseRobot")
    grippers = profile.get("grippers")
    if not isinstance(base, dict) or not isinstance(grippers, list) or not grippers:
        raise CompositionError("profile must contain a baseRobot and at least one gripper")
    composition = profile.get("composition")
    if (
        not isinstance(composition, dict)
        or composition.get("optionMergePolicy") != "strict_known_attributes"
        or composition.get("preserveNativePayloads") is not True
    ):
        raise CompositionError("unsupported or unsafe composition policy")
    if len(grippers) > 2:
        raise CompositionError("at most two grippers are supported by this profile")
    namespaces: set[str] = set()
    sides: set[str] = set()
    for gripper in grippers:
        namespace = gripper.get("namespace")
        side = gripper.get("side")
        if not isinstance(namespace, str) or not namespace.endswith("_"):
            raise CompositionError("each namespace must be a string ending in underscore")
        if namespace in namespaces:
            raise CompositionError(f"duplicate namespace: {namespace}")
        if side not in {"left", "right"} or side in sides:
            raise CompositionError(f"invalid or duplicate side: {side}")
        namespaces.add(namespace)
        sides.add(side)
        validate_transform(gripper["mount"], f"{namespace}mount")
        if gripper.get("evidenceStatus") not in {"estimated", "derived", "measured"}:
            raise CompositionError("composition mounts require an explicit evidence status")
        if gripper.get("validationStatus") not in {
            "unvalidated",
            "native_load_passed",
            "kinematic_validated",
            "dynamic_validated",
        }:
            raise CompositionError("invalid gripper validationStatus")


def find_source(
    lock: dict[str, Any], component_id: str
) -> tuple[int, dict[str, Any], dict[str, Any]]:
    for index, source in enumerate(lock["sources"]):
        for component in source["components"]:
            if component["id"] == component_id:
                return index, source, component
    raise CompositionError(f"component is absent from source lock: {component_id}")


def repository_path(cache: Path, index: int) -> Path:
    path = cache / "repositories" / f"source-{index}"
    if not path.is_dir():
        raise CompositionError(f"verified repository is absent: {path}")
    return path


def verify_cache(cache: Path, lock: dict[str, Any], lock_digest: str) -> None:
    manifest_path = cache / "verified-manifest.json"
    if not manifest_path.is_file():
        raise CompositionError("cache has no verified-manifest.json")
    manifest = read_json(manifest_path)
    if manifest.get("lockDigest") != lock_digest:
        raise CompositionError("verified cache was created from a different source lock")
    for index, source in enumerate(lock["sources"]):
        try:
            verify_repository(repository_path(cache, index), source)
        except VerificationError as exc:
            raise CompositionError(str(exc)) from exc


def component_root(
    cache: Path,
    lock: dict[str, Any],
    component_id: str,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    index, source, component = find_source(lock, component_id)
    repository = repository_path(cache, index)
    if component["kind"] == "tree":
        return safe_relative(repository, component["path"]), source, component
    raise CompositionError(f"component is not a source tree: {component_id}")


def component_file(
    component_root_path: Path,
    component: dict[str, Any],
    declared_path: str,
) -> Path:
    declared = Path(declared_path)
    component_path = Path(component["path"])
    if (
        declared.is_absolute()
        or ".." in declared.parts
        or len(declared.parts) <= len(component_path.parts)
        or declared.parts[: len(component_path.parts)] != component_path.parts
    ):
        raise CompositionError(
            f"sourceModelPath must be inside locked component {component['path']}: "
            f"{declared_path}"
        )
    internal = Path(*declared.parts[len(component_path.parts) :])
    return safe_relative(component_root_path, internal.as_posix())


def declared_symbols(root: ET.Element) -> set[str]:
    names: set[str] = set()
    for element in root.iter():
        name = element.get("name")
        if name and element.tag in DECLARATION_TAGS:
            names.add(name)
        if element.tag == "mesh" and not name and element.get("file"):
            names.add(Path(element.get("file", "")).stem)
        class_name = element.get("class")
        if element.tag == "default" and class_name:
            names.add(class_name)
    return names


def namespace_tree(root: ET.Element, namespace: str) -> None:
    symbols = declared_symbols(root)
    for element in root.iter():
        implicit_mesh_name = None
        if element.tag == "mesh" and not element.get("name") and element.get("file"):
            implicit_mesh_name = Path(element.get("file", "")).stem
            element.set("name", f"{namespace}{implicit_mesh_name}")
        name = element.get("name")
        if name and name in symbols and name != f"{namespace}{implicit_mesh_name}":
            element.set("name", f"{namespace}{name}")
        for attribute in REFERENCE_ATTRIBUTES:
            value = element.get(attribute)
            if value in symbols:
                element.set(attribute, f"{namespace}{value}")


def rewrite_mesh_paths(root: ET.Element, directory: str) -> None:
    for mesh in root.findall(".//mesh"):
        file_name = mesh.get("file")
        if not file_name:
            continue
        relative = Path(file_name)
        if relative.is_absolute() or ".." in relative.parts:
            raise CompositionError(f"unsafe mesh path in source model: {file_name}")
        mesh.set("file", f"{directory}/{relative.as_posix()}")


def require_child(root: ET.Element, tag: str) -> ET.Element:
    child = root.find(tag)
    if child is None:
        raise CompositionError(f"source model has no <{tag}> section")
    return child


def find_body(root: ET.Element, name: str) -> ET.Element:
    for body in root.findall(".//body"):
        if body.get("name") == name:
            return body
    raise CompositionError(f"parent body is absent from H1 model: {name}")


def merge_option(base_root: ET.Element, gripper_root: ET.Element) -> None:
    source = gripper_root.find("option")
    if source is None:
        return
    unknown = set(source.attrib) - KNOWN_OPTION_ATTRIBUTES
    if unknown:
        raise CompositionError(f"unknown Robotiq option attributes: {sorted(unknown)}")
    target = base_root.find("option")
    if target is None:
        target = ET.Element("option")
        compiler = base_root.find("compiler")
        insertion = list(base_root).index(compiler) + 1 if compiler is not None else 0
        base_root.insert(insertion, target)
    for key, value in source.attrib.items():
        current = target.get(key)
        if current is not None and current != value:
            raise CompositionError(f"conflicting MuJoCo option {key}: {current} != {value}")
        target.set(key, value)


def append_section(base_root: ET.Element, tag: str, source_root: ET.Element) -> None:
    source = source_root.find(tag)
    if source is None:
        return
    target = base_root.find(tag)
    if target is None:
        target = ET.SubElement(base_root, tag)
    for child in list(source):
        target.append(copy.deepcopy(child))


def copy_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        raise CompositionError(f"refusing to overwrite copied tree: {destination}")
    shutil.copytree(source, destination, symlinks=False)


def file_inventory(root: Path) -> list[dict[str, Any]]:
    result = []
    for path in sorted(
        (
            item
            for item in root.rglob("*")
            if item.is_file() and item.name != "composition-manifest.json"
        ),
        key=lambda item: item.relative_to(root).as_posix().encode(),
    ):
        result.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sizeBytes": path.stat().st_size,
                "digest": digest_file(path),
            }
        )
    return result


def compose(
    cache: Path,
    lock_path: Path,
    profile_path: Path,
    output: Path,
) -> dict[str, Any]:
    lock = read_lock(lock_path)
    lock_digest = digest_file(lock_path)
    profile = read_json(profile_path)
    validate_profile(profile, lock_digest)
    verify_cache(cache, lock, lock_digest)
    if output.exists():
        raise CompositionError(f"refusing to overwrite existing output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    base_root_path, base_source, base_component = component_root(
        cache, lock, profile["baseRobot"]["componentId"]
    )
    base_model = component_file(
        base_root_path,
        base_component,
        profile["baseRobot"]["sourceModelPath"],
    )
    if not base_model.is_file():
        raise CompositionError(f"base model is absent: {base_model}")

    with tempfile.TemporaryDirectory(prefix=f".{output.name}.", dir=output.parent) as temporary:
        staging = Path(temporary) / "bundle"
        staging.mkdir()
        native = staging / "native"
        assets = staging / "assets"
        native.mkdir()
        assets.mkdir()

        copy_tree(base_root_path, native / "unitree_h1")
        copy_tree(base_root_path / "assets", assets / "h1")
        base_tree = parse_xml(base_model)
        base_xml_root = base_tree.getroot()
        base_xml_root.set("model", profile["composition"]["modelName"])
        rewrite_mesh_paths(require_child(base_xml_root, "asset"), "h1")

        composition_entries = []
        for gripper in profile["grippers"]:
            gripper_root_path, gripper_source, gripper_component = component_root(
                cache, lock, gripper["componentId"]
            )
            gripper_model = component_file(
                gripper_root_path,
                gripper_component,
                gripper["sourceModelPath"],
            )
            if not gripper_model.is_file():
                raise CompositionError(f"gripper model is absent: {gripper_model}")
            directory = gripper["namespace"].removesuffix("_")
            copy_tree(gripper_root_path, native / directory)
            copy_tree(gripper_root_path / "assets", assets / directory)

            gripper_tree = parse_xml(gripper_model)
            gripper_xml_root = gripper_tree.getroot()
            namespace_tree(gripper_xml_root, gripper["namespace"])
            rewrite_mesh_paths(require_child(gripper_xml_root, "asset"), directory)
            merge_option(base_xml_root, gripper_xml_root)

            append_section(base_xml_root, "asset", gripper_xml_root)
            append_section(base_xml_root, "default", gripper_xml_root)

            worldbody = require_child(gripper_xml_root, "worldbody")
            source_body = worldbody.find("body")
            if source_body is None:
                raise CompositionError("Robotiq source has no root body")
            mounted_body = copy.deepcopy(source_body)
            mount_body_name = f"{gripper['namespace']}mount_frame"
            mount_body = ET.Element(
                "body",
                {
                    "name": mount_body_name,
                    "pos": float_list(gripper["mount"]["translation"]),
                    "quat": float_list(gripper["mount"]["rotationWxyz"]),
                },
            )
            mount_body.append(mounted_body)
            find_body(base_xml_root, gripper["parentBody"]).append(mount_body)

            for section in ("contact", "tendon", "equality", "actuator"):
                append_section(base_xml_root, section, gripper_xml_root)

            namespaced_site = f"{gripper['namespace']}{gripper['tcp']['sourceSite']}"
            if not any(
                site.get("name") == namespaced_site
                for site in mount_body.findall(".//site")
            ):
                raise CompositionError(f"TCP site is absent after namespacing: {namespaced_site}")
            composition_entries.append(
                {
                    "id": gripper["id"],
                    "side": gripper["side"],
                    "namespace": gripper["namespace"],
                    "parentBody": gripper["parentBody"],
                    "mountBody": mount_body_name,
                    "mount": gripper["mount"],
                    "tcp": {
                        **gripper["tcp"],
                        "composedSite": namespaced_site,
                    },
                    "evidenceStatus": gripper["evidenceStatus"],
                    "validationStatus": gripper["validationStatus"],
                    "source": {
                        "repository": gripper_source["repository"],
                        "commit": gripper_source["commit"],
                        "componentId": gripper_component["id"],
                        "treeDigest": gripper_component["treeDigest"],
                    },
                }
            )

        ET.indent(base_tree, space="  ")
        model_path = staging / "model.xml"
        base_tree.write(model_path, encoding="utf-8", xml_declaration=True)
        shutil.copy2(lock_path, staging / "source-lock.json")
        shutil.copy2(profile_path, staging / "composition-profile.json")
        shutil.copy2(
            ROOT / "third_party" / "THIRD_PARTY_NOTICES.md",
            staging / "THIRD_PARTY_NOTICES.md",
        )

        profile_digest = digest_json(profile)
        manifest = {
            "manifestVersion": "0.1.0",
            "bundleKind": "h1_robotiq_composition",
            "model": "model.xml",
            "sourceLockDigest": lock_digest,
            "compositionProfileDigest": profile_digest,
            "baseRobot": {
                "repository": base_source["repository"],
                "commit": base_source["commit"],
                "componentId": base_component["id"],
                "treeDigest": base_component["treeDigest"],
            },
            "grippers": composition_entries,
            "evidenceStatus": "estimated",
            "validationStatus": "unvalidated",
            "executionStatus": "not_executed",
        }
        (staging / "composition-manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        inventory = file_inventory(staging)
        manifest["artifacts"] = inventory
        manifest["bundleDigest"] = digest_json(inventory)
        (staging / "composition-manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        staging.rename(output)
        return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest = compose(args.cache, args.lock, args.profile, args.output)
    except (CompositionError, VerificationError, OSError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
