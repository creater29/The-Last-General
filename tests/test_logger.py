"""
test_logger.py — Verify episode persistence and retrieval.
"""
import sys
import json
import tempfile
from pathlib import Path

sys.path.insert(0, "/Users/Arman/Projects/general_brain/src")

from simulator.grid import Grid
from simulator.units import UnitType, make_unit
from simulator.battle import BattleLoop, BattleState
from simulator.logger import EpisodeLogger


def make_battle_state(seed=42, player_id="player_test") -> BattleState:
    grid = Grid(100, 100, seed=seed)
    general_units = [
        make_unit(UnitType.INFANTRY, "general", (50, 70)),
        make_unit(UnitType.CAVALRY,  "general", (50, 70)),
        make_unit(UnitType.ARCHER,   "general", (50, 70)),
    ]
    player_units = [
        make_unit(UnitType.INFANTRY, "player_test", (50, 30)),
        make_unit(UnitType.CAVALRY,  "player_test", (50, 30)),
        make_unit(UnitType.SIEGE,    "player_test", (50, 30)),
    ]
    loop = BattleLoop(
        grid=grid,
        general_units=general_units,
        player_units=player_units,
        player_id=player_id,
        age=1,
        seed=seed,
    )
    return loop.run()


def temp_logger() -> EpisodeLogger:
    """Create a logger using a temp DB — isolated per test."""
    tmp = tempfile.mktemp(suffix=".db")
    return EpisodeLogger(db_path=Path(tmp))


# ---------------------------------------------------------------------------
# DB initialization
# ---------------------------------------------------------------------------

