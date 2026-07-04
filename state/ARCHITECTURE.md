# The Last General's Mind — Architecture

## Project Identity
A standalone AI brain for "The Last General" — a centuries-old commander who learns
players across encounters, forms doctrines from battlefield experience, and reasons
like a commander rather than an optimizer.

This is NOT a game. This is the brain only.
Unreal integration is a future concern. Ignore it entirely until Stage 4+.

---

## Core Philosophy
- The General learns the PLAYER, not just tactics
- Doctrines generalize across battlefields (principles, not coordinates)
- Fun is explicitly NOT a design constraint
- The system is built for self-satisfaction and intellectual rigor

---

## System Boundaries
```
[Simulator]  →  generates episodes
[Brain]      →  consumes episodes, updates knowledge, makes decisions
[API]        →  exposes brain to outside world (Stage 3+)
[Unreal]     →  calls API (future, ignore now)
```

---

## Abstraction Hierarchy
```
Raw World (grid coordinates, cell properties)
    ↓
Terrain Features (cover, elevation, mobility, hazard potential)
    ↓
Military Zones (emergent: chokepoint, high_ground, ambush, supply — NOT hardcoded map slices)
    ↓
Observations (what the General witnessed — raw evidence, not yet generalized)
    ↓
Doctrines (generalized principles formed from N observations)
```

The General NEVER reasons in coordinates.
He reasons in principles derived FROM coordinates.

CRITICAL SEPARATION:
- Simulator owns TERRAIN_PHYSICS (ground truth, hardcoded)
- General owns terrain_knowledge in DB (observed, discovered through episodes)
- These NEVER share data. General is NOT initialized with physics values.

---

## Three Memory Systems — Orthogonality Rule (Permanent)

The General has three independent memory systems. Each answers a different question.
They must never answer each other's questions.

**Doctrine Memory** — "What works on the battlefield?"
  Military knowledge about terrain, weather, unit interactions.
  Examples: rivers flood under heavy rain, cavalry risk ice-break on frozen lakes.
  Encoded as: anonymous generalizable principles (no player_id).

**Player Profile** — "How does this commander usually fight?"
  Tactical understanding of a specific opponent's behaviour.
  Examples: aggressive tendency 0.72, prefers cavalry flanks, adapts quickly.
  Encoded as: per-player statistical profiles (server_id + player_id).

**Relationship Memory** — "What is my history with this commander?"
  Psychological state toward a specific opponent.
  Examples: trust level, betrayal count, willingness to commit or retreat.
  Encoded as: per-player relational state (server_id + player_id).

**The rule:**
These three systems must remain orthogonal.

  Doctrine must never encode player behaviour.
  Player Profile must never encode psychological history.
  Relationship must never encode battlefield tactics.

Relationship may influence only: risk tolerance, caution threshold, confidence
adjustment, willingness to retreat or regroup.

Relationship must NEVER directly score specific tactics:
AMBUSH, FLANK, SIEGE, CAVALRY_CHARGE, TERRAIN_EXPLOIT — those belong to
doctrines and player profiling.

**Interface rule — RelationshipManager is intent-blind AND modifier-blind:**
RelationshipManager returns raw relationship state, never computed modifiers
and never intent weights:
```python
@dataclass(frozen=True)
class RelationshipState:
    trust_level:              float  # [-1.0, 1.0]
    betrayal_count:           int
    cooperation_count:        int
    times_attempted_capture:  int
    known_deceptions:         int
    encounters:               int    # total battles vs this opponent
```
DecisionEngine computes psychological modifiers FROM this state and translates
them into intent score adjustments (`_relationship_factor()` in decision_engine.py):
```python
risk_modifier       = clamp(1.0 + trust_level * 0.15, 0.85, 1.15)
commitment_modifier = clamp(1.0 + trust_level * 0.15, 0.85, 1.15)
confidence_modifier = 1.0  # deferred — awaits prediction-accuracy evidence,
                           # NOT derived from betrayal_count (different concepts:
                           # "I trust him less" ≠ "I'm less confident in my read")
```
RelationshipManager must never reference intent names, and must never compute
modifiers — that interpretation step belongs exclusively to DecisionEngine.
This preserves: if relationship interpretation is later replaced (e.g. by a
learned evaluator), RelationshipManager and its storage remain untouched.

