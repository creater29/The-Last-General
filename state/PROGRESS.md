# Progress Tracker

## Current Stage: STAGE 3 — IN PROGRESS 🔄
## Last Updated: 2026-06-28
## Test Count: 319/319

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

### Candidate C — Player-General Relationship [NEXT 🔲]
- Build player_general_relationship table (trust, betrayal, cooperation)
- Schema described in ARCHITECTURE.md; no code exists yet
- Requires live loop (now available) to generate relationship events

### Candidate D — Logger Repository Split [NOT STARTED]
- logger.py at ~885 lines; split into EpisodeRepository, ObservationRepository,
  DoctrineRepository, ProfileRepository
- Pure refactor; deferred until after B

### Candidate E — Scout Mechanics [NOT STARTED]
- Hidden armies, scout report success/failure, intel confidence
- Touches Stage 1 files (battle.py, grid.py)
- Deferred until C is done

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
