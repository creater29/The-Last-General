"""
snapshot.py — CommanderKnowledge: what the General perceives during a battle.

This module bridges the simulator and the brain. It defines the only object
the decision engine is allowed to consume about the current battle state.

Two projections from BattleLoop:
    BattleLoop.to_episode()           → post-battle learning (all truth)
    BattleLoop.to_brain_snapshot()    → live decision input (perception only)

Design rule:
    The simulator knows reality.
    The General knows perception.
    These are different objects for a reason.

What CommanderKnowledge deliberately omits:
    - Grid cells, Cell objects, coordinates
    - Unit objects (roster, types, positions)
    - PhysicsEngine values
    - terrain_events (post-event — happens after the turn, not before)
    - combat_results
    - final result

What it contains:
    - What the General can currently see or infer
    - Aggregate enemy presence (not a unit roster — hidden armies unknown)
    - Terrain types present on the battlefield (not coordinates)
    - Weather (observable)
    - Events visible so far this battle

Future extensions (Stage 3+):
    - known_enemy_units → populated by scout reports, not battlefield truth
    - intel_confidence  → how reliable the current information is
    - active_threats    → when threat-assessment layer exists
    - current_objectives→ when objective system exists
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List


@dataclass
class CommanderKnowledge:
    """
    The General's current perceived state of the battlefield.

    Every field represents what the General can know — not what exists.
    The decision engine must never receive raw simulator truth.

    Fields:
        server_id             — which server this battle is on
        player_id             — opponent identifier
        turn                  — current turn number
        weather               — currently observed weather condition
        battlefield_features  — terrain types present {has_frozen_lake, has_river,
                                has_walls, has_forest, has_hazard}
        known_enemy_presence  — observable enemy state: count, avg_health,
                                avg_morale, avg_supply (no unit type roster)
        known_friendly_state  — General's own forces: count, avg_health,
                                avg_morale, avg_supply, has_siege, has_cavalry
        visible_terrain       — list of terrain type strings currently on field
                                e.g. ["frozen_lake", "river", "forest"]
        visible_events        — terrain events observed so far this battle
                                e.g. [{"event_type": "ice_break", ...}]
    """
    server_id:             str
    player_id:             str
    turn:                  int
    weather:               str
    battlefield_features:  dict
    known_enemy_presence:  dict
    known_friendly_state:  dict
    visible_terrain:       List[str] = field(default_factory=list)
    visible_events:        List[dict] = field(default_factory=list)
