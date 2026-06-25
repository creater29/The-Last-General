"""
test_doctrine_extractor.py — Verify doctrine promotion from terrain beliefs.

All tests use isolated temp databases.
Observations are seeded directly, beliefs built via WorldModel,
then doctrine extraction is verified.

Key invariants:
  - doctrine_extractor.py imports only from simulator.logger and brain.world_model
  - Doctrines are anonymous: no player_id in any doctrine row
  - One doctrine per (terrain_type, action_type, effect) triple
  - Doctrine ids are deterministic: "doctrine_{terrain}_{action}_{effect}"
  - derived_principle uses template strings, never raw physics values
  - Confidence and episode_count thresholds are both enforced
  - extract_doctrines is idempotent
"""

import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

import pytest
from simulator.logger import EpisodeLogger
from brain.world_model import WorldModel
from brain.doctrine_extractor import DoctrineExtractor, PRINCIPLE_TEMPLATES, _derive_principle


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def temp_logger() -> EpisodeLogger:
    tmp = tempfile.mktemp(suffix=".db")
    return EpisodeLogger(db_path=Path(tmp))


def seed_observations(
    logger: EpisodeLogger,
    terrain_context: str,
    observed_effect: str,
    count: int,
    episode_id: str = "test_ep_001",
) -> None:
    """Insert test observations — full strings in tag to avoid id collisions."""
    timestamp = datetime.now(timezone.utc).isoformat()
    conn = logger._get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO episodes "
        "(id, timestamp, player_id, age, result, turns_played, data) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (episode_id, timestamp, "test_player", 1, "win", 10, "{}"),
    )
    tag = f"{terrain_context}_{observed_effect}".replace("+", "_").replace(" ", "_")
    for i in range(count):
        obs_id = f"{tag}_{i:05d}"
        conn.execute(
            "INSERT OR IGNORE INTO observations "
            "(id, episode_id, timestamp, terrain_context, action_taken, "
            "observed_effect, confidence, last_verified, decay_rate) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (obs_id, episode_id, timestamp, terrain_context, "charge",
             observed_effect, 1.0, timestamp, 0.01),
        )
    conn.commit()


def build_extractor(logger: EpisodeLogger) -> DoctrineExtractor:
    """Build a WorldModel + DoctrineExtractor pair against the same logger."""
    wm = WorldModel(logger)
    wm.update_from_observations()
    return DoctrineExtractor(logger, wm)


# ---------------------------------------------------------------------------
# Rule 3: import constraint
# ---------------------------------------------------------------------------

def test_no_simulator_internals_imported_in_doctrine_extractor():
    """
    doctrine_extractor.py may only import from simulator.logger
    and brain.world_model. No grid, units, physics, or battle.
    """
    src = (_PROJECT_ROOT / "src" / "brain" / "doctrine_extractor.py").read_text()
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
            f"doctrine_extractor.py must not import '{token}'"
        )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

def test_doctrine_extractor_constructs():
    logger = temp_logger()
    wm = WorldModel(logger)
    de = DoctrineExtractor(logger, wm)
    assert de is not None
    logger.close()


def test_get_doctrines_empty_before_extraction():
    logger = temp_logger()
    de = build_extractor(logger)
    assert de.get_doctrines() == []
    logger.close()


# ---------------------------------------------------------------------------
# extract_doctrines return value
# ---------------------------------------------------------------------------

def test_extract_returns_zero_with_no_beliefs():
    logger = temp_logger()
    de = build_extractor(logger)
    assert de.extract_doctrines() == 0
    logger.close()


def test_extract_returns_count_of_doctrines_upserted():
    logger = temp_logger()
    seed_observations(logger, "river+weather",      "flood",    100, "ep_a")
    seed_observations(logger, "frozen_lake+cavalry", "ice_break", 10, "ep_b")
    de = build_extractor(logger)
    count = de.extract_doctrines(min_confidence=0.6, min_episode_count=5)
    assert count == 2
    logger.close()


def test_extract_populates_doctrines_table():
    logger = temp_logger()
    seed_observations(logger, "river+weather", "flood", 50)
    de = build_extractor(logger)
    de.extract_doctrines()
    assert len(de.get_doctrines()) == 1
    logger.close()


# ---------------------------------------------------------------------------
# Doctrine structure
# ---------------------------------------------------------------------------

def test_doctrine_has_required_keys():
    logger = temp_logger()
    seed_observations(logger, "river+weather", "flood", 50)
    de = build_extractor(logger)
    de.extract_doctrines()
    doc = de.get_doctrines()[0]
    required = {
        "id", "abstraction_level", "condition", "learned_effect",
        "confidence", "episode_count", "failure_count",
        "derived_principle", "exceptions", "last_verified", "decay_rate",
    }
    assert required.issubset(doc.keys())
    logger.close()


