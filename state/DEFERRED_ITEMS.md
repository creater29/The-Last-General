# DEFERRED_ITEMS.md
# Everything explicitly pushed back for later — with exact details on when and what to do.
# Update this file whenever something new is deferred or a deferred item is completed.

---

## How to Read This File

Each item has:
- What it is
- Why it was deferred
- Exactly when to address it (which Stage, which file, which trigger)
- What to do when the time comes

---

## Open — Address During Stage 3

---

### D001 — Doctrine failure_count and decay_rate wiring
**Status: OPEN — Stage 3 Candidate B (NOT YET BUILT)**
**NOTE:** This item was pre-written in anticipation of Candidate B with a
completion tick that does not reflect reality. Candidate B has not been
implemented. The feedback loop described here is exactly what Candidate B
must build. Do not treat this as done.
**Prerequisite:** Fix W009 first — `doctrines_consulted` must return real
doctrine IDs before failure_count can be incremented on the correct row.
**What to build (Candidate B, Part 1 — fix W009):**
- decision_engine.py: `_doctrine_factor()` returns the matched doctrine's real
  `id` field from the DB, not a synthetic key string.
- decide() collects those real IDs into `doctrines_consulted`.
**What to build (Candidate B, Part 2 — feedback loop):**
- logger.py: `increment_doctrine_failure(doctrine_id: str) -> None` — increments
  failure_count, recomputes decay_rate = failure_count / (episode_count + failure_count)
- decision_engine.py: `_doctrine_factor()` applies decay at read time:
  effective_confidence = confidence × (1 − decay_rate)
- decision_engine.py: `record_battle_outcome(result, decisions_made)` — after a
  losing battle, increments failure_count on every doctrine in doctrines_consulted.
**Target test count:** ~14 new tests, reaching 318/318 total.

---

### D002 — Full confidence decay (time-based staleness not yet implemented)
**Deferred from:** Architecture design
**Partially done:** decay_rate is computed and applied in _doctrine_factor() as
  effective_confidence = confidence × (1 − decay_rate)
  decay_rate = failure_count / (episode_count + failure_count)
**What is NOT done:** Time-based staleness scan. Doctrines that have not been
  triggered for many episodes should lose confidence slowly even without failures.
**When to address:** After player_general_relationship is complete (Candidate C)
**What to do:**
- Add `episodes_since_last_verified` as a computed field when reading doctrines.
- In a new `DecisionEngine.decay_stale_doctrines(current_episode_count)` method:
  For each doctrine: staleness = current_episode_count - last_verified_episode
  If staleness > 50: apply soft decay → confidence *= (1 - decay_rate * staleness/100)
  Floor: never reduce below 0.1 (General never fully forgets)
- Call this method once per game session start, before making decisions.
- Re-verify (reset staleness) whenever a new episode confirms the doctrine.

---

### D005 — Scoring weight evolution mechanism
**Deferred from:** Architecture decision — weights should not be fixed constants
**Current state:** decision_engine.py uses hardcoded factor ranges:
  [0.8, 1.5] for doctrine, [0.5, 1.5] for player, [0.5, 1.5] for situation
**When to address:** After 1000+ live decisions have been logged (see also D017)
**What to do:**
- When doctrine_count < 5: reduce doctrine factor ceiling to 1.2 (fewer doctrines
  → trust terrain analysis more)
- When doctrine_count > 20: raise doctrine factor ceiling to 1.7 (deep experience
  → trust doctrines more)
- counter_doctrine_weight stays low until counter_doctrines table has ≥ 3 entries
- Log the raw factor values used for every decision so they can be reviewed.
- Do NOT hard-code thresholds — make them configurable parameters in a
  SCORING_CONFIG dict at the top of decision_engine.py.

---

### D006 — Player intent prediction improvement (rule-based → ML)
**Deferred from:** Architecture — "General FIRST predicts player intent"
**Current state:** player_adaptation uses aggression_index and terrain_tendencies
  from player_profiler. This is the rule-based v1 predictor.
