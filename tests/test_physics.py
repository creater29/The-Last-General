"""
test_physics.py — Verify terrain event resolution and combat physics.
"""
import sys
sys.path.insert(0, "/Users/Arman/Projects/general_brain/src")

from simulator.grid import Grid, Cell, TerrainType
from simulator.units import Unit, UnitType, UnitGroup, make_unit, make_group
from simulator.physics import PhysicsEngine, TerrainEvent, CombatResult


def make_grid(seed=42) -> Grid:
    return Grid(100, 100, seed=seed)


# ---------------------------------------------------------------------------
# Ice break
# ---------------------------------------------------------------------------

def test_siege_breaks_ice_via_physics():
    grid = make_grid()
    engine = PhysicsEngine(grid)
    ice_cell = Cell(x=50, y=50, terrain=TerrainType.FROZEN_LAKE,
                    break_threshold=800.0, cascade=False)
    grid.cells[50][50] = ice_cell

    siege = make_unit(UnitType.SIEGE, "player_1", (49, 50))
    success, event = engine.resolve_movement(siege, ice_cell)

    assert success
    assert event is not None
    assert event.event_type == "ice_break"
    assert ice_cell.is_broken

def test_infantry_does_not_break_ice_via_physics():
    grid = make_grid()
    engine = PhysicsEngine(grid)
    ice_cell = Cell(x=50, y=50, terrain=TerrainType.FROZEN_LAKE,
                    break_threshold=800.0, cascade=False)
    grid.cells[50][50] = ice_cell

    inf = make_unit(UnitType.INFANTRY, "general", (49, 50))
    success, event = engine.resolve_movement(inf, ice_cell)

    assert success
    assert event is None
    assert not ice_cell.is_broken

def test_ice_breaker_takes_damage():
    grid = make_grid()
    engine = PhysicsEngine(grid)
    ice_cell = Cell(x=50, y=50, terrain=TerrainType.FROZEN_LAKE,
                    break_threshold=800.0, cascade=False)
    grid.cells[50][50] = ice_cell

    siege = make_unit(UnitType.SIEGE, "player_1", (49, 50))
    engine.resolve_movement(siege, ice_cell)
    assert siege.health < 1.0  # took damage falling through

def test_ice_cascade_logged():
    grid = make_grid()
    engine = PhysicsEngine(grid)

    # Place adjacent frozen lake cells
    for x in range(48, 53):
        cell = Cell(x=x, y=50, terrain=TerrainType.FROZEN_LAKE,
                    break_threshold=800.0, cascade=True)
        grid.cells[50][x] = cell

    siege = make_unit(UnitType.SIEGE, "player_1", (47, 50))
    success, event = engine.resolve_movement(siege, grid.cells[50][48])

    assert event is not None
    assert event.event_type == "ice_break"
    assert len(event.cascade_cells) > 0


# ---------------------------------------------------------------------------
# Wall collapse
# ---------------------------------------------------------------------------

def test_siege_collapses_wall():
    grid = make_grid()
    engine = PhysicsEngine(grid)
    wall_cell = Cell(x=40, y=40, terrain=TerrainType.WALL,
                     mobility_cost=float("inf"), stability=0.95,
                     break_threshold=float("inf"), is_broken=False)
    grid.cells[40][40] = wall_cell

    siege = make_unit(UnitType.SIEGE, "general", (39, 40))
    event = engine.resolve_siege_attack(siege, wall_cell)

    assert event is not None
    assert event.event_type == "wall_collapse"
    assert wall_cell.is_broken
    assert wall_cell.has_rubble
    assert wall_cell.mobility_cost < float("inf")  # now passable as rubble

