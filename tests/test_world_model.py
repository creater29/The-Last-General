"""
test_world_model.py — Verify the General's terrain belief system.

All tests use isolated temp databases — never the production DB.
Observations are seeded directly via SQL to keep tests fast and
independent of the battle simulator.

Key invariants under test:
  - world_model.py imports ONLY from simulator.logger (Rule 3)
  - No coordinates in any belief output
  - Confidence formula: episode_count / (episode_count + 1)
  - observed_outcomes is a list of distinct effect types
  - Beliefs are None before update_from_observations is called
  - update_from_observations is idempotent (calling twice = same result)
"""

import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List

sys.path.insert(0, "/Users/Arman/Projects/general_brain/src")

from simulator.logger import EpisodeLogger
from brain.world_model import WorldModel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def temp_logger() -> EpisodeLogger:
    """Isolated temp DB — one per test."""
    tmp = tempfile.mktemp(suffix=".db")
    return EpisodeLogger(db_path=Path(tmp))


def seed_observations(
    logger: EpisodeLogger,
    terrain_context: str,
    observed_effect: str,
    count: int,
    episode_id: str = "test_ep_001",
) -> None:
    """
    Insert `count` observations for the given terrain_context + effect pair.
    Creates a dummy parent episode if it does not already exist.
    Uses deterministic obs IDs so INSERT OR IGNORE prevents duplicates
    when the same (context, effect) pair is seeded across multiple calls
    that share the same episode_id.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    conn = logger._get_conn()

    # Ensure parent episode row exists (FK constraint is ON).
    conn.execute(
        """
        INSERT OR IGNORE INTO episodes
            (id, timestamp, player_id, age, result, turns_played, data)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (episode_id, timestamp, "test_player", 1, "win", 10, "{}"),
    )

    # Use full strings (no truncation) to avoid id collisions between
    # contexts that share a common prefix (e.g. "river+weather" vs "river+cavalry").
    tag = f"{terrain_context}_{observed_effect}".replace("+", "_").replace(" ", "_")
    for i in range(count):
        obs_id = f"{tag}_{i:05d}"
        conn.execute(
            """
            INSERT OR IGNORE INTO observations
                (id, episode_id, timestamp, terrain_context,
                 action_taken, observed_effect, confidence, last_verified, decay_rate)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                obs_id,
                episode_id,
                timestamp,
                terrain_context,
                "charge",
                observed_effect,
                1.0,
                timestamp,
                0.01,
            ),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Rule 3: import constraint
# ---------------------------------------------------------------------------

def test_no_simulator_imports_in_world_model():
    """
    world_model.py must import ONLY from simulator.logger.
    Importing grid, units, physics, or battle would let simulator internals
    (coordinates, physics constants) leak into the brain layer.
    """
    src = Path("/Users/Arman/Projects/general_brain/src/brain/world_model.py").read_text()
    forbidden = [
        "from simulator.grid",
        "from simulator.units",
        "from simulator.physics",
        "from simulator.battle",
        "import simulator.grid",
        "import simulator.units",
        "import simulator.physics",
        "import simulator.battle",
    ]
    for token in forbidden:
        assert token not in src, (
            f"world_model.py must not import '{token}' — "
            f"only simulator.logger is permitted"
        )


# ---------------------------------------------------------------------------
# Basic construction
# ---------------------------------------------------------------------------

def test_world_model_constructs():
    logger = temp_logger()
    wm = WorldModel(logger)
    assert wm is not None
    logger.close()


def test_get_all_beliefs_empty_before_update():
    logger = temp_logger()
    wm = WorldModel(logger)
    assert wm.get_all_beliefs() == []
    logger.close()


def test_get_terrain_belief_none_before_update():
    logger = temp_logger()
    wm = WorldModel(logger)
    assert wm.get_terrain_belief("river", "weather") is None
    logger.close()


def test_get_high_confidence_beliefs_empty_before_update():
    logger = temp_logger()
    wm = WorldModel(logger)
    assert wm.get_high_confidence_beliefs() == []
    logger.close()


# ---------------------------------------------------------------------------
# update_from_observations
# ---------------------------------------------------------------------------

def test_update_returns_zero_on_empty_db():
    logger = temp_logger()
    wm = WorldModel(logger)
    result = wm.update_from_observations()
    assert result == 0
    logger.close()


def test_update_returns_count_of_beliefs_upserted():
    """Each distinct terrain_context that qualifies produces one belief row."""
    logger = temp_logger()
    seed_observations(logger, "river+weather", "flood", 10, "ep_a")
    seed_observations(logger, "frozen_lake+cavalry", "ice_break", 5, "ep_b")
    wm = WorldModel(logger)
    count = wm.update_from_observations(min_count=3)
    assert count == 2
    logger.close()


def test_update_populates_terrain_knowledge_table():
    logger = temp_logger()
    seed_observations(logger, "river+weather", "flood", 10)
    wm = WorldModel(logger)
    wm.update_from_observations(min_count=3)
    beliefs = wm.get_all_beliefs()
    assert len(beliefs) == 1
    logger.close()


def test_min_count_filter_excludes_sparse_observations():
    """Pairs below min_count must not become beliefs."""
    logger = temp_logger()
    seed_observations(logger, "river+weather", "flood", 10, "ep_a")
    seed_observations(logger, "swamp+infantry", "slow", 2, "ep_b")  # below 3
    wm = WorldModel(logger)
    wm.update_from_observations(min_count=3)
    beliefs = wm.get_all_beliefs()
    terrain_types = [b["terrain_type"] for b in beliefs]
    assert "river" in terrain_types
    assert "swamp" not in terrain_types
    logger.close()


def test_update_is_idempotent():
    """
    Calling update_from_observations twice must not double counts or
    create duplicate rows. The second call should produce the same state.
    """
    logger = temp_logger()
    seed_observations(logger, "river+weather", "flood", 10)
    wm = WorldModel(logger)
    wm.update_from_observations(min_count=3)
    first = wm.get_terrain_belief("river", "weather")

    wm.update_from_observations(min_count=3)
    second = wm.get_terrain_belief("river", "weather")

    assert first["episode_count"] == second["episode_count"]
    assert first["confidence"] == second["confidence"]
    assert first["observed_outcomes"] == second["observed_outcomes"]
    logger.close()


# ---------------------------------------------------------------------------
# Belief structure
# ---------------------------------------------------------------------------

def test_belief_has_required_keys():
    logger = temp_logger()
    seed_observations(logger, "river+weather", "flood", 10)
    wm = WorldModel(logger)
    wm.update_from_observations(min_count=3)
    belief = wm.get_terrain_belief("river", "weather")
    assert belief is not None
    required = {"terrain_type", "action_type", "observed_outcomes", "confidence", "episode_count"}
    assert required.issubset(belief.keys())
    logger.close()


def test_terrain_type_and_action_type_split_correctly():
    """terrain_context "river+weather" → terrain_type="river", action_type="weather"."""
    logger = temp_logger()
    seed_observations(logger, "frozen_lake+cavalry", "ice_break", 6)
    wm = WorldModel(logger)
    wm.update_from_observations(min_count=3)
    belief = wm.get_terrain_belief("frozen_lake", "cavalry")
    assert belief is not None
    assert belief["terrain_type"] == "frozen_lake"
    assert belief["action_type"] == "cavalry"
    logger.close()


def test_observed_outcomes_is_list():
    logger = temp_logger()
    seed_observations(logger, "river+weather", "flood", 10)
    wm = WorldModel(logger)
    wm.update_from_observations(min_count=3)
    belief = wm.get_terrain_belief("river", "weather")
    assert isinstance(belief["observed_outcomes"], list)
    logger.close()


def test_observed_outcomes_contains_effect_type():
    logger = temp_logger()
    seed_observations(logger, "river+weather", "flood", 10)
    wm = WorldModel(logger)
    wm.update_from_observations(min_count=3)
    belief = wm.get_terrain_belief("river", "weather")
    assert "flood" in belief["observed_outcomes"]
    logger.close()


def test_observed_outcomes_distinct_no_duplicates():
    """The same effect type must appear only once in observed_outcomes."""
    logger = temp_logger()
    seed_observations(logger, "river+weather", "flood", 20)
    wm = WorldModel(logger)
    wm.update_from_observations(min_count=3)
    belief = wm.get_terrain_belief("river", "weather")
    outcomes = belief["observed_outcomes"]
    assert len(outcomes) == len(set(outcomes))
    logger.close()


def test_multiple_effects_for_same_terrain_action():
    """
    One terrain+action pair can produce multiple distinct effects.
    Both must appear in observed_outcomes.
    """
    logger = temp_logger()
    seed_observations(logger, "river+weather", "flood", 10, "ep_a")
    seed_observations(logger, "river+weather", "unknown", 5, "ep_b")
    wm = WorldModel(logger)
    wm.update_from_observations(min_count=3)
    belief = wm.get_terrain_belief("river", "weather")
    assert belief is not None
    outcomes = set(belief["observed_outcomes"])
    assert "flood" in outcomes
    assert "unknown" in outcomes
    logger.close()


def test_episode_count_sums_across_effects():
    """
    episode_count for a terrain+action pair is the total count across
    all qualifying effects for that pair, not just one effect.
    """
    logger = temp_logger()
    seed_observations(logger, "river+weather", "flood", 10, "ep_a")
    seed_observations(logger, "river+weather", "unknown", 5, "ep_b")
    wm = WorldModel(logger)
    wm.update_from_observations(min_count=3)
    belief = wm.get_terrain_belief("river", "weather")
    assert belief["episode_count"] == 15
    logger.close()


# ---------------------------------------------------------------------------
# Confidence formula
# ---------------------------------------------------------------------------

def test_confidence_formula_exact():
    """confidence = episode_count / (episode_count + 1)"""
    logger = temp_logger()
    n = 10
    seed_observations(logger, "river+weather", "flood", n)
    wm = WorldModel(logger)
    wm.update_from_observations(min_count=3)
    belief = wm.get_terrain_belief("river", "weather")
    expected = n / (n + 1)
    assert abs(belief["confidence"] - expected) < 1e-9
    logger.close()


def test_confidence_formula_small_count():
    """Six ice_break observations → confidence ≈ 0.857."""
    logger = temp_logger()
    seed_observations(logger, "frozen_lake+cavalry", "ice_break", 6)
    wm = WorldModel(logger)
    wm.update_from_observations(min_count=3)
    belief = wm.get_terrain_belief("frozen_lake", "cavalry")
    expected = 6 / 7
    assert abs(belief["confidence"] - expected) < 1e-9
    logger.close()


def test_all_confidences_in_valid_range():
    """Confidence must always be in [0.0, 1.0]."""
    logger = temp_logger()
    seed_observations(logger, "river+weather", "flood", 1000, "ep_a")
    seed_observations(logger, "frozen_lake+cavalry", "ice_break", 3, "ep_b")
    wm = WorldModel(logger)
    wm.update_from_observations(min_count=3)
    for belief in wm.get_all_beliefs():
        assert 0.0 <= belief["confidence"] <= 1.0, (
            f"Confidence out of range for {belief['terrain_type']}+"
            f"{belief['action_type']}: {belief['confidence']}"
        )
    logger.close()


# ---------------------------------------------------------------------------
# get_high_confidence_beliefs
# ---------------------------------------------------------------------------

def test_high_confidence_beliefs_threshold_filter():
    """Only beliefs at or above threshold should be returned."""
    logger = temp_logger()
    # High confidence: 100 observations → 100/101 ≈ 0.990
    seed_observations(logger, "river+weather", "flood", 100, "ep_a")
    # Low confidence: 3 observations → 3/4 = 0.75 — still above 0.6
    seed_observations(logger, "frozen_lake+cavalry", "ice_break", 3, "ep_b")
    wm = WorldModel(logger)
    wm.update_from_observations(min_count=3)

    high = wm.get_high_confidence_beliefs(threshold=0.9)
    terrain_types = [b["terrain_type"] for b in high]
    assert "river" in terrain_types
    assert "frozen_lake" not in terrain_types
    logger.close()


def test_high_confidence_includes_ice_break_at_six_observations():
    """
    Six ice_break observations → confidence 6/7 ≈ 0.857.
    This must pass the default threshold of 0.6.
    """
    logger = temp_logger()
    seed_observations(logger, "frozen_lake+cavalry", "ice_break", 6)
    wm = WorldModel(logger)
    wm.update_from_observations(min_count=3)
    high = wm.get_high_confidence_beliefs(threshold=0.6)
    assert len(high) == 1
    assert high[0]["terrain_type"] == "frozen_lake"
    logger.close()


def test_high_confidence_empty_when_none_qualify():
    logger = temp_logger()
    # Only 3 observations → 3/4 = 0.75, below a 0.9 threshold
    seed_observations(logger, "frozen_lake+cavalry", "ice_break", 3)
    wm = WorldModel(logger)
    wm.update_from_observations(min_count=3)
    high = wm.get_high_confidence_beliefs(threshold=0.9)
    assert high == []
    logger.close()


# ---------------------------------------------------------------------------
# get_all_beliefs ordering
# ---------------------------------------------------------------------------

def test_get_all_beliefs_ordered_by_confidence_descending():
    logger = temp_logger()
    seed_observations(logger, "river+weather", "flood", 100, "ep_a")
    seed_observations(logger, "frozen_lake+cavalry", "ice_break", 6, "ep_b")
    wm = WorldModel(logger)
    wm.update_from_observations(min_count=3)
    beliefs = wm.get_all_beliefs()
    confidences = [b["confidence"] for b in beliefs]
    assert confidences == sorted(confidences, reverse=True)
    logger.close()


# ---------------------------------------------------------------------------
# belief_summary
# ---------------------------------------------------------------------------

def test_belief_summary_structure():
    logger = temp_logger()
    seed_observations(logger, "river+weather", "flood", 10, "ep_a")
    seed_observations(logger, "frozen_lake+cavalry", "ice_break", 6, "ep_b")
    wm = WorldModel(logger)
    wm.update_from_observations(min_count=3)
    summary = wm.belief_summary()

    required_keys = {
        "total_beliefs",
        "high_confidence_beliefs",
        "terrain_types",
        "action_types",
        "by_terrain",
    }
    assert required_keys.issubset(summary.keys())
    logger.close()


def test_belief_summary_total_count():
    logger = temp_logger()
    seed_observations(logger, "river+weather", "flood", 10, "ep_a")
    seed_observations(logger, "frozen_lake+cavalry", "ice_break", 6, "ep_b")
    wm = WorldModel(logger)
    wm.update_from_observations(min_count=3)
    summary = wm.belief_summary()
    assert summary["total_beliefs"] == 2
    logger.close()


def test_belief_summary_terrain_types_list():
    logger = temp_logger()
    seed_observations(logger, "river+weather", "flood", 10, "ep_a")
    seed_observations(logger, "frozen_lake+cavalry", "ice_break", 6, "ep_b")
    wm = WorldModel(logger)
    wm.update_from_observations(min_count=3)
    summary = wm.belief_summary()
    assert isinstance(summary["terrain_types"], list)
    assert "river" in summary["terrain_types"]
    assert "frozen_lake" in summary["terrain_types"]
    logger.close()


def test_belief_summary_by_terrain():
    logger = temp_logger()
    seed_observations(logger, "river+weather", "flood", 10, "ep_a")
    seed_observations(logger, "river+cavalry", "flood", 8, "ep_b")
    seed_observations(logger, "frozen_lake+cavalry", "ice_break", 6, "ep_c")
    wm = WorldModel(logger)
    wm.update_from_observations(min_count=3)
    summary = wm.belief_summary()
    # river has two action types (weather, cavalry) → 2 beliefs
    assert summary["by_terrain"]["river"] == 2
    assert summary["by_terrain"]["frozen_lake"] == 1
    logger.close()


def test_belief_summary_empty_db():
    logger = temp_logger()
    wm = WorldModel(logger)
    summary = wm.belief_summary()
    assert summary["total_beliefs"] == 0
    assert summary["high_confidence_beliefs"] == 0
    assert summary["terrain_types"] == []
    assert summary["action_types"] == []
    assert summary["by_terrain"] == {}
    logger.close()


# ---------------------------------------------------------------------------
# No coordinates invariant
# ---------------------------------------------------------------------------

def test_no_coordinates_in_any_belief():
    """
    Beliefs must never contain coordinate-like keys.
    The General reasons about terrain types, not map positions.
    """
    logger = temp_logger()
    seed_observations(logger, "river+weather", "flood", 10, "ep_a")
    seed_observations(logger, "frozen_lake+cavalry", "ice_break", 6, "ep_b")
    wm = WorldModel(logger)
    wm.update_from_observations(min_count=3)

    coord_keys = {"x", "y", "zone", "position", "coordinate", "location", "col", "row"}
    for belief in wm.get_all_beliefs():
        for key in belief.keys():
            assert key.lower() not in coord_keys, (
                f"Coordinate-like key '{key}' found in belief — "
                f"the brain must not expose location data"
            )
    logger.close()
