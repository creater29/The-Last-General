# Progress Tracker

## Current Stage: STAGE 3 — IN PROGRESS 🔄
## Last Updated: 2026-06-28
## Test Count: 365/365

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

### Candidate D — Logger Repository Split [IN PROGRESS 🔄 — Phase 2/6 complete]

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

**Phase 3 (DoctrineStore) — NOT STARTED.** Next up per extraction order.

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
