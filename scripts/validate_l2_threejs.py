#!/usr/bin/env python3
"""Exercise real local Three.js browser L2 issue and tamper rejection."""

from __future__ import annotations

import json
import platform
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], *, expect_success: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if expect_success and result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="worldspec-threejs-l2-cert-") as temporary:
        root = Path(temporary)
        profile = json.loads(
            (ROOT / "examples/minimal-cube/target-profile-threejs.json").read_text()
        )
        profile["id"] = "profile://worldspec/threejs-local-l2"
        profile["platform"]["os"] = platform.system().lower()
        profile["platform"]["architecture"] = platform.machine().lower()
        profile_path = root / "target-profile.json"
        profile_path.write_text(json.dumps(profile, indent=2) + "\n")
        bundle = root / "bundle"
        cli = [
            "cargo",
            "run",
            "--quiet",
            "-p",
            "worldspec-cli",
            "--offline",
            "--",
        ]
        run(
            cli
            + [
                "compile",
                "--input",
                "examples/minimal-cube/world.json",
                "--target-profile",
                str(profile_path),
                "--build-intent",
                "examples/minimal-cube/build-intent.json",
                "--output-dir",
                str(bundle),
                "--schema-dir",
                "schemas/0.1",
            ]
        )
        conformance_path = bundle / "conformance-report.json"
        run(
            [
                "node",
                "web/threejs-preview/conformance.mjs",
                "--bundle",
                str(bundle),
                "--target-profile",
                str(profile_path),
                "--output",
                str(conformance_path),
            ]
        )
        certificate_path = bundle / "certificate.json"
        assessment_path = bundle / "assessment.json"
        issue = cli + [
            "certify",
            "--output",
            str(certificate_path),
            "--issuer",
            "WorldSpec local Three.js L2 validation",
            "--world",
            "examples/minimal-cube/world.json",
            "--target-profile",
            str(profile_path),
            "--build-manifest",
            str(bundle / "build-manifest.json"),
            "--loss-report",
            str(bundle / "loss-report.json"),
            "--conformance-report",
            str(conformance_path),
            "--bundle-dir",
            str(bundle),
            "--assessment-output",
            str(assessment_path),
            "--schema-dir",
            "schemas/0.1",
        ]
        run(issue)
        certificate = json.loads(certificate_path.read_text())
        report = json.loads(conformance_path.read_text())
        assert certificate["level"] == "L2"
        assert certificate["valid"] is True
        assert certificate["signatureStatus"] == "unsigned"
        assert report["executionEvidence"] == "executed"
        assert report["summary"]["overall"] == "pass"
        assert (bundle / "conformance/threejs-preview.png").is_file()

        scene = bundle / "scene.glb"
        scene.write_bytes(scene.read_bytes() + b"tampered")
        tampered = run(issue, expect_success=False)
        assert tampered.returncode != 0
        assert "BUNDLE_ARTIFACT_DIGEST_MISMATCH" in tampered.stderr

        print(
            json.dumps(
                {
                    "runtime": profile["runtimeVersion"],
                    "platform": {
                        "os": profile["platform"]["os"],
                        "architecture": profile["platform"]["architecture"],
                    },
                    "browserL2Issued": True,
                    "screenshotEvidence": True,
                    "tamperRejected": True,
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
