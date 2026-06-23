"""
units.py — Unit types and behavior on the battlefield.

Defines UnitType, Unit, and UnitGroup.
Units interact with terrain through the physics layer.
The General reasons about unit TYPES and BEHAVIORS, not individual unit IDs.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple, Dict
import uuid

from simulator.grid import Cell, TerrainType


# ---------------------------------------------------------------------------
# Unit Types
# ---------------------------------------------------------------------------

class UnitType(str, Enum):
    INFANTRY = "infantry"
    CAVALRY  = "cavalry"
    ARCHER   = "archer"
    SIEGE    = "siege"


# ---------------------------------------------------------------------------
# Base stats per unit type
# These are simulator ground truth — like TERRAIN_PHYSICS.
# The General does NOT start knowing these. He observes outcomes.
# ---------------------------------------------------------------------------

UNIT_BASE_STATS: Dict[UnitType, dict] = {
    UnitType.INFANTRY: {
        "mass":          80.0,    # kg per unit
        "speed":         1.0,     # base movement per turn
        "health":        1.0,
        "attack_force":  200.0,   # N — for physics interactions
        "supply_drain":  0.05,    # per turn
        "morale_base":   0.8,
        "range":         1,       # melee only
        "uphill_penalty": 0.10,   # less penalized than cavalry
    },
    UnitType.CAVALRY: {
        "mass":          600.0,   # kg — horse + rider + armour
        "speed":         2.5,
        "health":        1.0,
        "attack_force":  800.0,   # N — devastating charge
        "supply_drain":  0.08,
        "morale_base":   0.85,
        "range":         1,
        "uphill_penalty": 0.35,   # heavily penalized uphill
        "charge_bonus":  1.5,     # multiplier when charging open ground
    },
    UnitType.ARCHER: {
        "mass":          70.0,
        "speed":         0.9,
        "health":        1.0,
        "attack_force":  50.0,    # N — arrows, low physics impact
        "supply_drain":  0.06,    # arrows are supply
        "morale_base":   0.7,
        "range":         5,       # cells
        "cover_bonus":   1.4,     # more effective firing from cover
        "forest_penalty": 0.5,    # range halved in forest
    },
    UnitType.SIEGE: {
        "mass":          2000.0,  # kg — will break ice, collapse walls
        "speed":         0.3,
        "health":        1.0,
        "attack_force":  2000.0,  # N — wall collapse threshold is 1000N
        "supply_drain":  0.12,
        "morale_base":   0.6,
        "range":         3,
        "wall_damage":   1.0,     # full damage to fortifications
        "mobility_penalty": 2.0,  # extra mobility cost on difficult terrain
    },
}


# ---------------------------------------------------------------------------
# Unit
# ---------------------------------------------------------------------------

@dataclass
class Unit:
    """
    A single unit on the battlefield.

    Units are the actors. They move, fight, consume supply, lose morale.
    Their interactions with terrain generate the raw events that the
    General's brain eventually learns from.
    """
    unit_type: UnitType
    owner:     str              # "general" | "player_{id}"
    position:  Tuple[int, int]  # (x, y)

    # Identity
    id:     str   = field(default_factory=lambda: str(uuid.uuid4())[:8])
    label:  str   = ""          # human-readable e.g. "cavalry_alpha"

    # Dynamic state (0.0 = dead/empty, 1.0 = full)
    health:  float = 1.0
    supply:  float = 1.0
    morale:  float = 0.8

    # Derived from UNIT_BASE_STATS at init
    mass:         float = 0.0
    speed:        float = 1.0
    attack_force: float = 0.0
    supply_drain: float = 0.05
    attack_range: int   = 1

    def __post_init__(self) -> None:
        stats = UNIT_BASE_STATS[self.unit_type]
        self.mass         = stats["mass"]
        self.speed        = stats["speed"]
        self.attack_force = stats["attack_force"]
        self.supply_drain = stats["supply_drain"]
        self.morale       = stats["morale_base"]
        self.attack_range = stats["range"]
        if not self.label:
            self.label = f"{self.unit_type.value}_{self.id[:4]}"

    # ------------------------------------------------------------------
    # State checks
    # ------------------------------------------------------------------

    def is_alive(self) -> bool:
        return self.health > 0.0

    def is_supplied(self) -> bool:
        return self.supply > 0.0

    def is_effective(self) -> bool:
        """Unit is alive, has supply, and morale hasn't broken."""
        return self.is_alive() and self.is_supplied() and self.morale > 0.2

    def effective_attack_force(self, target_cell: Optional[Cell] = None) -> float:
        """
        Compute actual attack force accounting for terrain, supply, morale.
        This is what gets applied to terrain physics calculations.
        """
        force = self.attack_force

        # Supply degrades fighting ability
        if self.supply < 0.3:
            force *= 0.6

        # Morale degrades fighting ability
        force *= max(0.3, self.morale)

        # Health degrades fighting ability
        force *= max(0.2, self.health)

        # Terrain modifiers
        if target_cell:
            stats = UNIT_BASE_STATS[self.unit_type]

            # Uphill penalty
            if target_cell.elevation > 5.0 and "uphill_penalty" in stats:
                force *= (1.0 - stats["uphill_penalty"])

            # Cavalry charge bonus on open ground
            if (self.unit_type == UnitType.CAVALRY
                    and target_cell.terrain == TerrainType.PLAIN
                    and not target_cell.is_broken):
                force *= stats.get("charge_bonus", 1.0)

            # Archer forest penalty
            if (self.unit_type == UnitType.ARCHER
                    and target_cell.terrain == TerrainType.FOREST):
                force *= stats.get("forest_penalty", 1.0)

        return round(force, 2)

    # ------------------------------------------------------------------
    # Movement
    # ------------------------------------------------------------------

    def can_move_to(self, cell: Cell) -> Tuple[bool, str]:
        """
        Check if this unit can move to a cell.
        Returns (can_move, reason).
        """
        if not self.is_alive():
            return False, "unit_dead"

        if not self.is_supplied():
            return False, "no_supply"

        # Impassable terrain
        if cell.mobility_cost == float("inf"):
            if cell.terrain == TerrainType.WALL and not cell.is_broken:
                return False, "wall_impassable"
            return False, "terrain_impassable"

        # Broken ice — falling through
        if cell.terrain == TerrainType.FROZEN_LAKE and cell.is_broken:
            return False, "ice_broken"

        # Siege units cannot enter forest efficiently
        if (self.unit_type == UnitType.SIEGE
                and cell.terrain == TerrainType.FOREST):
            return False, "siege_cannot_enter_forest"

        return True, "ok"

    def movement_cost(self, cell: Cell) -> float:
        """
        How much of this unit's speed budget moving to this cell costs.
        Higher = slower movement.
        """
        base = cell.mobility_cost

        # Siege units pay extra on difficult terrain
        if self.unit_type == UnitType.SIEGE:
            stats = UNIT_BASE_STATS[UnitType.SIEGE]
            if cell.mobility_cost > 1.0:
                base *= stats["mobility_penalty"]

        # Supply affects movement ability
        if self.supply < 0.2:
            base *= 1.5

        return round(base, 2)

    def move_to(self, cell: Cell) -> Optional[str]:
        """
        Move unit to a cell. Updates position, applies terrain mass,
        consumes supply. Returns terrain event if triggered, else None.
        """
        can, reason = self.can_move_to(cell)
        if not can:
            return f"move_blocked:{reason}"

        self.position = (cell.x, cell.y)
        terrain_event = cell.apply_mass(self.mass)
        self._consume_supply()

        return terrain_event

    # ------------------------------------------------------------------
    # Combat
    # ------------------------------------------------------------------

    def take_damage(self, amount: float, source: str = "unknown") -> dict:
        """
        Apply damage to this unit.
        Returns damage report dict for episode logging.
        """
        old_health = self.health
        self.health = max(0.0, self.health - amount)
        self.morale = max(0.0, self.morale - amount * 0.3)  # morale hit

        return {
            "unit_id":     self.id,
            "unit_type":   self.unit_type.value,
            "owner":       self.owner,
            "source":      source,
            "damage":      round(amount, 3),
            "health_before": round(old_health, 3),
            "health_after":  round(self.health, 3),
            "killed":      not self.is_alive(),
        }

    def attack(self, target_cell: Cell) -> dict:
        """
        This unit attacks into target_cell.
        Returns attack report including force applied (for physics calculation).
        """
        force = self.effective_attack_force(target_cell)
        return {
            "attacker_id":    self.id,
            "attacker_type":  self.unit_type.value,
            "attacker_owner": self.owner,
            "target_cell":    (target_cell.x, target_cell.y),
            "target_terrain": target_cell.terrain.value,
            "force_applied":  force,
            "attack_range":   self.attack_range,
        }

    # ------------------------------------------------------------------
    # Supply
    # ------------------------------------------------------------------

    def _consume_supply(self) -> None:
        self.supply = max(0.0, self.supply - self.supply_drain)

    def resupply(self, amount: float = 0.3) -> None:
        self.supply = min(1.0, self.supply + amount)

    def tick_supply(self) -> None:
        """Called each turn — passive supply drain."""
        self._consume_supply()
        # Low supply damages morale
        if self.supply < 0.2:
            self.morale = max(0.0, self.morale - 0.02)

    # ------------------------------------------------------------------
    # Behavioral features (what the brain observes — no raw stats)
    # ------------------------------------------------------------------

    def behavioral_features(self) -> dict:
        """
        What the General can observe about this unit type behaviorally.
        NOT raw stats — observed behavior patterns.
        These feed into episode logs that the brain learns from.
        """
        return {
            "unit_type":       self.unit_type.value,
            "owner":           self.owner,
            "is_heavy":        self.mass > 300.0,        # cavalry, siege
            "is_ranged":       self.attack_range > 1,    # archer, siege
            "is_fast":         self.speed > 1.5,         # cavalry
            "is_supplied":     self.is_supplied(),
            "is_effective":    self.is_effective(),
            "morale_state":    self._morale_label(),
            "health_state":    self._health_label(),
            "supply_state":    self._supply_label(),
        }

    def _morale_label(self) -> str:
        if self.morale > 0.7:  return "high"
        if self.morale > 0.4:  return "wavering"
        return "broken"

    def _health_label(self) -> str:
        if self.health > 0.7:  return "fresh"
        if self.health > 0.3:  return "bloodied"
        return "routing"

    def _supply_label(self) -> str:
        if self.supply > 0.6:  return "supplied"
        if self.supply > 0.2:  return "strained"
        return "starving"

    def __repr__(self) -> str:
        x, y = self.position
        return (
            f"Unit({self.label} [{self.owner}] "
            f"hp={self.health:.2f} sup={self.supply:.2f} "
            f"mor={self.morale:.2f} @({x},{y}))"
        )


