"""Verify and finalize an A5-CI artifact handoff."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import tempfile
from datetime import datetime, timezone
from typing import Any


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()


def identity(path: pathlib.Path) -> dict[str, Any]:
    payload = path.read_bytes()
    return {
        "path": path.name,
        "sizeBytes": len(payload),
        "digest": f"sha256:{hashlib.sha256(payload).hexdigest()}",
    }


def _assert_artifact(
    report: dict[str, Any],
    report_field: str,
    path: pathlib.Path,
) -> None:
    expected = report[report_field]
    actual = identity(path)
    if expected["path"] != actual["path"]:
        raise ValueError(
            f"{report_field} path mismatch: "
            f"expected={expected['path']} actual={actual['path']}"
        )
    for field in ("sizeBytes", "digest"):
        if expected[field] != actual[field]:
            raise ValueError(
                f"{report_field} {field} mismatch: "
                f"expected={expected[field]} actual={actual[field]}"
            )


def _atomic_write(path: pathlib.Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    temporary = pathlib.Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def finalize(
    *,
    report_path: pathlib.Path,
    controller_path: pathlib.Path,
    trace_path: pathlib.Path,
    equivalence_path: pathlib.Path,
    receipt_path: pathlib.Path,
    attempt_id: str,
    generated_at: str | None = None,
) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report["attemptId"] != attempt_id:
        raise ValueError("diagnostic report Attempt ID mismatch")
    if report["scope"] != "h1_whole_body_task_space_control_diagnostic_replay":
        raise ValueError("diagnostic report scope mismatch")
    if report["artifactTransferStatus"] not in {"pending", "passed"}:
        raise ValueError("diagnostic artifact transfer state is invalid")

    _assert_artifact(report, "controllerArtifact", controller_path)
    _assert_artifact(report, "traceArtifact", trace_path)
    _assert_artifact(report, "equivalenceArtifact", equivalence_path)

    equivalence = json.loads(equivalence_path.read_text(encoding="utf-8"))
    if equivalence["attemptId"] != attempt_id:
        raise ValueError("equivalence report Attempt ID mismatch")

    report["artifactTransferStatus"] = "passed"
    report_payload = canonical_bytes(report)
    report_identity = {
        "path": report_path.name,
        "sizeBytes": len(report_payload),
        "digest": f"sha256:{hashlib.sha256(report_payload).hexdigest()}",
    }
    receipt = {
        "id": f"receipt://worldspec/h1/a5ci/{attempt_id}",
        "receiptVersion": "0.1.0",
        "attemptId": attempt_id,
        "status": "verified",
        "artifactCopied": True,
        "artifacts": {
            "report": report_identity,
            "controller": identity(controller_path),
            "trace": identity(trace_path),
            "equivalence": identity(equivalence_path),
        },
        "generatedAt": generated_at
        or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    _atomic_write(report_path, report_payload)
    _atomic_write(receipt_path, canonical_bytes(receipt))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=pathlib.Path, required=True)
    parser.add_argument("--controller", type=pathlib.Path, required=True)
    parser.add_argument("--trace", type=pathlib.Path, required=True)
    parser.add_argument("--equivalence", type=pathlib.Path, required=True)
    parser.add_argument("--receipt", type=pathlib.Path, required=True)
    parser.add_argument("--attempt-id", required=True)
    arguments = parser.parse_args()

    receipt = finalize(
        report_path=arguments.report,
        controller_path=arguments.controller,
        trace_path=arguments.trace,
        equivalence_path=arguments.equivalence,
        receipt_path=arguments.receipt,
        attempt_id=arguments.attempt_id,
    )
    print(json.dumps(receipt, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
