from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from worldspec_h1_training.contract import digest_json
from worldspec_h1_training.errors import TrainingError
from worldspec_h1_training.full_task import (
    A5CK_CONTROL_LINEAGE,
    A6_SUPERVISOR_EVIDENCE,
    FULL_TASK_HANDOFF_EVIDENCE,
    FULL_TASK_LOCOMOTION_HANDOFF,
    FULL_TASK_PHASE_CONTROLLER,
    FULL_TASK_SINGLE_GATES,
    make_full_task_single_evaluation_profile,
    validate_full_task_single_profile,
)
from worldspec_h1_training.kitchen_task import ERGONOMIC_TASK_SCENE, TASK_CAPACITY
from worldspec_h1_training.whole_body import (
    DYNAMIC_ARM_TRACKING,
    FORWARD_ONLY_BASE_ANCHOR_RECOVERY,
    TASK_GEOMETRY_CALIBRATION,
    TASK_POLICY_HANDOFF,
    WHOLE_BODY_CONTROLLER,
)

ROOT = Path(__file__).resolve().parents[3]
BASE_PATH = ROOT / "examples" / "h1-kitchen" / "locomotion-training-profile.json"
SUPERVISOR_PATH = (
    ROOT / "examples" / "h1-kitchen" / "locomotion-task-load-supervisor-profile.json"
)
LOCKED_PROFILE_PATH = (
    ROOT / "examples" / "h1-kitchen" / "task-load-full-kitchen-single-profile.json"
)


def _profiles() -> tuple[dict, dict, dict]:
    base = json.loads(BASE_PATH.read_text(encoding="utf-8"))
    supervisor = json.loads(SUPERVISOR_PATH.read_text(encoding="utf-8"))
    image_digest = "sha256:" + ("a" * 64)
    profile = {
        "id": "taskprofile://worldspec/h1-kitchen/task-load-full-loop-single-v1",
        "profileVersion": "0.1.0",
        "status": "research",
        "stage": "task_load_fixed_kitchen_single_probe",
        "seed": 41,
        "baseTrainingProfileDigest": digest_json(base),
        "supervisorProfileDigest": digest_json(supervisor),
        "supervisorEvidence": copy.deepcopy(A6_SUPERVISOR_EVIDENCE),
        "motionPolicy": copy.deepcopy(supervisor["motionPolicy"]),
        "capturePolicy": copy.deepcopy(supervisor["capturePolicy"]),
        "standPolicy": copy.deepcopy(supervisor["standPolicy"]),
        "controlLineage": copy.deepcopy(A5CK_CONTROL_LINEAGE),
        "scene": copy.deepcopy(ERGONOMIC_TASK_SCENE),
        "wholeBodyController": copy.deepcopy(WHOLE_BODY_CONTROLLER),
        "taskPolicyHandoff": copy.deepcopy(TASK_POLICY_HANDOFF),
        "dynamicArmTracking": copy.deepcopy(DYNAMIC_ARM_TRACKING),
        "taskGeometryCalibration": copy.deepcopy(TASK_GEOMETRY_CALIBRATION),
        "baseAnchorRecovery": copy.deepcopy(FORWARD_ONLY_BASE_ANCHOR_RECOVERY),
        "taskSceneLocomotionHandoff": copy.deepcopy(FULL_TASK_LOCOMOTION_HANDOFF),
        "taskSceneHandoffEvidence": copy.deepcopy(FULL_TASK_HANDOFF_EVIDENCE),
        "phaseController": copy.deepcopy(FULL_TASK_PHASE_CONTROLLER),
        "qualityGates": copy.deepcopy(FULL_TASK_SINGLE_GATES),
        "runtime": {
            "containerImage": f"registry.invalid/worldspec@{image_digest}",
            "containerDigest": image_digest,
            "imageSourceRevision": "1" * 40,
            "packageLockDigest": base["runtime"]["packageLockDigest"],
            "ccdIterations": 50,
            "evaluationEnvironments": 1,
            "mjxCapacity": copy.deepcopy(TASK_CAPACITY),
        },
        "artifactPolicy": {
            "controller": "research_only",
            "distribution": "internal_only",
            "fiveRunClaim": "forbidden",
            "l3Claim": "forbidden",
        },
    }
    return base, supervisor, profile


