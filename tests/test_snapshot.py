"""
test_snapshot.py — Verify CommanderKnowledge and to_brain_snapshot().

Tests that the perception boundary holds:
  - No coordinates in CommanderKnowledge
  - No Unit objects
  - Enemy presence is aggregate-only (no unit type roster)
  - to_brain_snapshot() produces a valid CommanderKnowledge mid-battle
  - visible_terrain is strings only
"""

import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from simulator.snapshot import CommanderKnowledge
from simulator.grid import Grid
from simulator.units import UnitType, make_unit
from simulator.battle import BattleLoop


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_knowledge(
    server_id="srv_1",
    player_id="player_A",
    turn=5,
    weather="clear",
    battlefield_features=None,
    known_enemy_presence=None,
    known_friendly_state=None,
    visible_terrain=None,
    visible_events=None,
) -> CommanderKnowledge:
    return CommanderKnowledge(
        server_id            = server_id,
        player_id            = player_id,
        turn                 = turn,
        weather              = weather,
        battlefield_features = battlefield_features or {
            "has_frozen_lake": True,
            "has_river": False,
            "has_walls": False,
            "has_forest": True,
            "has_hazard": True,
        },
        known_enemy_presence = known_enemy_presence or {
            "count": 3, "avg_health": 0.8,
            "avg_morale": 0.7, "avg_supply": 0.9,
        },
        known_friendly_state = known_friendly_state or {
            "count": 3, "avg_health": 0.9,
            "avg_morale": 0.85, "avg_supply": 0.95,
            "has_siege": False, "has_cavalry": True,
        },
        visible_terrain       = visible_terrain or ["frozen_lake", "forest"],
        visible_events        = visible_events or [],
    )


def make_loop(seed=42):
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
    loop = BattleLoop(grid=grid, general_units=general_units,
                      player_units=player_units, seed=seed)
    # Run one turn so battlefield_features is populated
    loop.state.battlefield_features = loop.grid.battlefield_features()
    loop.turn = 1
    return loop


# ---------------------------------------------------------------------------
# CommanderKnowledge dataclass
# ---------------------------------------------------------------------------

def test_commander_knowledge_constructs():
    k = make_knowledge()
    assert k.server_id == "srv_1"
    assert k.player_id == "player_A"
    assert k.turn == 5


def test_commander_knowledge_has_all_required_fields():
    k = make_knowledge()
    required = {
        "server_id", "player_id", "turn", "weather",
        "battlefield_features", "known_enemy_presence",
        "known_friendly_state", "visible_terrain", "visible_events",
    }
    for field in required:
        assert hasattr(k, field), f"Missing field: {field}"


def test_visible_terrain_is_list_of_strings():
    k = make_knowledge(visible_terrain=["frozen_lake", "forest"])
    assert isinstance(k.visible_terrain, list)
    for item in k.visible_terrain:
        assert isinstance(item, str)


def test_no_coordinates_in_commander_knowledge():
    k = make_knowledge()
    coord_keys = {"x", "y", "position", "coordinate", "col", "row", "zone"}
    all_keys = (
        set(k.battlefield_features.keys())
        | set(k.known_enemy_presence.keys())
        | set(k.known_friendly_state.keys())
    )
    for key in all_keys:
        assert key.lower() not in coord_keys, (
            f"Coordinate-like key '{key}' found in CommanderKnowledge"
        )


def test_known_enemy_presence_has_no_unit_type_roster():
    """Enemy presence is aggregate only — no individual unit types."""
    k = make_knowledge()
    # Should have aggregate stats, not a roster
    allowed_keys = {"count", "avg_health", "avg_morale", "avg_supply"}
    for key in k.known_enemy_presence:
        assert key in allowed_keys, (
            f"Unexpected key '{key}' in known_enemy_presence — "
            f"no unit type roster allowed"
        )


def test_visible_events_defaults_to_empty_list():
    k = make_knowledge(visible_events=None)
    assert k.visible_events == []


