# Progress Tracker

## Current Stage: STAGE 3 — IN PROGRESS 🔄
## Last Updated: 2026-06-28
## Test Count: 402/402

---

## Stage 1 — Simulator [COMPLETE ✅]

| File | Tests | Notes |
|------|-------|-------|
| src/simulator/grid.py | 12 | Terrain world, zone generation |
| src/simulator/units.py | 29 | Unit types, mass, behaviour |
| src/simulator/physics.py | 23 | Terrain interaction engine |
| src/simulator/battle.py | 26 | Battle loop + to_brain_snapshot() |
| src/simulator/logger.py | 35 | SQLite persistence, all DB access |
| src/simulator/snapshot.py | 20 | CommanderKnowledge dataclass |
| src/simulator/training_profiles.py | 22 | Corpus generation profiles |
| scripts/generate_corpus.py | (integration) | CLI generation tool |

### Stage 1 DB State
- Original 100 battles: flood=6296, tree_fall=146, wall_collapse=78, ice_break=6
- After balanced corpus run (1900 battles, ~97s):
  flood=118,124 | tree_fall=20,396 | wall_collapse=11,597 | ice_break=1,011
- All four event types well above doctrine promotion threshold (5+)

---

## Stage 2 — Brain Core [COMPLETE ✅]

| File | Tests | Notes |
|------|-------|-------|
| src/brain/world_model.py | 30 | Terrain beliefs from observations |
| src/brain/doctrine_extractor.py | 36 | Promotes beliefs → doctrines |
| src/brain/player_profiler.py | 35 | Per-player behaviour profiles |
| src/brain/decision_engine.py | 57 | Hierarchical reasoning pipeline |

### Stage 2 Completion Criteria (all met)
- ✅ General forms 4 doctrines with confidence > 0.6 (one per terrain event type)
- ✅ Player profile populates from episode history
- ✅ Decisions differ by context (TERRAIN_EXPLOIT on frozen lake, DEFENSIVE_HOLD vs aggressive player)
- ✅ Decision reasoning is inspectable (full trace in decide() output)
- ✅ 304/304 tests passing

---

## Stage 3 — Live Pipeline [IN PROGRESS 🔄]

### Candidate A — Live Integration Test [COMPLETE ✅]
**Completed:** 2026-06-28
**File:** scripts/run_integration_test.py

Wires to_brain_snapshot() → DecisionEngine.decide() → GeneralIntent in a live
battle loop. First time simulator and brain ran together end-to-end.

**Results (seed=42, 30 turns):**
- Battle result: WIN
- Decisions made: 30/30 (every turn)
- Doctrines consulted: 30 (doctrine influence confirmed)
- Rejected intents: 30 (SIEGE filtered every turn — no siege units)
- Pipeline errors: 0
- Post-battle analysis: executed successfully (5 beliefs, 5 doctrines)

**Success criteria: 7/7 PASS**
- [✓] Pre-battle knowledge priming executed
- [✓] Doctrine influence detected (30 consultations)
- [✓] Decision logged every turn (30/30)
- [✓] All 8 intent strings → GeneralIntent enum verified
- [✓] Decision trace complete on all turns
- [✓] Pipeline completed with 0 errors
- [✓] Post-battle analysis pipeline executed

**Acceptance:** impl ✓ | unit tests ✓ | integration ✓ | db verified ✓ | docs ✓

**Observed behaviors (confirms correct design):**
- Doctrines loaded: 5 with confidence 0.9872–1.0000
- Weather-driven oscillation visible: TERRAIN_EXPLOIT (clear) → AMBUSH (fog) → TERRAIN_EXPLOIT
- Situation factor confirmed working: fog × AMBUSH = ×1.4 factor beats frozen_lake doctrine
- Decision trace readable and inspectable per turn

**Note:** W009 (synthetic doctrine IDs) was discovered during this run but was
already fixed in source; resolved and verified as part of Candidate B.

### Candidate B — Doctrine Feedback Loop [COMPLETE ✅]
**Completed:** 2026-06-28