def test_full_task_single_profile_binds_a6_and_a5ck_without_claiming_five_runs() -> None:
    base, supervisor, profile = _profiles()

    validate_full_task_single_profile(base, supervisor, profile)

    assert profile["supervisorProfileDigest"] == digest_json(supervisor)
    assert profile["supervisorEvidence"]["formalTaskLoadSupervisorGate"] == "passed"
    assert profile["controlLineage"]["reuseBoundary"] == "controller_contract_only"
    assert profile["qualityGates"]["probeRuns"] == 1
    assert profile["artifactPolicy"]["fiveRunClaim"] == "forbidden"
    assert profile["artifactPolicy"]["l3Claim"] == "forbidden"


def test_locked_full_task_single_profile_is_semantically_valid() -> None:
    base = json.loads(BASE_PATH.read_text(encoding="utf-8"))
    supervisor = json.loads(SUPERVISOR_PATH.read_text(encoding="utf-8"))
    profile = json.loads(LOCKED_PROFILE_PATH.read_text(encoding="utf-8"))

    validate_full_task_single_profile(base, supervisor, profile)

    assert profile["runtime"]["imageSourceRevision"] == "f37eacc4bd8a9834caaf1094cd8567ca34bd73ca"
    assert profile["qualityGates"]["probeRuns"] == 1


def test_full_task_trace_contract_keeps_policy_command_and_base_state() -> None:
    source = (
        ROOT
        / "python"
        / "worldspec-h1-training"
        / "src"
        / "worldspec_h1_training"
        / "full_task.py"
    ).read_text(encoding="utf-8")

    assert '"command": [_trace_number(value) for value in np.asarray(policy_command)]' in source
    assert '"policyCommand": [_trace_number(value) for value in np.asarray(policy_command)]' in source
    assert '"baseState": {' in source


def test_full_task_single_effective_profile_preserves_task_load() -> None:
    base, supervisor, profile = _profiles()

    effective = make_full_task_single_evaluation_profile(base, supervisor, profile)

    assert effective["training"]["seed"] == 41
    assert effective["training"]["numEnvs"] == 1
    assert (
        effective["trainingEnvironment"]["taskLoadCurriculum"]
        == supervisor["evaluationEnvironment"]["taskLoadCurriculum"]
    )
    assert effective["runtime"]["mjxCapacity"] == TASK_CAPACITY


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda profile: profile["supervisorEvidence"].update(
                {"formalTaskLoadSupervisorGate": "failed"}
            ),
            "passing A6-S evidence",
        ),
        (
            lambda profile: profile["controlLineage"].update(
                {"reuseBoundary": "unrestricted"}
            ),
            "controlLineage contract changed",
        ),
        (
            lambda profile: profile["qualityGates"].update({"probeRuns": 5}),
            "qualityGates contract changed",
        ),
        (
            lambda profile: profile["taskSceneLocomotionHandoff"]["captureGate"].update(
                {"maximumSteps": 51}
            ),
            "taskSceneLocomotionHandoff contract changed",
        ),
        (
            lambda profile: profile["artifactPolicy"].update(
                {"fiveRunClaim": "allowed"}
            ),
            "cannot claim 5/5",
        ),
    ],
)
def test_full_task_single_rejects_gate_or_lineage_drift(mutation, message: str) -> None:
    base, supervisor, profile = _profiles()
    mutation(profile)

    with pytest.raises(TrainingError, match=message):
        validate_full_task_single_profile(base, supervisor, profile)


def test_full_task_single_rejects_historical_unloaded_supervisor() -> None:
    base, _, profile = _profiles()
    historical = json.loads(
        (
            ROOT / "examples" / "h1-kitchen" / "locomotion-supervisor-profile.json"
        ).read_text(encoding="utf-8")
    )
    profile["supervisorProfileDigest"] = digest_json(historical)
    profile["motionPolicy"] = copy.deepcopy(historical["motionPolicy"])

    with pytest.raises(TrainingError, match="passing A6-S supervisor"):
        validate_full_task_single_profile(base, historical, profile)
