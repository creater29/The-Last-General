"""
grid.py — The battlefield world.

Defines Cell, TerrainType, and Grid.
The General never sees raw coordinates — he sees features extracted from
these cells. This file is the lowest abstraction layer.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple, Dict
import numpy as np
import random


# ---------------------------------------------------------------------------
# Terrain Types
# ---------------------------------------------------------------------------

class TerrainType(str, Enum):
    PLAIN        = "plain"
    FROZEN_LAKE  = "frozen_lake"
    FOREST       = "forest"
    HILL         = "hill"
    RIVER        = "river"
    ROAD         = "road"
    WALL         = "wall"


# ---------------------------------------------------------------------------
# Physics constants per terrain type
# The General does NOT know these at start. He discovers them through episodes.
# ---------------------------------------------------------------------------

TERRAIN_PHYSICS: Dict[TerrainType, dict] = {
    TerrainType.PLAIN: {
        "break_threshold":  float("inf"),  # cannot break
        "flammability":     0.1,
        "stability":        1.0,
        "base_temperature": 15.0,
        "mobility_cost":    1.0,
        "base_cover":       0.05,
        "base_elevation":   0.0,
        "cascade":          False,
    },
    TerrainType.FROZEN_LAKE: {
        "break_threshold":  800.0,    # kg — cavalry ~600, siege ~2000
        "flammability":     0.0,
        "stability":        0.6,
        "base_temperature": -8.0,
        "mobility_cost":    1.3,      # slippery
        "base_cover":       0.0,
        "base_elevation":   -1.0,     # slightly below grade
        "cascade":          True,     # breaking spreads to adjacent cells
    },
    TerrainType.FOREST: {
        "break_threshold":  float("inf"),
        "flammability":     0.8,
        "stability":        0.9,
        "base_temperature": 12.0,
        "mobility_cost":    2.0,
        "base_cover":       0.7,
        "base_elevation":   0.5,
        "cascade":          False,
        "tree_fall_force":  500.0,    # N — force needed to fell trees
        "fire_spread":      True,
    },
    TerrainType.HILL: {
        "break_threshold":  float("inf"),
        "flammability":     0.2,
        "stability":        1.0,
        "base_temperature": 10.0,
        "mobility_cost":    1.8,
        "base_cover":       0.3,
        "base_elevation":   15.0,     # meters above baseline
        "cascade":          False,
        "charge_penalty":   0.30,     # -30% uphill effectiveness
        "visibility_bonus": 0.40,     # +40% sight range from top
    },
    TerrainType.RIVER: {
        "break_threshold":  float("inf"),
        "flammability":     0.0,
        "stability":        0.5,
        "base_temperature": 8.0,
        "mobility_cost":    3.5,      # -60% effective movement speed
        "base_cover":       0.0,
        "base_elevation":   -2.0,
        "cascade":          False,
        "flood_trigger":    "heavy_rain",
    },
    TerrainType.ROAD: {
        "break_threshold":  float("inf"),
        "flammability":     0.05,
        "stability":        1.0,
        "base_temperature": 15.0,
        "mobility_cost":    0.6,      # faster movement
        "base_cover":       0.0,
        "base_elevation":   0.0,
        "cascade":          False,
    },
    TerrainType.WALL: {
        "break_threshold":  float("inf"),
        "flammability":     0.1,
        "stability":        0.95,
        "base_temperature": 15.0,
        "mobility_cost":    float("inf"),  # impassable unless broken
        "base_cover":       0.9,
        "base_elevation":   8.0,
        "cascade":          False,
        "collapse_threshold": 1000.0,      # N from siege impact
        "rubble_on_collapse": True,
    },
}


# ---------------------------------------------------------------------------
# Cell
# ---------------------------------------------------------------------------

@dataclass
class Cell:
    """
    One tile on the battlefield.
    Properties are the raw physical reality.
    The General derives principles from observing what HAPPENS on these cells.
    """
    x: int
    y: int
    terrain: TerrainType

    # Derived from TERRAIN_PHYSICS + per-cell variation
    elevation:     float = 0.0
    cover:         float = 0.0
    mobility_cost: float = 1.0
    temperature:   float = 15.0

    # Physics properties (what the terrain can DO)
    break_threshold:  float = float("inf")
    flammability:     float = 0.0
    stability:        float = 1.0
    cascade:          bool  = False

    # Dynamic state (changes during battle)
    is_broken:    bool  = False   # ice broken, wall collapsed
    is_burning:   bool  = False
    is_flooded:   bool  = False
    has_rubble:   bool  = False   # from collapsed wall
    current_mass: float = 0.0    # total unit mass currently on this cell

    def military_features(self) -> dict:
        """
        Extract military-relevant features from raw cell data.
        This is the abstraction layer between raw terrain and tactical reasoning.
        These features are what gets logged in episodes.
        """
        return {
            "terrain_type":        self.terrain.value,
            "is_hazardous":        self.break_threshold < float("inf") or self.flammability > 0.5,
            "provides_cover":      self.cover > 0.3,
            "restricts_movement":  self.mobility_cost > 1.5,
            "elevation_advantage": self.elevation > 5.0,
            "is_crossable":        self.mobility_cost < float("inf") and not self.is_broken,
            "ambush_value":        self.cover > 0.5 and self.mobility_cost < 2.5,
            "chokepoint_potential": self.mobility_cost > 2.0,
            "is_broken":           self.is_broken,
            "is_burning":          self.is_burning,
            "mass_threshold":      self.break_threshold,
        }

    def apply_mass(self, mass: float) -> Optional[str]:
        """
        Called when a unit moves onto or through this cell.
        Returns terrain event string if something happens, else None.
        """
        self.current_mass += mass

        if self.terrain == TerrainType.FROZEN_LAKE and not self.is_broken:
            if self.current_mass >= self.break_threshold:
                self.is_broken = True
                return "ice_break"

        if self.terrain == TerrainType.WALL and not self.is_broken:
            # Wall collapse handled by physics engine via siege force, not mass
            pass

        return None

    def __repr__(self) -> str:
        state = ""
        if self.is_broken:  state += "[BROKEN]"
        if self.is_burning: state += "[FIRE]"
        if self.is_flooded: state += "[FLOOD]"
        return f"Cell({self.x},{self.y} {self.terrain.value}{state})"


# ---------------------------------------------------------------------------
# Grid
# ---------------------------------------------------------------------------

class Grid:
    """
    The battlefield. 100x100 by default.

    Terrain is generated in coherent zones — not random per-cell.
    A frozen lake is a region, not scattered pixels.
    """

    def __init__(self, width: int = 100, height: int = 100, seed: Optional[int] = None):
        self.width  = width
        self.height = height
        self.seed   = seed
        self.cells: List[List[Cell]] = []
        self._generate(seed)

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def _generate(self, seed: Optional[int] = None) -> None:
        """Generate a coherent battlefield with terrain zones."""
        rng = random.Random(seed)
        np_rng = np.random.default_rng(seed)

        # Start with plain everywhere
        self.cells = [
            [self._make_cell(x, y, TerrainType.PLAIN) for x in range(self.width)]
            for y in range(self.height)
        ]

        # Place terrain zones in order (later zones can overwrite earlier)
        self._place_zone(TerrainType.FROZEN_LAKE, count=2, min_r=5,  max_r=10, rng=rng)
        self._place_zone(TerrainType.FOREST,      count=3, min_r=6,  max_r=14, rng=rng)
        self._place_zone(TerrainType.HILL,        count=2, min_r=4,  max_r=9,  rng=rng)
        self._place_zone(TerrainType.RIVER,       count=1, min_r=1,  max_r=2,  rng=rng, as_line=True)
        self._place_zone(TerrainType.WALL,        count=2, min_r=1,  max_r=2,  rng=rng, as_line=True)
        self._place_zone(TerrainType.ROAD,        count=2, min_r=1,  max_r=1,  rng=rng, as_line=True)

        # Apply per-cell elevation variation
        self._apply_elevation_noise(np_rng)

    def _make_cell(self, x: int, y: int, terrain: TerrainType) -> Cell:
        """Create a cell with physics from terrain type."""
        p = TERRAIN_PHYSICS[terrain]
        return Cell(
            x=x, y=y,
            terrain=terrain,
            elevation=p["base_elevation"],
            cover=p["base_cover"],
            mobility_cost=p["mobility_cost"],
            temperature=p["base_temperature"],
            break_threshold=p["break_threshold"],
            flammability=p["flammability"],
            stability=p["stability"],
            cascade=p["cascade"],
        )

    def _place_zone(
        self,
        terrain: TerrainType,
        count: int,
        min_r: int,
        max_r: int,
        rng: random.Random,
        as_line: bool = False,
    ) -> None:
        """Place elliptical terrain zones or lines on the grid."""
        for _ in range(count):
            cx = rng.randint(max_r, self.width  - max_r)
            cy = rng.randint(max_r, self.height - max_r)

            if as_line:
                # Draw a rough line across the map
                length    = rng.randint(self.width // 3, self.width // 2)
                direction = rng.choice(["h", "v", "d"])
                thickness = rng.randint(min_r, max_r)
                for step in range(length):
                    if direction == "h":
                        bx, by = cx + step, cy
                    elif direction == "v":
                        bx, by = cx, cy + step
                    else:
                        bx, by = cx + step, cy + step
                    for t in range(-thickness, thickness + 1):
                        px = bx if direction == "v" else bx
                        py = by + t if direction != "v" else by + t
                        if 0 <= px < self.width and 0 <= py < self.height:
                            self.cells[py][px] = self._make_cell(px, py, terrain)
            else:
                # Elliptical zone
                rx = rng.randint(min_r, max_r)
                ry = rng.randint(min_r, max_r)
                for dy in range(-ry, ry + 1):
                    for dx in range(-rx, rx + 1):
                        if (dx / rx) ** 2 + (dy / ry) ** 2 <= 1.0:
                            px, py = cx + dx, cy + dy
                            if 0 <= px < self.width and 0 <= py < self.height:
                                self.cells[py][px] = self._make_cell(px, py, terrain)

    def _apply_elevation_noise(self, rng: np.random.Generator) -> None:
        """Add small elevation variation per cell for realism."""
        for y in range(self.height):
            for x in range(self.width):
                cell = self.cells[y][x]
                noise = float(rng.normal(0, 0.5))
                cell.elevation = max(cell.elevation + noise, -5.0)

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------

    def get(self, x: int, y: int) -> Optional[Cell]:
        """Get cell at (x, y). Returns None if out of bounds."""
        if 0 <= x < self.width and 0 <= y < self.height:
            return self.cells[y][x]
        return None

    def neighbors(self, x: int, y: int, radius: int = 1) -> List[Cell]:
        """Return all valid cells within Manhattan radius."""
        result = []
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dx == 0 and dy == 0:
                    continue
                cell = self.get(x + dx, y + dy)
                if cell:
                    result.append(cell)
        return result

    def cells_of_type(self, terrain: TerrainType) -> List[Cell]:
        """Return all cells of a given terrain type."""
        return [
            self.cells[y][x]
            for y in range(self.height)
            for x in range(self.width)
            if self.cells[y][x].terrain == terrain
        ]

    # ------------------------------------------------------------------
    # Features (what the brain sees — no raw coordinates)
    # ------------------------------------------------------------------

    def battlefield_features(self) -> dict:
        """
        High-level features of the entire battlefield.
        This is what gets logged per episode for doctrine formation.
        No coordinates. Only principles.
        """
        total = self.width * self.height
        counts: Dict[str, int] = {}
        for terrain in TerrainType:
            counts[terrain.value] = len(self.cells_of_type(terrain))

        hazardous = counts[TerrainType.FROZEN_LAKE.value] + counts[TerrainType.RIVER.value]

        return {
            "terrain_distribution": {k: round(v / total, 3) for k, v in counts.items()},
            "hazard_coverage":      round(hazardous / total, 3),
            "forest_coverage":      round(counts[TerrainType.FOREST.value] / total, 3),
            "has_frozen_lake":      counts[TerrainType.FROZEN_LAKE.value] > 0,
            "has_river":            counts[TerrainType.RIVER.value] > 0,
            "has_walls":            counts[TerrainType.WALL.value] > 0,
            "elevation_variance":   self._elevation_variance(),
            "dominant_terrain":     max(counts, key=counts.get),
        }

    def military_zones(self) -> List[dict]:
        """
        Identify emergent military zones from terrain analysis.
        These are NOT hardcoded map slices (no left/center/right).
        Zones emerge from what the terrain actually offers militarily.

        Returns a list of zone descriptors the General can reason about.
        Each zone is defined by military value, not coordinates.
        """
        zones = []

        # Scan in NxN blocks to find militarily significant clusters
        block = 10  # block size in cells
        for by in range(0, self.height, block):
            for bx in range(0, self.width, block):
                block_cells = [
                    self.cells[y][x]
                    for y in range(by, min(by + block, self.height))
                    for x in range(bx, min(bx + block, self.width))
                ]
                if not block_cells:
                    continue

                avg_cover    = sum(c.cover         for c in block_cells) / len(block_cells)
                avg_mobility = sum(c.mobility_cost for c in block_cells) / len(block_cells)
                avg_elev     = sum(c.elevation     for c in block_cells) / len(block_cells)
                has_hazard   = any(
                    c.terrain in (TerrainType.FROZEN_LAKE, TerrainType.RIVER)
                    for c in block_cells
                )
                has_wall     = any(c.terrain == TerrainType.WALL     for c in block_cells)
                has_road     = any(c.terrain == TerrainType.ROAD     for c in block_cells)
                has_forest   = any(c.terrain == TerrainType.FOREST   for c in block_cells)
                has_hill     = any(c.terrain == TerrainType.HILL     for c in block_cells)

                zone_type = self._classify_zone(
                    avg_cover, avg_mobility, avg_elev,
                    has_hazard, has_wall, has_road, has_forest, has_hill
                )

                if zone_type:
                    zones.append({
                        # Simulator-internal coordinates — stripped before brain sees this
                        "_center_x":       bx + block // 2,
                        "_center_y":       by + block // 2,
                        # Brain-facing fields only below
                        "zone_type":       zone_type,
                        "avg_cover":       round(avg_cover, 3),
                        "avg_mobility":    round(avg_mobility, 3),
                        "avg_elevation":   round(avg_elev, 2),
                        "has_hazard":      has_hazard,
                        "military_value":  self._military_value(zone_type, avg_elev, avg_cover),
                    })

        return zones

    def _classify_zone(
        self,
        avg_cover: float,
        avg_mobility: float,
        avg_elev: float,
        has_hazard: bool,
        has_wall: bool,
        has_road: bool,
        has_forest: bool,
        has_hill: bool,
    ) -> Optional[str]:
        """
        Classify a block into a military zone type based on terrain properties.
        Returns None if the block has no significant military value.
        """
        # High ground — elevation advantage, visibility
        if avg_elev > 8.0 or has_hill:
            return "high_ground"

        # Chokepoint — difficult to cross, forces narrow movement
        if avg_mobility > 2.5:
            return "chokepoint"

        # Ambush corridor — good cover, passable
        if avg_cover > 0.5 and avg_mobility < 2.5 and has_forest:
            return "ambush_corridor"

        # Hazard zone — terrain that can damage units
        if has_hazard:
            return "hazard_zone"

        # Fortified — walls present, defensive value
        if has_wall:
            return "fortified"

        # Supply corridor — roads, easy movement
        if has_road and avg_mobility < 1.0:
            return "supply_corridor"

        # Open field — no significant feature, but tactically relevant
        if avg_mobility < 1.3 and avg_cover < 0.1:
            return "open_field"

        return None  # no significant military value

    def _military_value(self, zone_type: str, avg_elev: float, avg_cover: float) -> float:
        """
        Score how militarily valuable a zone is.
        Higher = General should care more about controlling this zone.
        """
        base_values = {
            "high_ground":      0.9,
            "chokepoint":       0.8,
            "ambush_corridor":  0.75,
            "fortified":        0.85,
            "hazard_zone":      0.6,   # valuable to exploit, dangerous to occupy
            "supply_corridor":  0.7,
            "open_field":       0.3,
        }
        base = base_values.get(zone_type, 0.2)
        # Elevation bonus for high ground
        if zone_type == "high_ground":
            base = min(1.0, base + avg_elev / 100.0)
        return round(base, 3)

    def top_military_zones(self, n: int = 5) -> List[dict]:
        """
        Return the N most militarily valuable zones on this battlefield.
        This is what the General scans when assessing a new battlefield.
        """
        zones = self.military_zones()
        return sorted(zones, key=lambda z: z["military_value"], reverse=True)[:n]

    def _elevation_variance(self) -> float:
        elevations = [
            self.cells[y][x].elevation
            for y in range(self.height)
            for x in range(self.width)
        ]
        arr = np.array(elevations)
        return round(float(np.var(arr)), 3)

    # ------------------------------------------------------------------
    # Cascade handling (ice breaks spreading)
    # ------------------------------------------------------------------

    def trigger_cascade(self, x: int, y: int) -> List[Tuple[int, int]]:
        """
        When a cell breaks (ice), cascade to adjacent cells of the same type.
        Returns list of (x, y) that also broke.
        """
        origin = self.get(x, y)
        if not origin or not origin.cascade:
            return []

        broken = []
        queue  = self.neighbors(x, y, radius=1)
        seen   = {(x, y)}

        for neighbor in queue:
            if (neighbor.x, neighbor.y) in seen:
                continue
            seen.add((neighbor.x, neighbor.y))
            if neighbor.terrain == origin.terrain and not neighbor.is_broken:
                neighbor.is_broken = True
                broken.append((neighbor.x, neighbor.y))

        return broken

    # ------------------------------------------------------------------
    # Debug / Visualization
    # ------------------------------------------------------------------

    def ascii_map(self, width: int = 50, height: int = 25) -> str:
        """
        Print a scaled-down ASCII representation.
        Useful for debugging terrain generation.
        """
        symbols = {
            TerrainType.PLAIN:       ".",
            TerrainType.FROZEN_LAKE: "~",
            TerrainType.FOREST:      "T",
            TerrainType.HILL:        "^",
            TerrainType.RIVER:       "=",
            TerrainType.ROAD:        "-",
            TerrainType.WALL:        "#",
        }
        step_x = max(1, self.width  // width)
        step_y = max(1, self.height // height)
        rows   = []
        for y in range(0, self.height, step_y):
            row = ""
            for x in range(0, self.width, step_x):
                cell = self.cells[y][x]
                sym  = symbols.get(cell.terrain, "?")
                if cell.is_broken:  sym = "x"
                if cell.is_burning: sym = "*"
                row += sym
            rows.append(row)

        legend = (
            "  . plain  ~ lake  T forest  ^ hill  "
            "= river  - road  # wall  x broken  * fire"
        )
        return "\n".join(rows) + "\n" + legend

    def terrain_stats(self) -> str:
        """Print terrain distribution for quick verification."""
        total  = self.width * self.height
        lines  = [f"Grid {self.width}x{self.height} (seed={self.seed}):"]
        for terrain in TerrainType:
            count = len(self.cells_of_type(terrain))
            pct   = 100 * count / total
            bar   = "█" * int(pct / 2)
            lines.append(f"  {terrain.value:<14} {count:>5} ({pct:5.1f}%)  {bar}")
        return "\n".join(lines)