**Discovered via audit (pre-written alongside implementation):**
- decision_engine.py: `_doctrine_factor()` returns real doctrine `id` from DB (W009 fix)
- decision_engine.py: effective_confidence = confidence × (1 − decay_rate) applied at read time
- logger.py: `increment_doctrine_failure(doctrine_id)` — increments failure_count, recomputes decay_rate
- decision_engine.py: `record_battle_outcome(result, decisions_made)` — fires on loss only
- 14 tests (319/319 total)

**Schema fix (this session — not pre-written):**
- `player_general_relationship` table: added `server_id NOT NULL`, composite PK `(server_id, player_id)`
- `upsert_relationship(server_id, player_id, data)` and `get_relationship(server_id, player_id)` updated
- `migrate_relationship_schema()` added and run on production DB
- Server isolation test added → 319/319

**Verification (run_integration_test.py — 8/8 criteria PASS):**
- Battle 1 (seed=42): WIN in 30 turns, 30 doctrine consultations ✓
- Battle 2 (seed=9):  LOSS in 30 turns, record_battle_outcome() applied 30 increments ✓
- doctrine_forest_cavalry_tree_fall: failure_count 0→24, decay_rate 0.005000→0.001175 ✓
- doctrine_river_weather_flood:      failure_count 0→6,  decay_rate 0.005000→0.000051 ✓
- Unconsulted doctrines (wall, frozen_lake_*) unchanged ✓

**Tests added: 14 (was 305 pre-written → 319 after schema fix test)**
Integration test: 8/8 PASS (added feedback_loop_verified criterion)

**Acceptance:** impl ✓ | unit tests ✓ | integration ✓ | db verified ✓ | docs ✓

### Candidate C — Player-General Relationship [COMPLETE ✅]
**Completed:** 2026-06-28

**Design (per architectural review chain — see ARCHITECTURE.md orthogonality rule):**
- RelationshipManager returns `RelationshipState` (raw data) — intent-blind, never
  computes modifiers, never references intent names
- DecisionEngine computes `RelationshipModifiers`-equivalent via `_relationship_factor()`
  — owns the translation from psychological state to per-intent score adjustment
- `confidence_modifier` deferred at 1.0 — awaits prediction-accuracy evidence (not betrayal_count)
- `SUPPLY_RAID` classified NEUTRAL — execution-dependent risk profile, not posture-driven
- `encounters` field distinguishes "never met" (encounters=0) from "known neutral"
  (encounters>0, trust=0.0) — avoids `Optional[RelationshipState]`, consistent with
  the CommanderKnowledge pattern (domain layers never see missing-data as None)

**Built:**
- `src/brain/relationship_manager.py` (173 lines) — `RelationshipState` frozen dataclass,
  `RelationshipManager.get_state()`, `update_after_battle(result, events=None)`
- `src/simulator/logger.py` — schema fix: `encounters INTEGER NOT NULL DEFAULT 0` added
  to `player_general_relationship`; `upsert_relationship()`, `get_relationship()`,
  `migrate_relationship_schema()` updated
- `src/brain/decision_engine.py` — `_relationship_factor()` (module-level function,
  same pattern as `_doctrine_factor`/`_player_factor`); `__init__` accepts optional
  `relationship_manager` (backward-compatible); `decide()` wires it in, adds
  `relationship_used` to return dict
- `tests/test_relationship_manager.py` — 22 new tests
- Test count: 319 → 341 (initial), 341 → 345 (post-review fixes: input
  validation on `update_after_battle()`, dead `risk_mod` removed — see
  SESSION_HANDOFF "Post-completion code review")

**Temporary implementation detail (documented, not permanent):**
Intent categories (`_HIGH_COMMITMENT`, `_CAUTIOUS`, `_NEUTRAL`) are hardcoded in
`decision_engine.py`. This is explicitly temporary — see DEFERRED_ITEMS D022
(IntentMetadata). Acceptable for 8 intents; must be replaced before intent count
becomes unmanageable.

**Verification (run_integration_test.py — 9/9 criteria PASS):**
- Battle 1 (seed=42, WIN): relationship encounters incremented +1, confirmed via delta check
- Battle 2 (seed=9, LOSS): relationship encounters incremented +1, confirmed via delta check
- `relationship_used=True` on all 30 turns of Battle 1 (encounters>0 from prior test runs)