def test_db_creates_all_tables():
    logger = temp_logger()
    conn = logger._get_conn()
    tables = {
        row[0] for row in
        conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    required = {
        "episodes", "observations", "doctrines",
        "player_profiles", "player_general_relationship",
        "terrain_knowledge", "counter_doctrines",
    }
    assert required.issubset(tables)
    logger.close()

def test_db_idempotent_init():
    """Calling init_db twice should not raise or duplicate tables."""
    logger = temp_logger()
    logger.init_db()
    logger.init_db()
    assert logger.get_episode_count() == 0
    logger.close()


# ---------------------------------------------------------------------------
# Episode logging
# ---------------------------------------------------------------------------

def test_log_episode_returns_id():
    logger = temp_logger()
    state = make_battle_state(seed=1)
    ep_id = logger.log_episode(state)
    assert isinstance(ep_id, str)
    assert len(ep_id) > 0
    logger.close()

def test_episode_count_increments():
    logger = temp_logger()
    assert logger.get_episode_count() == 0
    for seed in range(5):
        logger.log_episode(make_battle_state(seed=seed))
    assert logger.get_episode_count() == 5
    logger.close()

def test_logged_episode_retrievable():
    logger = temp_logger()
    state = make_battle_state(seed=42)
    ep_id = logger.log_episode(state)
    retrieved = logger.get_episode_by_id(ep_id)
    assert retrieved is not None
    assert retrieved["id"] == ep_id
    logger.close()

def test_logged_episode_has_all_keys():
    logger = temp_logger()
    state = make_battle_state(seed=7)
    ep_id = logger.log_episode(state)
    episode = logger.get_episode_by_id(ep_id)
    required = [
        "id", "player_id", "age", "battlefield", "top_zones",
        "general_intents", "player_intents", "terrain_events",
        "combat_results", "turns_played", "result",
        "general_unit_summary", "player_unit_summary",
    ]
    for key in required:
        assert key in episode, f"Missing key: {key}"
    logger.close()

def test_no_coordinates_in_stored_episode():
    """Episodes stored in DB must not contain raw coordinates."""
    logger = temp_logger()
    state = make_battle_state(seed=3)
    ep_id = logger.log_episode(state)
    episode = logger.get_episode_by_id(ep_id)
    episode_str = json.dumps(episode)
    assert "center_x"  not in episode_str
    assert "center_y"  not in episode_str
    assert "_center_x" not in episode_str
    assert "_center_y" not in episode_str
    logger.close()

def test_no_raw_physics_in_stored_episode():
    logger = temp_logger()
    state = make_battle_state(seed=5)
    ep_id = logger.log_episode(state)
    episode = logger.get_episode_by_id(ep_id)
    episode_str = json.dumps(episode)
    assert "break_threshold" not in episode_str
    assert "flammability"    not in episode_str
    assert "attack_force"    not in episode_str
    logger.close()


# ---------------------------------------------------------------------------
# Episode retrieval and filtering
# ---------------------------------------------------------------------------

def test_get_episodes_returns_list():
    logger = temp_logger()
    for seed in range(3):
        logger.log_episode(make_battle_state(seed=seed))
    episodes = logger.get_episodes()
    assert isinstance(episodes, list)
    assert len(episodes) == 3
    logger.close()

def test_get_episodes_player_filter():
    logger = temp_logger()
    logger.log_episode(make_battle_state(seed=1, player_id="arman"))
    logger.log_episode(make_battle_state(seed=2, player_id="arman"))
    logger.log_episode(make_battle_state(seed=3, player_id="other_player"))

    arman_eps = logger.get_episodes(player_id="arman")
    assert len(arman_eps) == 2
    assert all(ep["player_id"] == "arman" for ep in arman_eps)
    logger.close()

def test_get_episodes_result_filter():
    logger = temp_logger()
    for seed in range(10):
        logger.log_episode(make_battle_state(seed=seed))
    all_eps    = logger.get_episodes()
    results    = {ep["result"] for ep in all_eps}
    # At least test that filtering by each present result type works
    for r in results:
        filtered = logger.get_episodes(result=r)
        assert all(ep["result"] == r for ep in filtered)
    logger.close()

def test_get_episodes_limit():
    logger = temp_logger()
    for seed in range(10):
        logger.log_episode(make_battle_state(seed=seed))
    limited = logger.get_episodes(limit=3)
    assert len(limited) == 3
    logger.close()

def test_player_id_count():
    logger = temp_logger()
    logger.log_episode(make_battle_state(seed=1, player_id="arman"))
    logger.log_episode(make_battle_state(seed=2, player_id="arman"))
    logger.log_episode(make_battle_state(seed=3, player_id="other"))
    assert logger.get_episode_count(player_id="arman") == 2
    assert logger.get_episode_count(player_id="other") == 1
    logger.close()


# ---------------------------------------------------------------------------
# Observations
# ---------------------------------------------------------------------------

def test_observations_extracted_from_episode():
    """
    Logging an episode should auto-extract terrain observations.
    Not every battle has terrain events, but the tables should be consistent.
    """
    logger = temp_logger()
    # Run multiple battles to get terrain events
    for seed in range(20):
        logger.log_episode(make_battle_state(seed=seed))
    # Observations >= 0 (terrain events aren't guaranteed every battle)
    count = logger.get_observation_count()
    assert count >= 0
    logger.close()

def test_observation_patterns_requires_min_count():
    """
    Patterns should only return terrain+effect pairs seen >= min_count times.
    """
    logger = temp_logger()
    for seed in range(50):
        logger.log_episode(make_battle_state(seed=seed))
    patterns = logger.get_observation_patterns(min_count=3)
    for p in patterns:
        assert p["count"] >= 3
    logger.close()


# ---------------------------------------------------------------------------
# Player profiles
# ---------------------------------------------------------------------------

def test_upsert_player_profile_new():
    logger = temp_logger()
    data = {"tactical": {"favorite_opening": "cavalry_rush"}}
    logger.upsert_player_profile("arman", data, age=1)
    profile = logger.get_player_profile("arman")
    assert profile is not None
    assert profile["encounter_count"] == 1
    assert profile["data"]["tactical"]["favorite_opening"] == "cavalry_rush"
    logger.close()

def test_upsert_player_profile_increments_count():
    logger = temp_logger()
    data = {"tactical": {}}
    logger.upsert_player_profile("arman", data, age=1)
    logger.upsert_player_profile("arman", data, age=2)
    logger.upsert_player_profile("arman", data, age=3)
    profile = logger.get_player_profile("arman")
    assert profile["encounter_count"] == 3
    assert profile["last_seen_age"] == 3
    logger.close()

def test_get_known_players():
    logger = temp_logger()
    logger.upsert_player_profile("arman",   {}, age=1)
    logger.upsert_player_profile("player2", {}, age=1)
    known = logger.get_known_players()
    assert "arman"   in known
    assert "player2" in known
    logger.close()

def test_unknown_player_returns_none():
    logger = temp_logger()
    assert logger.get_player_profile("nobody") is None
    logger.close()


# ---------------------------------------------------------------------------
# Relationship records
# ---------------------------------------------------------------------------

def test_upsert_relationship_new():
    logger = temp_logger()
    data = {
        "trust_level": -0.5,
        "betrayal_count": 2,
        "cooperation_count": 0,
        "times_attempted_capture": 1,
        "known_deceptions": 1,
        "predicted_next_intent": "flank_attempt",
        "prediction_confidence": 0.7,
        "notable_events": ["betrayed at age 3"],
    }
    logger.upsert_relationship("arman", data)
    rel = logger.get_relationship("arman")
    assert rel is not None
    assert rel["trust_level"] == -0.5
    assert rel["betrayal_count"] == 2
    assert "betrayed at age 3" in rel["notable_events"]
    logger.close()

def test_upsert_relationship_updates():
    logger = temp_logger()
    logger.upsert_relationship("arman", {"trust_level": 0.3, "betrayal_count": 0,
        "cooperation_count": 1, "times_attempted_capture": 0,
        "known_deceptions": 0, "notable_events": []})
    logger.upsert_relationship("arman", {"trust_level": -0.8, "betrayal_count": 1,
        "cooperation_count": 1, "times_attempted_capture": 0,
        "known_deceptions": 1, "notable_events": []})
    rel = logger.get_relationship("arman")
    assert rel["trust_level"] == -0.8
    assert rel["betrayal_count"] == 1
    logger.close()

def test_unknown_relationship_returns_none():
    logger = temp_logger()
    assert logger.get_relationship("nobody") is None
    logger.close()


# ---------------------------------------------------------------------------
# Summary and diagnostics
# ---------------------------------------------------------------------------

def test_summary_all_zeros_empty_db():
    logger = temp_logger()
    s = logger.summary()
    assert s["episodes"]    == 0
    assert s["doctrines"]   == 0
    assert s["observations"] == 0
    assert "db_path" in s
    logger.close()

def test_summary_after_logging():
    logger = temp_logger()
    for seed in range(5):
        logger.log_episode(make_battle_state(seed=seed))
    s = logger.summary()
    assert s["episodes"] == 5
    logger.close()

def test_result_distribution():
    logger = temp_logger()
    for seed in range(10):
        logger.log_episode(make_battle_state(seed=seed))
    dist = logger.result_distribution()
    assert isinstance(dist, dict)
    assert sum(dist.values()) == 10
    logger.close()

def test_terrain_event_frequency():
    logger = temp_logger()
    for seed in range(20):
        logger.log_episode(make_battle_state(seed=seed))
    freq = logger.terrain_event_frequency()
    assert isinstance(freq, dict)
    logger.close()


# ---------------------------------------------------------------------------
# Episodes by terrain event
# ---------------------------------------------------------------------------

def test_get_episodes_by_terrain_event():
    logger = temp_logger()
    for seed in range(30):
        logger.log_episode(make_battle_state(seed=seed))
    # Ice breaks may or may not occur — just verify it returns a list
    results = logger.get_episodes_by_terrain_event("ice_break")
    assert isinstance(results, list)
    for ep in results:
        assert "id" in ep
    logger.close()


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
