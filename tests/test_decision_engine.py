"""
test_decision_engine.py — Verify the General's reasoning pipeline.

Tests cover:
  - Import constraint (Rule 3 extended)
  - Situation filter: impossible intents eliminated with reasons
  - Doctrine evaluation: high-confidence doctrines boost relevant intents
  - Player adaptation: aggressive player → counter-aggressive intent boosted
  - Situation fit: weather, health, turn effects
  - Output structure: all required keys present
  - confidence in [0, 1]
  - choose_intent() returns valid intent string
  - Fallback to DEFENSIVE_HOLD when knowledge insufficient
  - No coordinates in any output
  - Idempotency: same knowledge → same decision
"""

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from simulator.logger import EpisodeLogger
from simulator.snapshot import CommanderKnowledge
from brain.world_model import WorldModel
from brain.doctrine_extractor import DoctrineExtractor
from brain.player_profiler import PlayerProfiler
from brain.decision_engine import (
    DecisionEngine, ALL_INTENTS, FALLBACK_INTENT,
    _filter_intents, _doctrine_factor, _player_factor, _situation_factor,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def temp_logger() -> EpisodeLogger:
    tmp = tempfile.mktemp(suffix=".db")
    return EpisodeLogger(db_path=Path(tmp))


def make_engine(logger: EpisodeLogger) -> DecisionEngine:
    wm = WorldModel(logger)
    wm.update_from_observations()
    de = DoctrineExtractor(logger, wm)
    de.extract_doctrines()
    pp = PlayerProfiler(logger)
    return DecisionEngine(logger, wm, de, pp)


def seed_observations(logger, terrain_context, observed_effect, count,
                      episode_id="test_ep"):
    timestamp = datetime.now(timezone.utc).isoformat()
    conn = logger._get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO episodes "
        "(id, timestamp, player_id, age, result, turns_played, data) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (episode_id, timestamp, "test_player", 1, "win", 10, "{}"),
    )
    tag = f"{terrain_context}_{observed_effect}".replace("+", "_")
    for i in range(count):
        conn.execute(
            "INSERT OR IGNORE INTO observations "
            "(id, episode_id, timestamp, terrain_context, action_taken, "
            "observed_effect, confidence, last_verified, decay_rate) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (f"{tag}_{i:05d}", episode_id, timestamp, terrain_context,
             "charge", observed_effect, 1.0, timestamp, 0.01),
        )
    conn.commit()


def seed_profile(logger, player_id, aggression=0.5, adaptability=0.5,
                 server_id="srv_1", total_battles=5, win_count=2):
    logger.upsert_player_profile(
        server_id=server_id, player_id=player_id,
        first_seen="2026-01-01T00:00:00+00:00",
        last_seen="2026-01-01T00:00:00+00:00",
        total_battles=total_battles,
        win_count=win_count, loss_count=total_battles - win_count, draw_count=0,
        preferred_units={}, terrain_tendencies={},
        aggression_index=aggression, adaptability_score=adaptability,
        raw_data={"intent_counts": {}, "strategy_switches": 0,
                  "loss_recoveries": 0, "unit_usage": {}, "terrain_stats": {}},
    )


def make_knowledge(
    server_id="srv_1", player_id="player_A",
    weather="clear", turn=5,
    has_frozen_lake=False, has_river=False,
    has_walls=False, has_forest=False,
    has_siege=False, has_cavalry=True,
    enemy_count=3, friendly_health=0.9,
) -> CommanderKnowledge:
    has_hazard = has_frozen_lake or has_river
    visible = []
    if has_frozen_lake: visible.append("frozen_lake")
    if has_river:       visible.append("river")
    if has_walls:       visible.append("wall")
    if has_forest:      visible.append("forest")
    return CommanderKnowledge(
        server_id=server_id, player_id=player_id,
        turn=turn, weather=weather,
        battlefield_features={
            "has_frozen_lake": has_frozen_lake,
            "has_river":       has_river,
            "has_walls":       has_walls,
            "has_forest":      has_forest,
            "has_hazard":      has_hazard,
        },
        known_enemy_presence={
            "count": enemy_count, "avg_health": 0.8,
            "avg_morale": 0.7, "avg_supply": 0.9,
        },
        known_friendly_state={
            "count": 3, "avg_health": friendly_health,
            "avg_morale": 0.85, "avg_supply": 0.95,
            "has_siege": has_siege, "has_cavalry": has_cavalry,
        },
        visible_terrain=visible,
        visible_events=[],
    )