**Important note — trust value accumulates across integration test runs (like doctrine
failure_count):** Because the integration test uses the production DB, the relationship
record for `(integration_test_server, integration_test_player)` accrues history across
every run. The feedback battle (seed=9) always produces a loss by design, so trust drifts
downward with repeated test runs — this is expected accumulation, not a defect. The
success criterion checks the *delta* (`encounters == before + 1`), not the absolute trust
value. If trust reaches -1.0 (clamped) after many runs, this remains correct behavior.

**Acceptance:** impl ✓ | unit tests ✓ | integration ✓ | db verified ✓ | docs ✓

### Candidate D — Logger Repository Split [IN PROGRESS 🔄 — Phase 5/6 complete]

Full specification in DEFERRED_ITEMS.md D014 (4 artifacts: interface spec,
transaction policy, facade contract, extraction order + completion criteria).
Extraction order: Relationship → PlayerProfile → Doctrine → Observation →
Episode+facade workflow → facade cleanup (one commit per phase).

**Phase 1 — RelationshipStore — COMPLETE ✅ (2026-06-28)**
- `src/simulator/stores/relationship_store.py` (new, 157 lines):
  `RelationshipStore` — owns `player_general_relationship` exclusively.
  `upsert_relationship()`, `get_relationship()`, `migrate_relationship_schema()`
  — verbatim extraction, zero behavior change.
- `src/simulator/logger.py`: imports `RelationshipStore`, constructs it in
  `__init__` right after `init_db()` (connection already exists by then —
  verified, not assumed). All three facade methods now thin one-line
  delegations. Old inline implementation fully removed — no duplicate left
  behind. 949 → 859 lines.
- `tests/test_relationship_store.py` (new, 8 tests): includes an explicit
  Repository Independence test — `RelationshipStore(conn)` constructed and
  fully exercised with zero import of `EpisodeLogger` or any other store.
- `tests/test_logger_facade_stability.py` (new, 2 tests): captures
  `EpisodeLogger`'s complete public method signature baseline (27 methods)
  from immediately before Phase 1 began, asserts it stays byte-identical
  through every future phase — the concrete mechanism Artifact 3 promised,
  not just documented intent.
- Test count: 345 → 355 (all passing)
- Integration test: 9/9 PASS, verified live (`encounters: 21→22, trust: -0.33`
  through the new delegation path — not just "didn't crash")

**Definition of Done, verified for Phase 1:**
- [✓] Store extracted
- [✓] LoggerFacade delegates correctly
- [✓] Repository Independence confirmed (standalone construction + 8 tests)
- [✓] Old inline implementation removed (no duplication)
- [✓] Full test suite passes (355/355)
- [✓] Logger public API unchanged (facade-stability test, 2/2)

**Acceptance:** impl ✓ | unit tests ✓ | integration ✓ | db verified ✓ | docs ✓

**Phase 2 (PlayerProfileStore) — COMPLETE ✅ (2026-06-28)**
- `src/simulator/stores/player_profile_store.py` (new, 175 lines):
  `PlayerProfileStore` — owns `player_profiles` exclusively.
  `upsert_player_profile()`, `get_player_profile()`, `get_all_player_profiles()`,
  `migrate_player_profiles()` — verbatim extraction, zero behavior change.
- `src/simulator/logger.py`: imports `PlayerProfileStore`, constructs it in
  `__init__` alongside `RelationshipStore`. All four facade methods now
  thin delegations. Old inline implementation fully removed.
  858 → 788 lines.
- `tests/test_player_profile_store.py` (new, 10 tests): includes an explicit
  Repository Independence test — `PlayerProfileStore(conn)` constructed and
  fully exercised standalone.
- **Spec correction found during this phase's audit:** `get_player_episodes()`
  sits physically near the player-profile methods in `logger.py` and its
  docstring says "Used by PlayerProfiler," but it queries the `episodes`
  table only — it belongs to `EpisodeStore` (Phase 5), not
  `PlayerProfileStore`. Same "who reads ≠ who owns" reasoning already
  applied to `terrain_knowledge`/WorldModelStore. DEFERRED_ITEMS.md D014
  Artifact 1 corrected; left untouched in `logger.py` for now (Phase 5's
  territory).
