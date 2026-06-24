"""
test_training_profiles.py — Verify the training profile system.

Tests cover:
  - Profile structure validity
  - weather_weights correctness (anti_flood has 0 heavy_rain)
  - BattleLoop accepts and uses weather_weights (backward compatible)
  - generate_corpus runs and produces observations without errors
  - target count logic
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/Users/Arman/Projects/general_brain/src")

import random
import pytest
from simulator.grid import Grid
from simulator.units import UnitType, make_unit
from simulator.battle import BattleLoop, WEATHER_CONDITIONS
from simulator.logger import EpisodeLogger
from simulator.training_profiles import (
    PROFILES,
    TARGET_COUNTS,
    validate_profile,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def temp_logger() -> EpisodeLogger:
    tmp = tempfile.mktemp(suffix=".db")
    return EpisodeLogger(db_path=Path(tmp))


def quick_battle(weather_weights=None, seed=42):
    """Run a minimal battle and return the state."""
    grid = Grid(seed=seed)
    general_units = [
        make_unit(UnitType.CAVALRY,  "general", (20, 75)),
        make_unit(UnitType.SIEGE,    "general", (23, 75)),
        make_unit(UnitType.INFANTRY, "general", (26, 75)),
    ]
    player_units = [
        make_unit(UnitType.INFANTRY, "player", (20, 25)),
        make_unit(UnitType.CAVALRY,  "player", (23, 25)),
    ]
    loop = BattleLoop(
        grid=grid,
        general_units=general_units,
        player_units=player_units,
        seed=seed,
        weather_weights=weather_weights,
    )
    return loop.run()


# ---------------------------------------------------------------------------
# Profile structure
# ---------------------------------------------------------------------------

def test_all_expected_profiles_exist():
    for name in ["natural", "anti_flood", "terrain_learning", "siege_learning", "balanced"]:
        assert name in PROFILES, f"Profile '{name}' missing from PROFILES"


def test_every_profile_has_required_keys():
    for name, profile in PROFILES.items():
        assert "description"       in profile, f"Profile '{name}' missing 'description'"
        assert "weather_weights"   in profile, f"Profile '{name}' missing 'weather_weights'"
        assert "general_unit_types" in profile, f"Profile '{name}' missing 'general_unit_types'"
        assert "player_unit_types"  in profile, f"Profile '{name}' missing 'player_unit_types'"


def test_every_profile_has_positive_total_weight():
    for name, profile in PROFILES.items():
        total = sum(profile["weather_weights"].values())
        assert total > 0, f"Profile '{name}' has all-zero weather weights"


def test_anti_flood_disables_heavy_rain():
    weight = PROFILES["anti_flood"]["weather_weights"].get("heavy_rain", -1)
    assert weight == 0.0, (
        f"anti_flood must set heavy_rain weight to 0.0, got {weight}"
    )


def test_terrain_learning_disables_heavy_rain():
    weight = PROFILES["terrain_learning"]["weather_weights"].get("heavy_rain", -1)
    assert weight == 0.0


def test_siege_learning_disables_heavy_rain():
    weight = PROFILES["siege_learning"]["weather_weights"].get("heavy_rain", -1)
    assert weight == 0.0


def test_anti_flood_includes_cavalry_and_siege():
    unit_types = PROFILES["anti_flood"]["general_unit_types"]
    assert unit_types is not None
    assert "cavalry" in unit_types
    assert "siege" in unit_types


def test_siege_learning_includes_multiple_siege():
    unit_types = PROFILES["siege_learning"]["general_unit_types"]
    assert unit_types is not None
    assert unit_types.count("siege") >= 2, (
        "siege_learning should have at least 2 siege units to reliably trigger wall_collapse"
    )


# ---------------------------------------------------------------------------
# validate_profile
# ---------------------------------------------------------------------------

def test_validate_profile_accepts_all_defined_profiles():
    for name in PROFILES:
        validate_profile(name)   # must not raise


def test_validate_profile_rejects_unknown_name():
    with pytest.raises(ValueError, match="Unknown training profile"):
        validate_profile("nonexistent_profile")


# ---------------------------------------------------------------------------
# TARGET_COUNTS structure
# ---------------------------------------------------------------------------

def test_target_counts_exist_for_key_profiles():
    for name in ["balanced", "anti_flood", "natural"]:
        assert name in TARGET_COUNTS, f"TARGET_COUNTS missing entry for '{name}'"


def test_target_counts_are_positive_integers():
    for profile_name, targets in TARGET_COUNTS.items():
        for event, count in targets.items():
            assert isinstance(count, int) and count > 0, (
                f"TARGET_COUNTS['{profile_name}']['{event}'] = {count} "
                f"must be a positive integer"
            )


def test_balanced_targets_three_events_no_flood():
    targets = TARGET_COUNTS["balanced"]
    expected = {"ice_break", "wall_collapse", "tree_fall"}
    assert set(targets.keys()) == expected, (
        f"balanced targets should be {expected}, got {set(targets.keys())}"
    )


def test_anti_flood_targets_exclude_flood():
    targets = TARGET_COUNTS["anti_flood"]
    assert "flood" not in targets, (
        "anti_flood target counts must not include 'flood' — "
        "it is suppressed by design, not targeted"
    )


# ---------------------------------------------------------------------------
# BattleLoop backward compatibility
# ---------------------------------------------------------------------------

def test_battle_loop_runs_without_weather_weights():
    """Existing API (no weather_weights arg) still works."""
    grid = Grid(seed=1)
    general_units = [make_unit(UnitType.INFANTRY, "general", (20, 75))]
    player_units  = [make_unit(UnitType.INFANTRY, "player",  (20, 25))]
    loop = BattleLoop(grid=grid, general_units=general_units,
                      player_units=player_units, seed=1)
    state = loop.run()
    assert state.result in ("win", "loss", "draw")


def test_battle_loop_accepts_weather_weights():
    weights = {"clear": 5.0, "fog": 2.0, "heavy_rain": 0.0, "blizzard": 1.0, "wind": 1.0}
    state = quick_battle(weather_weights=weights)
    assert state.result in ("win", "loss", "draw")


def test_anti_flood_weights_produce_no_flood_events():
    """
    With heavy_rain=0.0, flood should not appear in terrain events.
    Run 5 battles to get reasonable coverage.
    """
    weights = PROFILES["anti_flood"]["weather_weights"]
    for seed in range(5):
        state = quick_battle(weather_weights=weights, seed=seed * 7 + 1)
        flood_events = [
            e for e in state.terrain_events
            if e.get("event_type") == "flood"
        ]
        assert len(flood_events) == 0, (
            f"Seed {seed}: flood event appeared despite heavy_rain=0.0. "
            f"Events: {state.terrain_events}"
        )


def test_weather_weights_none_uses_natural_generation():
    """
    Without weather_weights, the natural distribution is used.
    Just verify no crash and battle completes.
    """
    state = quick_battle(weather_weights=None)
    assert state.turns_played > 0


# ---------------------------------------------------------------------------
# generate_corpus integration (lightweight)
# ---------------------------------------------------------------------------

def test_generate_corpus_runs_and_logs_episodes():
    """
    Run 5 battles via the generate_corpus logic using a temp DB.
    Verify episodes and observations are written.
    """
    # Inline the generate_corpus logic at minimal scale
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from generate_corpus import run

    tmp = tempfile.mktemp(suffix=".db")
    run(profile_name="anti_flood", max_battles=5, report_every=999, db_path=Path(tmp))

    logger = EpisodeLogger(db_path=Path(tmp))
    count = logger.get_episode_count()
    assert count == 5, f"Expected 5 episodes, got {count}"
    logger.close()


def test_generate_corpus_produces_observations():
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from generate_corpus import run

    tmp = tempfile.mktemp(suffix=".db")
    run(profile_name="balanced", max_battles=10, report_every=999, db_path=Path(tmp))

    logger = EpisodeLogger(db_path=Path(tmp))
    patterns = logger.get_observation_patterns(min_count=1)
    assert len(patterns) > 0, "No observations extracted after 10 battles"
    logger.close()


def test_generate_corpus_no_flood_with_anti_flood_profile():
    """With anti_flood profile, flood events must not appear in the DB."""
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from generate_corpus import run

    tmp = tempfile.mktemp(suffix=".db")
    run(profile_name="anti_flood", max_battles=20, report_every=999, db_path=Path(tmp))

    logger = EpisodeLogger(db_path=Path(tmp))
    freq = logger.terrain_event_frequency()
    assert freq.get("flood", 0) == 0, (
        f"anti_flood profile produced {freq.get('flood')} flood events — expected 0"
    )
    logger.close()


def test_all_targets_met_logic():
    """Verify the stopping condition helper works correctly."""
    from generate_corpus import all_targets_met
    targets  = {"flood": 100, "ice_break": 50}

    assert all_targets_met({"flood": 100, "ice_break": 50}, targets)
    assert all_targets_met({"flood": 200, "ice_break": 50}, targets)
    assert not all_targets_met({"flood": 99,  "ice_break": 50}, targets)
    assert not all_targets_met({"flood": 100, "ice_break": 49}, targets)
    assert not all_targets_met({}, targets)
