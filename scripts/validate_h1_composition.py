#!/usr/bin/env python3
"""Validate a composed H1/Robotiq bundle with the native MuJoCo runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class ConformanceError(RuntimeError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode()


def digest_bytes(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def digest_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return f"sha256:{hasher.hexdigest()}"


def safe_file(bundle: Path, relative_value: str) -> Path:
    relative = Path(relative_value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ConformanceError(f"unsafe artifact path: {relative_value}")
    candidate = bundle / relative
    if candidate.is_symlink():
        raise ConformanceError(f"symlink artifact is forbidden: {relative_value}")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(bundle):
        raise ConformanceError(f"artifact escapes bundle: {relative_value}")
    return resolved


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


def validate_inventory(
    bundle: Path, manifest: dict[str, Any]
) -> tuple[bool, list[str]]:
    errors = []
    for artifact in manifest["artifacts"]:
        try:
            path = safe_file(bundle, artifact["path"])
        except (ConformanceError, OSError) as exc:
            errors.append(str(exc))
            continue
        if path.stat().st_size != artifact["sizeBytes"]:
            errors.append(f"artifact size mismatch: {artifact['path']}")
        if digest_file(path) != artifact["digest"]:
            errors.append(f"artifact digest mismatch: {artifact['path']}")
    return not errors, errors


def validate_bundle(bundle: Path, steps: int) -> dict[str, Any]:
    manifest_path = safe_file(bundle, "composition-manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tests = []
    inventory_ok, inventory_errors = validate_inventory(bundle, manifest)
    tests.append(
        test(
            "test://worldspec/h1-composition/artifact-integrity",
            "pass" if inventory_ok else "fail",
            {"artifactCount": len(manifest.get("artifacts", []))},
            [
                diagnostic("COMPOSITION_ARTIFACT_INTEGRITY_FAILED", message)
                for message in inventory_errors
            ],
        )
    )

    try:
        import mujoco
        import numpy as np
    except (ImportError, OSError) as exc:
        tests.append(
            test(
                "test://worldspec/h1-composition/native-load",
                "not_run",
                diagnostics=[diagnostic("MUJOCO_RUNTIME_UNAVAILABLE", str(exc))],
            )
        )
        runtime_version = "unavailable"
    else:
        runtime_version = mujoco.__version__
        if not inventory_ok:
            tests.append(
                test(
                    "test://worldspec/h1-composition/native-load",
                    "not_run",
                    diagnostics=[
                        diagnostic(
                            "COMPOSITION_INTEGRITY_REQUIRED",
                            "native loading is blocked until artifact integrity passes",
                        )
                    ],
                )
            )
        else:
            model_path = safe_file(bundle, manifest["model"])
            try:
                model = mujoco.MjModel.from_xml_path(str(model_path))
                data = mujoco.MjData(model)
                mujoco.mj_forward(model, data)
                initial_finite = bool(
                    np.isfinite(data.qpos).all()
                    and np.isfinite(data.qvel).all()
                    and np.isfinite(data.qacc).all()
                )
                for _ in range(steps):
                    mujoco.mj_step(model, data)
                after_finite = bool(
                    np.isfinite(data.qpos).all()
                    and np.isfinite(data.qvel).all()
                    and np.isfinite(data.qacc).all()
                )
                missing = []
                for gripper in manifest["grippers"]:
                    site_name = gripper["tcp"]["composedSite"]
                    actuator_name = f"{gripper['namespace']}fingers_actuator"
                    if (
                        mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, site_name)
                        < 0
                    ):
                        missing.append(site_name)
                    if (
                        mujoco.mj_name2id(
                            model, mujoco.mjtObj.mjOBJ_ACTUATOR, actuator_name
                        )
                        < 0
                    ):
                        missing.append(actuator_name)
                passed = initial_finite and after_finite and not missing
                tests.append(
                    test(
                        "test://worldspec/h1-composition/native-load",
                        "pass" if passed else "fail",
                        {
                            "steps": steps,
                            "simulationTimeSeconds": float(data.time),
                            "initialFinite": initial_finite,
                            "afterFinite": after_finite,
                            "bodies": int(model.nbody),
                            "joints": int(model.njnt),
                            "actuators": int(model.nu),
                            "meshes": int(model.nmesh),
                            "sites": int(model.nsite),
                            "missingNames": missing,
                        },
                        []
                        if passed
                        else [
                            diagnostic(
                                "COMPOSITION_NATIVE_LOAD_FAILED",
                                "the model produced non-finite state or omitted required names",
                            )
                        ],
                    )
                )
            except (ValueError, RuntimeError, mujoco.FatalError) as exc:
                tests.append(
                    test(
                        "test://worldspec/h1-composition/native-load",
                        "fail",
                        diagnostics=[
                            diagnostic("COMPOSITION_NATIVE_LOAD_FAILED", str(exc))
                        ],
                    )
                )

    return {
        "id": "conformance://worldspec/h1-composition/native-load",
        "reportVersion": "0.1.0",
        "bundleDigest": manifest["bundleDigest"],
        "sourceLockDigest": manifest["sourceLockDigest"],
        "compositionProfileDigest": manifest["compositionProfileDigest"],
        "executionEvidence": "executed" if runtime_version != "unavailable" else "not_executed",
        "environment": {
            "os": platform.system().lower(),
            "architecture": platform.machine().lower(),
            "python": platform.python_version(),
            "runtime": "mujoco",
            "runtimeVersion": runtime_version,
        },
        "tests": tests,
        "summary": summarize(tests),
        "generatedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=20)
    args = parser.parse_args()
    if not 1 <= args.steps <= 100_000:
        raise SystemExit("--steps must be between 1 and 100000")
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite output: {args.output}")
    try:
        report = validate_bundle(args.bundle.resolve(strict=True), args.steps)
    except (ConformanceError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical(report) + b"\n")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["summary"]["overall"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