- Test count: 355 → 365 (all passing)
- Integration test: 9/9 PASS, verified live (`encounters=29, trust=-0.4000`
  through the new delegation path)

**Definition of Done, verified for Phase 2:**
- [✓] Store extracted
- [✓] LoggerFacade delegates correctly
- [✓] Repository Independence confirmed (standalone construction + 10 tests)
- [✓] Old inline implementation removed (no duplication)
- [✓] Full test suite passes (365/365)
- [✓] Logger public API unchanged (facade-stability test)

**Acceptance:** impl ✓ | unit tests ✓ | integration ✓ | db verified ✓ | docs ✓

**Phase 3 (DoctrineStore) — COMPLETE ✅ (2026-06-28)**

First "behavior-critical" extraction — DoctrineStore sits directly in
DecisionEngine's read path, per supervisor review requiring explicit
behavioral-equivalence verification, not just passing tests.

**Behavior-critical invariant found and preserved:** `upsert_doctrine()`'s
`ON CONFLICT` clause deliberately does NOT touch `failure_count` or
`exceptions` — only `confidence`, `episode_count`, `derived_principle`,
`last_verified` update on conflict. This means accumulated failure feedback
survives re-extraction. Verified in 2 dedicated tests
(`test_upsert_on_conflict_does_not_reset_failure_count`,
`test_upsert_on_conflict_updates_only_specific_fields`) AND directly against
the live production DB after this phase's integration run: `failure_count=102`
survived a fresh `extract_doctrines()` re-upsert pass without being reset.

- `src/simulator/stores/doctrine_store.py` (new, 157 lines): `DoctrineStore`
  — owns `doctrines` exclusively. `upsert_doctrine()`, `get_doctrine_by_id()`,
  `get_all_doctrines()`, `increment_doctrine_failure()` — verbatim
  extraction, zero behavior change. No `migrate_*_schema()` method — unlike
  Relationship/PlayerProfile, doctrines' schema never needed a repair; that
  method existed on the first two for specific historical reasons (R006,
  encounters field) that never applied here. Initial `CREATE TABLE` stays
  a DBManager/facade concern (`init_db()`).
- `src/simulator/logger.py`: imports `DoctrineStore`, constructs it in
  `__init__` alongside the first two stores. All four facade methods now
  thin delegations. Old inline implementation fully removed.
  789 → 739 lines.
- `tests/test_doctrine_store.py` (new, 12 tests): Repository Independence
  test, plus the two behavior-critical invariant tests above, plus
  `decay_rate` formula verification (`failure_count / (episode_count +
  failure_count)`) with exact float comparisons.
- Test count: 365 → 377 (all passing)
- Integration test: 9/9 PASS. Both doctrine-specific criteria explicitly
  confirmed: "Doctrine influence detected (30 consultations)" and "Doctrine
  DB updated after loss (30 failure_count increments applied)" — same
  magnitudes as pre-Phase-3 runs, confirming behavioral equivalence.

**Definition of Done, verified for Phase 3:**
- [✓] Store extracted
- [✓] LoggerFacade delegates correctly
- [✓] Repository Independence confirmed (standalone construction + 12 tests)
- [✓] Old inline implementation removed (no duplication)
- [✓] Full test suite passes (377/377)
- [✓] Logger public API unchanged (facade-stability test)
- [✓] Behavioral equivalence verified against live production DB (not just
  unit tests) — the specific additional bar this phase was held to

**Acceptance:** impl ✓ | unit tests ✓ | integration ✓ | db verified ✓ | docs ✓

**Phase 4 (ObservationStore) — COMPLETE ✅ (2026-06-28)**

More significant than Phases 1-3: this phase touches `log_episode()` itself,
the central write path every battle goes through — not an isolated CRUD
method.

