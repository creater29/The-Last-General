"""
Tests for RelationshipManager (Stage 3 Candidate C).

Covers:
  - RelationshipState.neutral() for unknown opponents
  - encounters distinguishes "never met" from "known neutral"
  - trust update rules (win/loss/draw)
  - trust clamping at +/-1.0
  - encounters increments on every result
  - update creates record if none exists
  - update preserves non-trust fields
  - server isolation (same player_id, different server_ids)
  - events=None is safe (reserved, not yet interpreted)
  - multiple updates accumulate correctly
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from simulator.logger import EpisodeLogger
from brain.relationship_manager import RelationshipManager, RelationshipState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def temp_rm():
    logger = EpisodeLogger(db_path=":memory:")
    logger.migrate_relationship_schema()
    rm = RelationshipManager(logger)
    return logger, rm


SERVER  = "test_server"
PLAYER  = "test_player"
SERVER2 = "other_server"
PLAYER2 = "other_player"


# ---------------------------------------------------------------------------
# RelationshipState.neutral()
# ---------------------------------------------------------------------------

def test_neutral_state_has_zero_trust():
    state = RelationshipState.neutral()
    assert state.trust_level == 0.0

def test_neutral_state_has_zero_encounters():
    state = RelationshipState.neutral()
    assert state.encounters == 0

def test_neutral_state_all_counts_zero():
    state = RelationshipState.neutral()
    assert state.betrayal_count == 0
    assert state.cooperation_count == 0
    assert state.times_attempted_capture == 0
    assert state.known_deceptions == 0

def test_relationship_state_is_immutable():
    state = RelationshipState.neutral()
    with pytest.raises((AttributeError, TypeError)):
        state.trust_level = 0.5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# get_state — unknown opponent
# ---------------------------------------------------------------------------

def test_get_state_unknown_player_returns_neutral():
    _, rm = temp_rm()
    state = rm.get_state(SERVER, "nobody")
    assert state.trust_level == 0.0
    assert state.encounters == 0

def test_get_state_never_returns_none():
    _, rm = temp_rm()
    state = rm.get_state(SERVER, "completely_unknown")
    assert state is not None
    assert isinstance(state, RelationshipState)


# ---------------------------------------------------------------------------
# encounters distinguishes "never met" from "known neutral"
# ---------------------------------------------------------------------------

def test_never_met_has_zero_encounters():
    _, rm = temp_rm()
    state = rm.get_state(SERVER, PLAYER)
    assert state.encounters == 0

def test_known_neutral_has_nonzero_encounters():
    _, rm = temp_rm()
    rm.update_after_battle(SERVER, PLAYER, "draw")
    rm.update_after_battle(SERVER, PLAYER, "draw")
    state = rm.get_state(SERVER, PLAYER)
    assert state.encounters == 2
    assert state.trust_level == 0.0

def test_encounters_increments_on_every_result():
    _, rm = temp_rm()
    rm.update_after_battle(SERVER, PLAYER, "win")
    rm.update_after_battle(SERVER, PLAYER, "loss")
    rm.update_after_battle(SERVER, PLAYER, "draw")
    state = rm.get_state(SERVER, PLAYER)
    assert state.encounters == 3


# ---------------------------------------------------------------------------
# Trust update rules
# ---------------------------------------------------------------------------

def test_loss_decreases_trust():
    _, rm = temp_rm()
    rm.update_after_battle(SERVER, PLAYER, "loss")
    state = rm.get_state(SERVER, PLAYER)
    assert state.trust_level == pytest.approx(-0.05, abs=1e-6)

def test_win_increases_trust():
    _, rm = temp_rm()
    rm.update_after_battle(SERVER, PLAYER, "win")
    state = rm.get_state(SERVER, PLAYER)
    assert state.trust_level == pytest.approx(0.02, abs=1e-6)

def test_draw_does_not_change_trust():
    _, rm = temp_rm()
    rm.update_after_battle(SERVER, PLAYER, "draw")
    state = rm.get_state(SERVER, PLAYER)
    assert state.trust_level == pytest.approx(0.0, abs=1e-6)

def test_multiple_losses_accumulate():
    _, rm = temp_rm()
    for _ in range(4):
        rm.update_after_battle(SERVER, PLAYER, "loss")
    state = rm.get_state(SERVER, PLAYER)
    assert state.trust_level == pytest.approx(-0.20, abs=1e-5)

def test_mixed_results_accumulate():
    _, rm = temp_rm()
    rm.update_after_battle(SERVER, PLAYER, "win")
    rm.update_after_battle(SERVER, PLAYER, "loss")
    state = rm.get_state(SERVER, PLAYER)
    assert state.trust_level == pytest.approx(-0.03, abs=1e-6)


# ---------------------------------------------------------------------------
# Trust clamping
# ---------------------------------------------------------------------------

def test_trust_clamped_at_negative_one():
    _, rm = temp_rm()
    for _ in range(30):
        rm.update_after_battle(SERVER, PLAYER, "loss")
    state = rm.get_state(SERVER, PLAYER)
    assert state.trust_level >= -1.0

def test_trust_clamped_at_positive_one():
    _, rm = temp_rm()
    for _ in range(60):
        rm.update_after_battle(SERVER, PLAYER, "win")
    state = rm.get_state(SERVER, PLAYER)
    assert state.trust_level <= 1.0


# ---------------------------------------------------------------------------
# Record creation and field preservation
# ---------------------------------------------------------------------------

def test_update_creates_record_if_none_exists():
    _, rm = temp_rm()
    rm.update_after_battle(SERVER, PLAYER, "loss")
    state = rm.get_state(SERVER, PLAYER)
    assert state.encounters == 1
    assert state.trust_level == pytest.approx(-0.05, abs=1e-6)

def test_update_preserves_non_trust_fields():
    logger, rm = temp_rm()
    logger.upsert_relationship(SERVER, PLAYER, {
        "trust_level": 0.0,
        "betrayal_count": 3,
        "cooperation_count": 5,
        "times_attempted_capture": 1,
        "known_deceptions": 2,
        "encounters": 10,
        "notable_events": [],
    })
    rm.update_after_battle(SERVER, PLAYER, "win")
    state = rm.get_state(SERVER, PLAYER)
    assert state.trust_level == pytest.approx(0.02, abs=1e-6)
    assert state.encounters == 11
    assert state.betrayal_count == 3
    assert state.cooperation_count == 5
    assert state.times_attempted_capture == 1
    assert state.known_deceptions == 2


# ---------------------------------------------------------------------------
# Server isolation
# ---------------------------------------------------------------------------

def test_server_isolation_get_state():
    _, rm = temp_rm()
    rm.update_after_battle(SERVER,  PLAYER, "win")
    rm.update_after_battle(SERVER2, PLAYER, "loss")
    state_a = rm.get_state(SERVER,  PLAYER)
    state_b = rm.get_state(SERVER2, PLAYER)
    assert state_a.trust_level == pytest.approx(0.02,  abs=1e-6)
    assert state_b.trust_level == pytest.approx(-0.05, abs=1e-6)

def test_server_isolation_encounters_independent():
    _, rm = temp_rm()
    for _ in range(3):
        rm.update_after_battle(SERVER, PLAYER, "draw")
    rm.update_after_battle(SERVER2, PLAYER, "draw")
    assert rm.get_state(SERVER,  PLAYER).encounters == 3
    assert rm.get_state(SERVER2, PLAYER).encounters == 1


# ---------------------------------------------------------------------------
# events parameter
# ---------------------------------------------------------------------------

def test_events_none_is_safe():
    _, rm = temp_rm()
    rm.update_after_battle(SERVER, PLAYER, "loss", events=None)
    state = rm.get_state(SERVER, PLAYER)
    assert state.encounters == 1

def test_events_list_is_safe_and_ignored():
    _, rm = temp_rm()
    rm.update_after_battle(SERVER, PLAYER, "win", events=["cooperation"])
    state = rm.get_state(SERVER, PLAYER)
    assert state.trust_level == pytest.approx(0.02, abs=1e-6)
    assert state.encounters == 1



# ---------------------------------------------------------------------------
# Input validation (result parameter)
# ---------------------------------------------------------------------------

def test_invalid_result_raises_value_error():
    _, rm = temp_rm()
    with pytest.raises(ValueError):
        rm.update_after_battle(SERVER, PLAYER, "victory")

def test_invalid_result_wrong_case_raises_value_error():
    """A case-typo like 'Win' must not silently fall through as a no-op draw."""
    _, rm = temp_rm()
    with pytest.raises(ValueError):
        rm.update_after_battle(SERVER, PLAYER, "Win")

def test_invalid_result_does_not_mutate_state():
    """A rejected call must not create a record or change encounters."""
    _, rm = temp_rm()
    with pytest.raises(ValueError):
        rm.update_after_battle(SERVER, PLAYER, "victory")
    state = rm.get_state(SERVER, PLAYER)
    assert state.encounters == 0

def test_all_three_valid_results_accepted():
    _, rm = temp_rm()
    rm.update_after_battle(SERVER, PLAYER, "win")
    rm.update_after_battle(SERVER, PLAYER, "loss")
    rm.update_after_battle(SERVER, PLAYER, "draw")
    state = rm.get_state(SERVER, PLAYER)
    assert state.encounters == 3
