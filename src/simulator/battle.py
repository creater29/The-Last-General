"""
battle.py — The battle loop.

Connects Grid + Units + PhysicsEngine into a running simulation.
Produces a complete BattleState that logger.py will persist.

Turn structure per turn:
  1. Weather effects applied
  2. Supply ticked for all units
  3. General chooses intent → executed as unit actions
  4. Player acts (scripted or random for simulator purposes)
  5. Physics resolves all interactions
  6. Battle end condition checked

The General's intent is always abstracted (aggressive_push, flank_attempt...)
never raw coordinates. This is the abstraction boundary that makes
doctrine formation possible.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple
from enum import Enum
import random
import uuid

from simulator.grid import Grid, Cell, TerrainType
from simulator.units import Unit, UnitGroup, UnitType, make_unit, make_group
from simulator.physics import PhysicsEngine, TerrainEvent, CombatResult


# ---------------------------------------------------------------------------
# Intents — the abstraction layer between brain and action
# ---------------------------------------------------------------------------

class GeneralIntent(str, Enum):
    AGGRESSIVE_PUSH   = "aggressive_push"    # direct advance on enemy
    DEFENSIVE_HOLD    = "defensive_hold"     # hold current position
    FLANK_ATTEMPT     = "flank_attempt"      # move around enemy flank
    TERRAIN_EXPLOIT   = "terrain_exploit"    # use hazardous terrain as weapon
    SUPPLY_RAID       = "supply_raid"        # target enemy supply lines
    AMBUSH            = "ambush"             # set up in cover, wait
    RETREAT           = "retreat"            # pull back to regroup
    SIEGE             = "siege"              # assault fortifications


class PlayerIntent(str, Enum):
    ATTACK_CENTER     = "attack_center"
    ATTACK_FLANK      = "attack_flank"
    DEFEND            = "defend"
    RETREAT           = "retreat"
    SIEGE             = "siege"
    SUPPLY_PROTECT    = "supply_protect"
    AGGRESSIVE_RUSH   = "aggressive_rush"


WEATHER_CONDITIONS = ["clear", "fog", "heavy_rain", "blizzard", "wind"]


# ---------------------------------------------------------------------------
# Turn Record — what happened in one turn
# ---------------------------------------------------------------------------

@dataclass
class TurnRecord:
    """
    Full record of one turn. Feeds into episode log.
    Contains both raw events (for physics verification) and
    brain-facing observations (for doctrine formation).
    """
    turn_number:      int
    weather:          str
    general_intent:   str
    player_intent:    str
    terrain_events:   List[dict]     # from physics engine (observations only)
    combat_results:   List[dict]     # attacker/defender outcomes (observations only)
    general_losses:   float          # total health lost by general's units
    player_losses:    float          # total health lost by player's units
    supply_states:    dict           # general/player supply status this turn
    zone_contested:   Optional[str]  # which military zone saw action this turn


# ---------------------------------------------------------------------------
# Battle State
# ---------------------------------------------------------------------------

@dataclass
class BattleState:
    """
    Complete state of a battle — before, during, and after.
    This is what logger.py persists as an Episode.
    """
    battle_id:        str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    player_id:        str = "player_unknown"
    age:              int = 1        # which age/era this battle occurred in
    seed:             int = 0

    # Participants
    general_units:    List[Unit] = field(default_factory=list)
    player_units:     List[Unit] = field(default_factory=list)

    # Battlefield snapshot at start (features only — no raw coords)
    battlefield_features: dict = field(default_factory=dict)
    top_military_zones:   List[dict] = field(default_factory=list)

    # What happened
    turn_records:     List[TurnRecord] = field(default_factory=list)
    terrain_events:   List[dict]       = field(default_factory=list)  # all turns combined
    combat_results:   List[dict]       = field(default_factory=list)  # all turns combined

    # Outcome
    result:           str  = "in_progress"  # win | loss | draw — set only by _determine_result()
    turns_played:     int  = 0
    final_weather:    str  = "clear"

    # General's decision record (for doctrine formation)
    general_intents:  List[str] = field(default_factory=list)
    player_intents:   List[str] = field(default_factory=list)

    def to_episode(self) -> dict:
        """
        Convert to episode dict for the brain.
        Raw physics stripped — only brain-facing observations remain.
        """
        # Strip simulator-internal keys (prefixed with _) from zone data
        # before handing to brain. Coordinates stay in the simulator layer.
        clean_zones = [
            {k: v for k, v in z.items() if not k.startswith("_")}
            for z in self.top_military_zones
        ]

        return {
            "id":                   self.battle_id,
            "player_id":            self.player_id,
            "age":                  self.age,
            "battlefield":          self.battlefield_features,
            "top_zones":            clean_zones,
            "general_intents":      self.general_intents,
            "player_intents":       self.player_intents,
            "terrain_events":       self.terrain_events,
            "combat_results":       self.combat_results,
            "turns_played":         self.turns_played,
            "result":               self.result,
            "general_unit_summary": self._unit_summary(self.general_units),
            "player_unit_summary":  self._unit_summary(self.player_units),
        }

    def _unit_summary(self, units: List[Unit]) -> dict:
        alive = [u for u in units if u.is_alive()]
        # Count starting units by type so the brain can track unit composition.
        type_counts: Dict[str, int] = {}
        for u in units:
            label = u.unit_type.value
            type_counts[label] = type_counts.get(label, 0) + 1
        return {
            "total":       len(units),
            "surviving":   len(alive),
            "loss_rate":   round(1.0 - len(alive) / max(1, len(units)), 3),
            "avg_health":  round(sum(u.health for u in alive) / max(1, len(alive)), 3),
            "avg_supply":  round(sum(u.supply for u in alive) / max(1, len(alive)), 3),
            "avg_morale":  round(sum(u.morale for u in alive) / max(1, len(alive)), 3),
            "unit_types":  type_counts,
        }


# ---------------------------------------------------------------------------
# Battle Loop
# ---------------------------------------------------------------------------

class BattleLoop:
    """
    Runs a complete battle between the General and a player.

    For the simulator, the player acts via scripted/random intents.
    The General's intent comes from outside (will be the brain in Stage 2).
    For Stage 1, the General also uses scripted/random intents so we can
    generate training episodes.
    """

    MAX_TURNS = 30

    def __init__(
        self,
        grid:            Grid,
        general_units:   List[Unit],
        player_units:    List[Unit],
        player_id:       str = "player_sim",
        age:             int = 1,
        seed:            Optional[int] = None,
        weather_seed:    Optional[int] = None,
        weather_weights: Optional[Dict[str, float]] = None,
    ):
        self.grid          = grid
        self.physics       = PhysicsEngine(grid)
        self.general_units = general_units
        self.player_units  = player_units
        self.player_id     = player_id
        self.age           = age
        self.rng             = random.Random(seed)
        self.weather_rng     = random.Random(weather_seed or seed)
        self.weather_weights = weather_weights   # None = natural behaviour
        self.turn            = 0
        self.weather         = "clear"

        self.state = BattleState(
            player_id=player_id,
            age=age,
            seed=seed or 0,
            general_units=general_units,
            player_units=player_units,
        )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self, general_intent_fn=None) -> BattleState:
        """
        Run a complete battle to conclusion.

        general_intent_fn: callable(BattleState) → GeneralIntent
        If None, uses random intent selection (for data generation).
        """
        # Record battlefield at start
        self.state.battlefield_features = self.grid.battlefield_features()
        self.state.top_military_zones   = self.grid.top_military_zones(5)

        while not self._battle_over():
            self.turn += 1
            self._run_turn(general_intent_fn)

        self.state.turns_played  = self.turn
        self.state.final_weather = self.weather
        self.state.result        = self._determine_result()

        return self.state

    def to_brain_snapshot(
        self, server_id: str, player_id: str
    ) -> "CommanderKnowledge":
        """
        Return a CommanderKnowledge snapshot of the current live battle state.

        Called during a battle turn to give the decision engine a perception-
        filtered view of the battlefield. Omits coordinates, unit rosters,
        physics constants, and any information that requires a scout report.

        This is the only method in BattleLoop that the brain layer is
        permitted to call. All other BattleLoop state is simulator-internal.
        """
        from simulator.snapshot import CommanderKnowledge

        alive_friendly = [u for u in self.general_units if u.is_alive()]
        alive_enemy    = [u for u in self.player_units  if u.is_alive()]

        def _avg(units: list, attr: str) -> float:
            if not units:
                return 0.0
            return round(sum(getattr(u, attr) for u in units) / len(units), 3)

        # Friendly state — General knows his own forces fully
        known_friendly_state = {
            "count":       len(alive_friendly),
            "avg_health":  _avg(alive_friendly, "health"),
            "avg_morale":  _avg(alive_friendly, "morale"),
            "avg_supply":  _avg(alive_friendly, "supply"),
            "has_siege":   any(
                u.unit_type == UnitType.SIEGE for u in alive_friendly
            ),
            "has_cavalry": any(
                u.unit_type == UnitType.CAVALRY for u in alive_friendly
            ),
        }

        # Enemy state — aggregate only, no unit type roster
        # (hidden armies not reported by scouts remain unknown)
        known_enemy_presence = {
            "count":      len(alive_enemy),
            "avg_health": _avg(alive_enemy, "health"),
            "avg_morale": _avg(alive_enemy, "morale"),
            "avg_supply": _avg(alive_enemy, "supply"),
        }

        # Visible terrain — type strings only, no coordinates
        features = self.state.battlefield_features
        has_forest = bool(self.grid.cells_of_type(TerrainType.FOREST))
        visible_terrain: List[str] = []
        if features.get("has_frozen_lake"):  visible_terrain.append("frozen_lake")
        if features.get("has_river"):        visible_terrain.append("river")
        if features.get("has_walls"):        visible_terrain.append("wall")
        if has_forest:                       visible_terrain.append("forest")

        # Enrich battlefield_features with forest flag (not in grid method)
        full_features = {**features, "has_forest": has_forest}
        full_features["has_hazard"] = (
            features.get("has_frozen_lake", False)
            or features.get("has_river", False)
        )

        return CommanderKnowledge(
            server_id             = server_id,
            player_id             = player_id,
            turn                  = self.turn,
            weather               = self.weather,
            battlefield_features  = full_features,
            known_enemy_presence  = known_enemy_presence,
            known_friendly_state  = known_friendly_state,
            visible_terrain       = visible_terrain,
            visible_events        = list(self.state.terrain_events),
        )

    # ------------------------------------------------------------------
    # Turn execution
    # ------------------------------------------------------------------

    def _run_turn(self, general_intent_fn=None) -> None:
        self.physics.clear_log()

        # 1. Weather
        self.weather = self._update_weather()
        weather_events = self.physics.apply_weather(
            self.weather,
            self.general_units + self.player_units
        )

        # 2. Supply tick
        for u in self.general_units + self.player_units:
            if u.is_alive():
                u.tick_supply()

        # 3. General chooses intent
        if general_intent_fn:
            g_intent = general_intent_fn(self.state)
        else:
            g_intent = self._scripted_general_intent()

        # 4. Player acts (scripted for simulator)
        p_intent = self._scripted_player_intent()

        # 5. Execute intents → unit actions → physics
        g_combat = self._execute_general_intent(g_intent)
        p_combat = self._execute_player_intent(p_intent)

        # 6. Collect all events this turn
        all_events    = [e.to_observation() for e in self.physics.event_log]
        all_events    += [e.to_observation() for e in weather_events]
        all_combat    = [r.to_observation() for r in g_combat + p_combat]

        # 7. Compute losses this turn
        g_losses = float(sum(
            r.damage_dealt for r in p_combat
            if r.defender_owner == "general"
        ))
        p_losses = float(sum(
            r.damage_dealt for r in g_combat
            if r.defender_owner.startswith("player")
        ))

        # 8. Determine contested zone
        contested = self._contested_zone()

        # 9. Record turn
        record = TurnRecord(
            turn_number=self.turn,
            weather=self.weather,
            general_intent=g_intent.value,
            player_intent=p_intent.value,
            terrain_events=all_events,
            combat_results=all_combat,
            general_losses=round(g_losses, 3),
            player_losses=round(p_losses, 3),
            supply_states={
                "general": self._supply_state(self.general_units),
                "player":  self._supply_state(self.player_units),
            },
            zone_contested=contested,
        )

        self.state.turn_records.append(record)
        self.state.terrain_events.extend(all_events)
        self.state.combat_results.extend(all_combat)
        self.state.general_intents.append(g_intent.value)
        self.state.player_intents.append(p_intent.value)

    # ------------------------------------------------------------------
    # Intent execution
    # ------------------------------------------------------------------

    def _execute_general_intent(self, intent: GeneralIntent) -> List[CombatResult]:
        """
        Translate a high-level intent into unit actions.
        Returns list of combat results this turn.
        """
        results = []
        alive_general = [u for u in self.general_units if u.is_alive()]
        alive_player  = [u for u in self.player_units  if u.is_alive()]

        if not alive_general or not alive_player:
            return results

        if intent == GeneralIntent.AGGRESSIVE_PUSH:
            # Move forward and attack nearest player unit
            target = self.rng.choice(alive_player)
            tx, ty = target.position
            target_cell = self.grid.get(tx, ty)
            if target_cell:
                for unit in alive_general[:3]:  # commit up to 3 units
                    result = self.physics.resolve_combat(unit, target, target_cell)
                    results.append(result)

        elif intent == GeneralIntent.FLANK_ATTEMPT:
            # Attack with cavalry if available, otherwise infantry
            cavalry = [u for u in alive_general if u.unit_type == UnitType.CAVALRY]
            attackers = cavalry if cavalry else alive_general[:2]
            target = self.rng.choice(alive_player)
            tx, ty = target.position
            target_cell = self.grid.get(tx, ty)
            if target_cell:
                for unit in attackers:
                    result = self.physics.resolve_combat(unit, target, target_cell)
                    results.append(result)

        elif intent == GeneralIntent.TERRAIN_EXPLOIT:
            # Move heavy units toward hazardous terrain to trigger events
            hazard_zones = [
                z for z in self.grid.top_military_zones(5)
                if z["has_hazard"]
            ]
            if hazard_zones:
                zone = self.rng.choice(hazard_zones)
                zx, zy = zone["_center_x"], zone["_center_y"]
                hazard_cell = self.grid.get(zx, zy)
                if hazard_cell:
                    heavy = [u for u in alive_general
                             if u.unit_type in (UnitType.CAVALRY, UnitType.SIEGE)]
                    for unit in heavy[:2]:
                        self.physics.resolve_movement(unit, hazard_cell)
            # Also attack if possible
            if alive_player:
                target = self.rng.choice(alive_player)
                tx, ty = target.position
                target_cell = self.grid.get(tx, ty)
                if target_cell and alive_general:
                    result = self.physics.resolve_combat(
                        alive_general[0], target, target_cell
                    )
                    results.append(result)

        elif intent == GeneralIntent.SIEGE:
            # Use siege units against walls
            siege_units = [u for u in alive_general if u.unit_type == UnitType.SIEGE]
            wall_cells  = self.grid.cells_of_type(TerrainType.WALL)
            if siege_units and wall_cells:
                wall = self.rng.choice(wall_cells)
                for s in siege_units[:1]:
                    self.physics.resolve_siege_attack(s, wall)
            # Infantry/cavalry attack while siege works
            infantry = [u for u in alive_general if u.unit_type != UnitType.SIEGE]
            if infantry and alive_player:
                target = self.rng.choice(alive_player)
                tx, ty = target.position
                target_cell = self.grid.get(tx, ty)
                if target_cell:
                    result = self.physics.resolve_combat(
                        infantry[0], target, target_cell
                    )
                    results.append(result)

        elif intent == GeneralIntent.AMBUSH:
            # Move into forest cover, attack only if player advances
            forest_cells = self.grid.cells_of_type(TerrainType.FOREST)
            if forest_cells:
                cover = self.rng.choice(forest_cells)
                for unit in alive_general[:2]:
                    if unit.unit_type != UnitType.SIEGE:
                        self.physics.resolve_movement(unit, cover)
            # Archers attack from cover
            archers = [u for u in alive_general if u.unit_type == UnitType.ARCHER]
            if archers and alive_player:
                target = self.rng.choice(alive_player)
                tx, ty = target.position
                target_cell = self.grid.get(tx, ty)
                if target_cell:
                    for arc in archers[:2]:
                        result = self.physics.resolve_combat(arc, target, target_cell)
                        results.append(result)

        elif intent == GeneralIntent.SUPPLY_RAID:
            # Attack player units with lowest supply
            low_supply = sorted(alive_player, key=lambda u: u.supply)
            if low_supply and alive_general:
                target = low_supply[0]
                tx, ty = target.position
                target_cell = self.grid.get(tx, ty)
                if target_cell:
                    for unit in alive_general[:2]:
                        result = self.physics.resolve_combat(unit, target, target_cell)
                        results.append(result)

        elif intent == GeneralIntent.RETREAT:
            # No attacks — conserve units
            # Move toward own rear (high y = own territory in simulator)
            for unit in alive_general[:3]:
                ux, uy = unit.position
                retreat_cell = self.grid.get(ux, min(uy + 2, self.grid.height - 1))
                if retreat_cell:
                    self.physics.resolve_movement(unit, retreat_cell)

        elif intent == GeneralIntent.DEFENSIVE_HOLD:
            # Stay in position, counterattack if player is close
            if alive_player:
                target = self.rng.choice(alive_player)
                tx, ty = target.position
                target_cell = self.grid.get(tx, ty)
                if target_cell and alive_general:
                    # Only attack with archers at range
                    archers = [u for u in alive_general
                                if u.unit_type == UnitType.ARCHER]
                    for arc in archers[:2]:
                        result = self.physics.resolve_combat(arc, target, target_cell)
                        results.append(result)

        return results

    def _execute_player_intent(self, intent: PlayerIntent) -> List[CombatResult]:
        """Scripted player behavior for episode generation."""
        results = []
        alive_general = [u for u in self.general_units if u.is_alive()]
        alive_player  = [u for u in self.player_units  if u.is_alive()]

        if not alive_general or not alive_player:
            return results

        target = self.rng.choice(alive_general)
        tx, ty = target.position
        target_cell = self.grid.get(tx, ty)
        if not target_cell:
            return results

        if intent == PlayerIntent.ATTACK_CENTER:
            for unit in alive_player[:3]:
                result = self.physics.resolve_combat(unit, target, target_cell)
                results.append(result)

        elif intent == PlayerIntent.ATTACK_FLANK:
            cavalry = [u for u in alive_player if u.unit_type == UnitType.CAVALRY]
            attackers = cavalry if cavalry else alive_player[:2]
            for unit in attackers:
                result = self.physics.resolve_combat(unit, target, target_cell)
                results.append(result)

        elif intent == PlayerIntent.AGGRESSIVE_RUSH:
            for unit in alive_player[:4]:
                result = self.physics.resolve_combat(unit, target, target_cell)
                results.append(result)

        elif intent == PlayerIntent.SIEGE:
            siege = [u for u in alive_player if u.unit_type == UnitType.SIEGE]
            wall_cells = self.grid.cells_of_type(TerrainType.WALL)
            if siege and wall_cells:
                wall = self.rng.choice(wall_cells)
                for s in siege[:1]:
                    self.physics.resolve_siege_attack(s, wall)

        elif intent in (PlayerIntent.DEFEND, PlayerIntent.SUPPLY_PROTECT):
            # Archers only
            archers = [u for u in alive_player if u.unit_type == UnitType.ARCHER]
            for arc in archers[:2]:
                result = self.physics.resolve_combat(arc, target, target_cell)
                results.append(result)

        elif intent == PlayerIntent.RETREAT:
            for unit in alive_player[:3]:
                ux, uy = unit.position
                retreat_cell = self.grid.get(ux, max(uy - 2, 0))
                if retreat_cell:
                    self.physics.resolve_movement(unit, retreat_cell)

        return results

    # ------------------------------------------------------------------
    # Scripted intent selection (for data generation)
    # ------------------------------------------------------------------

    def _scripted_general_intent(self) -> GeneralIntent:
        """
        Simple heuristic intent for data generation.
        Later replaced by the brain's decision engine.
        """
        alive = [u for u in self.general_units if u.is_alive()]
        if not alive:
            return GeneralIntent.RETREAT

        avg_supply = sum(u.supply for u in alive) / len(alive)
        avg_health = sum(u.health for u in alive) / len(alive)
        has_siege  = any(u.unit_type == UnitType.SIEGE for u in alive)
        has_hazard = self.state.battlefield_features.get("has_frozen_lake", False) \
                  or self.state.battlefield_features.get("has_river", False)
        has_walls  = self.state.battlefield_features.get("has_walls", False)

        # Low supply → raid or retreat
        if avg_supply < 0.2:
            return self.rng.choice([GeneralIntent.SUPPLY_RAID, GeneralIntent.RETREAT])

        # Low health → defensive
        if avg_health < 0.3:
            return self.rng.choice([GeneralIntent.DEFENSIVE_HOLD, GeneralIntent.RETREAT])

        # Hazardous terrain present → exploit it
        if has_hazard and avg_health > 0.5:
            if self.rng.random() < 0.4:
                return GeneralIntent.TERRAIN_EXPLOIT

        # Siege available + walls present → siege
        if has_siege and has_walls:
            if self.rng.random() < 0.35:
                return GeneralIntent.SIEGE

        # Default: mix of offensive intents
        return self.rng.choice([
            GeneralIntent.AGGRESSIVE_PUSH,
            GeneralIntent.FLANK_ATTEMPT,
            GeneralIntent.AMBUSH,
            GeneralIntent.AGGRESSIVE_PUSH,  # weighted toward aggression
        ])

    def _scripted_player_intent(self) -> PlayerIntent:
        """Scripted player for data generation — varied behavior."""
        alive = [u for u in self.player_units if u.is_alive()]
        if not alive:
            return PlayerIntent.RETREAT

        avg_health = sum(u.health for u in alive) / len(alive)
        if avg_health < 0.25:
            return PlayerIntent.RETREAT

        return self.rng.choice([
            PlayerIntent.ATTACK_CENTER,
            PlayerIntent.ATTACK_FLANK,
            PlayerIntent.AGGRESSIVE_RUSH,
            PlayerIntent.DEFEND,
            PlayerIntent.ATTACK_CENTER,
        ])

    # ------------------------------------------------------------------
    # Battle end conditions
    # ------------------------------------------------------------------

    def _battle_over(self) -> bool:
        if self.turn >= self.MAX_TURNS:
            return True
        alive_general = [u for u in self.general_units if u.is_alive()]
        alive_player  = [u for u in self.player_units  if u.is_alive()]
        return len(alive_general) == 0 or len(alive_player) == 0

    def _determine_result(self) -> str:
        alive_general = [u for u in self.general_units if u.is_alive()]
        alive_player  = [u for u in self.player_units  if u.is_alive()]

        if self.turn >= self.MAX_TURNS:
            # Determine by casualties
            g_remaining = len(alive_general) / max(1, len(self.general_units))
            p_remaining = len(alive_player)  / max(1, len(self.player_units))
            if g_remaining > p_remaining + 0.1:
                return "win"
            elif p_remaining > g_remaining + 0.1:
                return "loss"
            return "draw"

        if not alive_player:
            return "win"
        if not alive_general:
            return "loss"
        return "draw"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _update_weather(self) -> str:
        """
        Weather changes occasionally.
        If weather_weights was supplied at construction, uses those weights
        for weighted random selection. Weights of 0.0 disable that condition.
        Default (None) preserves the original natural-generation behaviour.
        """
        if self.weather_weights:
            active = {w: wt for w, wt in self.weather_weights.items() if wt > 0.0}
            options = list(active.keys())
            weights = list(active.values())
            if self.turn == 1 or self.weather_rng.random() < 0.15:
                return self.weather_rng.choices(options, weights=weights, k=1)[0]
            return self.weather
        # Original natural behaviour
        if self.turn == 1:
            return self.weather_rng.choice(["clear", "clear", "clear", "fog", "heavy_rain"])
        if self.weather_rng.random() < 0.15:  # 15% chance of change per turn
            return self.weather_rng.choice(WEATHER_CONDITIONS)
        return self.weather

    def _supply_state(self, units: List[Unit]) -> str:
        alive = [u for u in units if u.is_alive()]
        if not alive:
            return "no_units"
        avg = sum(u.supply for u in alive) / len(alive)
        if avg > 0.6:  return "supplied"
        if avg > 0.2:  return "strained"
        return "starving"

    def _contested_zone(self) -> Optional[str]:
        """Which military zone type saw the most action this turn.
        Uses _center_x/_center_y (simulator-internal) for proximity check.
        These coordinates never leave the simulator layer.
        """
        events = self.physics.event_log
        if not events:
            return None
        zones = self.grid.top_military_zones(5)
        for event in events:
            ex, ey = event.location
            for zone in zones:
                cx = zone["_center_x"]   # simulator-internal only
                cy = zone["_center_y"]
                if abs(ex - cx) <= 10 and abs(ey - cy) <= 10:
                    return zone["zone_type"]
        return None