**Repository Independence revision (decided before Phase 1, exercised for
the first time here):** `ObservationStore` has NO reference to
`EpisodeStore`/episodes. `insert_observations()` (renamed from the private
`_extract_observations()`) does not commit internally — this is deliberate,
not an oversight, because `observations.episode_id` has a
`FOREIGN KEY REFERENCES episodes(id)`, enforced in production
(`PRAGMA foreign_keys=ON`). The facade's `log_episode()` still owns the
full workflow: insert the episode row, call
`self._observation_store.insert_observations(...)`, then commit once —
exactly matching the pre-existing atomic behavior, with the facade
composing two independent stores rather than one store depending on another.

- `src/simulator/stores/observation_store.py` (new, 160 lines):
  `ObservationStore` — owns `observations` exclusively. No
  `migrate_*_schema()` — same reasoning as `DoctrineStore` (schema correct
  from original creation, no repair ever needed).
- `src/simulator/logger.py`: imports `ObservationStore`, constructs it in
  `__init__`. `log_episode()`'s body now calls
  `self._observation_store.insert_observations(...)` instead of
  `self._extract_observations(...)`; the old private method is fully
  removed (not just delegated — it no longer exists as a separate method).
  Three read methods reduced to delegations. Caught and fixed a leftover
  dangling `return` line during the edit (verified via full suite before
  and after). 739 → ~672 lines (net, after this and the dangling-line fix).
- `tests/test_observation_store.py` (new, 12 tests): includes a specific
  behavior-critical test (`test_insert_does_not_commit_internally`) that
  uses two separate connections to the same file-backed DB to directly
  prove the method doesn't commit — not just asserting on return values.
- Test count: 377 → 389 (all passing)
- Integration test: 9/9 PASS. Went further than "tests pass" given this
  phase's significance: ran a precise before/after delta check against the
  live production DB — `episodes: 12021→12022 (+1), observations:
  151338→151348 (+10)` — confirming the exact expected atomic composition
  (one battle logged via the integration script → one episode row + ten
  observation rows, matching the actual number of terrain events in that
  battle, not a coincidental pass).

**Definition of Done, verified for Phase 4:**
- [✓] Store extracted
- [✓] LoggerFacade delegates correctly (including the composed
  `log_episode()` workflow, not just simple CRUD delegation)
- [✓] Repository Independence confirmed (standalone construction + 12
  tests, zero reference to EpisodeStore/episodes)
- [✓] Old inline implementation removed (`_extract_observations()` no
  longer exists as a separate method anywhere)
- [✓] Full test suite passes (389/389)
- [✓] Logger public API unchanged (facade-stability test)
- [✓] Behavioral equivalence verified against live production DB via
  precise before/after delta, not just aggregate counts

**Acceptance:** impl ✓ | unit tests ✓ | integration ✓ | db verified ✓ | docs ✓

**Phase 5 (EpisodeStore + facade workflow) — COMPLETE ✅ (2026-06-28)**

The phase the entire Repository Independence revision was designed for.
Both supervisor reviews flagged this as the highest remaining risk in
Candidate D — it owns the transaction boundary for the whole logging
pipeline, not an isolated CRUD path.

**The exact anti-pattern both reviews warned against, avoided:**
```
EpisodeStore.insert_episode_row() → commit()
ObservationStore.insert_observations() → commit()
```
would silently destroy atomicity (two transactions instead of one) and
violate the FK constraint found in Phase 4. Implemented instead:
```
EpisodeStore.insert_episode_row()        (no commit)
ObservationStore.insert_observations()   (no commit)
EpisodeLogger.commit()                    (once, on the facade)
```
`log_episode()` is now pure orchestration — it no longer contains any
inline SQL, only composes two independent stores and owns the single
transaction boundary.

- `src/simulator/stores/episode_store.py` (new, 170 lines): `EpisodeStore`
  — owns `episodes` exclusively. `insert_episode_row()` (renamed from
  inline SQL in `log_episode()`, does NOT commit), `get_episode_count()`,
  `get_episodes()` (ORDER BY timestamp DESC), `get_episode_by_id()`,
  `get_player_episodes()` (ORDER BY timestamp ASC — deliberately the
  opposite ordering, verified not assumed). Zero reference to
  `ObservationStore` — Repository Independence fully realized.
