"""
test_units.py — Verify unit behavior, terrain interaction, group mechanics.
"""
import sys
sys.path.insert(0, "/Users/Arman/Projects/general_brain/src")

from simulator.grid import Grid, Cell, TerrainType
from simulator.units import (
    Unit, UnitGroup, UnitType, UNIT_BASE_STATS,
    make_unit, make_group
)


# ---------------------------------------------------------------------------
# Unit base stats
# ---------------------------------------------------------------------------

def test_unit_mass_values():
    """Mass values must match physics constants exactly."""
    inf = make_unit(UnitType.INFANTRY, "general", (0, 0))
    cav = make_unit(UnitType.CAVALRY,  "general", (0, 0))
    arc = make_unit(UnitType.ARCHER,   "general", (0, 0))
    sig = make_unit(UnitType.SIEGE,    "general", (0, 0))

    assert inf.mass ==   80.0
    assert cav.mass ==  600.0
    assert arc.mass ==   70.0
    assert sig.mass == 2000.0

def test_cavalry_is_fast():
    cav = make_unit(UnitType.CAVALRY, "general", (0, 0))
    assert cav.speed > 1.5

def test_siege_is_slow():
    sig = make_unit(UnitType.SIEGE, "general", (0, 0))
    assert sig.speed < 1.0

def test_archer_has_range():
    arc = make_unit(UnitType.ARCHER, "general", (0, 0))
    assert arc.attack_range > 1

def test_infantry_melee_only():
    inf = make_unit(UnitType.INFANTRY, "general", (0, 0))
    assert inf.attack_range == 1


# ---------------------------------------------------------------------------
# Unit state
# ---------------------------------------------------------------------------

def test_unit_alive_at_creation():
    u = make_unit(UnitType.INFANTRY, "general", (5, 5))
    assert u.is_alive()
    assert u.is_supplied()
    assert u.is_effective()

def test_unit_dies_at_zero_health():
    u = make_unit(UnitType.INFANTRY, "general", (0, 0))
    u.take_damage(1.0)
    assert not u.is_alive()

def test_take_damage_report():
    u = make_unit(UnitType.CAVALRY, "player_1", (3, 3))
    report = u.take_damage(0.4, source="archer_volley")
    assert report["damage"]      == 0.4
    assert report["unit_type"]   == "cavalry"
    assert report["health_after"] < 1.0
    assert report["killed"]      == False

def test_morale_drops_with_damage():
    u = make_unit(UnitType.INFANTRY, "general", (0, 0))
    initial_morale = u.morale
    u.take_damage(0.5)
    assert u.morale < initial_morale

def test_supply_drains_on_move():
    u = make_unit(UnitType.INFANTRY, "general", (5, 5))
    initial_supply = u.supply
    plain_cell = Cell(x=6, y=5, terrain=TerrainType.PLAIN,
                      mobility_cost=1.0, break_threshold=float("inf"))
    u.move_to(plain_cell)
    assert u.supply < initial_supply

def test_resupply_caps_at_one():
    u = make_unit(UnitType.INFANTRY, "general", (0, 0))
    u.supply = 0.5
    u.resupply(1.0)
    assert u.supply == 1.0


# ---------------------------------------------------------------------------
# Terrain interaction — the critical physics link
# ---------------------------------------------------------------------------

def test_cavalry_breaks_ice():
    """
    Cavalry mass (600kg) < ice threshold (800kg) alone.
    But combined in a group they should break it.
    Two cavalry = 1200kg > 800kg threshold.
    """
    ice_cell = Cell(x=10, y=10, terrain=TerrainType.FROZEN_LAKE,
                    break_threshold=800.0, cascade=False)
    cav1 = make_unit(UnitType.CAVALRY, "player_1", (9, 10))
    cav2 = make_unit(UnitType.CAVALRY, "player_1", (9, 10))

    event1 = cav1.move_to(ice_cell)
    assert event1 is None           # 600kg — not broken yet
    assert not ice_cell.is_broken

    event2 = cav2.move_to(ice_cell)
    assert event2 == "ice_break"    # 1200kg total — breaks
    assert ice_cell.is_broken

def test_siege_breaks_ice_alone():
    """Siege (2000kg) exceeds ice threshold (800kg) by itself."""
    ice_cell = Cell(x=5, y=5, terrain=TerrainType.FROZEN_LAKE,
                    break_threshold=800.0, cascade=False)
    sig = make_unit(UnitType.SIEGE, "general", (4, 5))
    event = sig.move_to(ice_cell)
    assert event == "ice_break"
    assert ice_cell.is_broken

def test_infantry_does_not_break_ice_alone():
    """Infantry (80kg) cannot break ice (800kg threshold) alone."""
    ice_cell = Cell(x=5, y=5, terrain=TerrainType.FROZEN_LAKE,
                    break_threshold=800.0, cascade=False)
    inf = make_unit(UnitType.INFANTRY, "general", (4, 5))
    event = inf.move_to(ice_cell)
    assert event is None
    assert not ice_cell.is_broken

def test_unit_cannot_move_to_broken_ice():
    """Once ice is broken, units cannot cross."""
    ice_cell = Cell(x=5, y=5, terrain=TerrainType.FROZEN_LAKE,
                    break_threshold=800.0, cascade=False, is_broken=True)
    inf = make_unit(UnitType.INFANTRY, "general", (4, 5))
    can, reason = inf.can_move_to(ice_cell)
    assert not can
    assert reason == "ice_broken"