**When to address:** After 500+ battles with player profiles logged
**What to do:**
- In Stage 3: improve rule-based predictor to also use recent_intents
  (last 5 player intents from the running battle). Currently unused.
- Full NN-based predictor is D010 — do not build until rule-based is shown
  to be demonstrably insufficient.
- prediction_confidence should be 0.5 for new players (no history), rising
  with encounter_count.

---

### D007 — Counter-doctrine table population
**Deferred from:** Architecture — counter_doctrines table exists but is empty
**Why deferred:** Requires both doctrines AND player intent prediction to exist first.
**When to address:** After Candidate C (relationship manager) is complete
**What to do:**
- A counter-doctrine forms when:
  1. Player used intent X in terrain context Y
  2. General responded with intent Z
  3. Result was win or significantly better than average
- After 5+ such (X, Y, Z, win) patterns: form counter_doctrine entry.
  triggers_on_intent = X, condition = Y, counter_action = Z
  success_rate = wins / total times this counter was applied
- This runs as a post-battle sweep, same as observation extraction.

---

### D008 — Relationship memory (player_general_relationship table) ✅
**Completed:** 2026-06-28 (Stage 3 Candidate C)
**Note:** Implementation diverged from the original spec below after architectural
review (three-round supervisor review chain). Original spec had RelationshipManager
computing modifiers and directly boosting named intents — this was corrected before
implementation. See PROGRESS.md Candidate C and ARCHITECTURE.md orthogonality rule
for the actual design: RelationshipManager returns raw RelationshipState; DecisionEngine
owns all interpretation via `_relationship_factor()`. `get_trust()` and
`get_relationship_summary()` were not built — `get_state()` returning `RelationshipState`
replaced them. `encounters` field added (not in original spec) to distinguish
"never met" from "known neutral" without using `Optional`.
**Original spec (superseded, kept for history):**
**When to address:** NOW (next session after Candidate B)
**What to do:**
See SESSION_HANDOFF.md for the full implementation spec. Summary:
1. `logger.py` — confirm `upsert_relationship()` and `get_relationship()` exist;
   add if missing.
2. `src/brain/relationship_manager.py` (new file):
   - `update_after_battle(server_id, player_id, result, decisions_made)`
     → updates trust_level based on outcome and notable events
   - `get_trust(server_id, player_id)` → float in [-1.0, 1.0]
   - `get_relationship_summary(server_id, player_id)` → dict
3. Wire into DecisionEngine.decide(): trust < -0.5 → boost DEFENSIVE_HOLD/AMBUSH;
   trust > 0.5 → slight boost to FLANK_ATTEMPT.
4. Trust update rules for Stage 3 (simple):
   loss  → trust_level -= 0.05 (player is dangerous)
   win   → trust_level += 0.02 (General has measure of this player)
   draw  → no change

---

### D009 — Turn-based → event-triggered battle loop upgrade
**Deferred from:** Stage 1 design decision
**Why deferred:** Turn-based sufficient for data generation and Stage 2/3 brain work.
**When to address:** Start of Stage 4, before any Stage 4 features
**What to do:**
- Refactor battle.py: replace _run_turn() with an event queue system.
- Events are added to queue: unit moves → physics resolves → terrain event fires
  → brain has option to re-evaluate.
- The General's decide() should be callable at any point, not just turn start.
- Keep the turn-based loop as a fallback/config option. Do not delete it.
- All 318 existing tests must still pass after refactor.

---

### D014 — Logger.py repository split
**Deferred from:** Design concern raised in ChatGPT review
**Current state (updated 2026-06-28, post pre-cleanup):** logger.py is 950 lines
  (was 981 before dead-code removal — see below). PAST the 800-line trigger.