# ---------------------------------------------------------------------------
# Rule 3: import constraint
# ---------------------------------------------------------------------------

def test_no_forbidden_imports_in_decision_engine():
    src = (_PROJECT_ROOT / "src" / "brain" / "decision_engine.py").read_text()
    forbidden = [
        "from simulator.grid",   "import simulator.grid",
        "from simulator.units",  "import simulator.units",
        "from simulator.physics","import simulator.physics",
        "from simulator.battle", "import simulator.battle",
    ]
    for token in forbidden:
        assert token not in src, f"Forbidden import: '{token}'"


def test_snapshot_import_is_permitted():
    src = (_PROJECT_ROOT / "src" / "brain" / "decision_engine.py").read_text()
    assert "from simulator.snapshot import CommanderKnowledge" in src


# ---------------------------------------------------------------------------
# Situation filter — impossible intents
# ---------------------------------------------------------------------------

def test_siege_filtered_when_no_walls():
    k = make_knowledge(has_walls=False)
    available, rejected = _filter_intents(k)
    assert "SIEGE" not in available
    assert any("SIEGE" in r for r in rejected)


def test_siege_filtered_when_walls_but_no_siege_units():
    k = make_knowledge(has_walls=True, has_siege=False)
    available, rejected = _filter_intents(k)
    assert "SIEGE" not in available


def test_siege_available_when_walls_and_siege_units():
    k = make_knowledge(has_walls=True, has_siege=True)
    available, _ = _filter_intents(k)
    assert "SIEGE" in available


def test_terrain_exploit_filtered_when_no_hazard():
    k = make_knowledge(has_frozen_lake=False, has_river=False)
    available, rejected = _filter_intents(k)
    assert "TERRAIN_EXPLOIT" not in available
    assert any("TERRAIN_EXPLOIT" in r for r in rejected)


def test_terrain_exploit_available_when_frozen_lake_present():
    k = make_knowledge(has_frozen_lake=True)
    available, _ = _filter_intents(k)
    assert "TERRAIN_EXPLOIT" in available


def test_terrain_exploit_available_when_river_present():
    k = make_knowledge(has_river=True)
    available, _ = _filter_intents(k)
    assert "TERRAIN_EXPLOIT" in available


def test_ambush_filtered_when_no_forest():
    k = make_knowledge(has_forest=False)
    available, rejected = _filter_intents(k)
    assert "AMBUSH" not in available
    assert any("AMBUSH" in r for r in rejected)


def test_ambush_available_when_forest_present():
    k = make_knowledge(has_forest=True)
    available, _ = _filter_intents(k)
    assert "AMBUSH" in available


def test_always_at_least_one_intent_available():
    k = make_knowledge(has_frozen_lake=False, has_river=False,
                       has_walls=False, has_forest=False)
    available, _ = _filter_intents(k)
    assert len(available) >= 1


def test_fallback_guaranteed_when_all_filtered():
    """If everything is filtered, DEFENSIVE_HOLD must survive."""
    k = make_knowledge()
    available, _ = _filter_intents(k)
    # DEFENSIVE_HOLD has no prerequisites — always available
    assert FALLBACK_INTENT in available


def test_rejected_list_contains_reasons():
    k = make_knowledge(has_walls=False, has_frozen_lake=False,
                       has_river=False, has_forest=False)
    _, rejected = _filter_intents(k)
    assert len(rejected) >= 2
    for reason in rejected:
        assert ":" in reason   # format: "INTENT: reason"


