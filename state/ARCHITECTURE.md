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
# Currently implemented:
commitment_modifier = clamp(1.0 + trust_level * 0.15, 0.85, 1.15)

# Documented but NOT implemented — no current consumer, would be dead code
# per "evidence before implementation" (removed from executable code after
# code review during Candidate C; see D022 for reintroduction trigger):
# risk_modifier       — would diverge from commitment once IntentMetadata
#                        exists (e.g. SUPPLY_RAID: small raid = low risk/low
#                        commitment, deep strike = high risk/high commitment —
#                        a distinction the current intent category sets cannot express)
# confidence_modifier = 1.0  # deferred — awaits prediction-accuracy evidence,
#                            # NOT derived from betrayal_count (different concepts:
#                            # "I trust him less" ≠ "I'm less confident in my read")
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

## Engineering Process Principles (Permanent)

These emerged from disciplined review during Stage 3 (Candidates B, C, D
pre-audit) and apply to all future work on this project, not just the
subsystem that surfaced them.

**1. Heuristics identify candidates; implementation establishes truth.**
Any automated shortcut — grep, a quick script, a static-analysis pass, an AI
summary — is a lead generator, not a source of truth. Confirmed multiple
times on this project: a table-reference heuristic built during Candidate D's
audit produced several false positives (docstring bleed-through, cross-
referencing comments mistaken for real code touches), all caught only by
reading the actual method body before including anything in a specification.
Treat every heuristic result as "worth checking," never as "verified."

**2. Repository/module boundaries follow data ownership, not method-name
grouping.** A split based on what methods happen to be named similarly will
drift from what the data actually requires. Candidate D's original plan
(pre-dating Candidate C) grouped "player profiles, relationships" into one
store by naming convention; the corrected plan gave them separate stores
because they own different tables and represent different bounded contexts.
Building an explicit table-to-owner dependency graph before any split is
mandatory, not optional cleanup.

**3. Repositories own writes; facades own workflows.** A repository/store is
responsible for persisting and retrieving its own table(s). A facade is
responsible for sequencing multi-store operations, owning transaction
boundaries, and answering queries that legitimately compose more than one
store's data (a JOIN, a cross-table aggregate). A cross-store READ is not a
boundary violation — it belongs on the facade, not forced into either store.

---

## EpisodeLogger Responsibility Classification (Permanent)

Produced at the end of Candidate D (Phase 6) — every method remaining in
`EpisodeLogger` was consciously classified, not left unexamined. This
table is the permanent record of *why* each responsibility lives where it
does. Update it when responsibilities move; do not let it go stale.

**Lifecycle / DBManager** (facade-owned; tracked in DEFERRED_ITEMS D026,
evidence-gated, not acted on):
`__init__`, `_connect`, `_get_conn`, `close`, `__enter__`, `__exit__`,
`init_db`

**Thin delegation** (facade-owned; correct and expected — the facade's job
is exposing a stable public API while internally delegating to the
extracted store):
all CRUD-style methods for the five extracted stores (Relationship,
PlayerProfile, Doctrine, Observation, Episode) — 21 methods total.