**Status:** TRIGGER HIT. Pre-cleanup complete; split itself NOT YET STARTED.
**Pre-cleanup done before this split can safely begin:**
  1. Removed two fully dead, shadowed methods: pre-R006 `upsert_player_profile`
     and `get_player_profile` (bare `player_id`, no `server_id` — unreachable,
     shadowed by the correct server-scoped versions). Verified zero callers
     via full-codebase grep before removal. 981 → 950 lines.
  2. `get_known_players()` marked ORPHANED in its docstring — zero callers
     anywhere, and currently broken (queries `encounter_count`, a column that
     doesn't exist in the current schema). Not repaired: no demonstrated
     consumer. Not deleted: cannot rule out a future need. Resolve during
     this split — if no consumer is found by then, delete it; if one is
     found, redesign it server-scoped.
**When to address the split itself:** Now unblocked — pre-cleanup done.

**Scope correction from original plan:** original plan bundled "player
  profiles, relationships" into one `profile_store.py`. This would have
  merged Player Profile and Relationship — two subsystems the orthogonality
  rule explicitly keeps separate (tactical understanding vs. psychological
  history). Corrected below to 6 concerns, not 4.

**Dependency graph — table ownership per store (verified via grep, not
  assumed; this is what the split must follow, not method-name grouping):**
```
episodes                  → EpisodeStore
observations               → ObservationStore
  (log_episode() writes to BOTH episodes AND observations in one call —
   EpisodeStore and ObservationStore must collaborate here, not a clean
   1:1 split; _extract_observations() is the seam)
terrain_knowledge          → WorldModelStore
  (RECLASSIFIED from original plan, which put this in doctrine_store.py.
   terrain_knowledge is WorldModel's domain — learned environmental beliefs,
   read BY DoctrineExtractor but not OWNED by it. Same distinction as
   Player Profile vs Relationship: "who reads this" ≠ "who owns this.")
doctrines                  → DoctrineStore
player_profiles            → PlayerProfileStore
player_general_relationship → RelationshipStore
counter_doctrines          → (schema exists, zero methods reference it beyond
  a COUNT in summary() — same "schema-only, unimplemented" pattern
  player_general_relationship had before Candidate C. Out of scope for this
  split; will need its own store when a future Candidate builds the
  Counter-Doctrine layer. Do not build methods for it now.)
```

**Cross-cutting methods that don't belong to any single store** (`summary()`,
`result_distribution()`, `terrain_event_frequency()` — all read across
episodes/terrain_knowledge/doctrines/player_profiles/counter_doctrines/
player_general_relationship): keep on the `EpisodeLogger` facade itself,
or extract to a separate `StatsAggregator` that composes all stores. Do not
force these into any single store.

**What to do:**
- Split into six modules matching the dependency graph above:
  src/simulator/stores/episode_store.py      — log_episode, get_episodes,
    get_episode_count, get_episodes_by_terrain_event, get_episode_by_id
  src/simulator/stores/observation_store.py  — _extract_observations,
    get_observation_count, get_observations_by_terrain, get_observation_patterns
  src/simulator/stores/world_model_store.py  — upsert_terrain_knowledge,
    get_terrain_knowledge, get_all_terrain_knowledge
  src/simulator/stores/doctrine_store.py     — upsert_doctrine, get_doctrine_by_id,
    get_all_doctrines, increment_doctrine_failure
  src/simulator/stores/player_profile_store.py — upsert_player_profile,
    get_player_profile, get_all_player_profiles, migrate_player_profiles
  src/simulator/stores/relationship_store.py — upsert_relationship,
    get_relationship, migrate_relationship_schema
  src/simulator/db_manager.py                — _connect, init_db, close
- Keep EpisodeLogger as a facade that composes all six stores.
  All existing call sites (brain files, tests) use logger.X — no call site
  changes required.
- Resolve `get_known_players()` during this split (see above) — search for
  a consumer one more time at split time in case anything changed; if none,
  delete; if found, redesign server-scoped.
- All 345 existing tests must pass without modification after split.

---