def test_visible_terrain_defaults_to_empty_list():
    k = CommanderKnowledge(
        server_id="s", player_id="p", turn=1, weather="clear",
        battlefield_features={}, known_enemy_presence={},
        known_friendly_state={},
    )
    assert k.visible_terrain == []


# ---------------------------------------------------------------------------
# to_brain_snapshot() on BattleLoop
# ---------------------------------------------------------------------------

def test_to_brain_snapshot_returns_commander_knowledge():
    loop = make_loop()
    snap = loop.to_brain_snapshot("srv_1", "player_A")
    assert isinstance(snap, CommanderKnowledge)


def test_to_brain_snapshot_server_and_player_id():
    loop = make_loop()
    snap = loop.to_brain_snapshot("my_server", "hero_player")
    assert snap.server_id == "my_server"
    assert snap.player_id == "hero_player"


def test_to_brain_snapshot_visible_terrain_is_strings():
    loop = make_loop()
    snap = loop.to_brain_snapshot("srv_1", "player_A")
    for t in snap.visible_terrain:
        assert isinstance(t, str)


def test_to_brain_snapshot_no_coordinates():
    loop = make_loop()
    snap = loop.to_brain_snapshot("srv_1", "player_A")
    coord_keys = {"x", "y", "position", "coordinate", "col", "row"}
    all_keys = (
        set(snap.battlefield_features.keys())
        | set(snap.known_enemy_presence.keys())
        | set(snap.known_friendly_state.keys())
    )
    for key in all_keys:
        assert key.lower() not in coord_keys


def test_to_brain_snapshot_friendly_count_matches_alive():
    loop = make_loop()
    alive_count = sum(1 for u in loop.general_units if u.is_alive())
    snap = loop.to_brain_snapshot("srv_1", "player_A")
    assert snap.known_friendly_state["count"] == alive_count


def test_to_brain_snapshot_enemy_count_matches_alive():
    loop = make_loop()
    alive_count = sum(1 for u in loop.player_units if u.is_alive())
    snap = loop.to_brain_snapshot("srv_1", "player_A")
    assert snap.known_enemy_presence["count"] == alive_count


def test_to_brain_snapshot_has_hazard_derived_correctly():
    loop = make_loop()
    snap = loop.to_brain_snapshot("srv_1", "player_A")
    expected_hazard = (
        snap.battlefield_features.get("has_frozen_lake", False)
        or snap.battlefield_features.get("has_river", False)
    )
    assert snap.battlefield_features.get("has_hazard") == expected_hazard


def test_to_brain_snapshot_friendly_state_has_siege_flag():
    loop = make_loop()
    snap = loop.to_brain_snapshot("srv_1", "player_A")
    assert "has_siege" in snap.known_friendly_state


def test_to_brain_snapshot_friendly_state_has_cavalry_flag():
    loop = make_loop()
    snap = loop.to_brain_snapshot("srv_1", "player_A")
    assert "has_cavalry" in snap.known_friendly_state


def test_to_brain_snapshot_siege_flag_true_when_siege_present():
    grid = Grid(seed=42)
    general_units = [make_unit(UnitType.SIEGE, "general", (20, 75))]
    player_units  = [make_unit(UnitType.INFANTRY, "player", (20, 25))]
    loop = BattleLoop(grid=grid, general_units=general_units,
                      player_units=player_units, seed=42)
    loop.state.battlefield_features = loop.grid.battlefield_features()
    loop.turn = 1
    snap = loop.to_brain_snapshot("srv_1", "player_A")
    assert snap.known_friendly_state["has_siege"] is True


def test_to_brain_snapshot_cavalry_flag_false_when_no_cavalry():
    grid = Grid(seed=42)
    general_units = [make_unit(UnitType.INFANTRY, "general", (20, 75))]
    player_units  = [make_unit(UnitType.INFANTRY, "player", (20, 25))]
    loop = BattleLoop(grid=grid, general_units=general_units,
                      player_units=player_units, seed=42)
    loop.state.battlefield_features = loop.grid.battlefield_features()
    loop.turn = 1
    snap = loop.to_brain_snapshot("srv_1", "player_A")
    assert snap.known_friendly_state["has_cavalry"] is False
