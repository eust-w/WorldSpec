from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from worldspec_h1_training.contract import digest_json
from worldspec_h1_training.errors import TrainingError
from worldspec_h1_training.whole_body import (
    A5R_FAILED_REPORT_DIGEST,
    WHOLE_BODY_CONTROLLER,
    WHOLE_BODY_GATES,
    make_whole_body_evaluation_profile,
    solve_box_qp,
    validate_whole_body_profile,
)

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "examples" / "h1-kitchen" / "locomotion-training-profile.json"
SUPERVISOR = ROOT / "examples" / "h1-kitchen" / "locomotion-supervisor-profile.json"
CONTROL = ROOT / "examples" / "h1-kitchen" / "whole-body-control-profile.json"


def _profiles() -> tuple[dict, dict, dict]:
    return tuple(
        json.loads(path.read_text(encoding="utf-8"))
        for path in (BASE, SUPERVISOR, CONTROL)
    )


def test_a5c_profile_is_bound_to_failure_and_forbids_full_task_claim() -> None:
    base, supervisor, control = _profiles()

    validate_whole_body_profile(base, supervisor, control)

    assert control["baseTrainingProfileDigest"] == digest_json(base)
    assert control["supervisorProfileDigest"] == digest_json(supervisor)
    assert control["failedA5RReportDigest"] == A5R_FAILED_REPORT_DIGEST
    assert control["controller"] == WHOLE_BODY_CONTROLLER
    assert control["qualityGates"] == WHOLE_BODY_GATES
    assert control["artifactPolicy"]["fullTaskClaim"] == "forbidden"
    assert control["artifactPolicy"]["l3Claim"] == "forbidden"


def test_a5c_effective_profile_uses_single_environment_runtime() -> None:
    base, supervisor, control = _profiles()

    effective = make_whole_body_evaluation_profile(base, supervisor, control)

    assert effective["training"]["seed"] == 41
    assert effective["training"]["numEnvs"] == 1
    assert effective["runtime"]["ccdIterations"] == 50
    assert effective["runtime"]["mjxCapacity"] == control["runtime"]["mjxCapacity"]


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("failedA5RReportDigest", "sha256:" + ("0" * 64), "A5-R failure"),
        ("controller", {}, "controller contract"),
        ("qualityGates", {}, "gates cannot be relaxed"),
    ],
)
def test_a5c_rejects_lineage_or_gate_drift(field: str, value, match: str) -> None:
    base, supervisor, control = _profiles()
    candidate = copy.deepcopy(control)
    candidate[field] = value

    with pytest.raises(TrainingError, match=match):
        validate_whole_body_profile(base, supervisor, candidate)


def test_box_qp_matches_diagonal_solution_and_reports_kkt_residual() -> None:
    hessian = np.diag([2.0, 4.0])
    gradient = np.asarray([-2.0, 8.0])

    solution, objective, projected_gradient = solve_box_qp(
        hessian,
        gradient,
        np.asarray([-0.5, -1.0]),
        np.asarray([0.75, 1.0]),
        iterations=16,
    )

    assert solution == pytest.approx([0.75, -1.0])
    assert objective == pytest.approx(-6.9375)
    assert projected_gradient <= 1e-12


def test_a800_whole_body_spike_is_fail_closed_and_not_training() -> None:
    entrypoint = (
        ROOT / "ops" / "a800" / "h1-locomotion-midterm-entrypoint.sh"
    ).read_text(encoding="utf-8")
    launcher = (
        ROOT / "scripts" / "run_a800_h1_locomotion_midterm.sh"
    ).read_text(encoding="utf-8")
    wrapper = (
        ROOT / "scripts" / "run_a800_h1_whole_body_control_spike.sh"
    ).read_text(encoding="utf-8")

    assert "run_whole_body_control_spike" in entrypoint
    assert "WORLDSPEC_A800_WHOLE_BODY_RESULT=" in entrypoint
    assert "formalControlGate" in launcher
    assert "h1-whole-body-control-report.schema.json" in launcher
    assert "whole-body-controller.json" in launcher
    assert "whole-body-control-profile.json" in wrapper
    assert "100000000" not in wrapper