### D017 — Decision scoring calibration from live data
**Deferred from:** KNOWN_ISSUES W003 (scoring weights are untested heuristics)
**Why deferred:** Cannot calibrate without live decision data.
**When to address:** After 1000 live decisions have been logged in run_integration_test
**Open architectural decision (resolve when D017 is activated):**
  Two storage options for decision logs:
  Option A — JSONL file (logs/decisions.jsonl): simple, text-based, easy to grep
    and inspect. No schema changes. Risk: not queryable across battles without
    parsing.
  Option B — New `decisions` table in general_brain.db: fully queryable, joins
    with episodes table, consistent with existing persistence layer. Risk: logger.py
    grows further before D014 split.
  Recommended: decide at D017 activation time based on how many battles have
  been run and whether cross-battle aggregation is needed immediately.
**What to do:**
- Add decision logging to run_integration_test.py: after each battle, persist
  every decide() output (with all raw factors) using whichever format is chosen.
  Note: the per-turn trace already exists in decide() output — the missing piece
  is persistence across runs, not the trace itself.
- After 1000 decisions, analyse:
  Which intents are chosen most/least often?
  Which factors dominate (always near 1.5 or always near 0.5)?
  Does the General win more when doctrines are consulted vs not?
- Adjust factor ranges and weather multipliers in decision_engine.py based on
  observed distributions, not judgement.
- This is calibration, not redesign — only change values, not the structure.

---

### D018 — Thick mist + forest visibility scenario
**Deferred from:** Session 5 — ChatGPT suggested mist as a new observation category;
  explicitly pushed back as "requires touching Stage 1"
**Why deferred:** Requires adding new terrain event type to battle.py, grid.py,
  and physics.py (all Stage 1 complete files). Scope creep during Stage 2.
**When to address:** Stage 4, after D009 (event-triggered loop) is complete
**What to do:**
- Add TerrainType.DENSE_FOREST or a visibility modifier to existing FOREST cells.
- New terrain event: visibility_reduction (triggers when weather=fog AND terrain=forest)
- New physics outcomes: ambush_success_boost, ranged_accuracy_drop, command_delay
- New observation category: visibility_reduction — feeds into world_model.py
- New doctrines: "Dense forest combined with fog favours ambush tactics."
- This is militarily more interesting than flood because it directly affects
  decision-making, not just terrain damage.
- Do NOT add until the current event types (flood/ice_break/wall_collapse/tree_fall)
  are fully exercised through the entire doctrine → decision pipeline.

---

### D019 — Full scenario packs for targeted curriculum generation
**Deferred from:** Session 6 — ChatGPT suggested Scenario Packs A/B/C/D;
  Arman decided "start with just the TRAINING_PROFILE flag, not full packs"
**Why deferred:** training_profiles.py provides sufficient control for now.
  Full packs add curated unit compositions per scenario which is more code
  for marginal gain at current stage.
**When to address:** When a new terrain event type is added (D018 or new event)
  and the balanced corpus approach is no longer sufficient to generate enough
  observations of the new type.
**What to do:**
- Scenario Pack A (Ice Learning): Grid seeded to maximise frozen_lake cells,
  general army = cavalry heavy + 1 siege, weather_pool = [blizzard, clear, wind]
- Scenario Pack B (Siege Learning): Grid seeded with maximum walls,
  general army = siege heavy, player_army = defensive
- Scenario Pack C (Forest Learning): Grid seeded with dense forest,
  general army = infantry + cavalry, weather = wind/fog
- Scenario Pack D (Weather Learning): standard grid, weather_pool = [heavy_rain] only
- Each pack has its own TARGET_COUNTS (500 events minimum of the target type).
- Add to training_profiles.py as new PROFILES entries with pack-specific unit specs.

---

### D020 — PRINCIPLE_TEMPLATES extensibility
**Deferred from:** KNOWN_ISSUES W006 — 6 hardcoded entries will not scale
**When to address:** When PRINCIPLE_TEMPLATES has more than 20 entries
**Current count:** 6 entries in src/brain/doctrine_extractor.py
**What to do:**
- Refactor PRINCIPLE_TEMPLATES from a hardcoded dict to a metadata-driven system:
  principles.json in data/ — stores (terrain, action, effect) → principle mappings
  doctrine_extractor.py loads from JSON at startup
