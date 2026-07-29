import copy
import hashlib
import json
from pathlib import Path

import pytest

from worldspec_h1_training.contract import digest_json, validate_profile
from worldspec_h1_training.errors import TrainingError

ROOT = Path(__file__).resolve().parents[3]
PROFILE = ROOT / "examples" / "h1-kitchen" / "locomotion-training-profile.json"
TASK_PROFILE = (
    ROOT / "examples" / "h1-kitchen" / "locomotion-training-profile.task-v1.json"
)


def profile() -> dict:
    return json.loads(PROFILE.read_text(encoding="utf-8"))


def test_reference_profile_contract_is_accepted() -> None:
    validate_profile(profile())


def test_task_training_profile_is_frozen_and_valid() -> None:
    value = json.loads(TASK_PROFILE.read_text(encoding="utf-8"))

    validate_profile(value)

    assert value["training"]["numTimesteps"] == 100_000_000
    assert value["training"]["numEnvs"] == 8192
    assert value["training"]["commandDistribution"]["linearVelocityX"] == [
        0.0,
        0.8,
    ]
    assert value["initialization"]["optimizerState"] == "reset"


def test_task_training_rejects_a_wider_command_range() -> None:
    value = json.loads(TASK_PROFILE.read_text(encoding="utf-8"))
    value["training"]["commandDistribution"]["linearVelocityX"] = [0.0, 1.0]

    with pytest.raises(TrainingError, match="budget and command range"):
        validate_profile(value)


def test_framework_source_binding_is_fail_closed() -> None:
    value = copy.deepcopy(profile())
    value["framework"]["sourceCommit"] = "0" * 40
    with pytest.raises(TrainingError) as captured:
        validate_profile(value)
    assert captured.value.code == "TRAINING_FRAMEWORK_BINDING_MISMATCH"


def test_control_array_cardinality_is_checked() -> None:
    value = copy.deepcopy(profile())
    value["control"]["policyKps"].pop()
    with pytest.raises(TrainingError) as captured:
        validate_profile(value)
    assert captured.value.code == "TRAINING_CONTROL_CARDINALITY_INVALID"


def test_profile_digest_is_canonical() -> None:
    value = profile()
    alternate = json.loads(json.dumps(value, indent=4))
    assert digest_json(value) == digest_json(alternate)
    assert digest_json(value).startswith("sha256:")
    assert len(digest_json(value)) == len("sha256:") + hashlib.sha256().digest_size * 2


def test_mjx_capacity_is_fail_closed() -> None:
    value = copy.deepcopy(profile())
    value["runtime"]["mjxCapacity"]["ccdContactsPerEnvironment"] = 4
    with pytest.raises(TrainingError) as captured:
        validate_profile(value)
    assert captured.value.code == "TRAINING_RUNTIME_PROFILE_INVALID"
