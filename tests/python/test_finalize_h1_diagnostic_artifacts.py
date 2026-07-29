from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "finalize_h1_diagnostic_artifacts",
    ROOT / "scripts" / "finalize_h1_diagnostic_artifacts.py",
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
finalize = MODULE.finalize


def _identity(path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    return {
        "path": path.name,
        "sizeBytes": len(payload),
        "digest": f"sha256:{hashlib.sha256(payload).hexdigest()}",
    }


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    controller = tmp_path / "whole-body-controller.json"
    trace = tmp_path / "evaluation-traces.jsonl"
    equivalence = tmp_path / "equivalence-report.json"
    report = tmp_path / "whole-body-diagnostic-replay-report.json"
    receipt = tmp_path / "artifact-receipt.json"
    controller.write_text('{"controller":"frozen"}\n', encoding="utf-8")
    trace.write_text('{"step":0}\n', encoding="utf-8")
    _write_json(
        equivalence,
        {
            "attemptId": "a5-ci-test-replay-03",
            "formalEquivalenceGate": "passed",
        },
    )
    _write_json(
        report,
        {
            "attemptId": "a5-ci-test-replay-03",
            "scope": "h1_whole_body_task_space_control_diagnostic_replay",
            "artifactTransferStatus": "pending",
            "controllerArtifact": _identity(controller),
            "traceArtifact": _identity(trace),
            "equivalenceArtifact": _identity(equivalence),
        },
    )
    return report, controller, trace, equivalence, receipt


def test_finalize_verifies_artifacts_before_writing_receipt(
    tmp_path: Path,
) -> None:
    report, controller, trace, equivalence, receipt = _fixture(tmp_path)

    result = finalize(
        report_path=report,
        controller_path=controller,
        trace_path=trace,
        equivalence_path=equivalence,
        receipt_path=receipt,
        attempt_id="a5-ci-test-replay-03",
        generated_at="2026-07-30T00:00:00Z",
    )

    final_report = json.loads(report.read_text(encoding="utf-8"))
    assert final_report["artifactTransferStatus"] == "passed"
    assert result == json.loads(receipt.read_text(encoding="utf-8"))
    assert result["artifacts"]["report"] == _identity(report)
    assert result["artifacts"]["controller"] == _identity(controller)
    assert result["artifacts"]["trace"] == _identity(trace)
    assert result["artifacts"]["equivalence"] == _identity(equivalence)


def test_finalize_rejects_digest_mismatch_without_mutating_report(
    tmp_path: Path,
) -> None:
    report, controller, trace, equivalence, receipt = _fixture(tmp_path)
    original_report = report.read_bytes()
    trace.write_text('{"step":1}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="traceArtifact digest mismatch"):
        finalize(
            report_path=report,
            controller_path=controller,
            trace_path=trace,
            equivalence_path=equivalence,
            receipt_path=receipt,
            attempt_id="a5-ci-test-replay-03",
        )

    assert report.read_bytes() == original_report
    assert not receipt.exists()


def test_finalize_rejects_attempt_mismatch(tmp_path: Path) -> None:
    report, controller, trace, equivalence, receipt = _fixture(tmp_path)

    with pytest.raises(ValueError, match="Attempt ID mismatch"):
        finalize(
            report_path=report,
            controller_path=controller,
            trace_path=trace,
            equivalence_path=equivalence,
            receipt_path=receipt,
            attempt_id="a5-ci-test-replay-04",
        )
