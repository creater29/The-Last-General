# Progress Tracker

## Current Stage: STAGE 2 — IN PROGRESS
## Last Updated: 2026-06-25

---

## Stage 1 — Simulator [COMPLETE ✅]

### Files
- [x] src/simulator/grid.py       — 12 tests
- [x] src/simulator/units.py      — 29 tests
- [x] src/simulator/physics.py    — 23 tests
- [x] src/simulator/battle.py     — 26 tests
- [x] src/simulator/logger.py     — 27 tests + 3 terrain_knowledge methods added
- [x] src/simulator/training_profiles.py — (tested via test_training_profiles.py)
- Total: 117 simulator tests passing (+ 22 via training profiles)

### Stage 1 Verified Results (100 battles)
- 100 battles in 9.4s (94ms per battle)
- 6526 observations extracted and stored
- Result distribution: win=13, loss=63, draw=24
- Terrain events: flood=6296, tree_fall=146, wall_collapse=78, ice_break=6
- DB: ~/Projects/general_brain/data/episodes/general_brain.db

---

## Stage 2 — Brain Core [IN PROGRESS]

### Target Files
- [x] src/brain/world_model.py     — 30 tests
- [ ] src/brain/doctrine_extractor.py

### Corpus Generation
- [x] src/simulator/training_profiles.py — 5 profiles (natural/anti_flood/terrain_learning/siege_learning/balanced)
- [x] scripts/generate_corpus.py         — targeted generation with target counts and progress bars
- [x] Balanced corpus generated (1900 battles, 97s, 19.7 battles/s)
- Total: 169 tests passing

### DB State After Balanced Corpus Run
| event        | observations |
|--------------|-------------|
| flood        | 118,124     | ← pre-existing from earlier flood-heavy runs
| tree_fall    |  20,396     | ← target 1000 ✅
| wall_collapse|  11,597     | ← target 1000 ✅
| ice_break    |   1,011     | ← target 1000 ✅

All four event types are above the 5-observation doctrine threshold.
Corpus is ready for doctrine_extractor.py.
- [ ] src/brain/player_profiler.py
- [ ] src/brain/decision_engine.py
- [ ] src/brain/memory.py
- [ ] tests/test_brain.py

### Completion Criteria
After 100 simulated episodes the General:
1. Has formed at least 3 doctrines with confidence > 0.6
2. Has a player profile with populated fields
3. Makes decisions that demonstrably differ from random
4. Decision reasoning is inspectable and makes sense

### Status
world_model.py complete. doctrine_extractor.py complete. Next: player_profiler.py.

---

## Change Log

### 2026-06-25 (Session 9 — player_profiler.py)
- player_profiles schema: server_id+player_id composite PK (server-scoped memory)
- Added migrate_player_profiles() to logger.py — ran on production DB
- Added unit_types to BattleLoop._unit_summary() (BC, adds field to episode data)
- Added logger methods: get_player_episodes, upsert_player_profile, get_player_profile, get_all_player_profiles
- Built src/brain/player_profiler.py (258 lines) — 35 tests
- Raw evidence in data blob; aggression_index/adaptability_score as computed columns
- Updated 4 test_logger.py tests to new server-scoped API
- Full suite: 242/242 passing

### 2026-06-25 (Session 8 — doctrine_extractor.py)
- Added test_balanced_disables_heavy_rain + test_generate_corpus_no_flood_with_balanced_profile (2 tests)
- Added upsert_doctrine, get_doctrine_by_id, get_all_doctrines to logger.py
- Built src/brain/doctrine_extractor.py (202 lines) — 36 tests
- Doctrine ids are deterministic: "doctrine_{terrain}_{action}_{effect}"
- derived_principle uses PRINCIPLE_TEMPLATES with plain-English fallback
- Doctrines anonymous, no coordinates, idempotent extraction confirmed
- Full suite: 207/207 passing