def test_infantry_cannot_collapse_wall():
    grid = make_grid()
    engine = PhysicsEngine(grid)
    wall_cell = Cell(x=40, y=40, terrain=TerrainType.WALL,
                     mobility_cost=float("inf"), stability=0.95,
                     break_threshold=float("inf"), is_broken=False)
    grid.cells[40][40] = wall_cell

    inf = make_unit(UnitType.INFANTRY, "general", (39, 40))
    event = engine.resolve_siege_attack(inf, wall_cell)
    assert event is None
    assert not wall_cell.is_broken

def test_already_broken_wall_no_event():
    grid = make_grid()
    engine = PhysicsEngine(grid)
    wall_cell = Cell(x=40, y=40, terrain=TerrainType.WALL,
                     mobility_cost=1.8, is_broken=True, has_rubble=True)
    grid.cells[40][40] = wall_cell

    siege = make_unit(UnitType.SIEGE, "general", (39, 40))
    event = engine.resolve_siege_attack(siege, wall_cell)
    assert event is None


# ---------------------------------------------------------------------------
# Tree fall
# ---------------------------------------------------------------------------

def test_cavalry_charge_fells_trees():
    grid = make_grid()
    engine = PhysicsEngine(grid)
    forest_cell = Cell(x=30, y=30, terrain=TerrainType.FOREST,
                       mobility_cost=2.0, cover=0.7,
                       break_threshold=float("inf"))
    grid.cells[30][30] = forest_cell

    cav = make_unit(UnitType.CAVALRY, "player_1", (29, 30))
    # Cavalry attack_force=800N > tree_fall_force=500N
    event = engine.resolve_tree_fall(cav, forest_cell)

    assert event is not None
    assert event.event_type == "tree_fall"
    assert forest_cell.cover > 0.7    # cover increased
    assert forest_cell.mobility_cost > 2.0  # harder to move through

def test_archer_cannot_fell_trees():
    grid = make_grid()
    engine = PhysicsEngine(grid)
    forest_cell = Cell(x=30, y=30, terrain=TerrainType.FOREST,
                       mobility_cost=2.0, cover=0.7,
                       break_threshold=float("inf"))
    grid.cells[30][30] = forest_cell

    arc = make_unit(UnitType.ARCHER, "general", (29, 30))
    # Archer attack_force=50N < tree_fall_force=500N
    event = engine.resolve_tree_fall(arc, forest_cell)
    assert event is None


# ---------------------------------------------------------------------------
# Flood
# ---------------------------------------------------------------------------

def test_heavy_rain_floods_river():
    grid = make_grid()
    engine = PhysicsEngine(grid)
    river_cell = Cell(x=50, y=50, terrain=TerrainType.RIVER,
                      mobility_cost=3.5, break_threshold=float("inf"))
    plain_adj = Cell(x=51, y=50, terrain=TerrainType.PLAIN,
                     mobility_cost=1.0, break_threshold=float("inf"))
    grid.cells[50][50] = river_cell
    grid.cells[50][51] = plain_adj

    event = engine.resolve_flood(river_cell, weather="heavy_rain")

    assert event is not None
    assert event.event_type == "flood"
    assert river_cell.is_flooded

def test_clear_weather_no_flood():
    grid = make_grid()
    engine = PhysicsEngine(grid)
    river_cell = Cell(x=50, y=50, terrain=TerrainType.RIVER,
                      mobility_cost=3.5, break_threshold=float("inf"))
    grid.cells[50][50] = river_cell

    event = engine.resolve_flood(river_cell, weather="clear")
    assert event is None
    assert not river_cell.is_flooded


# ---------------------------------------------------------------------------
# Combat physics
# ---------------------------------------------------------------------------

def test_cavalry_damages_infantry():
    grid = make_grid()
    engine = PhysicsEngine(grid)
    plain_cell = Cell(x=50, y=50, terrain=TerrainType.PLAIN,
                      mobility_cost=1.0, cover=0.0,
                      break_threshold=float("inf"))
    grid.cells[50][50] = plain_cell

    cav = make_unit(UnitType.CAVALRY, "general", (49, 50))
    inf = make_unit(UnitType.INFANTRY, "player_1", (50, 50))

    result = engine.resolve_combat(cav, inf, plain_cell)

    assert result.damage_dealt > 0.0
    assert inf.health < 1.0
    assert result.attacker_type == "cavalry"
    assert result.defender_type == "infantry"

