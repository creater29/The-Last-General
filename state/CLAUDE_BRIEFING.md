# CLAUDE_BRIEFING.md
# Read this first. Read it completely. Do not skip sections.
# This document exists because you have no memory of previous sessions.

---

## What This Project Is

"The Last General's Mind" — a standalone AI brain for a game boss character.
The Last General is a centuries-old commander who:
- Learns individual players across encounters
- Forms generalizable military doctrines from battlefield experience
- Reasons like a commander (intents, principles) not like an optimizer (coordinates, stats)

This is NOT a game. This is the brain only.
Unreal Engine integration is a future concern — ignore it entirely.
The project is built for Arman's personal satisfaction, not for fun or commercial goals.

---

## Who You Are Talking To

Arman. He built this with Claude across multiple sessions.
He understands the architecture. Do not over-explain basics to him.
He values directness and honest assessment over optimism.

---

## Critical Rules — Never Violate These

### Rule 1: The General never sees raw coordinates
Zone coordinates (_center_x, _center_y) are simulator-internal only.
They are prefixed with underscore and stripped before any brain-facing output.
If you write brain code that uses x/y positions directly — you have violated this.

### Rule 2: The General never sees raw physics constants
TERRAIN_PHYSICS (in grid.py) and UNIT_BASE_STATS (in units.py) are
simulator ground truth. The brain NEVER imports from these files.
The General discovers physics through observed episode outcomes, not by reading constants.

### Rule 3: The brain imports from logger.py and snapshot.py only
src/brain/ files may import from:
  - simulator/logger.py   (DB reads/writes)
  - simulator/snapshot.py (CommanderKnowledge only — the perception bridge)
  - each other (brain modules can import brain modules)
src/brain/ files must NEVER import from:
  - simulator/grid.py
  - simulator/units.py
  - simulator/physics.py
  - simulator/battle.py
If you write a brain file that imports from any simulator file except logger.py
or snapshot.py, you have violated the architecture.

NOTE: simulator/snapshot.py is permitted because CommanderKnowledge is the
formally defined perception object — the only view of live battle state the
brain is allowed to consume. It contains no coordinates, no Unit objects,
no physics constants, and no post-turn truth (combat results, final units).
It is perception, not reality.

### Rule 4: Doctrines are anonymous — no player_id
Doctrines live in the doctrines table. They have NO player_id field.
If the General learns "cavalry breaks ice" from one player,
that knowledge transfers to ALL future players without revealing who taught it.
Player-specific memory lives ONLY in player_profiles and player_general_relationship.

### Rule 5: Observations precede doctrines
A doctrine forms ONLY when 5+ observations share the same
(terrain_context, observed_effect) pattern.
Never create a doctrine from a single episode.
The observation table is the evidence pool. Doctrines are conclusions drawn from it.

---

## Project Structure

```
~/Projects/general_brain/
├── state/
│   ├── ARCHITECTURE.md          ← full design spec, read this
│   ├── PROGRESS.md              ← what's built, what's next
│   ├── KNOWN_ISSUES.md          ← bugs found and fixed, watch list
│   ├── SESSION_HANDOFF.md       ← exact starting point for next task
│   └── CLAUDE_BRIEFING.md       ← this file
├── src/
│   ├── simulator/               ← Stage 1 COMPLETE
│   │   ├── grid.py              ← terrain world (12 tests)
│   │   ├── units.py             ← unit types and behavior (29 tests)
│   │   ├── physics.py           ← terrain interaction engine (23 tests)
│   │   ├── battle.py            ← battle loop, intent execution (26 tests)
│   │   └── logger.py            ← SQLite persistence (27 tests)
│   └── brain/                   ← Stage 2 NOT STARTED
│       ├── world_model.py       ← NEXT FILE TO BUILD
│       ├── doctrine_extractor.py
│       ├── player_profiler.py
│       ├── decision_engine.py
│       └── memory.py
├── data/
│   └── episodes/
│       └── general_brain.db     ← SQLite database (exists, has data)
├── tests/
│   ├── test_grid.py
│   ├── test_units.py
│   ├── test_physics.py
│   ├── test_battle.py
│   └── test_logger.py
└── README.md
```

---

## Current State (Stage 1 Complete)

All simulator files are built and tested. Do NOT modify simulator files
unless fixing a confirmed bug. They are done.

Test suite: 117/117 passing
Database: 100 episodes, 6526 observations

Run to verify:
```bash
cd ~/Projects/general_brain
python3 -m pytest tests/ --tb=short
```

---

## Database Contents Right Now

```
episodes:             100   (completed battle records)
observations:         6526  (terrain events extracted from episodes)
doctrines:            0     (brain hasn't run yet)
player_profiles:      0     (brain hasn't run yet)
relationships:        0     (brain hasn't run yet)
terrain_knowledge:    0     (brain hasn't run yet)
counter_doctrines:    0     (brain hasn't run yet)
```

Observation breakdown:
  flood:          6296  (dominant — weather-driven, from heavy_rain)
  tree_fall:       146
  wall_collapse:    78
  ice_break:         6  (rare — cavalry/siege on frozen lakes)

Result distribution across 100 battles:
  loss:  63
  draw:  24
  win:   13

---

## The Three Memory Stores (Critical Architecture)

### 1. player_profiles table
"What does THIS player do?"
Player-specific. Has player_id. Tactical + strategic + psychological fields.
Tracks: favorite_opening, flank_frequency, retreat_threshold, aggression_score, etc.