def test_doctrine_id_is_deterministic():
    """id must follow the format 'doctrine_{terrain}_{action}_{effect}'."""
    logger = temp_logger()
    seed_observations(logger, "river+weather", "flood", 50)
    de = build_extractor(logger)
    de.extract_doctrines()
    doc = de.get_doctrines()[0]
    assert doc["id"] == "doctrine_river_weather_flood"
    logger.close()


def test_doctrine_condition_format():
    """condition must be 'terrain_type+action_type'."""
    logger = temp_logger()
    seed_observations(logger, "frozen_lake+cavalry", "ice_break", 10)
    de = build_extractor(logger)
    de.extract_doctrines()
    doc = de.get_doctrines()[0]
    assert doc["condition"] == "frozen_lake+cavalry"
    logger.close()


def test_doctrine_abstraction_level_is_terrain():
    logger = temp_logger()
    seed_observations(logger, "river+weather", "flood", 50)
    de = build_extractor(logger)
    de.extract_doctrines()
    doc = de.get_doctrines()[0]
    assert doc["abstraction_level"] == "terrain"
    logger.close()


def test_doctrine_learned_effect_matches_observation():
    logger = temp_logger()
    seed_observations(logger, "wall+siege", "wall_collapse", 20)
    de = build_extractor(logger)
    de.extract_doctrines()
    doc = de.get_doctrines()[0]
    assert doc["learned_effect"] == "wall_collapse"
    logger.close()


def test_doctrine_failure_count_starts_at_zero():
    logger = temp_logger()
    seed_observations(logger, "river+weather", "flood", 50)
    de = build_extractor(logger)
    de.extract_doctrines()
    doc = de.get_doctrines()[0]
    assert doc["failure_count"] == 0
    logger.close()


def test_doctrine_exceptions_starts_empty():
    logger = temp_logger()
    seed_observations(logger, "river+weather", "flood", 50)
    de = build_extractor(logger)
    de.extract_doctrines()
    doc = de.get_doctrines()[0]
    assert doc["exceptions"] == []
    logger.close()


# ---------------------------------------------------------------------------
# Anonymity constraint
# ---------------------------------------------------------------------------

def test_doctrines_are_anonymous():
    """No player_id anywhere in any doctrine row."""
    logger = temp_logger()
    seed_observations(logger, "river+weather",       "flood",        100, "ep_a")
    seed_observations(logger, "frozen_lake+cavalry",  "ice_break",     10, "ep_b")
    seed_observations(logger, "wall+siege",           "wall_collapse",  20, "ep_c")
    de = build_extractor(logger)
    de.extract_doctrines()
    for doc in de.get_doctrines():
        assert "player_id" not in doc, (
            f"player_id found in doctrine row — doctrines must be anonymous"
        )
    logger.close()


# ---------------------------------------------------------------------------
# Promotion thresholds
# ---------------------------------------------------------------------------

def test_confidence_threshold_excludes_low_confidence_beliefs():
    """Beliefs below min_confidence must not become doctrines."""
    logger = temp_logger()
    # 3 observations → confidence = 3/4 = 0.75 (above 0.6 default)
    # 2 observations → belief won't even form (min_count=3 in world_model)
    # Use 5 observations → 5/6 ≈ 0.833 — above 0.6 but test with threshold 0.99
    seed_observations(logger, "river+weather", "flood", 5)
    de = build_extractor(logger)
    count = de.extract_doctrines(min_confidence=0.99)
    assert count == 0, (
        "5-observation belief has confidence 5/6 ≈ 0.833, "
        "should not qualify at threshold 0.99"
    )
    logger.close()


def test_confidence_threshold_includes_qualifying_beliefs():
    logger = temp_logger()
    seed_observations(logger, "river+weather", "flood", 100)
    de = build_extractor(logger)
    count = de.extract_doctrines(min_confidence=0.6)
    assert count == 1
    logger.close()


def test_episode_count_threshold_excludes_sparse_beliefs():
    """Beliefs with episode_count < min_episode_count must not promote."""
    logger = temp_logger()
    # 4 observations → belief exists (above world_model min_count=3)
    # but below doctrine min_episode_count=5
    seed_observations(logger, "river+weather", "flood", 4)
    de = build_extractor(logger)
    count = de.extract_doctrines(min_episode_count=5)
    assert count == 0, (
        "4-observation belief should not qualify at min_episode_count=5"
    )
    logger.close()