- `get_player_episodes()` (the Phase 2 finding) now correctly lives here,
  not in `PlayerProfileStore` — verified working through its actual caller
  (`PlayerProfiler`), not just in isolation: 24 real episodes, correctly
  enriched with `_timestamp`, correctly ordered ASC.
- `src/simulator/logger.py`: `log_episode()` rewritten as pure
  orchestration (no inline SQL remains). Five methods reduced to
  delegations. `get_episodes_by_terrain_event()` correctly left untouched
  on the facade (genuine cross-store JOIN, per Artifact 1).
- `tests/test_episode_store.py` (new, 13 tests): Repository Independence
  (including an AST-based static check that `EpisodeStore`'s module never
  imports `ObservationStore` — caught and fixed a false positive in this
  test itself, where a naive string-search flagged the module's own
  docstring prose as if it were a real dependency), a direct two-connection
  proof that `insert_episode_row()` doesn't commit internally, and an
  explicit atomic-composition test simulating the exact facade workflow.
- Test count: 389 → 402 (all passing)
- Integration test: 9/9 PASS. Verified with the most rigorous check yet:
  precise before/after delta on the live production DB —
  `episodes: 12023→12024 (+1), observations: 151358→151368 (+10)` —
  identical pattern to Phase 4, confirming the restructured orchestration
  produces byte-identical atomic behavior to before the restructure.

**Process note:** Desktop Commander MCP went unresponsive mid-edit during
this phase (the `__init__` construction edit). Did not assume it landed;
verified the actual file state directly once the server recovered, found
the edit had NOT applied, and redid it correctly before proceeding.

**Definition of Done, verified for Phase 5:**
- [✓] Store extracted
- [✓] LoggerFacade delegates correctly (full orchestration restructure,
  not simple CRUD delegation)
- [✓] Repository Independence confirmed (standalone construction + 13
  tests + AST-verified zero import of ObservationStore)
- [✓] Old inline implementation removed (log_episode() has no inline SQL
  left at all)
- [✓] Full test suite passes (402/402)
- [✓] Logger public API unchanged (facade-stability test)
- [✓] Behavioral equivalence verified against live production DB via
  precise before/after delta, matching Phase 4's elevated bar
- [✓] Real caller (PlayerProfiler) verified working through the delegated
  get_player_episodes(), not just isolated unit tests

**Acceptance:** impl ✓ | unit tests ✓ | integration ✓ | db verified ✓ | docs ✓

