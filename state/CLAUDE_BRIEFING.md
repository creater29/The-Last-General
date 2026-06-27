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
He values directness and honest technical assessment over encouragement.
He shares ChatGPT architectural reviews periodically — assess each critically,
accept correct points, push back on wrong or inapplicable ones, never adopt wholesale.

---

## Critical Rules — Never Violate These

### Rule 1: The General never sees raw coordinates
Zone coordinates (_center_x, _center_y) are simulator-internal only.
They are prefixed with underscore and stripped before any brain-facing output.
If you write brain code that uses x/y positions directly — you have violated this.
Enforced by test: test_no_coordinates_in_stored_episode()

### Rule 2: The General never sees raw physics constants
TERRAIN_PHYSICS (in grid.py) and UNIT_BASE_STATS (in units.py) are
simulator ground truth. The brain NEVER imports from these files.
The General discovers physics through observed episode outcomes, not by reading constants.

### Rule 3: The brain imports from logger.py and snapshot.py only
src/brain/ files may import from:
  - simulator/logger.py   (DB reads/writes — the only data access layer)
  - simulator/snapshot.py (CommanderKnowledge only — the live perception bridge)
  - each other (brain modules can import brain modules)
src/brain/ files must NEVER import from:
  - simulator/grid.py
  - simulator/units.py
  - simulator/physics.py
  - simulator/battle.py

snapshot.py is permitted because CommanderKnowledge is the formally defined
perception object — the only view of live battle state the brain may consume.
It contains no coordinates, no Unit objects, no physics constants, no post-turn
truth (combat results, final health). It is perception, not reality.

Enforced by source-inspection tests in every brain test file.

### Rule 4: Doctrines are anonymous — no player_id
Doctrines live in the doctrines table. They have NO player_id field.
If the General learns "cavalry breaks ice" from one player,
that knowledge transfers to ALL future players without revealing who taught it.
Player-specific memory lives ONLY in player_profiles.

### Rule 5: Observations precede doctrines
A doctrine forms ONLY when 5+ observations share the same
(terrain_context, observed_effect) pattern.
Never create a doctrine from a single episode.
The observation table is the evidence pool. Doctrines are conclusions.

### Rule 6: Persist facts, derive metrics
Raw evidence goes in the data JSON blob. Computed columns are derived from
raw evidence at write time (not at read time). If a formula changes, re-run
the profiler — never replay battles to recover lost raw data.
Applies to: player_profiles.data, observations, terrain_knowledge.

### Rule 7: Pre-coding confirmation protocol
Before writing any code in a new session:
1. Run pytest (must be 304/304)
2. Read all five state files fully
3. State your understanding of the next task to Arman
4. Wait for explicit confirmation before writing a line

---

## Project Structure (Current — Stage 2 Complete)

```
~/Projects/general_brain/
├── state/
│   ├── CLAUDE_BRIEFING.md       ← this file — read first
│   ├── ARCHITECTURE.md          ← full design spec
│   ├── PROGRESS.md              ← what is built and test counts
│   ├── KNOWN_ISSUES.md          ← bugs fixed, watch list
│   └── SESSION_HANDOFF.md       ← next task + open questions
├── src/
│   ├── simulator/               ← Stage 1 COMPLETE — do not modify without reason
│   │   ├── grid.py              ← terrain world (12 tests)
│   │   ├── units.py             ← unit types and behaviour (29 tests)
│   │   ├── physics.py           ← terrain interaction engine (23 tests)
│   │   ├── battle.py            ← battle loop + to_brain_snapshot() (26 tests)
│   │   ├── logger.py            ← SQLite persistence layer (31 tests)
│   │   ├── snapshot.py          ← CommanderKnowledge dataclass (NEW — 20 tests)
│   │   └── training_profiles.py ← corpus generation profiles (22 tests)
│   └── brain/                   ← Stage 2 COMPLETE
│       ├── world_model.py       ← terrain belief system (30 tests)
│       ├── doctrine_extractor.py← promotes beliefs to doctrines (36 tests)
│       ├── player_profiler.py   ← per-player behaviour profiles (35 tests)
│       └── decision_engine.py   ← hierarchical reasoning pipeline (43 tests)
├── scripts/
│   └── generate_corpus.py       ← CLI: targeted batch generation
├── data/
│   └── episodes/
│       └── general_brain.db     ← SQLite database (2000+ episodes)
└── tests/
    ├── test_grid.py             (12)
    ├── test_units.py            (29)
    ├── test_physics.py          (23)
    ├── test_battle.py           (26)
    ├── test_logger.py           (31)
    ├── test_training_profiles.py(22)
    ├── test_world_model.py      (30)
    ├── test_doctrine_extractor.py(36)
    ├── test_player_profiler.py  (35)
    ├── test_snapshot.py         (20)
    └── test_decision_engine.py  (43)
    Total: 304/304 passing
```

---

## Current DB State

```
episodes:          2000+
observations:
    flood:         118,124
    tree_fall:      20,396
    wall_collapse:  11,597
    ice_break:       1,011
terrain_knowledge: populated (refreshed by WorldModel.update_from_observations())
doctrines:         populated (refreshed by DoctrineExtractor.extract_doctrines())
player_profiles:   schema migrated — (server_id, player_id) composite PK
                   0 rows until update_profile() is called
```

