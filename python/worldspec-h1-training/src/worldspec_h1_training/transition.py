"""Pure move-to-zero curriculum phase helpers."""

from __future__ import annotations

from typing import Any


def transition_phase_masks(
    step: Any,
    move_steps: int,
    cycle_steps: int,
) -> tuple[Any, Any, Any]:
    """Return move, settle, and cycle-complete masks for a zero-based phase step."""

    moving = step < move_steps
    settling = (step >= move_steps) & (step < cycle_steps)
    complete = step >= cycle_steps
    return moving, settling, complete