- Fallback formula stays: f"{terrain} combined with {action} may cause {effect}."
- This allows adding new terrain types without code changes.
- When refactoring: ensure all 36 doctrine_extractor tests still pass.

---

### D021 — CommanderKnowledge field governance process
**Deferred from:** KNOWN_ISSUES W007 — snapshot could become a dumping ground
**Why deferred:** Not a code problem yet — only 9 fields currently. It's a discipline
  concern for the future.
**When to address:** Before each new field is added to CommanderKnowledge
**What to do:**
- Before adding any new field to snapshot.py, answer these two questions:
  1. Can the General observe this WITHOUT a scout report?
     If no → field belongs in a future intel layer, not CommanderKnowledge.
  2. Does decision_engine.py actually use this field in scoring logic?
     If no → do not add it; it will silently drift unused.
- If both answers are yes: add the field, update to_brain_snapshot(), add a
  test in test_snapshot.py that verifies the field is populated correctly.
- Reviewers: treat any CommanderKnowledge PR that adds a field without updating
  decision_engine.py as a red flag.

---

## D014 — Pre-Implementation Artifacts (required before any store file is written)

Per supervisor review: repository boundaries must be defined as contracts
before extraction begins, not discovered during it. All three items below
are verified against actual current code (not assumed) before being written.

---

### Artifact 1 — Repository Interface Specification

Exact current method signatures, grouped by store, per the dependency graph
already built above.

EpisodeStore
  Owns: episode persistence and retrieval
  Tables: episodes
  Methods: log_episode(state), get_episode_count(player_id=None),
    get_episode_by_id(episode_id), get_episodes(...)
  Note: log_episode() also triggers observation extraction — see Transaction
  Policy. Depends on ObservationStore for that sub-step only.

ObservationStore
  Owns: raw terrain-event evidence extracted from episodes
  Tables: observations
  Methods: _extract_observations(episode, timestamp) [called by EpisodeStore,
    does not commit internally — see Transaction Policy],
    get_observation_count(...), get_observations_by_terrain(...),
    get_observation_patterns(...)
  Depends on: none directly; is depended on by EpisodeStore

WorldModelStore
  Owns: learned environmental beliefs (terrain_knowledge)
  Tables: terrain_knowledge
  Methods: upsert_terrain_knowledge(...), get_terrain_knowledge(...),
    get_all_terrain_knowledge()
  Depends on: none. Read BY DoctrineExtractor (brain layer) but that is a
  caller relationship across layers, not an intra-logger dependency.

