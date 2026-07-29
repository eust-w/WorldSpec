from __future__ import annotations

from worldspec_h1_training.transition import transition_phase_masks


def test_transition_phase_boundaries_match_three_second_move_one_second_settle() -> None:
    assert transition_phase_masks(0, 150, 200) == (True, False, False)
    assert transition_phase_masks(149, 150, 200) == (True, False, False)
    assert transition_phase_masks(150, 150, 200) == (False, True, False)
    assert transition_phase_masks(199, 150, 200) == (False, True, False)
    assert transition_phase_masks(200, 150, 200) == (False, False, True)
