"""
test_player_profiler.py — Verify per-player profile construction.

All tests use isolated temp databases seeded with synthetic episodes.
The episode data is constructed to have known intent distributions,
terrain events, and unit compositions so formula results are verifiable.

Key invariants:
  - player_profiler.py imports only from simulator.logger (Rule 3)
  - Profiles are scoped to (server_id, player_id)
  - Same player_id on different server_id → independent profiles
  - aggression_index = aggressive_intents / total_intents
  - adaptability_score = adaptations_after_loss / max(1, loss_count)
  - preferred_units = {type: {used: N, wins: W}} — raw evidence retained
  - terrain_tendencies = {terrain: {count: N, wins: W, losses: L}}
  - Raw evidence blob persisted in data field
  - update_profile is idempotent
  - No coordinates anywhere in any profile
"""

import json
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

import pytest
from simulator.logger import EpisodeLogger
from brain.player_profiler import PlayerProfiler, AGGRESSIVE_INTENTS, _dominant_intent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def temp_logger() -> EpisodeLogger:
    tmp = tempfile.mktemp(suffix=".db")
    return EpisodeLogger(db_path=Path(tmp))


def seed_episode(
    logger:         EpisodeLogger,
    player_id:      str,
    result:         str,
    player_intents: List[str] = None,
    terrain_events: List[dict] = None,
    unit_types:     dict = None,
    episode_id:     str = None,
) -> str:
    """
    Insert a synthetic episode with controllable intent, terrain, and unit data.
    Returns the episode id.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    eid = episode_id or f"ep_{uuid.uuid4().hex[:10]}"
    intents = player_intents or ["aggressive_push"] * 5

    data = {
        "id":              eid,
        "player_id":       player_id,
        "age":             1,
        "battlefield":     {},
        "top_zones":       [],
        "general_intents": ["defensive"] * len(intents),
        "player_intents":  intents,
        "terrain_events":  terrain_events or [],
        "combat_results":  [],
        "turns_played":    len(intents),
        "result":          result,
        "general_unit_summary": {
            "total": 3, "surviving": 2, "loss_rate": 0.33,
            "avg_health": 0.7, "avg_supply": 0.8, "avg_morale": 0.75,
            "unit_types": {"infantry": 3},
        },
        "player_unit_summary": {
            "total": 3, "surviving": 2, "loss_rate": 0.33,
            "avg_health": 0.7, "avg_supply": 0.8, "avg_morale": 0.75,
            "unit_types": unit_types or {"infantry": 2, "cavalry": 1},
        },
    }
    conn = logger._get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO episodes "
        "(id, timestamp, player_id, age, result, turns_played, data) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (eid, timestamp, player_id, 1, result, len(intents), json.dumps(data)),
    )
    conn.commit()
    return eid


# ---------------------------------------------------------------------------
# Rule 3: import constraint
# ---------------------------------------------------------------------------

def test_no_simulator_internals_in_player_profiler():
    """player_profiler.py must import only from simulator.logger."""
    src = (_PROJECT_ROOT / "src" / "brain" / "player_profiler.py").read_text()
    forbidden = [
        "from simulator.grid",   "import simulator.grid",
        "from simulator.units",  "import simulator.units",
        "from simulator.physics","import simulator.physics",
        "from simulator.battle", "import simulator.battle",
        "from brain.world_model",
        "from brain.doctrine_extractor",
    ]
    for token in forbidden:
        assert token not in src, f"Forbidden import in player_profiler.py: '{token}'"


# ---------------------------------------------------------------------------
# Construction and empty state
# ---------------------------------------------------------------------------

def test_player_profiler_constructs():
    logger = temp_logger()
    pp = PlayerProfiler(logger)
    assert pp is not None
    logger.close()


def test_update_profile_returns_empty_dict_when_no_episodes():
    logger = temp_logger()
    pp = PlayerProfiler(logger)
    result = pp.update_profile("server_1", "player_A")
    assert result == {}
    logger.close()


def test_get_profile_returns_none_before_update():
    logger = temp_logger()
    pp = PlayerProfiler(logger)
    assert pp.get_profile("server_1", "player_A") is None
    logger.close()


# ---------------------------------------------------------------------------
# Basic profile fields
# ---------------------------------------------------------------------------

def test_update_profile_creates_profile_row():
    logger = temp_logger()
    seed_episode(logger, "player_A", "win")
    pp = PlayerProfiler(logger)
    pp.update_profile("server_1", "player_A")
    assert pp.get_profile("server_1", "player_A") is not None
    logger.close()


def test_total_battles_correct():
    logger = temp_logger()
    for i in range(5):
        seed_episode(logger, "player_A", "win", episode_id=f"ep_{i}")
    pp = PlayerProfiler(logger)
    pp.update_profile("server_1", "player_A")
    profile = pp.get_profile("server_1", "player_A")
    assert profile["total_battles"] == 5
    logger.close()


def test_win_loss_draw_counts_correct():
    logger = temp_logger()
    seed_episode(logger, "player_A", "win",  episode_id="ep_w1")
    seed_episode(logger, "player_A", "win",  episode_id="ep_w2")
    seed_episode(logger, "player_A", "loss", episode_id="ep_l1")
    seed_episode(logger, "player_A", "draw", episode_id="ep_d1")
    pp = PlayerProfiler(logger)
    pp.update_profile("server_1", "player_A")
    p = pp.get_profile("server_1", "player_A")
    assert p["win_count"]  == 2
    assert p["loss_count"] == 1
    assert p["draw_count"] == 1
    logger.close()


def test_first_seen_and_last_seen_are_set():
    logger = temp_logger()
    seed_episode(logger, "player_A", "win")
    pp = PlayerProfiler(logger)
    pp.update_profile("server_1", "player_A")
    p = pp.get_profile("server_1", "player_A")
    assert p["first_seen"] is not None
    assert p["last_seen"]  is not None
    logger.close()


def test_profile_has_all_required_keys():
    logger = temp_logger()
    seed_episode(logger, "player_A", "win")
    pp = PlayerProfiler(logger)
    pp.update_profile("server_1", "player_A")
    p = pp.get_profile("server_1", "player_A")
    required = {
        "server_id", "player_id", "first_seen", "last_seen",
        "total_battles", "win_count", "loss_count", "draw_count",
        "preferred_units", "terrain_tendencies",
        "aggression_index", "adaptability_score", "data",
    }
    assert required.issubset(p.keys())
    logger.close()


# ---------------------------------------------------------------------------
# Server scoping
# ---------------------------------------------------------------------------

def test_same_player_different_servers_are_independent():
    logger = temp_logger()
    for i in range(3):
        seed_episode(logger, "player_A", "win", episode_id=f"ep_{i}")
    pp = PlayerProfiler(logger)
    pp.update_profile("server_A", "player_A")
    pp.update_profile("server_B", "player_A")

    prof_a = pp.get_profile("server_A", "player_A")
    prof_b = pp.get_profile("server_B", "player_A")

    # Both exist but are separate rows
    assert prof_a is not None
    assert prof_b is not None
    assert prof_a["server_id"] == "server_A"
    assert prof_b["server_id"] == "server_B"
    logger.close()


def test_get_all_profiles_server_filter():
    logger = temp_logger()
    seed_episode(logger, "player_A", "win",  episode_id="ep_1")
    seed_episode(logger, "player_B", "loss", episode_id="ep_2")
    pp = PlayerProfiler(logger)
    pp.update_profile("server_A", "player_A")
    pp.update_profile("server_B", "player_B")

    a_profiles = pp.get_all_profiles(server_id="server_A")
    b_profiles = pp.get_all_profiles(server_id="server_B")

    assert len(a_profiles) == 1
    assert a_profiles[0]["player_id"] == "player_A"
    assert len(b_profiles) == 1
    assert b_profiles[0]["player_id"] == "player_B"
    logger.close()


def test_profile_from_server_a_not_visible_on_server_b():
    logger = temp_logger()
    seed_episode(logger, "player_A", "win")
    pp = PlayerProfiler(logger)
    pp.update_profile("server_A", "player_A")
    assert pp.get_profile("server_B", "player_A") is None
    logger.close()


# ---------------------------------------------------------------------------
# Aggression index
# ---------------------------------------------------------------------------

def test_aggression_index_all_aggressive():
    """5 aggressive intents → aggression_index = 1.0"""
    logger = temp_logger()
    seed_episode(logger, "player_A", "win",
                 player_intents=["aggressive_push"] * 5)
    pp = PlayerProfiler(logger)
    pp.update_profile("server_1", "player_A")
    p = pp.get_profile("server_1", "player_A")
    assert p["aggression_index"] == 1.0
    logger.close()


def test_aggression_index_all_defensive():
    """5 defensive intents → aggression_index = 0.0"""
    logger = temp_logger()
    seed_episode(logger, "player_A", "win",
                 player_intents=["defensive"] * 5)
    pp = PlayerProfiler(logger)
    pp.update_profile("server_1", "player_A")
    p = pp.get_profile("server_1", "player_A")
    assert p["aggression_index"] == 0.0
    logger.close()


def test_aggression_index_mixed():
    """4 aggressive + 4 defensive → aggression_index = 0.5"""
    logger = temp_logger()
    seed_episode(logger, "player_A", "win",
                 player_intents=["aggressive_push"] * 4 + ["defensive"] * 4)
    pp = PlayerProfiler(logger)
    pp.update_profile("server_1", "player_A")
    p = pp.get_profile("server_1", "player_A")
    assert abs(p["aggression_index"] - 0.5) < 1e-6
    logger.close()


def test_aggression_index_in_valid_range():
    logger = temp_logger()
    seed_episode(logger, "player_A", "win",
                 player_intents=["flanking", "defensive", "siege", "retreat"])
    pp = PlayerProfiler(logger)
    pp.update_profile("server_1", "player_A")
    p = pp.get_profile("server_1", "player_A")
    assert 0.0 <= p["aggression_index"] <= 1.0
    logger.close()


# ---------------------------------------------------------------------------
# Adaptability score
# ---------------------------------------------------------------------------

def test_adaptability_zero_when_no_losses():
    logger = temp_logger()
    seed_episode(logger, "player_A", "win",
                 player_intents=["aggressive_push"] * 3, episode_id="ep_1")
    seed_episode(logger, "player_A", "win",
                 player_intents=["defensive"] * 3, episode_id="ep_2")
    pp = PlayerProfiler(logger)
    pp.update_profile("server_1", "player_A")
    p = pp.get_profile("server_1", "player_A")
    # No losses → adaptability_score = 0 / max(1, 0) = 0
    assert p["adaptability_score"] == 0.0
    logger.close()


def test_adaptability_one_when_always_adapts_after_loss():
    """Player loses then always changes strategy → adaptability = 1.0"""
    logger = temp_logger()
    seed_episode(logger, "player_A", "loss",
                 player_intents=["aggressive_push"] * 3, episode_id="ep_1")
    seed_episode(logger, "player_A", "win",
                 player_intents=["defensive"] * 3, episode_id="ep_2")
    pp = PlayerProfiler(logger)
    pp.update_profile("server_1", "player_A")
    p = pp.get_profile("server_1", "player_A")
    assert p["adaptability_score"] == 1.0
    logger.close()


def test_adaptability_zero_when_never_adapts_after_loss():
    """Player loses twice with same strategy → no adaptation → 0.0"""
    logger = temp_logger()
    seed_episode(logger, "player_A", "loss",
                 player_intents=["aggressive_push"] * 3, episode_id="ep_1")
    seed_episode(logger, "player_A", "loss",
                 player_intents=["aggressive_push"] * 3, episode_id="ep_2")
    pp = PlayerProfiler(logger)
    pp.update_profile("server_1", "player_A")
    p = pp.get_profile("server_1", "player_A")
    assert p["adaptability_score"] == 0.0
    logger.close()


def test_adaptability_in_valid_range():
    logger = temp_logger()
    seed_episode(logger, "player_A", "loss",
                 player_intents=["aggressive_push"] * 3, episode_id="ep_1")
    seed_episode(logger, "player_A", "win",
                 player_intents=["siege"] * 3, episode_id="ep_2")
    seed_episode(logger, "player_A", "loss",
                 player_intents=["siege"] * 3, episode_id="ep_3")
    seed_episode(logger, "player_A", "win",
                 player_intents=["defensive"] * 3, episode_id="ep_4")
    pp = PlayerProfiler(logger)
    pp.update_profile("server_1", "player_A")
    p = pp.get_profile("server_1", "player_A")
    assert 0.0 <= p["adaptability_score"] <= 1.0
    logger.close()


# ---------------------------------------------------------------------------
# preferred_units
# ---------------------------------------------------------------------------

def test_preferred_units_structure():
    logger = temp_logger()
    seed_episode(logger, "player_A", "win",
                 unit_types={"cavalry": 2, "infantry": 1})
    pp = PlayerProfiler(logger)
    pp.update_profile("server_1", "player_A")
    p = pp.get_profile("server_1", "player_A")
    pu = p["preferred_units"]
    assert isinstance(pu, dict)
    for unit_type, stats in pu.items():
        assert "used" in stats
        assert "wins" in stats
    logger.close()


def test_preferred_units_counts_correct():
    logger = temp_logger()
    seed_episode(logger, "player_A", "win",
                 unit_types={"cavalry": 3}, episode_id="ep_1")
    seed_episode(logger, "player_A", "loss",
                 unit_types={"cavalry": 3}, episode_id="ep_2")
    pp = PlayerProfiler(logger)
    pp.update_profile("server_1", "player_A")
    p = pp.get_profile("server_1", "player_A")
    cav = p["preferred_units"].get("cavalry", {})
    assert cav["used"] == 6      # 3 + 3 across both battles
    assert cav["wins"] == 3      # only from the win battle
    logger.close()


def test_preferred_units_graceful_when_unit_types_missing():
    """Episodes without unit_types key (old schema) must not crash."""
    logger = temp_logger()
    # Seed an episode with no unit_types in player_unit_summary
    timestamp = datetime.now(timezone.utc).isoformat()
    data = {
        "id": "ep_old", "player_id": "player_A", "age": 1,
        "battlefield": {}, "top_zones": [], "general_intents": [],
        "player_intents": ["defensive"] * 3, "terrain_events": [],
        "combat_results": [], "turns_played": 3, "result": "win",
        "general_unit_summary": {"total": 1, "surviving": 1,
                                  "loss_rate": 0.0, "avg_health": 1.0,
                                  "avg_supply": 1.0, "avg_morale": 1.0},
        "player_unit_summary":  {"total": 1, "surviving": 1,
                                  "loss_rate": 0.0, "avg_health": 1.0,
                                  "avg_supply": 1.0, "avg_morale": 1.0},
        # NOTE: no "unit_types" key — old episode format
    }
    conn = logger._get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO episodes "
        "(id, timestamp, player_id, age, result, turns_played, data) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("ep_old", timestamp, "player_A", 1, "win", 3, json.dumps(data)),
    )
    conn.commit()
    pp = PlayerProfiler(logger)
    pp.update_profile("server_1", "player_A")  # must not raise
    p = pp.get_profile("server_1", "player_A")
    assert p is not None
    assert isinstance(p["preferred_units"], dict)
    logger.close()


# ---------------------------------------------------------------------------
# terrain_tendencies
# ---------------------------------------------------------------------------

def test_terrain_tendencies_structure():
    logger = temp_logger()
    seed_episode(logger, "player_A", "win",
                 terrain_events=[{"terrain_at_site": "forest", "event_type": "tree_fall",
                                   "triggered_by_type": "cavalry"}])
    pp = PlayerProfiler(logger)
    pp.update_profile("server_1", "player_A")
    p = pp.get_profile("server_1", "player_A")
    for terrain, stats in p["terrain_tendencies"].items():
        assert "count"  in stats
        assert "wins"   in stats
        assert "losses" in stats
    logger.close()


def test_terrain_tendencies_counts_wins_and_losses():
    logger = temp_logger()
    river_event = [{"terrain_at_site": "river", "event_type": "flood",
                    "triggered_by_type": "weather"}]
    seed_episode(logger, "player_A", "win",  terrain_events=river_event, episode_id="e1")
    seed_episode(logger, "player_A", "win",  terrain_events=river_event, episode_id="e2")
    seed_episode(logger, "player_A", "loss", terrain_events=river_event, episode_id="e3")
    pp = PlayerProfiler(logger)
    pp.update_profile("server_1", "player_A")
    p = pp.get_profile("server_1", "player_A")
    river = p["terrain_tendencies"].get("river", {})
    assert river["count"]  == 3
    assert river["wins"]   == 2
    assert river["losses"] == 1
    logger.close()


def test_terrain_counted_once_per_episode():
    """Even with multiple terrain events on same terrain, count is 1 per episode."""
    logger = temp_logger()
    seed_episode(
        logger, "player_A", "win",
        terrain_events=[
            {"terrain_at_site": "river", "event_type": "flood", "triggered_by_type": "weather"},
            {"terrain_at_site": "river", "event_type": "flood", "triggered_by_type": "weather"},
        ]
    )
    pp = PlayerProfiler(logger)
    pp.update_profile("server_1", "player_A")
    p = pp.get_profile("server_1", "player_A")
    river = p["terrain_tendencies"].get("river", {})
    assert river["count"] == 1
    logger.close()


# ---------------------------------------------------------------------------
# Raw evidence blob
# ---------------------------------------------------------------------------

def test_data_blob_contains_raw_evidence_keys():
    logger = temp_logger()
    seed_episode(logger, "player_A", "win",
                 player_intents=["aggressive_push", "defensive"])
    pp = PlayerProfiler(logger)
    pp.update_profile("server_1", "player_A")
    p = pp.get_profile("server_1", "player_A")
    required = {
        "intent_counts", "strategy_switches", "loss_recoveries",
        "unit_usage", "terrain_stats",
    }
    assert required.issubset(p["data"].keys())
    logger.close()


def test_data_blob_intent_counts_accurate():
    logger = temp_logger()
    seed_episode(logger, "player_A", "win",
                 player_intents=["aggressive_push", "aggressive_push", "defensive"])
    pp = PlayerProfiler(logger)
    pp.update_profile("server_1", "player_A")
    p = pp.get_profile("server_1", "player_A")
    counts = p["data"]["intent_counts"]
    assert counts.get("aggressive_push") == 2
    assert counts.get("defensive")       == 1
    logger.close()


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def test_update_profile_is_idempotent():
    logger = temp_logger()
    seed_episode(logger, "player_A", "win",  episode_id="ep_1")
    seed_episode(logger, "player_A", "loss", episode_id="ep_2")
    pp = PlayerProfiler(logger)
    pp.update_profile("server_1", "player_A")
    first = pp.get_profile("server_1", "player_A")
    pp.update_profile("server_1", "player_A")
    second = pp.get_profile("server_1", "player_A")
    assert first["total_battles"]      == second["total_battles"]
    assert first["aggression_index"]   == second["aggression_index"]
    assert first["adaptability_score"] == second["adaptability_score"]
    assert first["preferred_units"]    == second["preferred_units"]
    logger.close()


# ---------------------------------------------------------------------------
# profile_summary
# ---------------------------------------------------------------------------

def test_profile_summary_empty_when_no_profile():
    logger = temp_logger()
    pp = PlayerProfiler(logger)
    assert pp.profile_summary("server_1", "player_A") == {}
    logger.close()


def test_profile_summary_structure():
    logger = temp_logger()
    seed_episode(logger, "player_A", "win",
                 player_intents=["aggressive_push"] * 3,
                 unit_types={"cavalry": 2})
    pp = PlayerProfiler(logger)
    pp.update_profile("server_1", "player_A")
    s = pp.profile_summary("server_1", "player_A")
    required = {
        "player_id", "server_id", "total_battles", "win_rate",
        "aggression_index", "adaptability_score",
        "top_units", "terrain_comfort",
    }
    assert required.issubset(s.keys())
    logger.close()


def test_profile_summary_win_rate():
    logger = temp_logger()
    seed_episode(logger, "player_A", "win",  episode_id="e1")
    seed_episode(logger, "player_A", "win",  episode_id="e2")
    seed_episode(logger, "player_A", "loss", episode_id="e3")
    seed_episode(logger, "player_A", "loss", episode_id="e4")
    pp = PlayerProfiler(logger)
    pp.update_profile("server_1", "player_A")
    s = pp.profile_summary("server_1", "player_A")
    assert abs(s["win_rate"] - 0.5) < 1e-6
    logger.close()


# ---------------------------------------------------------------------------
# No coordinates
# ---------------------------------------------------------------------------

def test_no_coordinates_in_any_profile_field():
    logger = temp_logger()
    seed_episode(logger, "player_A", "win")
    pp = PlayerProfiler(logger)
    pp.update_profile("server_1", "player_A")
    p = pp.get_profile("server_1", "player_A")
    coord_keys = {"x", "y", "zone", "position", "coordinate", "location"}
    for key in p.keys():
        assert key.lower() not in coord_keys
    logger.close()


# ---------------------------------------------------------------------------
# _dominant_intent helper
# ---------------------------------------------------------------------------

def test_dominant_intent_returns_most_common():
    intents = ["aggressive_push", "aggressive_push", "defensive"]
    assert _dominant_intent(intents) == "aggressive_push"


def test_dominant_intent_empty_list():
    assert _dominant_intent([]) == ""