def test_episode_count_threshold_includes_qualifying_beliefs():
    logger = temp_logger()
    seed_observations(logger, "river+weather", "flood", 10)
    de = build_extractor(logger)
    count = de.extract_doctrines(min_episode_count=5)
    assert count == 1
    logger.close()


# ---------------------------------------------------------------------------
# Multiple effects → multiple doctrines
# ---------------------------------------------------------------------------

def test_multiple_effects_on_same_pair_produce_multiple_doctrines():
    """
    One terrain+action belief with two observed_outcomes must yield
    two separate doctrine rows.
    """
    logger = temp_logger()
    seed_observations(logger, "river+weather", "flood",   50, "ep_a")
    seed_observations(logger, "river+weather", "unknown", 10, "ep_b")
    de = build_extractor(logger)
    count = de.extract_doctrines()
    assert count == 2
    docs = de.get_doctrines()
    effects = {d["learned_effect"] for d in docs}
    assert "flood"   in effects
    assert "unknown" in effects
    logger.close()


# ---------------------------------------------------------------------------
# derived_principle
# ---------------------------------------------------------------------------

def test_known_template_river_weather_flood():
    logger = temp_logger()
    seed_observations(logger, "river+weather", "flood", 50)
    de = build_extractor(logger)
    de.extract_doctrines()
    doc = de.get_doctrines()[0]
    assert doc["derived_principle"] == "Rivers flood under heavy rain."
    logger.close()


def test_known_template_frozen_lake_cavalry_ice_break():
    logger = temp_logger()
    seed_observations(logger, "frozen_lake+cavalry", "ice_break", 10)
    de = build_extractor(logger)
    de.extract_doctrines()
    doc = de.get_doctrines()[0]
    assert doc["derived_principle"] == "Heavy cavalry on frozen lakes risks ice breakage."
    logger.close()


def test_known_template_wall_siege_wall_collapse():
    logger = temp_logger()
    seed_observations(logger, "wall+siege", "wall_collapse", 20)
    de = build_extractor(logger)
    de.extract_doctrines()
    doc = de.get_doctrines()[0]
    assert doc["derived_principle"] == "Siege weapons can collapse fortifications."
    logger.close()


def test_fallback_principle_for_unknown_combination():
    principle = _derive_principle("marsh", "infantry", "slow")
    assert "marsh" in principle.lower()
    assert "infantry" in principle.lower() or "infantry".replace("_", " ") in principle.lower()
    assert "slow" in principle.lower()
    assert principle.endswith(".")
    logger = temp_logger()
    logger.close()


def test_derived_principle_is_string():
    logger = temp_logger()
    seed_observations(logger, "river+weather", "flood", 50)
    de = build_extractor(logger)
    de.extract_doctrines()
    for doc in de.get_doctrines():
        assert isinstance(doc["derived_principle"], str)
        assert len(doc["derived_principle"]) > 0
    logger.close()


def test_derived_principle_contains_no_numeric_physics_constants():
    """Principles must be plain language, not physics values."""
    logger = temp_logger()
    seed_observations(logger, "river+weather",       "flood",        50, "ep_a")
    seed_observations(logger, "frozen_lake+cavalry",  "ice_break",    10, "ep_b")
    seed_observations(logger, "wall+siege",           "wall_collapse", 20, "ep_c")
    de = build_extractor(logger)
    de.extract_doctrines()
    for doc in de.get_doctrines():
        principle = doc["derived_principle"]
        # No numeric constants from physics (e.g. 800.0, 500.0, 0.15)
        import re
        numbers = re.findall(r"\b\d+\.\d+\b", principle)
        assert numbers == [], (
            f"Physics constant found in principle: '{principle}' — "
            f"principles must be plain language"
        )
    logger.close()


# ---------------------------------------------------------------------------
# get_doctrine
# ---------------------------------------------------------------------------

def test_get_doctrine_returns_correct_belief():
    logger = temp_logger()
    seed_observations(logger, "river+weather",       "flood",    50, "ep_a")
    seed_observations(logger, "frozen_lake+cavalry",  "ice_break", 10, "ep_b")
    de = build_extractor(logger)
    de.extract_doctrines()
    doc = de.get_doctrine("river", "weather")
    assert doc is not None
    assert doc["learned_effect"] == "flood"
    logger.close()


def test_get_doctrine_returns_none_for_unknown_pair():
    logger = temp_logger()
    seed_observations(logger, "river+weather", "flood", 50)
    de = build_extractor(logger)
    de.extract_doctrines()
    assert de.get_doctrine("swamp", "infantry") is None
    logger.close()