**RelationshipManager.get_state() always returns RelationshipState, never None.**
Unknown opponents return `RelationshipState.neutral()` — normalizing missing
data at the storage boundary, same philosophy as CommanderKnowledge (domain
layers operate on complete objects; persistence layers hide storage details).

**Distinguishing "never met" from "known neutral" — the `encounters` field:**
```
encounters == 0                      → never encountered this commander
encounters >  0, trust_level == 0.0  → known, currently neutral
```
This lives in the data, not the type system — avoids `Optional[RelationshipState]`
while still preserving the distinction for future features (diplomacy, negotiation)
that may need to behave differently for a stranger vs. a long-time neutral rival.

**Intent categories are a temporary implementation detail (see DEFERRED_ITEMS D022):**
`_relationship_factor()` currently classifies intents into HIGH_COMMITMENT / CAUTIOUS /
NEUTRAL via hardcoded sets in decision_engine.py. This is acceptable at 8 intents but
does not scale — it will be replaced by per-intent metadata (commitment/aggression/
exposure dimensions) when intent count or maintenance burden justifies it.
SUPPLY_RAID is classified NEUTRAL today because its risk profile is execution-dependent
(small raid vs. deep strike) — a distinction the current model cannot represent.

**Why this matters — the five-year explanation test:**
A decision should be fully explainable by citing exactly one contribution
from each system:
  "Forest → doctrine says ambush works here (military knowledge)
   Player often overextends left (tactical read)
   Low trust → General becomes cautious (psychological posture)
   → AMBUSH"

If relationship is producing tactic scores, the second and third lines
merge — and the explanation collapses. Any proposal that causes one system
to encode another's responsibility requires explicit architectural justification
before it can be accepted.

---

## Core Data Structures

### Cell
```python
Cell = {
    "x": int,
    "y": int,
    "terrain": str,          # frozen_lake, forest, hill, plain, river, road, wall
    "elevation": float,      # meters above baseline
    "cover": float,          # 0.0 - 1.0
    "mobility_cost": float,  # movement penalty multiplier
    "properties": {
        "break_threshold": float,   # ice/bridges: force required to break
        "flammability": float,      # forest/buildings
        "stability": float,         # walls, structures
        "temperature": float        # affects unit performance
    }
}
```

### Unit
```python
Unit = {
    "id": str,
    "type": str,             # infantry, cavalry, archer, siege
    "owner": str,            # "general" | "player"
    "position": (x, y),
    "health": float,         # 0.0 - 1.0
    "mass": float,           # affects terrain interactions
    "supply": float,         # 0.0 - 1.0
    "morale": float,         # 0.0 - 1.0
    "speed": float
}
```

### Episode
```python
Episode = {
    "id": str,               # uuid
    "timestamp": str,        # ISO format
    "player_id": str,
    "age": int,              # which age/cycle this occurred in
    "world_state_before": {
        "grid": [[Cell]],
        "units": [Unit],
        "weather": str,
        "time_of_day": str
    },
    "general_action": {
        "intent": str,       # ALWAYS intent, never coordinates
                             # aggressive_push | defensive_hold | flank_attempt
                             # terrain_exploit | supply_raid | retreat | ambush
        "units_committed": [str],
        "target_zone": str,  # descriptive: "enemy_left_flank", "center", "supply_line"
        "reasoning": str     # what doctrine/knowledge triggered this
    },
    "player_action": {
        "intent": str,
        "units_committed": [str],
        "target_zone": str
    },
    "outcome": {
        "terrain_events": [  # what the environment did
            {
                "type": str,         # ice_break, tree_fall, wall_collapse, flood
                "location": (x, y),
                "triggered_by": str, # unit_id or action type
                "casualties": int
            }
        ],
        "unit_casualties": {
            "general_losses": float,
            "player_losses": float
        },
        "territory_change": str,
        "supply_status": str,
        "result": str        # win | loss | draw | retreat
    }
}
```

