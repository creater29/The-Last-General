"""
physics.py — Terrain interaction engine.

Resolves what happens when units apply force to terrain.
This is the simulator's ground truth — the laws of this world.

The General does NOT have access to this module.
He observes OUTCOMES (terrain events logged in episodes)
and derives principles from them. He never reads these constants directly.

Key principle: physics.py knows the rules.
              The General discovers the rules through experience.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, TYPE_CHECKING

from simulator.grid import Cell, Grid, TerrainType, TERRAIN_PHYSICS
from simulator.units import Unit, UnitGroup, UnitType, UNIT_BASE_STATS

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Terrain Event
# ---------------------------------------------------------------------------

@dataclass
class TerrainEvent:
    """
    A physics event that occurred during battle.
    These are what get logged in episodes.
    The General learns from these — they are his observations.
    """
    event_type:   str               # ice_break, tree_fall, wall_collapse,
                                    # flood, fire_spread, rubble_created
    location:     Tuple[int, int]   # (x, y) where it happened
    triggered_by: str               # unit_id or "weather" or "cascade"
    trigger_type: str               # unit_type or "cascade" or "weather"
    force_applied: float            # N or kg — what caused it
    cascade_cells: List[Tuple[int, int]] = field(default_factory=list)
    casualties:   int  = 0          # units lost in this event
    blocks_movement: bool = False   # does the result block movement?

    def to_observation(self) -> dict:
        """
        What the General's observation layer sees from this event.
        No raw physics numbers — only military-relevant outcomes.
        """
        return {
            "event_type":      self.event_type,
            "terrain_at_site": self._terrain_label(),
            "triggered_by_type": self.trigger_type,
            "scale":           self._scale_label(),
            "casualties":      self.casualties,
            "blocks_movement": self.blocks_movement,
            "cascade_occurred": len(self.cascade_cells) > 0,
            "cascade_size":    len(self.cascade_cells),
        }

    def _terrain_label(self) -> str:
        labels = {
            "ice_break":      "frozen_lake",
            "tree_fall":      "forest",
            "wall_collapse":  "wall",
            "flood":          "river",
            "fire_spread":    "forest",
            "rubble_created": "wall",
        }
        return labels.get(self.event_type, "unknown")

    def _scale_label(self) -> str:
        """Was this a minor, moderate, or major event?"""
        if self.casualties == 0 and not self.cascade_cells:
            return "minor"
        if self.casualties < 3 and len(self.cascade_cells) < 5:
            return "moderate"
        return "major"

    def __repr__(self) -> str:
        return (
            f"TerrainEvent({self.event_type} @{self.location} "
            f"by={self.trigger_type} force={self.force_applied:.0f} "
            f"casualties={self.casualties})"
        )


# ---------------------------------------------------------------------------
# Combat Result
# ---------------------------------------------------------------------------

@dataclass
class CombatResult:
    """
    Result of one unit attacking another.
    Combines physics force with unit damage calculation.
    """
    attacker_id:   str
    attacker_type: str
    attacker_owner: str
    defender_id:   str
    defender_type: str
    defender_owner: str
    force_applied: float
    damage_dealt:  float
    defender_killed: bool
    terrain_type:  str    # terrain where combat occurred
    terrain_event: Optional[TerrainEvent] = None  # if combat caused terrain event

    def to_observation(self) -> dict:
        """Brain-facing summary — no raw force values."""
        return {
            "attacker_type":   self.attacker_type,
            "defender_type":   self.defender_type,
            "outcome":         "kill" if self.defender_killed else "damage",
            "terrain":         self.terrain_type,
            "terrain_event":   self.terrain_event.to_observation() if self.terrain_event else None,
        }


# ---------------------------------------------------------------------------
# Physics Engine
# ---------------------------------------------------------------------------

class PhysicsEngine:
    """
    Resolves terrain interactions and combat physics.

    This is called by the battle simulator.
    The General never calls this directly.
    He only sees the TerrainEvents and CombatResults that get logged.
    """

    def __init__(self, grid: Grid):
        self.grid = grid
        self.event_log: List[TerrainEvent] = []

    def clear_log(self) -> None:
        self.event_log = []

    # ------------------------------------------------------------------
    # Terrain interactions
    # ------------------------------------------------------------------

    def resolve_movement(
        self,
        unit: Unit,
        target_cell: Cell,
    ) -> Tuple[bool, Optional[TerrainEvent]]:
        """
        Attempt to move a unit to target_cell.
        Returns (success, terrain_event_if_any).

        This is the core physics call — it checks if movement triggers
        any terrain events (ice breaking, wall blocking, etc.).
        """
        can_move, reason = unit.can_move_to(target_cell)
        if not can_move:
            return False, None

        # Apply unit mass to cell — may trigger event
        raw_event = target_cell.apply_mass(unit.mass)

        terrain_event = None
        if raw_event == "ice_break":
            terrain_event = self._resolve_ice_break(
                cell=target_cell,
                triggered_by=unit.id,
                trigger_type=unit.unit_type.value,
                mass=unit.mass,
            )
            self.event_log.append(terrain_event)
            # Unit that broke the ice takes damage
            unit.take_damage(0.4, source="ice_break")
            terrain_event.casualties = 1 if not unit.is_alive() else 0

        # Actually move the unit
        unit.position = (target_cell.x, target_cell.y)
        unit._consume_supply()

        return True, terrain_event

    def resolve_group_movement(
        self,
        group: UnitGroup,
        target_cell: Cell,
    ) -> Tuple[bool, List[TerrainEvent]]:
        """
        Move an entire group to target_cell.
        Group mass accumulates — can break terrain single units couldn't.
        Returns (success, list_of_terrain_events).
        """
        can_move, reason = group.can_move_to(target_cell)
        if not can_move:
            return False, []

        events = []
        # Reset cell mass for accurate group calculation
        previous_mass = target_cell.current_mass

        for unit in group.alive_units:
            _, event = self.resolve_movement(unit, target_cell)
            if event:
                events.append(event)

        return True, events

    def resolve_siege_attack(
        self,
        siege_unit: Unit,
        target_cell: Cell,
    ) -> Optional[TerrainEvent]:
        """
        Siege unit attacks a fortification.
        Checks if force exceeds wall collapse threshold.
        """
        if target_cell.terrain != TerrainType.WALL:
            return None
        if target_cell.is_broken:
            return None

        force = siege_unit.effective_attack_force(target_cell)
        physics = TERRAIN_PHYSICS[TerrainType.WALL]
        threshold = physics["collapse_threshold"]

        if force >= threshold:
            target_cell.is_broken = True
            target_cell.has_rubble = True
            target_cell.mobility_cost = 1.8  # rubble slows but passable

            event = TerrainEvent(
                event_type="wall_collapse",
                location=(target_cell.x, target_cell.y),
                triggered_by=siege_unit.id,
                trigger_type="siege",
                force_applied=force,
                blocks_movement=False,  # rubble passable
            )

            # Check if collapse creates secondary rubble in adjacent cells
            adjacent = self.grid.neighbors(target_cell.x, target_cell.y, radius=1)
            for adj in adjacent:
                if adj.terrain == TerrainType.WALL and not adj.is_broken:
                    # Partial collapse from shockwave
                    adj.stability = max(0.0, adj.stability - 0.3)

            self.event_log.append(event)
            return event

        return None

    def resolve_tree_fall(
        self,
        unit: Unit,
        forest_cell: Cell,
        swing_force: Optional[float] = None,
    ) -> Optional[TerrainEvent]:
        """
        Heavy units or cavalry charges through forest can fell trees.
        Fallen trees create movement obstacles and ambush opportunities.
        """
        if forest_cell.terrain != TerrainType.FOREST:
            return None

        physics = TERRAIN_PHYSICS[TerrainType.FOREST]
        threshold = physics.get("tree_fall_force", 500.0)
        force = swing_force or unit.effective_attack_force(forest_cell)

        if force >= threshold:
            # Trees fall — increase cover temporarily, slow movement
            forest_cell.cover = min(1.0, forest_cell.cover + 0.2)
            forest_cell.mobility_cost = min(4.0, forest_cell.mobility_cost + 1.0)

            event = TerrainEvent(
                event_type="tree_fall",
                location=(forest_cell.x, forest_cell.y),
                triggered_by=unit.id,
                trigger_type=unit.unit_type.value,
                force_applied=force,
                blocks_movement=forest_cell.mobility_cost >= 4.0,
            )
            self.event_log.append(event)
            return event

        return None

    def resolve_flood(
        self,
        river_cell: Cell,
        weather: str = "clear",
    ) -> Optional[TerrainEvent]:
        """
        Heavy rain can trigger river flooding, expanding into adjacent cells.
        """
        if river_cell.terrain != TerrainType.RIVER:
            return None

        physics = TERRAIN_PHYSICS[TerrainType.RIVER]
        if weather != physics.get("flood_trigger", "heavy_rain"):
            return None

        river_cell.is_flooded = True
        flooded_adjacent = []

        adjacent = self.grid.neighbors(river_cell.x, river_cell.y, radius=1)
        for adj in adjacent:
            if adj.terrain == TerrainType.PLAIN and not adj.is_flooded:
                adj.is_flooded = True
                adj.mobility_cost = min(adj.mobility_cost + 2.0, 4.0)
                flooded_adjacent.append((adj.x, adj.y))

        if flooded_adjacent:
            event = TerrainEvent(
                event_type="flood",
                location=(river_cell.x, river_cell.y),
                triggered_by="weather",
                trigger_type="weather",
                force_applied=0.0,
                cascade_cells=flooded_adjacent,
                blocks_movement=True,
            )
            self.event_log.append(event)
            return event

        return None

    # ------------------------------------------------------------------
    # Ice cascade
    # ------------------------------------------------------------------

    def _resolve_ice_break(
        self,
        cell: Cell,
        triggered_by: str,
        trigger_type: str,
        mass: float,
    ) -> TerrainEvent:
        """
        Resolve ice breaking including cascade to adjacent ice cells.
        """
        cascade_cells = self.grid.trigger_cascade(cell.x, cell.y)

        return TerrainEvent(
            event_type="ice_break",
            location=(cell.x, cell.y),
            triggered_by=triggered_by,
            trigger_type=trigger_type,
            force_applied=mass,
            cascade_cells=cascade_cells,
            blocks_movement=True,
        )

    # ------------------------------------------------------------------
    # Combat physics
    # ------------------------------------------------------------------

    def resolve_combat(
        self,
        attacker: Unit,
        defender: Unit,
        combat_cell: Cell,
    ) -> CombatResult:
        """
        Resolve one unit attacking another.
        Force from attacker → damage to defender.
        Combat can also trigger terrain events (e.g. cavalry charge
        through forest fells trees, siege attack collapses wall).
        """
        force = attacker.effective_attack_force(combat_cell)

        # Damage calculation: force normalized by unit mass gives damage ratio
        # Infantry at full force (~200N) vs infantry (80kg) → ~0.15 damage
        # Cavalry charge (~800N) vs infantry → ~0.6 damage
        base_damage = force / (defender.mass * 8.0)
        base_damage = min(1.0, base_damage)

        # Cover reduces damage to defender
        cover_reduction = combat_cell.cover * 0.4
        actual_damage = max(0.0, base_damage - cover_reduction)

        damage_report = defender.take_damage(actual_damage, source=attacker.unit_type.value)

        # Check if combat triggered a terrain event
        terrain_event = None
        if (attacker.unit_type == UnitType.SIEGE
                and combat_cell.terrain == TerrainType.WALL):
            terrain_event = self.resolve_siege_attack(attacker, combat_cell)
        elif (attacker.unit_type in (UnitType.CAVALRY, UnitType.INFANTRY)
                and combat_cell.terrain == TerrainType.FOREST):
            terrain_event = self.resolve_tree_fall(attacker, combat_cell)

        return CombatResult(
            attacker_id=attacker.id,
            attacker_type=attacker.unit_type.value,
            attacker_owner=attacker.owner,
            defender_id=defender.id,
            defender_type=defender.unit_type.value,
            defender_owner=defender.owner,
            force_applied=force,
            damage_dealt=actual_damage,
            defender_killed=not defender.is_alive(),
            terrain_type=combat_cell.terrain.value,
            terrain_event=terrain_event,
        )

    # ------------------------------------------------------------------
    # Elevation physics
    # ------------------------------------------------------------------

    def elevation_modifier(
        self,
        attacker_cell: Cell,
        defender_cell: Cell,
        unit_type: UnitType,
    ) -> float:
        """
        Compute force modifier from elevation difference.
        Attacking uphill is penalized. Attacking downhill is a bonus.
        Returns multiplier (1.0 = neutral).
        """
        elev_diff = attacker_cell.elevation - defender_cell.elevation

        if elev_diff > 0:
            # Attacking downhill — bonus
            bonus = min(0.25, elev_diff / 40.0)
            return 1.0 + bonus
        else:
            # Attacking uphill — penalty scales with unit's uphill_penalty stat
            # Cavalry (0.35) is penalized much more than infantry (0.10)
            stats = UNIT_BASE_STATS[unit_type]
            penalty_rate = stats.get("uphill_penalty", 0.10)
            # Scale: at elev_diff=15, infantry gets ~0.15 penalty, cavalry ~0.525
            penalty = min(0.6, abs(elev_diff) / 20.0 * penalty_rate * 4)
            return max(0.35, 1.0 - penalty)

    # ------------------------------------------------------------------
    # Weather effects
    # ------------------------------------------------------------------

    def apply_weather(
        self,
        weather: str,
        units: List[Unit],
    ) -> List[TerrainEvent]:
        """
        Apply weather effects to battlefield and units.
        Weather is an external force the General cannot fully control
        but can learn to exploit.
        """
        events = []

        if weather == "heavy_rain":
            # All rivers may flood
            for y in range(self.grid.height):
                for x in range(self.grid.width):
                    cell = self.grid.cells[y][x]
                    if cell.terrain == TerrainType.RIVER:
                        event = self.resolve_flood(cell, weather)
                        if event:
                            events.append(event)
            # Units in open terrain take minor morale hit
            for unit in units:
                if unit.is_alive():
                    ux, uy = unit.position
                    cell = self.grid.get(ux, uy)
                    if cell and cell.terrain == TerrainType.PLAIN:
                        unit.morale = max(0.0, unit.morale - 0.05)

        elif weather == "blizzard":
            # Frozen lakes become MORE brittle (lower threshold)
            for y in range(self.grid.height):
                for x in range(self.grid.width):
                    cell = self.grid.cells[y][x]
                    if cell.terrain == TerrainType.FROZEN_LAKE and not cell.is_broken:
                        cell.break_threshold = max(
                            400.0,
                            cell.break_threshold - 200.0
                        )
            # All units lose supply faster
            for unit in units:
                if unit.is_alive():
                    unit.supply = max(0.0, unit.supply - 0.1)

        elif weather == "fog":
            # No terrain events, but archer range effectively halved
            # (handled in battle.py by checking weather state)
            pass

        return events

    # ------------------------------------------------------------------
    # Summary for episode logging
    # ------------------------------------------------------------------

    def get_event_summary(self) -> List[dict]:
        """
        Return all terrain events as brain-facing observations.
        Raw physics stripped out — only militarily relevant outcomes.
        """
        return [e.to_observation() for e in self.event_log]
