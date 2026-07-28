#!/usr/bin/env python3
"""Compile the synthetic cube twice and validate deterministic target artifacts."""

from __future__ import annotations

import json
import struct
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def compile_target(target: str, profile: str, output: Path) -> dict:
    subprocess.run(
        [
            "cargo",
            "run",
            "--quiet",
            "-p",
            "worldspec-cli",
            "--",
            "compile",
            "--input",
            "examples/minimal-cube/world.json",
            "--target-profile",
            profile,
            "--build-intent",
            "examples/minimal-cube/build-intent.json",
            "--output-dir",
            str(output),
            "--schema-dir",
            "schemas/0.1",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads((output / "build-manifest.json").read_text())


def validate_mujoco(output: Path) -> dict:
    import mujoco
    import numpy as np

    model = mujoco.MjModel.from_xml_path(str(output / "model.xml"))
    data = mujoco.MjData(model)
    for _ in range(20):
        mujoco.mj_step(model, data)
    assert np.isfinite(data.qpos).all()
    assert np.isfinite(data.qvel).all()
    return {
        "runtime": mujoco.__version__,
        "steps": 20,
        "bodies": int(model.nbody),
        "geometries": int(model.ngeom),
        "finite": True,
    }


def validate_glb(output: Path) -> dict:
    payload = (output / "scene.glb").read_bytes()
    magic, version, length = struct.unpack_from("<III", payload, 0)
    assert magic == 0x46546C67
    assert version == 2
    assert length == len(payload)
    chunk_length, chunk_type = struct.unpack_from("<II", payload, 12)
    assert chunk_type == 0x4E4F534A
    document = json.loads(payload[20 : 20 + chunk_length])
    assert document["asset"]["version"] == "2.0"
    return {
        "glbVersion": version,
        "bytes": length,
        "nodes": len(document["nodes"]),
        "meshes": len(document["meshes"]),
    }


def artifact_digests(manifest: dict) -> list[str]:
    return [artifact["digest"] for artifact in manifest["artifacts"]]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="worldspec-compiler-") as temporary:
        root = Path(temporary)
        mujoco_a = compile_target(
            "mujoco", "examples/minimal-cube/target-profile.json", root / "mujoco-a"
        )
        mujoco_b = compile_target(
            "mujoco", "examples/minimal-cube/target-profile.json", root / "mujoco-b"
        )
        three_a = compile_target(
            "threejs",
            "examples/minimal-cube/target-profile-threejs.json",
            root / "three-a",
        )
        three_b = compile_target(
            "threejs",
            "examples/minimal-cube/target-profile-threejs.json",
            root / "three-b",
        )
        assert artifact_digests(mujoco_a) == artifact_digests(mujoco_b)
        assert artifact_digests(three_a) == artifact_digests(three_b)
        assert mujoco_a == mujoco_b
        assert three_a == three_b
        report = {
            "mujoco": validate_mujoco(root / "mujoco-a"),
            "threejsGlb": validate_glb(root / "three-a"),
            "deterministicArtifacts": True,
            "browserValidation": "run npm test in web/threejs-preview",
        }
        print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