### Doctrine
```python
Doctrine = {
    "id": str,
    "abstraction_level": str,    # physical | tactical | strategic | psychological
    "condition": str,            # plain English: "frozen terrain + heavy unit mass"
    "learned_effect": str,       # "ice fracture causing unit loss"
    "confidence": float,         # 0.0 - 1.0, Bayesian updated
    "episode_count": int,        # supporting evidence count
    "failure_count": int,        # counter-evidence count
    "derived_principle": str,    # "Frozen terrain vulnerable to concentrated mass impact"
    "exceptions": []             # conditions where doctrine fails
}
```

### Observation (NEW — sits between Episode and Doctrine)
```python
Observation = {
    "id": str,
    "episode_id": str,           # source episode
    "timestamp": str,
    "terrain_context": str,      # terrain type(s) present
    "action_taken": str,         # intent used
    "observed_effect": str,      # what actually happened
    "player_id": str,            # who caused/witnessed this
    "confidence": float,         # 1.0 initially, decays if contradicted
    "last_verified": str,        # ISO timestamp of last supporting episode
    "decay_rate": float          # how fast confidence drops without reinforcement
}
```
Doctrines form ONLY when N observations share the same (terrain_context, observed_effect) pattern.
N = 5 minimum before a doctrine is created. Before that, only observations exist.

### Player Memory — Three Separate Stores

The General has three distinct kinds of memory about players.
Each serves a different purpose and has different persistence behavior.

---

#### Store 1 — Player Profile (player_profiles table)
"What does THIS player do?"
Player-specific. Tied to player_id. Permanent per player.

```python
PlayerProfile = {
    "player_id": str,
    "encounter_count": int,
    "first_seen_age": int,
    "last_seen_age": int,

    # Tactical layer — how they fight in battle
    "tactical": {
        "favorite_opening": str,         # e.g. "left_flank_cavalry", "center_rush"
        "supply_raid_frequency": float,  # 0.0-1.0 how often they target supply
        "retreat_threshold": float,      # health level at which they retreat
        "ambush_usage": float,           # how often they use cover/ambush
        "siege_preference": float,       # reliance on siege weapons
        "flank_frequency": float,        # preference for flanking vs direct assault
        "reserve_usage": float,          # how often holds forces back
        "force_concentration": float,    # 0.0 spreads forces, 1.0 concentrates
    },

    # Strategic layer — how they run campaigns
    "strategic": {
        "army_composition": str,         # cavalry_heavy | infantry | balanced | ranged
        "economic_priority": str,        # expansion | consolidation | military
        "diplomatic_tendency": str,      # aggressive | neutral | cooperative
        "supply_line_awareness": float,  # how well they protect logistics
        "risk_tolerance": float,         # 0.0 cautious, 1.0 reckless
        "territory_sacrifice_rate": float,
        "elite_preservation": float,     # sacrifices territory to save elite units
    },

    # Psychological layer — who they are as a commander
    "psychological": {
        "aggression_score": float,
        "caution_score": float,
        "adaptability": float,           # how fast they change strategy when losing
        "recovery_behavior": str,        # after major loss: aggressive | defensive | chaotic
        "honor_score": float,            # follows rules of engagement
        "greed_score": float,
    }
}
```

---

#### Store 2 — Doctrine Library (doctrines table)
"What have I learned about war itself?"
Anonymous. No player_id. General military knowledge.
Formed when N observations share the same (condition, effect) pattern.

