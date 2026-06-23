"""
test_battle.py — Verify battle loop, intent execution, end conditions.
"""
import sys
sys.path.insert(0, "/Users/Arman/Projects/general_brain/src")

from simulator.grid import Grid
from simulator.units import UnitType, make_unit, make_group
from simulator.battle import (
    BattleLoop, BattleState, TurnRecord,
    GeneralIntent, PlayerIntent
)


def make_battle(seed=42, g_comp=None, p_comp=None):
    grid = Grid(100, 100, seed=seed)
    g_comp = g_comp or {UnitType.INFANTRY: 5, UnitType.CAVALRY: 2}
    p_comp = p_comp or {UnitType.INFANTRY: 5, UnitType.CAVALRY: 2}

    general_units = []
    for utype, count in g_comp.items():
        for _ in range(count):
            general_units.append(make_unit(utype, "general", (50, 70)))

    player_units = []
    for utype, count in p_comp.items():
        for _ in range(count):
            player_units.append(make_unit(utype, "player_1", (50, 30)))

    return BattleLoop(
        grid=grid,
        general_units=general_units,
        player_units=player_units,
        player_id="player_1",
        age=1,
        seed=seed,
    )


# ---------------------------------------------------------------------------
# Battle runs to completion
# ---------------------------------------------------------------------------

def test_battle_runs_to_completion():
    loop = make_battle()
    state = loop.run()
    assert state.result in ("win", "loss", "draw", "retreat", "max_turns")
    assert state.turns_played > 0

def test_battle_does_not_exceed_max_turns():
    loop = make_battle()
    state = loop.run()
    assert state.turns_played <= BattleLoop.MAX_TURNS

def test_battle_records_turns():
    loop = make_battle()
    state = loop.run()
    assert len(state.turn_records) == state.turns_played
    assert len(state.general_intents) == state.turns_played
    assert len(state.player_intents) == state.turns_played

def test_battle_result_consistent_with_survivors():
    loop = make_battle(seed=7)
    state = loop.run()
    alive_general = [u for u in state.general_units if u.is_alive()]
    alive_player  = [u for u in state.player_units  if u.is_alive()]

    if state.result == "win":
        # General won — player should have fewer or no survivors
        assert len(alive_general) >= len(alive_player) or state.turns_played >= BattleLoop.MAX_TURNS
    elif state.result == "loss":
        assert len(alive_player) >= len(alive_general) or state.turns_played >= BattleLoop.MAX_TURNS


# ---------------------------------------------------------------------------
# Turn records
# ---------------------------------------------------------------------------

def test_turn_record_has_required_fields():
    loop = make_battle()
    state = loop.run()
    for record in state.turn_records:
        assert record.turn_number >= 1
        assert record.weather in ["clear", "fog", "heavy_rain", "blizzard", "wind"]
        assert record.general_intent in [i.value for i in GeneralIntent]
        assert record.player_intent  in [i.value for i in PlayerIntent]
        assert isinstance(record.terrain_events, list)
        assert isinstance(record.combat_results, list)
        assert isinstance(record.general_losses, float)
        assert isinstance(record.player_losses, float)
        assert "general" in record.supply_states
        assert "player"  in record.supply_states

def test_turn_numbers_sequential():
    loop = make_battle()
    state = loop.run()
    for i, record in enumerate(state.turn_records):
        assert record.turn_number == i + 1


# ---------------------------------------------------------------------------
# Intent execution — each intent runs without error
# ---------------------------------------------------------------------------

def _run_single_intent(intent: GeneralIntent, seed=1):
    loop = make_battle(seed=seed)
    loop.state.battlefield_features = loop.grid.battlefield_features()
    loop.state.top_military_zones   = loop.grid.top_military_zones(5)
    loop.turn = 1
    loop.weather = "clear"
    results = loop._execute_general_intent(intent)
    assert isinstance(results, list)

def test_intent_aggressive_push():
    _run_single_intent(GeneralIntent.AGGRESSIVE_PUSH)

def test_intent_flank_attempt():
    _run_single_intent(GeneralIntent.FLANK_ATTEMPT)

def test_intent_terrain_exploit():
    _run_single_intent(GeneralIntent.TERRAIN_EXPLOIT)

def test_intent_siege():
    # Need siege units for this
    loop = make_battle(seed=1, g_comp={UnitType.SIEGE: 1, UnitType.INFANTRY: 3})
    loop.state.battlefield_features = loop.grid.battlefield_features()
    loop.state.top_military_zones   = loop.grid.top_military_zones(5)
    results = loop._execute_general_intent(GeneralIntent.SIEGE)
    assert isinstance(results, list)

def test_intent_ambush():
    _run_single_intent(GeneralIntent.AMBUSH)