### 2026-06-24 (Session 7 — balanced profile fix + corpus generation)
- Fixed balanced profile: heavy_rain set to 0.0, flood removed from targets
- Fixed test_balanced_targets_three_events_no_flood to match new spec
- Ran balanced corpus: 1900 battles, 97s, all three rare-event targets met
- DB now has 1011 ice_break / 11597 wall_collapse / 20396 tree_fall / 118124 flood
- Confirmed: 0 new flood events in 1900 balanced battles (block works)
- Full suite: 169/169 passing

### 2026-06-23 (Session 6 — Training profiles + corpus generation)
- Built src/simulator/training_profiles.py (175 lines) — 5 profiles
- Built scripts/generate_corpus.py (237 lines) — CLI generation tool with target counts
- Added weather_weights param to BattleLoop (2 surgical edits, backward compatible)
- Fixed balanced profile: heavy_rain=0.0, flood removed from targets
- Ran balanced corpus: 1900 battles, 97s, all targets met
- Final DB state: flood=118124, tree_fall=20396, wall_collapse=11597, ice_break=1011
- All four event types well above doctrine threshold (5+)
- Full suite: 169/169 passing

### 2026-06-22 (Session 5 — world_model.py)
- Built src/brain/world_model.py (184 lines) — 30 tests, all passing
- Added upsert_terrain_knowledge, get_terrain_knowledge, get_all_terrain_knowledge to logger.py
- observed_outcomes confirmed as list of distinct effect types (not counts)
- Confidence formula: episode_count / (episode_count + 1) — confirmed intentional
- W005 (flood dominance) explicitly deferred to doctrine_extractor — world_model represents observations accurately
- Full suite: 147/147 passing

### 2026-06-21 (Session 4 — logger.py + Stage 1 Complete)
- Built src/simulator/logger.py (562 lines) — 27 tests
- Full suite: 117/117 passing
- Ran 100 battles into real DB — 9.4s total, 6526 observations
- Stage 1 COMPLETE

### 2026-06-21 (Session 3 — Fixes + Architecture)
- Fixed zone coordinate abstraction leak
- Fixed TERRAIN_EXPLOIT intent bug
- Updated player memory to three-store architecture
- Updated database schema to 7 tables
- 90/90 tests passing

### 2026-06-20 (Session 2)
- units.py, physics.py, battle.py built and tested
- Full suite: 90/90 passing

### 2026-06-20 (Session 1)
- grid.py built and tested (12/12)
- Zone system redesigned: emergent military zones
- Architecture established

### 2026-06-19 (Session 0)
- Project initialized, structure created, stack confirmed

---

## Decisions Made (permanent record)
| Date       | Decision | Reason |
|------------|----------|--------|
| 2026-06-19 | SQLite over PostgreSQL | M1 efficiency, Stage 1-2 volume manageable |
| 2026-06-19 | Turn-based simulator first | Simpler loop, upgrade later |
| 2026-06-19 | Intent abstraction over coordinate actions | Doctrines must generalize |
| 2026-06-19 | No GPU for Stage 1-2 | M1 8GB, CPU sufficient |
| 2026-06-20 | Zone coordinates prefixed _internal | Clean brain/simulator boundary |
| 2026-06-21 | Three memory stores | player_profiles, doctrines (anon), relationship |
| 2026-06-21 | Observations extracted per episode | Doctrine extractor reads patterns not raw episodes |
| 2026-06-22 | observed_outcomes = list of distinct effect types | Doctrine extractor reads effects, not counts; counts come from episode_count |
| 2026-06-22 | W005 flood dominance handled in doctrine_extractor only | world_model represents observations faithfully; weighting is downstream concern |

---

## Deleted / Abandoned
- Hardcoded zone names (left_flank, center, right_flank) — replaced by emergent zones
- boss-fight fields in PlayerProfile (weapon_preference, dodge_bias, spell_usage) — replaced by commander-level fields