**Cross-store composition** (facade-owned; correct — genuinely spans more
than one store's table, verified by direct read, not assumed):
`get_episodes_by_terrain_event` (real SQL JOIN, episodes+observations),
`summary` (reads across all seven tables)

**Analytics queries** (facade-owned; deliberately distinct from both thin
delegation and cross-store composition — see reasoning below):
`result_distribution`, `terrain_event_frequency`

**Intentionally inline** (facade-owned; tracked in DEFERRED_ITEMS D024,
evidence-gated, not acted on):
`upsert_terrain_knowledge`, `get_terrain_knowledge`, `get_all_terrain_knowledge`

---

### Why "analytics queries" is its own category, not folded into repositories

`result_distribution()` and `terrain_event_frequency()` each touch exactly
one table — by table-count alone they look like they belong in
`EpisodeStore`/`ObservationStore`. They do not, and the reasoning matters
more than the conclusion:

**Repository ownership means owning persistence and canonical retrieval of
domain objects — not every SQL statement that happens to reference that
table.** `get_episode_by_id()` returns an episode. `result_distribution()`
returns a derived aggregate (`{"win": 412, "loss": 89, ...}`) — it isn't
retrieving anything, it's computing a report.

**The test that actually distinguishes them, verified against real
callers, not assumed:** does the brain pipeline depend on this method as an
operational input, or is it an external diagnostic with no pipeline
dependency?

- `ObservationStore.get_observation_patterns()` is *also* a single-table
  `GROUP BY`/`HAVING`/`COUNT` aggregate — structurally identical in kind to
  `result_distribution()`. It correctly lives in `ObservationStore` anyway,
  because `world_model.py` calls it as a genuine operational input —
  `WorldModel.update_from_observations()` depends on it to form beliefs
  that `DoctrineExtractor` promotes into doctrines. It is load-bearing
  brain-pipeline logic.
- `terrain_event_frequency()` is called only by `scripts/generate_corpus.py`
  — a standalone corpus-generation utility, not the live decision pipeline.
- `result_distribution()` has zero callers anywhere in `src/` or `scripts/`.

Same SQL shape (single-table aggregate), opposite answer, because the real
question isn't "how many tables does this touch" — it's "is anything in
the actual system relying on this as an input." `get_observation_patterns()`
passes that test and belongs in a repository. `result_distribution()` and
`terrain_event_frequency()` fail it and are correctly facade-level
diagnostics — not because Candidate D ran out of time to move them, but
because moving them would extend "repository" to mean "persistence +
reporting," which is a real architectural expansion Candidate D's actual
goal (remove persistence responsibility from `EpisodeLogger`) never called
for.

**Re-evaluation trigger (not a timeline — may never fire), tracked as
DEFERRED_ITEMS D027:** revisit only if a dedicated reporting/analytics
subsystem is ever justified, or if the number of facade-level analytics
methods grows enough that their presence becomes genuine clutter rather
than two small diagnostic queries.

---

## Perception & Observation Architecture (Permanent)

Established during the Candidate E design review (audit + design conversation,
2026-06-28), before any scout-mechanics code was written — same discipline
as D014's artifacts preceding Phase 1.

### Permanent principle

**The General reasons from observations, not simulator truth. Observations
emerge from independent environmental and operational factors — terrain,
elevation, vegetation/occlusion, weather, observer capability, target
behavior — rather than single hardcoded terrain-type rules.**

This rules out patterns like `HILL: visibility_bonus = 0.40` (terrain TYPE
directly granting a visibility number) in favor of composable factors that
combine per-situation. The reason: terrain-type rules produce contradictions
a factor model doesn't — dense forest on a mountain, a ridge overlooking open
plain, fog on a clear field. Elevation answers "how far could I potentially
see." Vegetation/occlusion answers "how much of that horizon is actually
visible." Weather answers "how well can I identify what I'm looking at."
Observer quality (a scout's skill) and target behavior (marching in the open
vs. hiding in woods) are separate factors again. Each contributes
independently; none of them alone determines the outcome.

**Audit correction this principle produced:** `grid.py`'s `HILL.visibility_bonus`
(found during the Candidate E audit, confirmed dead — defined, never read
anywhere) should NOT be revived as-is when visibility mechanics are eventually
built. It represents exactly the terrain-type-coupled pattern this principle
rejects. Its existence is evidence something was once considered, not evidence
of an intended final design (dead code is never treated as a design commitment
in this project — same discipline already applied to `counter_doctrines` and
the pre-R006 `player_profiles` methods).

### Detection vs. Identification (a permanent distinction, not a synonym pair)

- **Detection** — can the General tell something is there at all? ("Movement
  in the trees.")
- **Identification** — can the General tell what it is? ("Looks like cavalry.")

These are different problems with different failure modes and different
confidence levels. A force can be detected without being identified. Candidate
E's staged model (below) deliberately improves identification first (E1) before
touching detection (E2/E3) — because identification failure is cheap to model
(perception layer only) while detection failure requires new simulator state
(a "hidden/reserve" concept that does not exist anywhere in `Unit` or
`BattleState` today — verified during the audit, not assumed).

### Staged capability model for Candidate E (not a realism-level commitment)

Framed as capabilities the simulator gains, not realism levels the project
commits to reaching. Each stage adds exactly one capability — the same
discipline that made Stage 2's brain subsystems (WorldModel → Doctrine →
PlayerProfile → Relationship) work. **Advancement between stages is
evidence-gated, identical in spirit to D023-D027: do not advance to the next
stage until the current stage has demonstrably limited the General's decision
quality. These are not a roadmap with a deadline.**

**E1 — Information Enhancement (current Candidate E target).** The simulator
still knows enemy armies exist and roughly how strong they are — exactly as
today (`known_enemy_presence`'s count/health/morale/supply aggregate is
unchanged). Composition becomes knowable, imperfectly, via scouting — reusing
the boolean-flag shape already proven on `known_friendly_state`
(`has_siege`, `has_cavalry`), gated by a confidence signal rather than
always-true. No hidden armies. No terrain-based visibility yet. Touches only
the perception layer (`to_brain_snapshot()`, `CommanderKnowledge`) — combat
execution (`_execute_general_intent()` and friends) needs zero changes, since
it already operates on complete simulator truth independent of perception
(verified during the audit).

**E2 — Information Availability.** Detection (not just identification) starts
depending on the factor model above — terrain, elevation, weather, distance.
Information can go stale: no memory of old facts as permanent truth, only
decaying belief ("scout reported cavalry yesterday; two days with no new
report; belief in that fact should now be weaker, not remembered as fixed").
This is a genuinely different kind of "memory" from `WorldModel`/
`DoctrineExtractor`'s cross-battle learning — those accumulate permanent,
slow-changing belief across hundreds of games; in-battle tactical intel about
one specific enemy force in one specific battle should decay on a much faster,
single-battle-scoped timescale. Not a contradiction; two different systems at
two different timescales, same underlying belief+confidence language.

**E3 — Hidden Entities.** The simulator itself changes — this is the line E1/E2
don't cross. Forces can genuinely exist without ever being detected; failure to
detect means no report exists, not a low-confidence report. Requires real new
simulator state (a hidden/reserve concept on `Unit`/`BattleState`) that nothing
in E1/E2 needed.

**E4 — Operational Intelligence.** Reports become time-delayed events (scout
departs → travels → finds enemy → returns → report arrives), not instantaneous
snapshot updates. Messengers can fail. Reports can be wrong. This is the
farthest stage from what exists today.

### Long-term aspiration (not committed, explicitly deferred)

`WorldModel` already speaks in `belief + confidence` pairs. The long-term
direction — not started, not scheduled, evidence-gated like everything else —
is for all knowledge subsystems to eventually share that same language:
`{enemy_cavalry: present, confidence: 0.81}`, `{enemy_siege: unknown,
confidence: 0.28}`. This is architecturally elegant (one vocabulary across
doctrine, profile, relationship, and perception) but is explicitly NOT part of
E1's scope — noted here so the direction isn't lost, not as a commitment.

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
