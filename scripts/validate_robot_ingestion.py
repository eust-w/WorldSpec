#!/usr/bin/env python3
"""Exercise URDF/MJCF ingestion through schema validation and MuJoCo loading."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import mujoco
import numpy as np


ROOT = Path(__file__).resolve().parents[1]


def run(*arguments: str) -> str:
    result = subprocess.run(
        ["cargo", "run", "--quiet", "-p", "worldspec-cli", "--", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def exercise(format_name: str, source: Path, root: Path) -> dict:
    draft = root / f"{format_name}-draft.json"
    world = root / f"{format_name}-world.json"
    bundle = root / f"{format_name}-mujoco"
    cas = root / "cas"
    first_digest = run(
        "ingest",
        str(source),
        "--rights",
        "examples/minimal-cube/rights.json",
        "--output",
        str(draft),
        "--candidate-output",
        str(world),
        "--cas-root",
        str(cas),
        "--schema-dir",
        "schemas/0.1",
    )
    second_draft = root / f"{format_name}-draft-second.json"
    second_world = root / f"{format_name}-world-second.json"
    second_digest = run(
        "ingest",
        str(source),
        "--rights",
        "examples/minimal-cube/rights.json",
        "--output",
        str(second_draft),
        "--candidate-output",
        str(second_world),
        "--cas-root",
        str(cas),
        "--schema-dir",
        "schemas/0.1",
    )
    assert first_digest == second_digest
    assert draft.read_bytes() == second_draft.read_bytes()
    assert world.read_bytes() == second_world.read_bytes()

    validation = json.loads(
        run(
            "validate",
            str(world),
            "--schema",
            "world-definition.schema.json",
            "--schema-dir",
            "schemas/0.1",
            "--output",
            "json",
        )
    )
    assert validation["valid"], validation
    run(
        "compile",
        "--input",
        str(world),
        "--target-profile",
        "examples/minimal-cube/target-profile.json",
        "--build-intent",
        "examples/minimal-cube/build-intent.json",
        "--output-dir",
        str(bundle),
        "--cas-root",
        str(cas),
        "--schema-dir",
        "schemas/0.1",
    )

    model = mujoco.MjModel.from_xml_path(str(bundle / "model.xml"))
    data = mujoco.MjData(model)
    for _ in range(20):
        mujoco.mj_step(model, data)
    assert np.isfinite(data.qpos).all()
    assert np.isfinite(data.qvel).all()
    summary = json.loads((bundle / "compile-summary.json").read_text())
    loss_capabilities = {item["capability"] for item in summary["losses"]}
    assert "capability://worldspec/resolved-physics-evidence" in loss_capabilities
    assert "capability://worldspec/collision-shape" in loss_capabilities
    return {
        "draftDigest": first_digest,
        "bodies": int(model.nbody),
        "joints": int(model.njnt),
        "steps": 20,
        "finite": True,
        "l2Eligible": False,
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="worldspec-robot-ingestion-") as temporary:
        root = Path(temporary)
        report = {
            "urdf": exercise(
                "urdf", ROOT / "examples/ingestion/robot/simple.urdf", root
            ),
            "mjcf": exercise(
                "mjcf", ROOT / "examples/ingestion/robot/simple.mjcf", root
            ),
            "mujocoRuntime": mujoco.__version__,
        }
        print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
