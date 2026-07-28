from __future__ import annotations

import json
from pathlib import Path

from worldspec_h1_training.contract import digest_json
from worldspec_h1_training.smoke import SMOKE_OVERRIDES, make_smoke_profile

ROOT = Path(__file__).resolve().parents[3]
PROFILE = ROOT / "examples" / "h1-kitchen" / "locomotion-training-profile.json"


def test_smoke_profile_is_bounded_and_does_not_mutate_canonical_profile() -> None:
    canonical = json.loads(PROFILE.read_text(encoding="utf-8"))
    original_digest = digest_json(canonical)

    smoke = make_smoke_profile(canonical)

    assert digest_json(canonical) == original_digest
    assert smoke["training"]["hyperparameterStatus"] == "research_smoke_override"
    assert {
        key: smoke["training"][key]
        for key in SMOKE_OVERRIDES
    } == SMOKE_OVERRIDES
    assert smoke["training"]["numTimesteps"] < canonical["training"]["numTimesteps"]
    assert smoke["training"]["numEnvs"] < canonical["training"]["numEnvs"]


def test_smoke_contract_cannot_be_confused_with_publishable_training() -> None:
    assert SMOKE_OVERRIDES["numTimesteps"] == 32768
    assert SMOKE_OVERRIDES["numEnvs"] == 256
    assert SMOKE_OVERRIDES["numEvals"] == 2


def test_smoke_uses_explicit_per_environment_mjx_capacity() -> None:
    canonical = json.loads(PROFILE.read_text(encoding="utf-8"))
    smoke = make_smoke_profile(canonical)

    assert smoke["runtime"]["mjxCapacity"] == {
        "activeContactsPerEnvironment": 16,
        "ccdContactsPerEnvironment": 8,
        "njmax": 128,
    }