def test_get_doctrine_returns_none_before_extraction():
    logger = temp_logger()
    seed_observations(logger, "river+weather", "flood", 50)
    de = build_extractor(logger)
    assert de.get_doctrine("river", "weather") is None
    logger.close()


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def test_extract_doctrines_is_idempotent():
    """Calling extract twice must not duplicate rows or change confidence."""
    logger = temp_logger()
    seed_observations(logger, "river+weather", "flood", 50)
    de = build_extractor(logger)
    de.extract_doctrines()
    first = de.get_doctrines()

    de.extract_doctrines()
    second = de.get_doctrines()

    assert len(first) == len(second)
    assert first[0]["confidence"]    == second[0]["confidence"]
    assert first[0]["episode_count"] == second[0]["episode_count"]
    assert first[0]["failure_count"] == second[0]["failure_count"]
    logger.close()


# ---------------------------------------------------------------------------
# doctrine_summary
# ---------------------------------------------------------------------------

def test_doctrine_summary_empty():
    logger = temp_logger()
    de = build_extractor(logger)
    s = de.doctrine_summary()
    assert s["total_doctrines"] == 0
    assert s["effects_covered"] == []
    assert s["terrain_types"]   == []
    assert s["avg_confidence"]  == 0.0
    logger.close()


def test_doctrine_summary_structure():
    logger = temp_logger()
    seed_observations(logger, "river+weather",       "flood",        50, "ep_a")
    seed_observations(logger, "frozen_lake+cavalry",  "ice_break",    10, "ep_b")
    seed_observations(logger, "wall+siege",           "wall_collapse", 20, "ep_c")
    de = build_extractor(logger)
    de.extract_doctrines()
    s = de.doctrine_summary()
    required = {
        "total_doctrines", "effects_covered", "terrain_types",
        "avg_confidence", "min_confidence", "principles",
    }
    assert required.issubset(s.keys())
    logger.close()


def test_doctrine_summary_total_count():
    logger = temp_logger()
    seed_observations(logger, "river+weather",       "flood",        50, "ep_a")
    seed_observations(logger, "frozen_lake+cavalry",  "ice_break",    10, "ep_b")
    seed_observations(logger, "wall+siege",           "wall_collapse", 20, "ep_c")
    de = build_extractor(logger)
    de.extract_doctrines()
    assert de.doctrine_summary()["total_doctrines"] == 3
    logger.close()


def test_doctrine_summary_effects_covered():
    logger = temp_logger()
    seed_observations(logger, "river+weather",       "flood",        50, "ep_a")
    seed_observations(logger, "frozen_lake+cavalry",  "ice_break",    10, "ep_b")
    de = build_extractor(logger)
    de.extract_doctrines()
    effects = de.doctrine_summary()["effects_covered"]
    assert "flood"    in effects
    assert "ice_break" in effects
    logger.close()


def test_doctrine_summary_avg_confidence_in_range():
    logger = temp_logger()
    seed_observations(logger, "river+weather",       "flood",        100, "ep_a")
    seed_observations(logger, "frozen_lake+cavalry",  "ice_break",     10, "ep_b")
    de = build_extractor(logger)
    de.extract_doctrines()
    avg = de.doctrine_summary()["avg_confidence"]
    assert 0.0 < avg <= 1.0
    logger.close()


def test_doctrine_summary_principles_list():
    logger = temp_logger()
    seed_observations(logger, "river+weather", "flood", 50)
    de = build_extractor(logger)
    de.extract_doctrines()
    principles = de.doctrine_summary()["principles"]
    assert isinstance(principles, list)
    assert len(principles) == 1
    assert principles[0] == "Rivers flood under heavy rain."
    logger.close()


# ---------------------------------------------------------------------------
# No coordinates
# ---------------------------------------------------------------------------

def test_no_coordinates_in_any_doctrine():
    """Doctrines must never contain coordinate-like keys."""
    logger = temp_logger()
    seed_observations(logger, "river+weather",       "flood",        50, "ep_a")
    seed_observations(logger, "frozen_lake+cavalry",  "ice_break",    10, "ep_b")
    de = build_extractor(logger)
    de.extract_doctrines()
    coord_keys = {"x", "y", "zone", "position", "coordinate", "location", "col", "row"}
    for doc in de.get_doctrines():
        for key in doc.keys():
            assert key.lower() not in coord_keys, (
                f"Coordinate-like key '{key}' found in doctrine — "
                "brain output must never expose location data"
            )
    logger.close()
