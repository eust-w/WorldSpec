from __future__ import annotations

from worldspec_h1_training.environment import _preserving_update


def test_environment_update_preserves_brax_wrapper_pytree_keys() -> None:
    wrapped = {
        "rng": "old",
        "command": "old",
        "AutoResetWrapper_rng": "wrapper",
        "episode_metrics": {"reward": 0.0},
        "truncation": 0,
    }

    updated = _preserving_update(
        wrapped,
        {
            "rng": "new",
            "command": "new",
            "last_action": "action",
        },
    )

    assert set(updated) == {
        "rng",
        "command",
        "last_action",
        "AutoResetWrapper_rng",
        "episode_metrics",
        "truncation",
    }
    assert updated["rng"] == "new"
    assert updated["AutoResetWrapper_rng"] == "wrapper"
    assert wrapped["rng"] == "old"