```python
Doctrine = {
    "id": str,
    "abstraction_level": str,        # physical | tactical | strategic
    "condition": str,                # "heavy cavalry on frozen terrain"
    "learned_effect": str,           # "ice fracture likely"
    "derived_principle": str,        # "Frozen terrain vulnerable to concentrated mass"
    "confidence": float,             # Bayesian updated 0.0-1.0
    "episode_count": int,
    "failure_count": int,
    "exceptions": [],
    "last_verified": str,            # ISO timestamp
    "decay_rate": float
}
```

Why anonymous: if General learned that cavalry breaks ice from Arman,
that knowledge should transfer to the next player who uses cavalry.
The player's identity should not gate the doctrine.

---

#### Store 3 — Relationship Record (player_general_relationship table)
"What is MY history with THIS player specifically?"
The General's personal record — trust, betrayal, cooperation.
Not tactical, not doctrinal. Purely relational.

```python
RelationshipRecord = {
    "player_id": str,
    "trust_level": float,            # General's current assessment -1.0 to 1.0
    "betrayal_count": int,           # times player broke agreements
    "cooperation_count": int,        # times player cooperated
    "times_attempted_capture": int,
    "known_deceptions": int,
    "predicted_next_intent": str,    # General's current prediction
    "prediction_confidence": float,
    "notable_events": []             # key moments the General remembers
}
```

---

#### How the three stores work together

```
Player appears on battlefield
        ↓
General checks player_profiles      → "I know this one. Cavalry rush opener."
General checks relationship_record  → "He betrayed me twice. Trust: -0.6"
General checks doctrine library     → "Cavalry + frozen terrain = ice risk"
        ↓
General decides: terrain_exploit
(not because he remembers Arman specifically broke ice —
 but because he learned cavalry breaks ice, and he knows
 this player uses cavalry)
```

300 years later, different player, same cavalry tactics:
- No player profile yet (new player)
- No relationship record
- Doctrine still applies: cavalry + frozen terrain = ice risk
- General exploits it anyway
```

### Counter-Doctrine (NEW)
```python
CounterDoctrine = {
    "id": str,
    "triggers_on_intent": str,       # predicted player intent that activates this
    "condition": str,                # terrain + situation context
    "counter_action": str,           # General's response intent
    "success_rate": float,           # how often this counter worked
    "confidence": float,
    "last_verified": str,
    "decay_rate": float,
    "episode_count": int
}
```
The General FIRST predicts player intent, THEN retrieves counter-doctrines,
THEN scores his own actions. Prediction comes before decision.

---

## Decision Architecture (Stage 2)

```
Current World State
        ↓
Terrain Feature Extraction
        ↓
Emergent Military Zone Analysis
(chokepoints, high_ground, ambush corridors, supply zones — from terrain, not hardcoded)
        ↓
Player Profile Lookup
        ↓
Player Intent Prediction  ← NEW (predict what player will do BEFORE deciding)
        ↓
Counter-Doctrine Retrieval (what counters the predicted intent in this terrain?)
        ↓
Doctrine Retrieval (general doctrines for this situation)
        ↓
Intent Scoring:
    score = 0.4 × doctrine_score
          + 0.3 × counter_doctrine_score
          + 0.2 × terrain_advantage
          + 0.1 × risk_assessment
        ↓
Prune low-scoring intents (threshold: 35)
        ↓
Chosen Intent
        ↓