def test_intent_supply_raid():
    _run_single_intent(GeneralIntent.SUPPLY_RAID)

def test_intent_retreat():
    _run_single_intent(GeneralIntent.RETREAT)

def test_intent_defensive_hold():
    _run_single_intent(GeneralIntent.DEFENSIVE_HOLD)


# ---------------------------------------------------------------------------
# Episode output — the thing the brain consumes
# ---------------------------------------------------------------------------

def test_to_episode_structure():
    loop = make_battle()
    state = loop.run()
    episode = state.to_episode()

    required = [
        "id", "player_id", "age", "battlefield",
        "top_zones", "general_intents", "player_intents",
        "terrain_events", "combat_results",
        "turns_played", "result",
        "general_unit_summary", "player_unit_summary",
    ]
    for key in required:
        assert key in episode, f"Missing key: {key}"

def test_episode_no_raw_physics():
    """Episode must not contain raw physics constants."""
    loop = make_battle()
    state = loop.run()
    episode = state.to_episode()

    import json
    episode_str = json.dumps(episode)
    # These raw physics values must NOT appear in episode
    assert "break_threshold" not in episode_str
    assert "flammability"    not in episode_str
    assert "attack_force"    not in episode_str

def test_episode_intents_are_strings():
    loop = make_battle()
    state = loop.run()
    episode = state.to_episode()
    for intent in episode["general_intents"]:
        assert isinstance(intent, str)
    for intent in episode["player_intents"]:
        assert isinstance(intent, str)

def test_unit_summary_loss_rate():
    loop = make_battle(seed=99)
    state = loop.run()
    episode = state.to_episode()
    summary = episode["general_unit_summary"]
    assert 0.0 <= summary["loss_rate"] <= 1.0
    assert 0.0 <= summary["avg_health"] <= 1.0
    assert 0.0 <= summary["avg_supply"] <= 1.0

def test_battlefield_features_in_episode():
    loop = make_battle()
    state = loop.run()
    episode = state.to_episode()
    bf = episode["battlefield"]
    assert "terrain_distribution" in bf
    assert "dominant_terrain"     in bf
    assert "has_frozen_lake"      in bf

def test_top_zones_in_episode():
    loop = make_battle()
    state = loop.run()
    episode = state.to_episode()
    zones = episode["top_zones"]
    assert isinstance(zones, list)
    for zone in zones:
        assert "zone_type"      in zone
        assert "military_value" in zone
        # Coordinates must NOT reach the brain
        assert "center_x"  not in zone
        assert "center_y"  not in zone
        assert "_center_x" not in zone
        assert "_center_y" not in zone


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_same_seed_same_result():
    loop1 = make_battle(seed=42)
    loop2 = make_battle(seed=42)
    state1 = loop1.run()
    state2 = loop2.run()
    assert state1.result       == state2.result
    assert state1.turns_played == state2.turns_played

def test_different_seed_may_differ():
    loop1 = make_battle(seed=1)
    loop2 = make_battle(seed=999)
    state1 = loop1.run()
    state2 = loop2.run()
    # Not guaranteed to differ but seeds are far apart enough they usually do
    # Just verify both complete
    assert state1.result is not None
    assert state2.result is not None


# ---------------------------------------------------------------------------
# Custom intent function
# ---------------------------------------------------------------------------

def test_custom_intent_fn():
    """General can be driven by external intent function."""
    call_count = {"n": 0}

    def always_aggressive(state: BattleState) -> GeneralIntent:
        call_count["n"] += 1
        return GeneralIntent.AGGRESSIVE_PUSH

    loop  = make_battle(seed=5)
    state = loop.run(general_intent_fn=always_aggressive)
    assert call_count["n"] == state.turns_played
    assert all(i == "aggressive_push" for i in state.general_intents)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_battle_with_only_siege_units():
    loop = make_battle(
        seed=3,
        g_comp={UnitType.SIEGE: 2},
        p_comp={UnitType.SIEGE: 2},
    )
    state = loop.run()
    assert state.result in ("win", "loss", "draw", "max_turns")

def test_battle_general_outnumbered():
    loop = make_battle(
        seed=10,
        g_comp={UnitType.INFANTRY: 2},
        p_comp={UnitType.INFANTRY: 8, UnitType.CAVALRY: 3},
    )
    state = loop.run()
    # Likely a loss but should complete cleanly
    assert state.result in ("win", "loss", "draw", "max_turns")

def test_multi_battle_accumulation():
    """Run 10 battles — no errors, results vary."""
    results = set()
    for seed in range(10):
        loop  = make_battle(seed=seed)
        state = loop.run()
        results.add(state.result)
    # Should see multiple different outcomes across 10 battles
    assert len(results) >= 2


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