def test_cover_reduces_damage():
    grid = make_grid()
    engine = PhysicsEngine(grid)

    open_cell = Cell(x=50, y=50, terrain=TerrainType.PLAIN,
                     cover=0.0, mobility_cost=1.0,
                     break_threshold=float("inf"))
    cover_cell = Cell(x=51, y=50, terrain=TerrainType.FOREST,
                      cover=0.8, mobility_cost=2.0,
                      break_threshold=float("inf"))
    grid.cells[50][50] = open_cell
    grid.cells[50][51] = cover_cell

    cav1 = make_unit(UnitType.CAVALRY, "general", (49, 50))
    inf1 = make_unit(UnitType.INFANTRY, "player_1", (50, 50))
    cav2 = make_unit(UnitType.CAVALRY, "general", (49, 50))
    inf2 = make_unit(UnitType.INFANTRY, "player_1", (51, 50))

    result_open  = engine.resolve_combat(cav1, inf1, open_cell)
    result_cover = engine.resolve_combat(cav2, inf2, cover_cell)

    assert result_open.damage_dealt > result_cover.damage_dealt

def test_combat_observation_no_raw_stats():
    """to_observation() must not expose force values."""
    grid = make_grid()
    engine = PhysicsEngine(grid)
    plain_cell = Cell(x=50, y=50, terrain=TerrainType.PLAIN,
                      cover=0.0, mobility_cost=1.0,
                      break_threshold=float("inf"))
    grid.cells[50][50] = plain_cell

    cav = make_unit(UnitType.CAVALRY, "general", (49, 50))
    inf = make_unit(UnitType.INFANTRY, "player_1", (50, 50))
    result = engine.resolve_combat(cav, inf, plain_cell)
    obs = result.to_observation()

    assert "force_applied"  not in obs
    assert "damage_dealt"   not in obs
    assert "attacker_type"  in obs
    assert "outcome"        in obs

def test_siege_combat_collapses_wall():
    grid = make_grid()
    engine = PhysicsEngine(grid)
    wall_cell = Cell(x=40, y=40, terrain=TerrainType.WALL,
                     mobility_cost=float("inf"), cover=0.9,
                     break_threshold=float("inf"), is_broken=False)
    grid.cells[40][40] = wall_cell

    siege = make_unit(UnitType.SIEGE, "general", (39, 40))
    # For combat we need a defender on the wall
    def_inf = make_unit(UnitType.INFANTRY, "player_1", (40, 40))

    result = engine.resolve_combat(siege, def_inf, wall_cell)
    # Siege attacking into wall should trigger wall collapse event
    assert result.terrain_event is not None
    assert result.terrain_event.event_type == "wall_collapse"


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------

def test_blizzard_weakens_ice():
    grid = make_grid()
    engine = PhysicsEngine(grid)

    # Place a frozen lake
    ice_cell = Cell(x=50, y=50, terrain=TerrainType.FROZEN_LAKE,
                    break_threshold=800.0, cascade=False)
    grid.cells[50][50] = ice_cell

    units = [make_unit(UnitType.INFANTRY, "general", (10, 10))]
    engine.apply_weather("blizzard", units)

    assert ice_cell.break_threshold < 800.0  # blizzard made it more brittle

def test_blizzard_drains_supply():
    grid = make_grid()
    engine = PhysicsEngine(grid)
    unit = make_unit(UnitType.INFANTRY, "general", (10, 10))
    initial_supply = unit.supply
    engine.apply_weather("blizzard", [unit])
    assert unit.supply < initial_supply