DoctrineStore
  Owns: military doctrines (anonymous, generalized)
  Tables: doctrines
  Methods: upsert_doctrine(doctrine_id, abstraction_level, condition,
    learned_effect, confidence, episode_count, derived_principle,
    last_verified, decay_rate=0.005), get_doctrine_by_id(doctrine_id),
    get_all_doctrines(), increment_doctrine_failure(doctrine_id)
  Depends on: none — verified directly; an early heuristic scan suggested
  an observations touch, confirmed false positive (docstring bleed from
  the adjacent method, not an actual reference in upsert_doctrine's body).

PlayerProfileStore
  Owns: per-player tactical behaviour profiles
  Tables: player_profiles
  Methods: upsert_player_profile(server_id, player_id, first_seen, last_seen,
    total_battles, win_count, loss_count, draw_count, preferred_units,
    terrain_tendencies, aggression_index, adaptability_score, raw_data),
    get_player_profile(server_id, player_id), get_all_player_profiles(...),
    migrate_player_profiles()
  Depends on: none — verified directly; an early heuristic scan suggested
  an observations touch, confirmed false positive (the docstring literally
  states "observations are untouched").

RelationshipStore
  Owns: psychological relationship state per opponent
  Tables: player_general_relationship
  Methods: upsert_relationship(server_id, player_id, data),
    get_relationship(server_id, player_id), migrate_relationship_schema()
  Depends on: none — verified directly; an early heuristic scan suggested
  a player_profiles touch, confirmed false positive (an inline comment
  referencing the player_profiles PRIMARY KEY pattern for documentation
  consistency, not an actual table reference).

LoggerFacade (EpisodeLogger itself — see Artifact 3)
  Owns: cross-store composition and transaction boundaries
  Tables: none directly
  Methods verified as genuinely cross-store (not store-specific):
    get_episodes_by_terrain_event(event_type, limit=50) — real SQL JOIN
    between episodes and observations, confirmed by direct read (not a
    false positive). Classified at facade level per the same rule already
    applied to summary(): methods spanning more than one store's tables
    live on the facade, not inside any single store.
    summary() — reads across all six tables plus counter_doctrines.
    result_distribution(), terrain_event_frequency() — verify table touches
    at extraction time.
  init_db(), close(), _connect(), _get_conn() stay at facade/DBManager
  level (shared connection lifecycle — see Transaction Policy).

counter_doctrines remains schema-only, zero methods, out of scope — no store
is created for it. get_known_players() remains ORPHANED (W010) — its final
store, if any, is decided when W010 is resolved during actual extraction.

---

### Artifact 2 — Transaction Ownership Policy

Verified current behavior before deciding a policy (not assumed): `_get_conn()`
lazily creates ONE `sqlite3.Connection`, cached on `self._conn`, returned
identically on every call — confirmed by reading `_get_conn()` directly. This
is why `log_episode()`'s single `conn.commit()` at the end already atomically
covers both the episodes INSERT and every observations INSERT made inside
`_extract_observations()` — they share one connection, and
`_extract_observations()` deliberately does not commit on its own. This is an
existing, working pattern, not something to invent from scratch.

Policy (preserves current behavior, applies it as an explicit rule):
1. All six stores share ONE underlying `sqlite3.Connection`, owned by
   DBManager and injected into each store at construction
   (e.g. EpisodeStore(conn), DoctrineStore(conn), ...). No store opens its
   own connection.
2. A store method that writes to only its own table commits at the end of
   its own method — matches every current single-table method
   (upsert_doctrine, upsert_relationship, etc.), requires no change.
3. A method spanning multiple stores' tables — currently only log_episode()
   (episodes + observations) — is not split so each store commits its own
   piece. ObservationStore keeps a non-committing internal method
   (_extract_observations, unchanged), and EpisodeStore.log_episode() calls
   it, then issues the single commit() itself, exactly mirroring current
   behavior. EpisodeStore needs a reference to ObservationStore to call that
   method directly — not a full transaction/session object, since none
   exists today and inventing one now would be speculative infrastructure
   ahead of a second real use case.
4. If a genuine second cross-store write operation is ever added, re-evaluate
   whether a shared transaction abstraction is justified then — do not build
   one now on the strength of a single existing case ("evidence before
   implementation").

---

### Artifact 3 — LoggerFacade Contract

EpisodeLogger remains the sole external-facing class. Every existing caller
(brain/*.py, tests/*.py, scripts/*.py) continues to call
logger.upsert_doctrine(...), logger.get_relationship(...), etc. — zero
call-site changes. Internally, EpisodeLogger.__init__ constructs one shared
connection via DBManager, then constructs all six stores with that
connection, and each public method becomes a thin delegate to the
corresponding store method (or, for facade-level methods identified in
Artifact 1, executes the cross-store logic directly).

Concrete verification mechanism (not just prose intent): before writing any
store file, capture the full current public method signature list of
EpisodeLogger (inspect.signature over every public method). After the split,
add a test asserting the post-split EpisodeLogger's public method signatures
are identical to the captured pre-split list. This gives the facade-stability
promise an enforced test, not just a documented intention.

---

Candidate D implementation may begin once these three artifacts are reviewed
and confirmed — this document is the proposal, not yet an approval to start
writing store files.

---

### D022 — IntentMetadata (replace hardcoded intent category tables)
**Deferred from:** Candidate C architectural review — supervisor review flagged
  hardcoded intent categories in `_relationship_factor()` as non-scalable
**Current state:** `decision_engine.py` has three hardcoded sets:
  `_HIGH_COMMITMENT`, `_CAUTIOUS`, `_NEUTRAL` — 8 intents split across them.
  `SUPPLY_RAID` left unclassified in `_NEUTRAL` — execution-dependent risk profile
  (small raid vs. deep strike) that the current model cannot represent.
**Why deferred:** Acceptable today at 8 intents. Not acceptable at 40+ intents —
  every new intent would require editing `_relationship_factor()`'s category sets,
  which is exactly the kind of coupling the orthogonality rule exists to prevent.
**When to address:** Trigger when EITHER:
  - intent count exceeds 15, OR
  - intent category maintenance becomes difficult (frequent edits, unclear
    classification for new intents — SUPPLY_RAID is already a preview of this)
**What to do:**
- Define `IntentMetadata` per intent: `commitment: float, aggression: float,
  exposure: float` (each roughly [0.0, 1.0])
- Replace `_HIGH_COMMITMENT`/`_CAUTIOUS`/`_NEUTRAL` set membership with a
  continuous function of `commitment_modifier` × intent's `commitment` dimension
- This also resolves the SUPPLY_RAID classification problem: metadata could
  eventually vary by battle context (raid size) rather than being a fixed label
- RelationshipManager is unaffected — it remains intent-blind before and after
  this change. Only DecisionEngine's `_relationship_factor()` changes.
- **Also reintroduce `risk_modifier` at this point** — it was removed from
  `_relationship_factor()` (code review, 2026-06-28) because it was numerically
  identical to `commitment_modifier` with no distinct consumer, i.e. dead code.
  The concept remains valid: once IntentMetadata's `exposure` dimension exists,
  risk and commitment can diverge (SUPPLY_RAID: small raid = low risk/low
  commitment, deep strike = high risk/high commitment). Do not reintroduce
  `risk_modifier` before that dimension exists to consume it — same "evidence
  before implementation" reasoning that removed it.

---

## Open — Address During Stage 3+ / 4

---

### D010 — Neural network intent predictor
**Deferred from:** Architecture discussions
**Why deferred:** Requires training data from Stage 2/3. Cannot train without
  episodes that include player profiles and relationship records.
**When to address:** Stage 3, after 500+ battles with player profiles logged
  AND the rule-based predictor (D006 improvement) is demonstrably insufficient.
**What to do:**
- Input features: player_profile fields + battlefield features + turn number
- Output: probability distribution over PlayerIntent values
- Architecture: small MLP, 3-4 layers, sklearn or PyTorch (Arman's choice)
- Training data: episodes where player_intent is known (all of them)
- Replace rule-based predictor with this NN.
- The NN becomes the "opponent model" in the MCTS pipeline (D011).

---

### D011 — MCTS / 4-cycle lookahead planner
**Deferred from:** ChatGPT architectural discussion, approved as correct design
**Why deferred:** Requires trained NN opponent model (D010) and outcome evaluator.
**When to address:** Stage 3, after D010 is complete
**What to do:**
- Implement Monte Carlo Tree Search with doctrine-informed pruning.
- Pipeline: doctrine_retrieval → intent_scoring → prune → rollout → evaluate
- 4 cycles: General acts → player responds → General responds → player responds
- Pruning: eliminate intents with score < 35 before rollout
- Branch factor target: 2-3 surviving intents per level
- Rollout uses simulator in fast mode (no rendering, just outcome calculation)

---

### D012 — Outcome evaluation NN
**Deferred from:** MCTS design (D011 dependency)
**When to address:** Stage 3, alongside D011
**What to do:**
- Input: (world state features, general intent, player intent, turn number)
- Output: (win_probability, expected_casualty_ratio, strategic_value)
- Used by MCTS to evaluate leaf nodes without running full simulations.

---

### D013 — API layer (Stage 3 boundary)
**Deferred from:** Architecture — system boundaries diagram
**When to address:** Stage 3, after all brain components work in live integration
**What to do:**
- REST wrapper around brain components.
- Endpoints:
  POST /observe  → submit completed episode, trigger learning update
  POST /decide   → given current state snapshot, return intent + reasoning trace
  GET  /profile  → return player model for (server_id, player_id)
  GET  /doctrine → return doctrine library (all or filtered by confidence)
  GET  /health   → return system summary (counts, db path, last updated)
- Unreal Engine calls these endpoints. Brain never knows about Unreal internals.

---

### D015 — Scout mechanics
**Deferred from:** Stage 3 candidate list, pushed to Stage 4
**Why deferred:** Pure gameplay addition. Brain must demonstrate intelligence first.
**When to address:** Stage 4, after MCTS is working
**What to do:**
- Add SCOUT unit type to units.py.
- Scout action: reveals terrain/enemy positions within a radius.
- Scout report: success → intel added to CommanderKnowledge visible_events;
  failure (scout dies) → no report, no intel. General cannot infer from silence.
- Scout observations feed into observation pipeline as intel_report events.
- This is the architectural enforcement of "what is the General allowed to know."

---

### D016 — Unreal Engine integration
**Deferred from:** Core architecture decision
**When to address:** After D013 (API layer) is complete and tested.
**What to do:**
- Unreal calls /decide endpoint with current game state as JSON snapshot.
- Brain returns: chosen_intent + reasoning_trace + confidence.
- Unreal translates intent into actual game unit commands.
- Brain never knows about Unreal internals. The API is the boundary.
- Latency target: /decide response < 200ms.

---

## Completed Deferred Items

---

### D001 — Doctrine failure_count and decay_rate wiring ✅
**Completed:** 2026-06-28 (Stage 3 Candidate B)
**What was built:**
- decision_engine.py: `_doctrine_factor()` returns real doctrine `id` from DB
  (fixes W009 — no more synthetic IDs in `doctrines_consulted`)
- decision_engine.py: `_doctrine_factor()` applies decay at read time:
  effective_confidence = confidence × (1 − decay_rate)
- logger.py: `increment_doctrine_failure(doctrine_id)` — increments
  failure_count, recomputes decay_rate = failure_count / (episode_count + failure_count)
- decision_engine.py: `record_battle_outcome(result, decisions_made)` — after a
  losing battle, increments failure_count on every doctrine consulted
- 14 new tests (319/319 total)
**Verification (run_integration_test.py, seed=9, LOSS):**
  Before: doctrine_forest_cavalry_tree_fall  failure_count=0  decay_rate=0.005000
  After:  doctrine_forest_cavalry_tree_fall  failure_count=24 decay_rate=0.001175
  Before: doctrine_river_weather_flood       failure_count=0  decay_rate=0.005000
  After:  doctrine_river_weather_flood       failure_count=6  decay_rate=0.000051
  Unconsulted doctrines (wall, frozen_lake_cavalry, frozen_lake_siege): unchanged ✓
  record_battle_outcome() returned 30 increments ✓
**Status:** COMPLETE — implemented, tested, and verified in live pipeline.

---

### D003 — Rare event weighting in doctrine extraction ✅
**Completed:** 2026-06-23 (Session 6 — training profiles)
**Resolution:** Solved at the data layer, not the extractor layer.
  training_profiles.py with anti_flood/balanced profiles ensures the corpus
  has 1000+ observations of each rare event type before doctrine extraction runs.
  DoctrineExtractor remains accurate (no artificial weighting).
**Deviations from original plan:** Did not add rarity multiplier to extractor.
  Architecture decision: world_model represents observations accurately;
  data imbalance is fixed upstream by corpus generation.

### D004 — Weather probability rebalancing ✅
**Completed:** 2026-06-23 (Session 6 — training profiles)
**Resolution:** training_profiles.py PROFILES dict controls weather_weights
  per profile. The balanced profile sets heavy_rain=0.0. The natural profile
  preserves original behaviour. weather_weights param added to BattleLoop.__init__()
  as optional parameter (default=None → original behaviour).
**Deviations from original plan:** Did not modify _update_weather() defaults.
  Added optional override instead — cleaner, backward-compatible.
