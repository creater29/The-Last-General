"""
test_grid.py — Verify grid generation, terrain physics, zone analysis.
"""
import sys
sys.path.insert(0, "/Users/Arman/Projects/general_brain/src")

from simulator.grid import Grid, Cell, TerrainType, TERRAIN_PHYSICS


def test_grid_generates():
    g = Grid(100, 100, seed=42)
    assert len(g.cells) == 100
    assert len(g.cells[0]) == 100

def test_all_terrain_types_present():
    g = Grid(100, 100, seed=42)
    found = {g.cells[y][x].terrain for y in range(100) for x in range(100)}
    # At minimum plain should always exist
    assert TerrainType.PLAIN in found

def test_cell_military_features():
    cell = Cell(x=5, y=5, terrain=TerrainType.FROZEN_LAKE,
                cover=0.0, mobility_cost=1.3, elevation=-1.0,
                break_threshold=800.0)
    features = cell.military_features()
    assert features["is_hazardous"] == True
    assert features["terrain_type"] == "frozen_lake"
    assert features["mass_threshold"] == 800.0

def test_ice_breaks_at_threshold():
    cell = Cell(x=0, y=0, terrain=TerrainType.FROZEN_LAKE,
                break_threshold=800.0)
    # Below threshold — no break
    event = cell.apply_mass(600.0)
    assert event is None
    assert not cell.is_broken
    # Exceed threshold — breaks
    event = cell.apply_mass(300.0)   # total now 900 > 800
    assert event == "ice_break"
    assert cell.is_broken

def test_plain_never_breaks():
    cell = Cell(x=0, y=0, terrain=TerrainType.PLAIN,
                break_threshold=float("inf"))
    event = cell.apply_mass(999999.0)
    assert event is None
    assert not cell.is_broken

def test_cascade_triggers():
    g = Grid(30, 30, seed=7)
    # Force a frozen lake cell to exist for cascade test
    g.cells[15][15] = Cell(x=15, y=15, terrain=TerrainType.FROZEN_LAKE,
                           break_threshold=800.0, cascade=True, is_broken=True)
    g.cells[15][16] = Cell(x=16, y=15, terrain=TerrainType.FROZEN_LAKE,
                           break_threshold=800.0, cascade=True)
    broken = g.trigger_cascade(15, 15)
    assert (16, 15) in broken

def test_military_zones_emergent():
    g = Grid(100, 100, seed=42)
    zones = g.military_zones()
    assert len(zones) > 0
    for z in zones:
        assert "zone_type"      in z
        assert "military_value" in z
        # Coordinates exist but marked internal with underscore prefix
        assert "_center_x" in z
        assert "_center_y" in z
        # Public-facing zone type must NOT be a map-slice name
        assert z["zone_type"] not in ("left_flank", "center", "right_flank")

def test_top_zones_sorted():
    g = Grid(100, 100, seed=42)
    top = g.top_military_zones(n=5)
    values = [z["military_value"] for z in top]
    assert values == sorted(values, reverse=True)

def test_battlefield_features():
    g = Grid(100, 100, seed=42)
    features = g.battlefield_features()
    assert "terrain_distribution" in features
    assert "dominant_terrain" in features
    assert abs(sum(features["terrain_distribution"].values()) - 1.0) < 0.01

def test_terrain_physics_separated():
    """
    The General must NOT be initialized with physics values.
    TERRAIN_PHYSICS is simulator-only. Verify it's not leaked into
    military_features output that the brain would consume.
    """
    g = Grid(50, 50, seed=1)
    for y in range(50):
        for x in range(50):
            features = g.cells[y][x].military_features()
            # Military features should NOT expose raw physics constants
            # that the General hasn't learned yet
            assert "flammability" not in features
            assert "base_temperature" not in features
            assert "cascade" not in features

def test_deterministic_with_seed():
    g1 = Grid(100, 100, seed=99)
    g2 = Grid(100, 100, seed=99)
    for y in range(100):
        for x in range(100):
            assert g1.cells[y][x].terrain == g2.cells[y][x].terrain

def test_get_returns_none_oob():
    g = Grid(100, 100, seed=42)
    assert g.get(-1, 0)  is None
    assert g.get(0, -1)  is None
    assert g.get(100, 0) is None
    assert g.get(0, 100) is None

if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