---

## The Three Memory Stores (Critical Architecture)

### 1. player_profiles — server-scoped
"What does THIS player do on THIS server?"
PRIMARY KEY (server_id, player_id). Same player on a different server
starts with a clean slate — the General has no global reputation database.
Tracks: raw evidence in data blob + computed aggression_index, adaptability_score,
preferred_units {type: {used, wins}}, terrain_tendencies {terrain: {count, wins, losses}}.

### 2. doctrines — anonymous
"What have I learned about war itself?"
NO player_id anywhere. Anonymous military knowledge.
Formed when 5+ observations share the same (terrain_context, effect) pattern.
Example: doctrine_frozen_lake_cavalry_ice_break →
"Heavy cavalry on frozen lakes risks ice breakage." (confidence 0.9998)

### 3. player_general_relationship — NOT YET BUILT
"What is my personal history with THIS player?"
Has player_id. Trust level, betrayal count, cooperation history.
Not tactical, not doctrinal — purely relational.

---

## Key Data Structures

### CommanderKnowledge (live battle input to DecisionEngine)
```python
@dataclass
class CommanderKnowledge:
    server_id:             str
    player_id:             str
    turn:                  int
    weather:               str
    battlefield_features:  dict  # has_frozen_lake, has_river, has_walls,
                                 # has_forest, has_hazard
    known_enemy_presence:  dict  # count, avg_health, avg_morale, avg_supply
                                 # NO unit type roster — hidden armies unknown
    known_friendly_state:  dict  # count, avg_health, avg_morale, avg_supply,
                                 # has_siege, has_cavalry
    visible_terrain:       List[str]  # ["frozen_lake", "river"] — no coordinates
    visible_events:        List[dict] # terrain events seen so far this battle
```

### decide() output (DecisionEngine)
```python
{
    "intent":              str,        # e.g. "TERRAIN_EXPLOIT"
    "confidence":          float,      # normalised [0, 1]
    "reasoning":           List[str],  # why this intent was chosen
    "rejected":            List[str],  # eliminated intents + reasons
    "alternatives":        List[tuple],# [(intent, confidence)] top 2 runners-up
    "doctrines_consulted": List[str],  # doctrine ids that influenced decision
    "profile_used":        bool,       # True if player profile was available
}
```

### Intent strings (match GeneralIntent enum values in battle.py)
AGGRESSIVE_PUSH | DEFENSIVE_HOLD | FLANK_ATTEMPT | TERRAIN_EXPLOIT |
SUPPLY_RAID | AMBUSH | RETREAT | SIEGE

### Terrain types
plain | frozen_lake | forest | hill | river | road | wall

### Unit types + masses
infantry (80kg) | cavalry (600kg) | archer (70kg) | siege (2000kg)
Ice break threshold: 800kg. Siege always breaks. 2 cavalry together break.

---

## Decision Pipeline (hierarchical, not flat scoring)

```
CommanderKnowledge
      │
      ▼
1. Situation Filter — eliminate physically impossible intents
   SIEGE:           requires has_walls + has_siege units
   TERRAIN_EXPLOIT: requires has_hazard (frozen_lake or river)
   AMBUSH:          requires has_forest
      │
      ▼
2. Doctrine Evaluation — factor per intent from belief confidence
   INTENT_TERRAIN_RELEVANCE maps intents to terrain types
   Matching doctrine → factor in [0.8, 1.5]; no doctrine → 1.0 neutral
      │
      ▼
3. Player Adaptation — counter-tendency reasoning
   aggression_index > 0.65 → boost DEFENSIVE_HOLD / AMBUSH / TERRAIN_EXPLOIT
   player weak on visible terrain → boost TERRAIN_EXPLOIT
      │
      ▼
4. Situation Fit — weather, health, turn
   fog + AMBUSH → ×1.4 | blizzard + AGGRESSIVE_PUSH → ×0.7
   health < 0.3 + RETREAT → ×1.5 | health < 0.3 + AGGRESSIVE_PUSH → ×0.55
      │
      ▼
5. Multiplicative score = doctrine × player × situation
   Fallback: DEFENSIVE_HOLD always available, returned if all else fails
```

---

## Training Profiles (for corpus generation)

Five profiles defined in training_profiles.py:
- natural: unbiased, floods dominate
- anti_flood: heavy_rain=0.0, cavalry+siege composition
- terrain_learning: ice_break + tree_fall focus
- siege_learning: double siege, wall_collapse focus
- balanced: heavy_rain=0.0, targets 1000 each of ice_break/wall_collapse/tree_fall

Run corpus generation:
```bash
python3 scripts/generate_corpus.py --profile balanced --max-battles 5000
```

---

## How to Start a New Session

```bash
cd ~/Projects/general_brain
python3 -m pytest tests/ --tb=short -q   # must be 304/304
```

Then read state files in this exact order:
1. state/CLAUDE_BRIEFING.md   ← this file
2. state/ARCHITECTURE.md      ← full design
3. state/PROGRESS.md          ← what is built
4. state/KNOWN_ISSUES.md      ← risks and bugs
5. state/SESSION_HANDOFF.md   ← exact next task

Never write code before Arman confirms your understanding.
Never guess at file contents — read them with Desktop Commander.