def test_unit_cannot_move_to_intact_wall():
    """Walls are impassable until broken."""
    wall_cell = Cell(x=5, y=5, terrain=TerrainType.WALL,
                     mobility_cost=float("inf"), is_broken=False)
    cav = make_unit(UnitType.CAVALRY, "player_1", (4, 5))
    can, reason = cav.can_move_to(wall_cell)
    assert not can
    assert "wall" in reason

def test_siege_cannot_enter_forest():
    forest_cell = Cell(x=5, y=5, terrain=TerrainType.FOREST,
                       mobility_cost=2.0, break_threshold=float("inf"))
    sig = make_unit(UnitType.SIEGE, "general", (4, 5))
    can, reason = sig.can_move_to(forest_cell)
    assert not can
    assert "forest" in reason

def test_effective_force_reduced_by_low_supply():
    u = make_unit(UnitType.CAVALRY, "general", (0, 0))
    full_force    = u.effective_attack_force()
    u.supply = 0.1
    reduced_force = u.effective_attack_force()
    assert reduced_force < full_force

def test_cavalry_charge_bonus_on_plain():
    cav = make_unit(UnitType.CAVALRY, "general", (0, 0))
    plain = Cell(x=1, y=0, terrain=TerrainType.PLAIN, mobility_cost=1.0,
                 break_threshold=float("inf"))
    forest = Cell(x=1, y=0, terrain=TerrainType.FOREST, mobility_cost=2.0,
                  break_threshold=float("inf"))
    force_plain  = cav.effective_attack_force(plain)
    force_forest = cav.effective_attack_force(forest)
    assert force_plain > force_forest


# ---------------------------------------------------------------------------
# Behavioral features (brain-facing — no raw stats)
# ---------------------------------------------------------------------------

def test_behavioral_features_no_raw_stats():
    """
    behavioral_features() must NOT expose mass, attack_force, speed numbers.
    Brain should only see qualitative labels.
    """
    cav = make_unit(UnitType.CAVALRY, "general", (5, 5))
    features = cav.behavioral_features()
    assert "mass"         not in features
    assert "attack_force" not in features
    assert "speed"        not in features
    # Should have qualitative flags
    assert features["is_heavy"]  == True
    assert features["is_fast"]   == True
    assert features["is_ranged"] == False

def test_archer_behavioral_features():
    arc = make_unit(UnitType.ARCHER, "player_1", (3, 3))
    features = arc.behavioral_features()
    assert features["is_ranged"] == True
    assert features["is_heavy"]  == False
    assert features["is_fast"]   == False


# ---------------------------------------------------------------------------
# UnitGroup
# ---------------------------------------------------------------------------

def test_group_total_mass():
    group = make_group(
        {UnitType.CAVALRY: 2, UnitType.INFANTRY: 5},
        owner="general", position=(50, 50)
    )
    # 2×600 + 5×80 = 1200 + 400 = 1600
    assert group.total_mass == 1600.0

def test_group_dominant_type():
    group = make_group(
        {UnitType.CAVALRY: 1, UnitType.INFANTRY: 8},
        owner="player_1", position=(10, 10)
    )
    assert group.dominant_type() == "infantry"

def test_group_is_heavy():
    heavy = make_group({UnitType.SIEGE: 1}, owner="general", position=(0, 0))
    light = make_group({UnitType.ARCHER: 5}, owner="player_1", position=(0, 0))
    assert heavy.group_features()["is_heavy_group"] == True
    assert light.group_features()["is_heavy_group"] == False

def test_group_move_triggers_ice_break():
    """A cavalry group moving onto ice should break it from combined mass."""
    ice_cell = Cell(x=20, y=20, terrain=TerrainType.FROZEN_LAKE,
                    break_threshold=800.0, cascade=False)
    group = make_group({UnitType.CAVALRY: 2}, owner="player_1", position=(19, 20))
    events = group.move_to(ice_cell)
    assert "ice_break" in events

def test_group_features_no_raw_stats():
    """group_features() must not expose raw physics values."""
    group = make_group(
        {UnitType.CAVALRY: 3, UnitType.INFANTRY: 6},
        owner="general", position=(50, 50)
    )
    features = group.group_features()
    # Should have total_mass_kg (observable) but not attack_force
    assert "total_mass_kg" in features
    assert "attack_force"  not in features
    assert "speed"         not in features

def test_group_supply_status():
    group = make_group({UnitType.INFANTRY: 3}, owner="general", position=(0, 0))
    assert group.supply_status() == "supplied"
    for u in group.units:
        u.supply = 0.1
    assert group.supply_status() == "starving"

def test_dead_units_excluded_from_group():
    group = make_group({UnitType.INFANTRY: 3}, owner="general", position=(0, 0))
    group.units[0].take_damage(1.0)  # kill one
    assert group.size == 2
    assert len(group.alive_units) == 2

def test_deterministic_unit_id():
    """Unit IDs should be unique per instance."""
    u1 = make_unit(UnitType.INFANTRY, "general", (0, 0))
    u2 = make_unit(UnitType.INFANTRY, "general", (0, 0))
    assert u1.id != u2.id


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