**Phase 6 (Facade cleanup) — NOT STARTED.** Final phase per extraction
order. Per Artifact 4: confirm `EpisodeLogger` delegates cleanly to all six
stores plus the facade-level methods, review the now-fully-delegated file
for any remaining dead code or unused imports (json/uuid may no longer be
directly needed in logger.py itself — verify, don't assume), and revisit
D023 (store-construction registry) now that all six stores exist.

### Candidate E — Scout Mechanics [NOT STARTED]
- Hidden armies, scout report success/failure, intel confidence
- Touches Stage 1 files (battle.py, grid.py)
- Deferred until D is done

---

## Architecture Decisions (permanent record)

| Date | Decision | Reason |
|------|----------|--------|
| 2026-06-19 | SQLite over PostgreSQL | M1 efficiency, manageable volume |
| 2026-06-19 | Turn-based simulator | Simpler loop; upgrade to event-triggered later |
| 2026-06-19 | Intent abstraction over coordinate actions | Doctrines must generalise |
| 2026-06-20 | Zone coordinates prefixed _internal | Clean brain/simulator boundary |
| 2026-06-21 | Three memory stores | player_profiles, doctrines (anon), relationship |
| 2026-06-21 | Observations extracted per episode | Extractor reads patterns not raw episodes |
| 2026-06-22 | observed_outcomes = list of distinct effects | Not counts; counts in episode_count |
| 2026-06-22 | W005 solved by corpus rebalancing, not extractor weighting | world_model accurate; data fixed upstream |
| 2026-06-23 | TRAINING_PROFILE flag for corpus generation | Reproducible; profile-named not mode-numbered |
| 2026-06-25 | player_profiles PRIMARY KEY (server_id, player_id) | Server-scoped memory; cross-server isolation |
| 2026-06-25 | Persist raw evidence, derive metrics | formula changes → re-profile, no DB replay |
| 2026-06-25 | CommanderKnowledge as typed dataclass | Strict perception boundary; no dict sprawl |
| 2026-06-25 | Rule 3 extended to permit simulator.snapshot | CommanderKnowledge is perception, not simulator internals |
| 2026-06-25 | Hierarchical filter before scoring | Impossible intents eliminated before ranking |
| 2026-06-25 | Multiplicative scoring (doctrine × player × situation) | Factors are conditional, not independent |
| 2026-06-25 | decide() always returns full trace | Debugging + future feedback loop foundation |
| 2026-06-25 | Intent strings not GeneralIntent enum in brain | No battle.py import needed |
| 2026-06-28 | Integration test uses production DB | Real corpus doctrines needed for influence validation |
| 2026-06-28 | brain_intent_fn closes over loop ref | Snapshot requires live BattleLoop state, not BattleState arg |

---

## Change Log

### 2026-06-28 (Session 11 — Stage 3 Candidate A)
- scripts/run_integration_test.py: 368 lines, standalone integration test
- First live end-to-end run: simulator → brain → decision → battle → logging
- W009 discovered and logged: doctrines_consulted shows synthetic IDs
- KNOWN_ISSUES.md: W009 added, format cleaned
- PROGRESS.md: Stage 3 section added, Candidate A marked complete
- SESSION_HANDOFF.md: updated for Candidate B start

### 2026-06-27 (Handoff — state files updated)
- CLAUDE_BRIEFING.md fully rewritten for Stage 2 complete state
- PROGRESS.md restructured, Stage 2 marked complete
- KNOWN_ISSUES.md W005 marked resolved, new watch items added
- SESSION_HANDOFF.md updated for Stage 3 start

### 2026-06-25 (Session 10 — decision_engine.py + snapshot)
- src/simulator/snapshot.py: CommanderKnowledge dataclass
- BattleLoop.to_brain_snapshot(): live perception snapshot
- Rule 3 extended: simulator.snapshot permitted for brain imports
- src/brain/decision_engine.py: 456 lines, hierarchical pipeline
- 43 decision engine tests + 20 snapshot tests
- 304/304 passing

### 2026-06-25 (Session 9 — player_profiler.py)
- player_profiles: (server_id, player_id) composite PK
- migrate_player_profiles() ran on production DB
- unit_types added to _unit_summary() (BC)
- src/brain/player_profiler.py: 258 lines, 35 tests
- 242/242 passing

### 2026-06-25 (Session 8 — doctrine_extractor.py)
- logger.py: upsert_doctrine, get_doctrine_by_id, get_all_doctrines
- src/brain/doctrine_extractor.py: 202 lines, 36 tests
- Deterministic ids, PRINCIPLE_TEMPLATES, anonymous, idempotent
- 207/207 passing

### 2026-06-24 (Session 7 — balanced profile fix)
- balanced profile: heavy_rain=0.0, flood removed from targets
- Ran corpus: 1900 battles, all targets met
- 169/169 passing

### 2026-06-23 (Session 6 — training profiles)
- src/simulator/training_profiles.py: 5 profiles
- scripts/generate_corpus.py: CLI generation tool
- weather_weights param added to BattleLoop
- 169/169 passing

### 2026-06-22 (Session 5 — world_model.py)
- src/brain/world_model.py: 184 lines, 30 tests
- logger.py: upsert_terrain_knowledge, get_terrain_knowledge, get_all_terrain_knowledge
- 147/147 passing

### 2026-06-21 (Session 4 — logger.py + Stage 1 complete)
- src/simulator/logger.py: 562 lines, 27 tests
- 100 battles → 6526 observations
- 117/117 passing

### Pre-session-4
- grid.py, units.py, physics.py, battle.py built and tested
- Zone coordinate abstraction enforced
- Three-store memory architecture established