# ---------------------------------------------------------------------------
# Doctrine factor
# ---------------------------------------------------------------------------

def test_doctrine_factor_neutral_when_no_doctrine():
    factor, notes = _doctrine_factor("AGGRESSIVE_PUSH", [], make_knowledge())
    assert factor == 1.0
    assert notes == []


def test_doctrine_factor_above_one_when_relevant_doctrine():
    doctrine = {
        "condition": "frozen_lake+cavalry",
        "learned_effect": "ice_break",
        "confidence": 0.9,
        "derived_principle": "Heavy cavalry on frozen lakes risks ice breakage.",
    }
    k = make_knowledge(has_frozen_lake=True)
    factor, notes = _doctrine_factor("TERRAIN_EXPLOIT", [doctrine], k)
    assert factor > 1.0
    assert len(notes) > 0


def test_doctrine_factor_not_applied_when_terrain_not_visible():
    """Doctrine for frozen_lake is irrelevant if frozen_lake not on battlefield."""
    doctrine = {
        "condition": "frozen_lake+cavalry",
        "learned_effect": "ice_break",
        "confidence": 0.95,
        "derived_principle": "Test.",
    }
    k = make_knowledge(has_frozen_lake=False)  # frozen_lake not visible
    factor, _ = _doctrine_factor("TERRAIN_EXPLOIT", [doctrine], k)
    assert factor == 1.0


def test_doctrine_factor_uses_highest_confidence():
    """When multiple relevant doctrines exist, highest confidence wins."""
    d1 = {"condition": "frozen_lake+cavalry", "learned_effect": "ice_break",
          "confidence": 0.7, "derived_principle": "Low."}
    d2 = {"condition": "frozen_lake+siege", "learned_effect": "ice_break",
          "confidence": 0.95, "derived_principle": "High."}
    k = make_knowledge(has_frozen_lake=True)
    factor_both, _ = _doctrine_factor("TERRAIN_EXPLOIT", [d1, d2], k)
    factor_low,  _ = _doctrine_factor("TERRAIN_EXPLOIT", [d1],      k)
    assert factor_both >= factor_low


# ---------------------------------------------------------------------------
# Player adaptation factor
# ---------------------------------------------------------------------------

def test_player_factor_neutral_when_no_profile():
    factor, notes = _player_factor("AGGRESSIVE_PUSH", None, make_knowledge())
    assert factor == 1.0
    assert "No player profile" in notes[0]


def test_player_factor_boosts_counter_against_aggressive_player():
    profile = {"aggression_index": 0.85, "adaptability_score": 0.5,
               "terrain_tendencies": {}}
    k = make_knowledge()
    factor_counter, _ = _player_factor("DEFENSIVE_HOLD", profile, k)
    factor_attack,  _ = _player_factor("AGGRESSIVE_PUSH", profile, k)
    assert factor_counter > 1.0
    assert factor_attack  < 1.0


def test_player_factor_neutral_against_average_aggression():
    profile = {"aggression_index": 0.5, "adaptability_score": 0.5,
               "terrain_tendencies": {}}
    factor, _ = _player_factor("AGGRESSIVE_PUSH", profile, make_knowledge())
    assert factor == 1.0


def test_player_factor_terrain_weakness_boosts_exploit():
    profile = {
        "aggression_index": 0.5,
        "adaptability_score": 0.5,
        "terrain_tendencies": {
            "river": {"count": 5, "wins": 1, "losses": 4}  # 20% win rate
        },
    }
    k = make_knowledge(has_river=True)
    factor, notes = _player_factor("TERRAIN_EXPLOIT", profile, k)
    assert factor > 1.0
    assert any("river" in n.lower() for n in notes)


# ---------------------------------------------------------------------------
# Situation factor
# ---------------------------------------------------------------------------

def test_situation_factor_fog_boosts_ambush():
    k = make_knowledge(weather="fog", has_forest=True)
    factor, notes = _situation_factor("AMBUSH", k)
    assert factor > 1.0
    assert any("fog" in n.lower() or "ambush" in n.lower() for n in notes)