### 2. doctrines table
"What have I learned about war itself?"
ANONYMOUS. NO player_id. General military knowledge.
Forms from patterns across many players. No single player's identity attached.
Example: "frozen_lake + cavalry → ice_break" (learned from observation patterns)

### 3. player_general_relationship table
"What is my personal history with THIS player?"
Has player_id. Trust level, betrayal count, cooperation history, predictions.
Purely relational — not tactical, not doctrinal.

---

## Key Data Structures

### Episode (what logger.py stores, what brain reads)
```python
{
    "id": str,
    "player_id": str,
    "age": int,
    "battlefield": {
        "terrain_distribution": {...},
        "dominant_terrain": str,
        "has_frozen_lake": bool,
        "has_river": bool,
        "has_walls": bool,
        "elevation_variance": float,
        "hazard_coverage": float,
        "forest_coverage": float,
    },
    "top_zones": [
        {
            "zone_type": str,        # high_ground | chokepoint | ambush_corridor |
                                     # hazard_zone | fortified | supply_corridor | open_field
            "avg_cover": float,
            "avg_mobility": float,
            "avg_elevation": float,
            "has_hazard": bool,
            "military_value": float,
            # NOTE: NO center_x, NO center_y — coordinates stripped
        }
    ],
    "general_intents": [str, ...],   # per turn: aggressive_push, flank_attempt, etc.
    "player_intents": [str, ...],    # per turn: attack_center, defend, etc.
    "terrain_events": [
        {
            "event_type": str,           # ice_break | tree_fall | wall_collapse | flood
            "terrain_at_site": str,      # frozen_lake | forest | wall | river
            "triggered_by_type": str,    # cavalry | siege | infantry | weather
            "scale": str,                # minor | moderate | major
            "casualties": int,
            "blocks_movement": bool,
            "cascade_occurred": bool,
            "cascade_size": int,
            # NOTE: NO raw force values, NO break_threshold
        }
    ],
    "combat_results": [
        {
            "attacker_type": str,
            "defender_type": str,
            "outcome": str,              # kill | damage
            "terrain": str,
            "terrain_event": dict or None,
            # NOTE: NO force_applied, NO damage_dealt numbers
        }
    ],
    "turns_played": int,
    "result": str,                   # win | loss | draw
    "general_unit_summary": {
        "total": int, "surviving": int,
        "loss_rate": float, "avg_health": float,
        "avg_supply": float, "avg_morale": float,
    },
    "player_unit_summary": {same structure},
}
```

### Observation (what logger.py extracts, what doctrine_extractor reads)
```python
{
    "id": str,
    "episode_id": str,
    "timestamp": str,
    "terrain_context": str,    # e.g. "frozen_lake+cavalry"
    "action_taken": str,       # e.g. "terrain_exploit"
    "observed_effect": str,    # e.g. "ice_break"
    "confidence": float,       # starts at 1.0
    "last_verified": str,
    "decay_rate": float,
}
```

---

## Intent Vocabulary

### General's intents (GeneralIntent enum in battle.py)
aggressive_push | defensive_hold | flank_attempt | terrain_exploit |
supply_raid | ambush | retreat | siege

### Player's intents (PlayerIntent enum in battle.py)
attack_center | attack_flank | defend | retreat | siege |
supply_protect | aggressive_rush

---

## Terrain Types
plain | frozen_lake | forest | hill | river | road | wall

## Unit Types
infantry (80kg) | cavalry (600kg) | archer (70kg) | siege (2000kg)
Mass matters: cavalry+siege can break frozen lakes (threshold 800kg)

---

## Stage 2 Build Order

1. world_model.py       ← START HERE
2. doctrine_extractor.py
3. player_profiler.py
4. decision_engine.py
5. memory.py

---

## What world_model.py Must Do

The world model is how the General builds terrain knowledge from observations.
It reads from terrain_knowledge table (starts empty) and populates it
by reading observation patterns from the DB.

Required methods:
- update_from_observations(logger) → scan observation_patterns, populate terrain_knowledge
- get_terrain_belief(terrain_type, action_type) → dict with confidence + outcomes
- get_all_beliefs() → full current world model dict
- get_high_confidence_beliefs(threshold=0.6) → only reliable knowledge

Must NOT import from: grid.py, units.py, physics.py, battle.py
May import from: logger.py, standard library, numpy

The General starts knowing nothing. After reading 6526 observations,
he should have beliefs about which terrain+action combinations produce which effects.

---

## Hardware
MacBook Air M1, 8GB RAM, ~40GB available, macOS Sequoia 15.7.3
Python 3.12.4, numpy 1.26.4, pytest 9.0.2, SQLite 3.45.3
Project path: ~/Projects/general_brain

---

## How to Start a Session

1. Run verification:
```bash
cd ~/Projects/general_brain
python3 -m pytest tests/ --tb=short   # must be 117/117
```

2. Read state files in this order:
   - state/CLAUDE_BRIEFING.md   (this file — already reading)
   - state/ARCHITECTURE.md      (full design)
   - state/PROGRESS.md          (current status)
   - state/KNOWN_ISSUES.md      (bugs and risks)
   - state/SESSION_HANDOFF.md   (exact next task)

3. Read existing source files relevant to current task before writing any code.

4. Never guess at file contents — read them.
