from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from worldspec_h1_training.errors import TrainingError
from worldspec_h1_training.viability import (
    BASELINE_METRICS,
    QUALITY_GATES,
    SEARCH,
    SOURCE_FAILURE,
    assess_viability_metrics,
    validate_viability_profile,
)

ROOT = Path(__file__).resolve().parents[3]
BASE_PROFILE = ROOT / "examples" / "h1-kitchen" / "locomotion-training-profile.json"
MANIPULATION_PROFILE = (
    ROOT / "examples" / "h1-kitchen" / "locomotion-manipulation-balance-profile.json"
)
VIABILITY_PROFILE = (
    ROOT / "examples" / "h1-kitchen" / "locomotion-manipulation-viability-profile.json"
)


def _profiles() -> tuple[dict, dict, dict]:
    return tuple(
        json.loads(path.read_text(encoding="utf-8"))
        for path in (BASE_PROFILE, MANIPULATION_PROFILE, VIABILITY_PROFILE)
    )


def test_viability_profile_is_evidence_bound_and_non_publishable() -> None:
    base, manipulation, profile = _profiles()

    validate_viability_profile(base, manipulation, profile)

    assert profile["sourceFailure"] == SOURCE_FAILURE
    assert profile["search"] == SEARCH
    assert profile["qualityGates"] == QUALITY_GATES
    assert profile["snapshotBank"]["criticalSnapshotIndex"] == 565
    assert profile["sourceFailure"]["evaluationSeed"] == 2
    assert profile["claimBoundary"] == {
        "witnessFoundProvesRecoverableUnderFrozenContract": True,
        "witnessNotFoundProvesUnrecoverable": False,
        "policyCandidateAllowed": False,
        "fullKitchenSingleAllowed": False,
        "fiveOfFiveAllowed": False,
        "hundredMillionTrainingAllowed": False,
        "automaticRetryAllowed": False,
    }


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("sourceFailure", "criticalSnapshotIndex"), 564),
        (("search", "population"), 2048),
        (("qualityGates", "minimumBaseHeight"), 0.7),
        (("claimBoundary", "witnessNotFoundProvesUnrecoverable"), True),
    ],
)
def test_viability_profile_rejects_contract_drift(
    path: tuple[str, str],
    value: object,
) -> None:
    base, manipulation, profile = _profiles()
    profile[path[0]][path[1]] = value

    with pytest.raises(TrainingError, match="diagnostic contract"):
        validate_viability_profile(base, manipulation, profile)


def test_viability_assessment_preserves_formal_manipulation_gates() -> None:
    passing = copy.deepcopy(BASELINE_METRICS)
    passing.update(
        {
            "minimumBaseHeight": 0.9,
            "minimumUprightCosine": 0.95,
            "maximumBaseTranslation": 0.1,
            "maximumBaseLateralDrift": 0.05,
            "maximumTerminalLinearSpeed": 0.1,
            "maximumTerminalAngularSpeed": 0.2,
        }
    )

    assert assess_viability_metrics(passing, QUALITY_GATES)["result"] == "pass"
    assert assess_viability_metrics(BASELINE_METRICS, QUALITY_GATES)["result"] == "fail"


def test_viability_search_uses_constructive_witness_semantics() -> None:
    source = (
        ROOT
        / "python"
        / "worldspec-h1-training"
        / "src"
        / "worldspec_h1_training"
        / "viability.py"
    ).read_text(encoding="utf-8")

    assert "cem_closed_loop_policy_residual_shooting_v1" in source
    assert "candidate_not_witness" in source
    assert '"unknown"' in source
    assert '"constructive_witness"' in source
    assert '"notFoundIsInfeasibilityProof": False' in source
    assert "criticalSnapshotIndex" in source
    assert "baselineReproduced" in source
    assert '_flat_observation_size(env.observation_size["state"])' in source
    assert "non_held_qpos" in source
    assert 'initial_state.info["held_targets"]' in source