def test_situation_factor_fog_penalises_aggressive_push():
    k = make_knowledge(weather="fog")
    factor, notes = _situation_factor("AGGRESSIVE_PUSH", k)
    assert factor < 1.0


def test_situation_factor_blizzard_penalises_offensive():
    k = make_knowledge(weather="blizzard")
    factor_att, _ = _situation_factor("AGGRESSIVE_PUSH",  k)
    factor_def, _ = _situation_factor("DEFENSIVE_HOLD",   k)
    assert factor_att < 1.0
    assert factor_def > 1.0


def test_situation_factor_heavy_rain_boosts_river_exploit():
    k = make_knowledge(weather="heavy_rain", has_river=True)
    factor, notes = _situation_factor("TERRAIN_EXPLOIT", k)
    assert factor > 1.0
    assert any("river" in n.lower() or "rain" in n.lower() for n in notes)


def test_situation_factor_critical_health_boosts_retreat():
    k = make_knowledge(friendly_health=0.15)
    factor, notes = _situation_factor("RETREAT", k)
    assert factor > 1.0
    assert any("health" in n.lower() or "retreat" in n.lower() for n in notes)


def test_situation_factor_critical_health_penalises_attack():
    k = make_knowledge(friendly_health=0.15)
    factor, _ = _situation_factor("AGGRESSIVE_PUSH", k)
    assert factor < 1.0


def test_situation_factor_neutral_weather_no_strong_effect():
    k = make_knowledge(weather="clear", friendly_health=0.9)
    factor, _ = _situation_factor("AGGRESSIVE_PUSH", k)
    # Clear weather, healthy forces — no strong penalty or boost
    assert 0.7 <= factor <= 1.3


# ---------------------------------------------------------------------------
# Full decide() output
# ---------------------------------------------------------------------------

def test_decide_returns_required_keys():
    logger = temp_logger()
    engine = make_engine(logger)
    k = make_knowledge()
    result = engine.decide(k)
    required = {
        "intent", "confidence", "reasoning",
        "rejected", "alternatives", "doctrines_consulted", "profile_used",
    }
    assert required.issubset(result.keys())
    logger.close()


def test_decide_intent_is_valid():
    logger = temp_logger()
    engine = make_engine(logger)
    result = engine.decide(make_knowledge())
    assert result["intent"] in ALL_INTENTS
    logger.close()


def test_decide_confidence_in_range():
    logger = temp_logger()
    engine = make_engine(logger)
    result = engine.decide(make_knowledge())
    assert 0.0 <= result["confidence"] <= 1.0
    logger.close()


def test_decide_reasoning_is_non_empty_list():
    logger = temp_logger()
    engine = make_engine(logger)
    result = engine.decide(make_knowledge())
    assert isinstance(result["reasoning"], list)
    assert len(result["reasoning"]) >= 1
    logger.close()


def test_decide_rejected_contains_filtered_intents():
    logger = temp_logger()
    engine = make_engine(logger)
    # No walls, no hazard, no forest → SIEGE, TERRAIN_EXPLOIT, AMBUSH rejected
    k = make_knowledge(has_walls=False, has_frozen_lake=False,
                       has_river=False, has_forest=False)
    result = engine.decide(k)
    rejected_str = " ".join(result["rejected"])
    assert "SIEGE" in rejected_str
    assert "TERRAIN_EXPLOIT" in rejected_str
    assert "AMBUSH" in rejected_str
    logger.close()


def test_decide_alternatives_are_top_runners_up():
    logger = temp_logger()
    engine = make_engine(logger)
    result = engine.decide(make_knowledge())
    assert isinstance(result["alternatives"], list)
    for alt in result["alternatives"]:
        assert len(alt) == 2
        intent, conf = alt
        assert intent in ALL_INTENTS
        assert 0.0 <= conf <= 1.0
    logger.close()


