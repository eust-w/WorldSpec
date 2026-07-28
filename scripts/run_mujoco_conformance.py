#!/usr/bin/env python3
"""Run digest-bound MuJoCo L2 conformance against a compiled bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def digest_bytes(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def digest_json(value: object) -> str:
    return digest_bytes(canonical(value))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_artifact(bundle: Path, artifact: dict[str, Any]) -> tuple[Path | None, str | None]:
    relative = Path(artifact["path"])
    if relative.is_absolute() or ".." in relative.parts:
        return None, "unsafe artifact path"
    joined = bundle / relative
    try:
        if joined.is_symlink():
            return None, "symlink artifact is forbidden"
        resolved = joined.resolve(strict=True)
        resolved.relative_to(bundle)
        payload = resolved.read_bytes()
    except (OSError, ValueError):
        return None, "artifact is missing or escapes the bundle"
    if digest_bytes(payload) != artifact["digest"]:
        return None, "artifact digest mismatch"
    if artifact.get("sizeBytes") != len(payload):
        return None, "artifact size mismatch"
    return resolved, None


def artifact_ref(
    identifier: str,
    path: str,
    payload: bytes,
    media_type: str,
    role: str,
) -> dict[str, Any]:
    return {
        "id": identifier,
        "digest": digest_bytes(payload),
        "mediaType": media_type,
        "path": path,
        "sizeBytes": len(payload),
        "role": role,
    }


def test_result(
    identifier: str,
    result: str,
    evidence: dict[str, Any],
    metrics: dict[str, Any] | None = None,
    diagnostics: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "id": identifier,
        "version": "0.1.0",
        "result": result,
        "metrics": metrics or {},
        "tolerances": {},
        "evidenceArtifacts": [evidence],
        "diagnostics": diagnostics or [],
    }
    return value


def diagnostic(code: str, message: str) -> dict[str, Any]:
    return {"code": code, "severity": "error", "message": message}


def summary(tests: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {
        "passed": sum(test["result"] == "pass" for test in tests),
        "failed": sum(test["result"] == "fail" for test in tests),
        "unknown": sum(test["result"] == "unknown" for test in tests),
        "notRun": sum(test["result"] == "not_run" for test in tests),
    }
    if counts["failed"]:
        overall = "fail"
    elif counts["unknown"] or counts["notRun"]:
        overall = "incomplete"
    else:
        overall = "pass"
    return {**counts, "overall": overall}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--target-profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=100)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 1 <= args.steps <= 100_000:
        raise SystemExit("--steps must be between 1 and 100000")
    bundle = args.bundle.resolve(strict=True)
    manifest = read_json(bundle / "build-manifest.json")
    target = read_json(args.target_profile)
    if target.get("target") != "mujoco":
        raise SystemExit("TargetProfile.target must be mujoco")
    manifest_digest = digest_json(manifest)
    target_digest = digest_json(target)
    runner_payload = Path(__file__).read_bytes()
    runner = {
        "name": "worldspec-mujoco-conformance",
        "version": "0.1.0",
        "digest": digest_bytes(runner_payload),
    }

    artifact_errors: list[str] = []
    resolved_artifacts: dict[str, Path] = {}
    for artifact in manifest["artifacts"]:
        path, error = safe_artifact(bundle, artifact)
        if error:
            artifact_errors.append(f"{artifact['id']}: {error}")
        elif path is not None:
            resolved_artifacts[artifact["id"]] = path

    actual_os = platform.system().lower()
    actual_arch = platform.machine().lower()
    runtime_version = "unavailable"
    import_error: str | None = None
    try:
        import mujoco
        import numpy as np

        runtime_version = mujoco.__version__
    except (ImportError, OSError) as error:
        import_error = str(error)

    evidence_document: dict[str, Any] = {
        "kind": "worldspec.mujoco.conformance-evidence",
        "specVersion": "0.1.0",
        "buildManifestDigest": manifest_digest,
        "targetProfileDigest": target_digest,
        "runner": runner,
        "host": {
            "os": actual_os,
            "architecture": actual_arch,
            "python": platform.python_version(),
            "runtimeVersion": runtime_version,
        },
        "artifactErrors": artifact_errors,
        "stepsRequested": args.steps,
    }
    evidence_path = "conformance/mujoco-evidence.json"
    evidence_payload = canonical(evidence_document)
    destination = bundle / evidence_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(evidence_payload)
    evidence = artifact_ref(
        "artifact://conformance/mujoco/evidence",
        evidence_path,
        evidence_payload,
        "application/vnd.worldspec.conformance-evidence+json",
        "conformance_evidence",
    )

    tests: list[dict[str, Any]] = []
    tests.append(
        test_result(
            "test://worldspec/artifact-integrity",
            "pass" if not artifact_errors else "fail",
            evidence,
            {"artifactCount": len(manifest["artifacts"])},
            [diagnostic("ARTIFACT_INTEGRITY_FAILED", item) for item in artifact_errors],
        )
    )
    expected_os = str(target["platform"]["os"]).lower()
    expected_arch = str(target["platform"]["architecture"]).lower()
    environment_matches = (
        actual_os == expected_os
        and actual_arch == expected_arch
        and runtime_version == target["runtimeVersion"]
    )
    tests.append(
        test_result(
            "test://worldspec/profile-environment",
            "pass" if environment_matches else "fail",
            evidence,
            {
                "expectedOs": expected_os,
                "actualOs": actual_os,
                "expectedArchitecture": expected_arch,
                "actualArchitecture": actual_arch,
                "expectedRuntimeVersion": target["runtimeVersion"],
                "actualRuntimeVersion": runtime_version,
            },
            []
            if environment_matches
            else [
                diagnostic(
                    "TARGET_PROFILE_ENVIRONMENT_MISMATCH",
                    "actual OS, architecture, or MuJoCo version differs from TargetProfile",
                )
            ],
        )
    )

    entrypoint = next(
        (
            resolved_artifacts[artifact["id"]]
            for artifact in manifest["artifacts"]
            if artifact.get("role") == "entrypoint"
            and artifact["id"] in resolved_artifacts
        ),
        None,
    )
    load_result = "not_run"
    load_metrics: dict[str, Any] = {}
    load_diagnostics: list[dict[str, Any]] = []
    rest_result = "not_run"
    rest_metrics: dict[str, Any] = {}
    rest_diagnostics: list[dict[str, Any]] = []
    if import_error is not None:
        load_diagnostics.append(diagnostic("MUJOCO_RUNTIME_UNAVAILABLE", import_error))
        rest_diagnostics.append(diagnostic("MUJOCO_RUNTIME_UNAVAILABLE", import_error))
    elif artifact_errors or entrypoint is None:
        message = "artifact integrity failed or no entrypoint artifact was resolved"
        load_diagnostics.append(diagnostic("MUJOCO_ENTRYPOINT_UNAVAILABLE", message))
        rest_diagnostics.append(diagnostic("MUJOCO_ENTRYPOINT_UNAVAILABLE", message))
    else:
        try:
            model = mujoco.MjModel.from_xml_path(str(entrypoint))
            data = mujoco.MjData(model)
            load_result = "pass"
            load_metrics = {
                "bodies": int(model.nbody),
                "joints": int(model.njnt),
                "geometries": int(model.ngeom),
                "degreesOfFreedom": int(model.nv),
            }
            for _ in range(args.steps):
                mujoco.mj_step(model, data)
            finite = bool(
                np.isfinite(data.qpos).all()
                and np.isfinite(data.qvel).all()
                and np.isfinite(data.qacc).all()
            )
            rest_result = "pass" if finite else "fail"
            rest_metrics = {"steps": args.steps, "finite": finite}
            if not finite:
                rest_diagnostics.append(
                    diagnostic("MUJOCO_NON_FINITE_STATE", "qpos, qvel, or qacc is non-finite")
                )
        # Native parsers may raise backend-specific exception subclasses. They are
        # converted into explicit target-load evidence instead of losing the report.
        except Exception as error:  # noqa: BLE001
            load_result = "fail"
            load_diagnostics.append(diagnostic("MUJOCO_NATIVE_LOAD_FAILED", str(error)))
            rest_diagnostics.append(
                diagnostic("MUJOCO_BEHAVIOR_NOT_RUN", "native load did not succeed")
            )

    known = {
        "test://worldspec/native-load": test_result(
            "test://worldspec/native-load",
            load_result,
            evidence,
            load_metrics,
            load_diagnostics,
        ),
        "test://worldspec/rigid-rest": test_result(
            "test://worldspec/rigid-rest",
            rest_result,
            evidence,
            rest_metrics,
            rest_diagnostics,
        ),
    }
    for required in target["certificationTests"]:
        tests.append(
            known.get(
                required,
                test_result(
                    required,
                    "not_run",
                    evidence,
                    diagnostics=[
                        diagnostic(
                            "CONFORMANCE_TEST_UNIMPLEMENTED",
                            "the MuJoCo v0.1 runner does not implement this test",
                        )
                    ],
                ),
            )
        )

    execution_evidence = "executed" if import_error is None else "not_executed"
    report = {
        "id": f"conformance://local/mujoco/{manifest_digest.removeprefix('sha256:')}",
        "reportVersion": "0.1.0",
        "buildManifestDigest": manifest_digest,
        "targetProfileDigest": target_digest,
        "target": "mujoco",
        "executionEvidence": execution_evidence,
        "runner": runner,
        "environment": {
            "os": actual_os,
            "architecture": actual_arch,
            "runtime": "mujoco",
            "runtimeVersion": runtime_version,
            "hardware": platform.processor() or "unknown",
        },
        "testedArtifacts": manifest["artifacts"],
        "tests": tests,
        "summary": summary(tests),
        "generatedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], sort_keys=True))
    return 0 if report["summary"]["overall"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