Episode Logger → Observation Logger
```

NOTE: Scoring weights are NOT fixed constants.
They represent the General's personality and evolve over time.
Early game: doctrine_weight lower (fewer doctrines exist), counter_doctrine_score near zero
Late game: both weights higher (centuries of experience and player modeling)

---

## Memory Layers

### Tactical Memory (short-term per encounter)
- Weapon used this fight
- Dodge patterns observed
- Attack timing
- Resets partially between encounters

### Strategic Memory (medium-term per player)
- Army composition preferences
- Economic behavior
- Diplomatic choices

### Psychological Memory (long-term permanent)
- Greed, caution, aggression scores
- Recovery behavior after loss
- Betrayal history
- The General's trust assessment

---

## Terrain Interaction Rules (Physics Layer)
The General does NOT know these at start.
He discovers them through experience.

```
frozen_lake:
    break_threshold: 800kg  (cavalry ~600kg, siege ~2000kg)
    cascade: True           (breaking spreads to adjacent cells)

forest:
    swing_threshold: force > 500N causes tree_fall
    fall_direction: based on swing direction + wind
    fire_spread: True

hill:
    charge_penalty: -30% effectiveness going uphill
    visibility_bonus: +40% sight range from top

river:
    crossing_speed: -60% mobility
    flood_trigger: heavy_rain event

wall:
    collapse_threshold: siege impact > 1000N
    rubble_creates: new_cover + mobility_block
```

---

## Database Schema (SQLite)

```sql
-- Raw battle records — source of truth for all learning
CREATE TABLE episodes (
    id TEXT PRIMARY KEY,
    timestamp TEXT,
    player_id TEXT,
    age INTEGER,
    data JSON               -- full to_episode() dict, no raw physics
);

-- Anonymous military knowledge — no player_id
CREATE TABLE doctrines (
    id TEXT PRIMARY KEY,
    abstraction_level TEXT,
    condition TEXT,
    learned_effect TEXT,
    confidence REAL,
    episode_count INTEGER,
    failure_count INTEGER,
    derived_principle TEXT,
    exceptions JSON,
    last_verified TEXT,
    decay_rate REAL
);

-- Raw observations before they become doctrines
CREATE TABLE observations (
    id TEXT PRIMARY KEY,
    episode_id TEXT,
    timestamp TEXT,
    terrain_context TEXT,
    action_taken TEXT,
    observed_effect TEXT,
    confidence REAL,
    last_verified TEXT,
    decay_rate REAL,
    FOREIGN KEY (episode_id) REFERENCES episodes(id)
);

-- What THIS player does — tactical/strategic/psychological
CREATE TABLE player_profiles (
    player_id TEXT PRIMARY KEY,
    encounter_count INTEGER,
    first_seen_age INTEGER,
    last_seen_age INTEGER,
    data JSON               -- full PlayerProfile dict
);

-- General's personal history with THIS player — trust, betrayal, etc.
CREATE TABLE player_general_relationship (
    player_id TEXT PRIMARY KEY,
    trust_level REAL,
    betrayal_count INTEGER,
    cooperation_count INTEGER,
    times_attempted_capture INTEGER,
    known_deceptions INTEGER,
    predicted_next_intent TEXT,
    prediction_confidence REAL,
    notable_events JSON
);

-- Terrain physics as observed by General (NOT the simulator's ground truth)
CREATE TABLE terrain_knowledge (
    terrain_type TEXT,
    action_type TEXT,
    observed_outcomes JSON,
    confidence REAL,
    episode_count INTEGER,
    PRIMARY KEY (terrain_type, action_type)
);

-- Counter-doctrine: what to do when player does X
CREATE TABLE counter_doctrines (
    id TEXT PRIMARY KEY,
    triggers_on_intent TEXT,
    condition TEXT,
    counter_action TEXT,
    success_rate REAL,
    confidence REAL,
    last_verified TEXT,
    decay_rate REAL,
    episode_count INTEGER
);
```

---

## What This System Is NOT
- Not a chess engine (no perfect play goal)
- Not a fun-optimized boss (fun is irrelevant)
- Not a rule-based scripted AI dressed as ML
- Not dependent on Unreal or any game engine

## What This System IS
- A genuine learning commander
- A psychological profiler of players
- A doctrine-forming intelligence
- The brain of an entity that has lived for centuries