def test_decide_profile_used_false_when_no_profile():
    logger = temp_logger()
    engine = make_engine(logger)
    k = make_knowledge(player_id="unknown_player")
    result = engine.decide(k)
    assert result["profile_used"] is False
    logger.close()


def test_decide_profile_used_true_when_profile_exists():
    logger = temp_logger()
    seed_profile(logger, "player_A", server_id="srv_1")
    engine = make_engine(logger)
    k = make_knowledge(server_id="srv_1", player_id="player_A")
    result = engine.decide(k)
    assert result["profile_used"] is True
    logger.close()


def test_decide_terrain_exploit_chosen_on_frozen_lake_with_doctrine():
    """
    High-confidence ice_break doctrine + frozen lake on field →
    TERRAIN_EXPLOIT should rank highest or be among top 2.
    """
    logger = temp_logger()
    seed_observations(logger, "frozen_lake+cavalry", "ice_break", 50,
                      episode_id="ep_ice")
    engine = make_engine(logger)
    k = make_knowledge(has_frozen_lake=True, weather="blizzard")
    result = engine.decide(k)
    top_intents = [result["intent"]] + [a[0] for a in result["alternatives"]]
    assert "TERRAIN_EXPLOIT" in top_intents, (
        f"Expected TERRAIN_EXPLOIT in top intents, got: {top_intents}"
    )
    logger.close()


def test_decide_defensive_hold_when_aggressive_player_no_terrain():
    """
    High aggression player + no special terrain →
    DEFENSIVE_HOLD or AMBUSH should rank highly.
    """
    logger = temp_logger()
    seed_profile(logger, "player_A", aggression=0.9, server_id="srv_1")
    engine = make_engine(logger)
    k = make_knowledge(has_frozen_lake=False, has_river=False,
                       has_walls=False, has_forest=False,
                       server_id="srv_1", player_id="player_A")
    result = engine.decide(k)
    top_intents = [result["intent"]] + [a[0] for a in result["alternatives"]]
    counter_intents = {"DEFENSIVE_HOLD", "TERRAIN_EXPLOIT"}
    assert any(i in counter_intents for i in top_intents)
    logger.close()


def test_decide_retreat_chosen_at_critical_health():
    """At 10% health, RETREAT should be the chosen intent."""
    logger = temp_logger()
    engine = make_engine(logger)
    k = make_knowledge(friendly_health=0.10, weather="clear")
    result = engine.decide(k)
    assert result["intent"] == "RETREAT", (
        f"Expected RETREAT at critical health, got: {result['intent']}"
    )
    logger.close()


def test_decide_no_coordinates_in_output():
    logger = temp_logger()
    engine = make_engine(logger)
    result = engine.decide(make_knowledge())
    coord_keys = {"x", "y", "position", "coordinate", "zone"}
    for key in result:
        assert key.lower() not in coord_keys
    logger.close()


def test_decide_is_deterministic():
    """Same knowledge → same intent on repeated calls."""
    logger = temp_logger()
    engine = make_engine(logger)
    k = make_knowledge(has_frozen_lake=True, weather="blizzard")
    result1 = engine.decide(k)
    result2 = engine.decide(k)
    assert result1["intent"] == result2["intent"]
    assert result1["confidence"] == result2["confidence"]
    logger.close()


# ---------------------------------------------------------------------------
# choose_intent()
# ---------------------------------------------------------------------------

def test_choose_intent_returns_string():
    logger = temp_logger()
    engine = make_engine(logger)
    intent = engine.choose_intent(make_knowledge())
    assert isinstance(intent, str)
    logger.close()


def test_choose_intent_returns_valid_intent():
    logger = temp_logger()
    engine = make_engine(logger)
    intent = engine.choose_intent(make_knowledge())
    assert intent in ALL_INTENTS
    logger.close()


def test_choose_intent_matches_decide_intent():
    logger = temp_logger()
    engine = make_engine(logger)
    k = make_knowledge(has_frozen_lake=True)
    assert engine.choose_intent(k) == engine.decide(k)["intent"]
    logger.close()
