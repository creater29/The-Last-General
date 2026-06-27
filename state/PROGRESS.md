# Progress Tracker

## Current Stage: STAGE 2 — COMPLETE ✅
## Last Updated: 2026-06-27
## Test Count: 304/304

---

## Stage 1 — Simulator [COMPLETE ✅]

| File | Tests | Notes |
|------|-------|-------|
| src/simulator/grid.py | 12 | Terrain world, zone generation |
| src/simulator/units.py | 29 | Unit types, mass, behaviour |
| src/simulator/physics.py | 23 | Terrain interaction engine |
| src/simulator/battle.py | 26 | Battle loop + to_brain_snapshot() |
| src/simulator/logger.py | 31 | SQLite persistence, all DB access |
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
| src/brain/decision_engine.py | 43 | Hierarchical reasoning pipeline |

### Stage 2 Completion Criteria (all met)
- ✅ General forms 4 doctrines with confidence > 0.6 (one per terrain event type)
- ✅ Player profile populates from episode history
- ✅ Decisions differ by context (TERRAIN_EXPLOIT on frozen lake, DEFENSIVE_HOLD vs aggressive player)
- ✅ Decision reasoning is inspectable (full trace in decide() output)
- ✅ 304/304 tests passing

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

---

## Change Log

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