# ---------------------------------------------------------------------------
# UnitGroup
# ---------------------------------------------------------------------------

class UnitGroup:
    """
    A collection of units acting together — an army, a regiment, a detachment.
    The General reasons about groups, not individual units.

    Groups have combined mass (for terrain physics),
    combined behavioral signature (for doctrine application),
    and collective supply state.
    """

    def __init__(self, units: List[Unit], label: str = ""):
        self.units = units
        self.label = label or f"group_{len(units)}units"

    # ------------------------------------------------------------------
    # Aggregate properties
    # ------------------------------------------------------------------

    @property
    def alive_units(self) -> List[Unit]:
        return [u for u in self.units if u.is_alive()]

    @property
    def effective_units(self) -> List[Unit]:
        return [u for u in self.units if u.is_effective()]

    @property
    def total_mass(self) -> float:
        """Combined mass of all alive units — key for terrain physics."""
        return sum(u.mass for u in self.alive_units)

    @property
    def size(self) -> int:
        return len(self.alive_units)

    @property
    def is_combat_effective(self) -> bool:
        return len(self.effective_units) > 0

    def composition(self) -> Dict[str, int]:
        """Count of each unit type — commander-level view."""
        counts: Dict[str, int] = {t.value: 0 for t in UnitType}
        for u in self.alive_units:
            counts[u.unit_type.value] += 1
        return counts

    def dominant_type(self) -> str:
        """Which unit type makes up the majority."""
        comp = self.composition()
        return max(comp, key=comp.get)

    def avg_supply(self) -> float:
        if not self.alive_units:
            return 0.0
        return round(sum(u.supply for u in self.alive_units) / len(self.alive_units), 3)

    def avg_morale(self) -> float:
        if not self.alive_units:
            return 0.0
        return round(sum(u.morale for u in self.alive_units) / len(self.alive_units), 3)

    def avg_health(self) -> float:
        if not self.alive_units:
            return 0.0
        return round(sum(u.health for u in self.alive_units) / len(self.alive_units), 3)

    # ------------------------------------------------------------------
    # Group movement
    # ------------------------------------------------------------------

    def can_move_to(self, cell: Cell) -> Tuple[bool, str]:
        """
        Can this group move to a cell?
        A group is blocked if ANY unit cannot move there
        (the slowest/most restricted unit determines group movement).
        """
        for unit in self.alive_units:
            can, reason = unit.can_move_to(cell)
            if not can:
                return False, f"{unit.unit_type.value}:{reason}"
        return True, "ok"

    def move_to(self, cell: Cell) -> List[str]:
        """
        Move all alive units to a cell.
        Returns list of terrain events triggered.
        NOTE: Mass accumulates per unit — heavy groups break ice faster.
        """
        events = []
        for unit in self.alive_units:
            event = unit.move_to(cell)
            if event and not event.startswith("move_blocked"):
                events.append(event)
        return events

    # ------------------------------------------------------------------
    # Group supply
    # ------------------------------------------------------------------

    def tick_supply(self) -> None:
        for unit in self.alive_units:
            unit.tick_supply()

    def resupply(self, amount: float = 0.3) -> None:
        for unit in self.alive_units:
            unit.resupply(amount)

    def supply_status(self) -> str:
        avg = self.avg_supply()
        if avg > 0.6:  return "supplied"
        if avg > 0.2:  return "strained"
        return "starving"

    # ------------------------------------------------------------------
    # Group features for episode logging
    # ------------------------------------------------------------------

    def group_features(self) -> dict:
        """
        Commander-level description of this group.
        No raw stats — behavioral and compositional features only.
        This is what gets logged in episodes for the brain to learn from.
        """
        comp = self.composition()
        return {
            "label":           self.label,
            "size":            self.size,
            "total_mass_kg":   round(self.total_mass, 1),
            "is_heavy_group":  self.total_mass > 500.0,
            "dominant_type":   self.dominant_type(),
            "composition":     comp,
            "has_cavalry":     comp[UnitType.CAVALRY.value] > 0,
            "has_siege":       comp[UnitType.SIEGE.value] > 0,
            "has_ranged":      comp[UnitType.ARCHER.value] > 0,
            "supply_status":   self.supply_status(),
            "avg_morale":      self.avg_morale(),
            "avg_health":      self.avg_health(),
            "is_effective":    self.is_combat_effective,
        }

    def __repr__(self) -> str:
        comp = self.composition()
        parts = [f"{v}{k[0].upper()}" for k, v in comp.items() if v > 0]
        return (
            f"UnitGroup({self.label}: {'+'.join(parts)} "
            f"mass={self.total_mass:.0f}kg "
            f"supply={self.supply_status()})"
        )


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def make_unit(unit_type: UnitType, owner: str, position: Tuple[int, int]) -> Unit:
    """Convenience factory."""
    return Unit(unit_type=unit_type, owner=owner, position=position)


def make_group(
    composition: Dict[UnitType, int],
    owner: str,
    position: Tuple[int, int],
    label: str = "",
) -> UnitGroup:
    """
    Create a UnitGroup from a composition dict.
    Example: make_group({UnitType.CAVALRY: 3, UnitType.INFANTRY: 10}, "general", (50, 50))
    """
    units = []
    for unit_type, count in composition.items():
        for _ in range(count):
            units.append(make_unit(unit_type, owner, position))
    return UnitGroup(units, label=label or f"{owner}_group")