# ---------------------------------------------------------------------------
# Event log and observation pipeline
# ---------------------------------------------------------------------------

def test_event_log_accumulates():
    grid = make_grid()
    engine = PhysicsEngine(grid)

    ice1 = Cell(x=50, y=50, terrain=TerrainType.FROZEN_LAKE,
                break_threshold=800.0, cascade=False)
    ice2 = Cell(x=60, y=60, terrain=TerrainType.FROZEN_LAKE,
                break_threshold=800.0, cascade=False)
    grid.cells[50][50] = ice1
    grid.cells[60][60] = ice2

    sig1 = make_unit(UnitType.SIEGE, "player_1", (49, 50))
    sig2 = make_unit(UnitType.SIEGE, "player_1", (59, 60))

    engine.resolve_movement(sig1, ice1)
    engine.resolve_movement(sig2, ice2)

    assert len(engine.event_log) == 2

def test_event_log_clears():
    grid = make_grid()
    engine = PhysicsEngine(grid)
    ice = Cell(x=50, y=50, terrain=TerrainType.FROZEN_LAKE,
               break_threshold=800.0, cascade=False)
    grid.cells[50][50] = ice
    sig = make_unit(UnitType.SIEGE, "player_1", (49, 50))
    engine.resolve_movement(sig, ice)
    assert len(engine.event_log) == 1

    engine.clear_log()
    assert len(engine.event_log) == 0

def test_get_event_summary_no_raw_physics():
    grid = make_grid()
    engine = PhysicsEngine(grid)
    ice = Cell(x=50, y=50, terrain=TerrainType.FROZEN_LAKE,
               break_threshold=800.0, cascade=False)
    grid.cells[50][50] = ice
    sig = make_unit(UnitType.SIEGE, "player_1", (49, 50))
    engine.resolve_movement(sig, ice)

    summary = engine.get_event_summary()
    assert len(summary) == 1
    obs = summary[0]
    # Observation must not contain raw physics
    assert "force_applied"    not in obs
    assert "break_threshold"  not in obs
    # Must contain military-relevant info
    assert "event_type"       in obs
    assert "triggered_by_type" in obs
    assert "casualties"       in obs


# ---------------------------------------------------------------------------
# Elevation modifier
# ---------------------------------------------------------------------------

def test_downhill_attack_bonus():
    grid = make_grid()
    engine = PhysicsEngine(grid)
    high = Cell(x=0, y=0, terrain=TerrainType.HILL, elevation=15.0,
                break_threshold=float("inf"))
    low  = Cell(x=1, y=0, terrain=TerrainType.PLAIN, elevation=0.0,
                break_threshold=float("inf"))

    mod = engine.elevation_modifier(high, low, UnitType.INFANTRY)
    assert mod > 1.0  # downhill attack bonus

def test_uphill_attack_penalty():
    grid = make_grid()
    engine = PhysicsEngine(grid)
    low  = Cell(x=0, y=0, terrain=TerrainType.PLAIN, elevation=0.0,
                break_threshold=float("inf"))
    high = Cell(x=1, y=0, terrain=TerrainType.HILL, elevation=15.0,
                break_threshold=float("inf"))

    mod = engine.elevation_modifier(low, high, UnitType.CAVALRY)
    assert mod < 1.0  # uphill penalty

def test_cavalry_penalized_more_uphill_than_infantry():
    grid = make_grid()
    engine = PhysicsEngine(grid)
    low  = Cell(x=0, y=0, terrain=TerrainType.PLAIN, elevation=0.0,
                break_threshold=float("inf"))
    high = Cell(x=1, y=0, terrain=TerrainType.HILL, elevation=15.0,
                break_threshold=float("inf"))

    mod_cav = engine.elevation_modifier(low, high, UnitType.CAVALRY)
    mod_inf = engine.elevation_modifier(low, high, UnitType.INFANTRY)
    assert mod_cav < mod_inf


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
