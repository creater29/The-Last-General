"""
test_battle.py — Verify battle loop, intent execution, end conditions.
"""
import sys
sys.path.insert(0, "/Users/Arman/Projects/general_brain/src")

from simulator.grid import Grid, TerrainType
from simulator.units import UnitType, make_unit, make_group
from simulator.battle import (
    BattleLoop, BattleState, TurnRecord,
    GeneralIntent, PlayerIntent,
    RECON_BASE_CONFIDENCE, RECON_THRESHOLD,
    RECON_WEATHER_PENALTY, RECON_OCCLUSION_SCALE,
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


def test_custom_player_intent_fn():
    """Player can be driven by external intent function, symmetric with
    general_intent_fn (Stage 3 completion exercise prerequisite,
    2026-09-04) — callback invoked once per turn, returned PlayerIntent
    values recorded in state.player_intents."""
    call_count = {"n": 0}

    def always_aggressive_rush(state: BattleState) -> PlayerIntent:
        call_count["n"] += 1
        return PlayerIntent.AGGRESSIVE_RUSH

    loop  = make_battle(seed=5)
    state = loop.run(player_intent_fn=always_aggressive_rush)
    assert call_count["n"] == state.turns_played
    assert all(i == "aggressive_rush" for i in state.player_intents)


def test_both_intent_fns_together():
    """Both callbacks can be supplied simultaneously, each driving its
    own side independently."""
    def always_defensive(state: BattleState) -> GeneralIntent:
        return GeneralIntent.DEFENSIVE_HOLD

    def always_defend(state: BattleState) -> PlayerIntent:
        return PlayerIntent.DEFEND

    loop  = make_battle(seed=5)
    state = loop.run(
        general_intent_fn=always_defensive,
        player_intent_fn=always_defend,
    )
    assert all(i == "defensive_hold" for i in state.general_intents)
    assert all(i == "defend"         for i in state.player_intents)


def test_no_player_intent_fn_preserves_existing_behavior():
    """Omitting player_intent_fn must produce identical behavior to before
    this parameter existed — same seed, same scripted distribution.
    Regression check: run the same seed twice, with and without an
    explicit None, and confirm identical player_intents sequences."""
    loop_a = make_battle(seed=7)
    state_a = loop_a.run()

    loop_b = make_battle(seed=7)
    state_b = loop_b.run(player_intent_fn=None)

    assert state_a.player_intents == state_b.player_intents
    assert state_a.result == state_b.result


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


# ---------------------------------------------------------------------------
# Reconnaissance / known_enemy_composition (Candidate E, E1)
# ---------------------------------------------------------------------------

def _nonforest_cell(grid):
    return next(
        c for c in (grid.get(x, y) for x in range(grid.width) for y in range(grid.height))
        if c and c.terrain != TerrainType.FOREST
    )


def _make_recon_loop(weather, enemy_cells, enemy_types=None):
    """Minimal BattleLoop with enemy (player) units placed on specific cells,
    to directly control the occlusion_fraction term of the reconnaissance
    formula. Uses the same grid seed as the rest of this file for determinism."""
    grid = Grid(seed=42)
    general_units = [make_unit(UnitType.CAVALRY, "general", (20, 75))]
    enemy_types = enemy_types or [UnitType.INFANTRY] * len(enemy_cells)
    player_units = [
        make_unit(t, "player", (c.x, c.y))
        for t, c in zip(enemy_types, enemy_cells)
    ]
    loop = BattleLoop(grid=grid, general_units=general_units,
                       player_units=player_units, seed=42)
    loop.state.battlefield_features = loop.grid.battlefield_features()
    loop.turn = 1
    loop.weather = weather
    return loop, grid


def test_known_enemy_composition_populated_in_clear_open_conditions():
    """Clear weather, 0 forest units: confidence = RECON_BASE_CONFIDENCE
    (0.6) -> fires."""
    grid = Grid(seed=42)
    loop, _ = _make_recon_loop("clear", [_nonforest_cell(grid)])
    snap = loop.to_brain_snapshot("srv_1", "player_A")
    assert snap.known_enemy_composition is not None
    assert snap.known_enemy_composition["confidence"] == RECON_BASE_CONFIDENCE
    assert "cavalry" in snap.known_enemy_composition
    assert "siege"   in snap.known_enemy_composition


def test_known_enemy_composition_populated_in_fog_open_conditions():
    """Fog, 0 forest units: confidence = RECON_BASE_CONFIDENCE +
    RECON_WEATHER_PENALTY['fog'] = 0.3 -> still fires (minimal but present
    confidence). Required worked example from the E1 spec — distinct from
    the blizzard case, which is the same shape but falls below threshold."""
    grid = Grid(seed=42)
    loop, _ = _make_recon_loop("fog", [_nonforest_cell(grid)])
    snap = loop.to_brain_snapshot("srv_1", "player_A")
    expected = RECON_BASE_CONFIDENCE + RECON_WEATHER_PENALTY["fog"]
    assert snap.known_enemy_composition is not None
    assert snap.known_enemy_composition["confidence"] == expected


def test_known_enemy_composition_none_when_blizzard_and_no_forest():
    """Blizzard, 0 forest units: confidence = RECON_BASE_CONFIDENCE +
    RECON_WEATHER_PENALTY['blizzard'] = 0.1 -> below RECON_THRESHOLD,
    stays None."""
    grid = Grid(seed=42)
    loop, _ = _make_recon_loop("blizzard", [_nonforest_cell(grid)])
    snap = loop.to_brain_snapshot("srv_1", "player_A")
    expected = RECON_BASE_CONFIDENCE + RECON_WEATHER_PENALTY["blizzard"]
    assert expected < RECON_THRESHOLD  # sanity-check the scenario itself
    assert snap.known_enemy_composition is None


def test_known_enemy_composition_none_when_all_units_in_forest_clear_weather():
    """Clear weather, all units in forest: confidence = RECON_BASE_CONFIDENCE
    - RECON_OCCLUSION_SCALE = 0.2 -> below RECON_THRESHOLD, stays None."""
    grid = Grid(seed=42)
    forest = grid.cells_of_type(TerrainType.FOREST)[0]
    loop, _ = _make_recon_loop("clear", [forest, forest])
    snap = loop.to_brain_snapshot("srv_1", "player_A")
    expected = RECON_BASE_CONFIDENCE - RECON_OCCLUSION_SCALE
    assert expected < RECON_THRESHOLD  # sanity-check the scenario itself
    assert snap.known_enemy_composition is None


def test_known_enemy_composition_fires_exactly_at_threshold():
    """Proves the comparison is `confidence >= RECON_THRESHOLD`, not a
    stricter `>` — the exact boundary case, not an approximation.
    7 of 8 enemy units in forest (occlusion_fraction = 0.875), clear
    weather: confidence = RECON_BASE_CONFIDENCE
    - RECON_OCCLUSION_SCALE * 0.875 = 0.25 = RECON_THRESHOLD exactly."""
    grid = Grid(seed=42)
    forest    = grid.cells_of_type(TerrainType.FOREST)[0]
    nonforest = _nonforest_cell(grid)
    occlusion_fraction = 7 / 8
    expected = round(
        RECON_BASE_CONFIDENCE - RECON_OCCLUSION_SCALE * occlusion_fraction, 3
    )
    assert expected == RECON_THRESHOLD  # sanity-check the scenario itself

    loop, _ = _make_recon_loop("clear", [forest] * 7 + [nonforest])
    snap = loop.to_brain_snapshot("srv_1", "player_A")
    assert snap.known_enemy_composition is not None
    assert snap.known_enemy_composition["confidence"] == RECON_THRESHOLD


def test_known_enemy_composition_confidence_gated_not_always_on():
    """Same seed/grid, different occlusion: half the enemy force in forest
    fires (confidence 0.4); all of it in forest does not (confidence 0.2).
    Proves the field is confidence-gated, not always-on."""
    grid = Grid(seed=42)
    forest    = grid.cells_of_type(TerrainType.FOREST)[0]
    nonforest = _nonforest_cell(grid)

    loop_half, _ = _make_recon_loop(
        "clear", [forest, nonforest], [UnitType.CAVALRY, UnitType.INFANTRY]
    )
    snap_half = loop_half.to_brain_snapshot("srv_1", "player_A")
    expected_half = round(RECON_BASE_CONFIDENCE - RECON_OCCLUSION_SCALE * 0.5, 3)
    assert snap_half.known_enemy_composition is not None
    assert snap_half.known_enemy_composition["confidence"] == expected_half

    loop_all_forest, _ = _make_recon_loop("clear", [forest, forest])
    snap_all_forest = loop_all_forest.to_brain_snapshot("srv_1", "player_A")
    assert snap_all_forest.known_enemy_composition is None


def test_known_enemy_composition_reflects_alive_enemy_cavalry():
    grid = Grid(seed=42)
    loop, _ = _make_recon_loop("clear", [_nonforest_cell(grid)], [UnitType.CAVALRY])
    snap = loop.to_brain_snapshot("srv_1", "player_A")
    assert snap.known_enemy_composition["cavalry"] is True
    assert snap.known_enemy_composition["siege"]   is False


def test_known_enemy_composition_reflects_alive_enemy_siege():
    """Positive siege case — the cavalry case above was the only unit-type
    coverage before this; siege needs its own direct assertion since it's
    a distinct boolean read from the same alive_enemy list."""
    grid = Grid(seed=42)
    loop, _ = _make_recon_loop("clear", [_nonforest_cell(grid)], [UnitType.SIEGE])
    snap = loop.to_brain_snapshot("srv_1", "player_A")
    assert snap.known_enemy_composition["siege"]   is True
    assert snap.known_enemy_composition["cavalry"] is False


def test_existing_snapshot_behavior_unaffected_by_known_enemy_composition():
    """Baseline regression check: a standard make_battle() snapshot still
    produces a valid CommanderKnowledge with the field present and typed
    correctly (None or dict) — existing snapshot behavior is untouched."""
    loop = make_battle()
    loop.state.battlefield_features = loop.grid.battlefield_features()
    loop.turn = 1
    snap = loop.to_brain_snapshot("srv_1", "player_A")
    assert snap.known_enemy_composition is None or isinstance(
        snap.known_enemy_composition, dict
    )


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
