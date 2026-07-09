# Known Issues

## Format
Each entry: date, component, description, fix, current status.

---

## Open Issues

None.

---

## Resolved Issues

### R008 — get_known_players() removed (RESOLVED 2026-06-28, Candidate D Phase 6)
**Component:** src/simulator/logger.py
**Description:** Was orphaned and broken — queried `encounter_count`, a
column that doesn't exist in the current `player_profiles` schema. Zero
callers anywhere, confirmed twice (once at discovery, once at resolution).
**Resolution:** Re-checked for a consumer one final time at Phase 6, per
its own stated resolution rule ("Candidate D... if still no consumer found,
delete it"). Still zero callers. Deleted rather than repaired. Facade-
stability test baseline updated in the same commit with this reason.
**Status:** Resolved. Method no longer exists.

---

## Resolved Issues

### R007 — doctrines_consulted field used synthetic IDs, not real doctrine IDs (FIXED 2026-06-28)
**Component:** src/brain/decision_engine.py (_doctrine_factor, decide())
**Description:** The `doctrines_consulted` list in `decide()` output was
returning synthetic strings constructed from terrain context rather than
real doctrine IDs from the DB. Discovered during Stage 3 Candidate A audit.
**Fix:** `_doctrine_factor()` returns `[best["id"]]` — the matched doctrine's
actual `id` field from the DB (e.g., `'doctrine_forest_cavalry_tree_fall'`).
`decide()` collects real IDs into `doctrines_consulted` and passes them to
`record_battle_outcome()`. Verified in integration test: only the two consulted
doctrines had `failure_count` incremented after a loss; unconsulted doctrines
were unchanged.
**Status:** Resolved. Verification confirmed in run_integration_test.py output.

### R001 — Zone coordinates leaking to brain (FIXED 2026-06-21)
**Component:** grid.py, battle.py
**Description:** military_zones() returned center_x/center_y in zone dicts,
which passed through to_episode() into brain-facing data.
**Fix:** Prefixed internal keys with underscore (_center_x, _center_y).
to_episode() strips all underscore-prefixed keys before persisting.
**Status:** Resolved. test_no_coordinates_in_stored_episode() enforces this.

### R002 — TERRAIN_EXPLOIT using old key name (FIXED 2026-06-21)
**Component:** battle.py _execute_general_intent()
**Description:** After R001 fix renamed center_x to _center_x, the
TERRAIN_EXPLOIT branch still used the old key name, causing KeyError.
**Fix:** Updated to use zone["_center_x"], zone["_center_y"].
**Status:** Resolved.

### R003 — player_losses int instead of float (FIXED 2026-06-21)
**Component:** battle.py _run_turn()
**Description:** sum() returned int 0; TurnRecord.player_losses typed as float.
**Fix:** Wrapped both loss calculations in float().
**Status:** Resolved.

### R004 — Grid too small for test (FIXED 2026-06-20)
**Component:** tests/test_units.py
**Description:** Test used Grid(20,20) but zone generation needs min ~28x28.
**Fix:** Removed Grid dependency; used bare Cell directly.
**Status:** Resolved.

### R005 — test seed_observations id collision (FIXED 2026-06-22)
**Component:** tests/test_world_model.py
**Description:** seed_observations truncated terrain_context to 6 chars for
obs_id prefix. "river+weather"[:6] == "river+cavalry"[:6] == "river+",
causing INSERT OR IGNORE to silently drop the second batch.
**Fix:** Use full strings: tag = f"{terrain_context}_{effect}".replace("+","_")
**Status:** Resolved. All seed_observations helpers in all test files use full strings.

### R006 — player_profiles schema missing server_id (FIXED 2026-06-25)
**Component:** logger.py init_db(), player_profiler.py
**Description:** Original schema had player_id as bare PRIMARY KEY.
Cross-server isolation impossible — Steve on Server A would be known on Server B.
**Fix:** Schema changed to PRIMARY KEY (server_id, player_id).
migrate_player_profiles() method added. Run on production DB 2026-06-25.
All profiler methods now require server_id parameter.
**Status:** Resolved. 4 test_logger.py tests updated.

---

## Watch List (potential future problems)

### W001 — Episode batch memory on 8GB M1
**Risk:** Loading large episode batches for doctrine extraction
may pressure 8GB unified memory.
**Mitigation:** Stream episodes in batches of 1000 max. Never load full DB.
**When to address:** When episode count exceeds 50,000.

### W002 — No feedback loop on doctrine quality
**Risk:** failure_count and decay_rate fields exist in doctrines table
but are always 0. The General's doctrines never degrade after a failed
application, and never improve from repeated success.
**Mitigation planned:** Wire failure_count increment when a doctrine-backed
decision leads to a loss. decay_rate logic reduces confidence over time
without observed reinforcement. Requires W009 fix first (need real doctrine IDs).
**When to address:** Stage 3 Candidate B.

### W003 — Decision scoring weights are untested heuristics
**Risk:** Weather factors (×1.4 for fog+ambush, ×0.7 for blizzard+attack etc.)
and player adaptation multipliers were set by judgement, not calibration.
**Confirmed behavior:** Integration test showed confidence=1.0 for winner every
turn. Normalization (score-min)/range correctly reflects dominance, but
weights have not been calibrated against real outcomes.
**Mitigation planned:** Log every decide() call with all factors. Review factor
distributions after 1000 live decisions. Calibrate from observed outcomes.
**When to address:** After integration test is running and logging decisions
(now complete) — revisit during Stage 3B or 3C.

### W004 — Turn-based to event-triggered upgrade
**Risk:** Simulator built turn-based may need significant refactoring
when upgrading to event-triggered execution (Stage 3+).
**Mitigation:** Keep battle loop modular. The to_brain_snapshot() method
is the clean integration point — the engine receives a snapshot per turn,
which maps naturally to event-triggered: snapshot per event instead.
**When to address:** Stage 3 planning.

### W005 — Flood dominance (RESOLVED 2026-06-23)
**Component:** training_profiles.py, generate_corpus.py
**Description:** 96% of original observations (6296/6526) were flood events.
Doctrine extractor risked over-fitting to flood.
**Resolution:** balanced training profile with heavy_rain=0.0 + target counts.
1900 battles generated: ice_break=1011, wall_collapse=11597, tree_fall=20396.
DB now has balanced evidence for all four terrain event types.
**Status:** Resolved.

### W006 — PRINCIPLE_TEMPLATES will not scale
**Risk:** 6 hardcoded entries in doctrine_extractor.py. Will become
unwieldy at 20+ entries. Unknown combinations fall back to template string.
**Mitigation planned:** When entry count reaches 20, refactor to metadata-
driven generation (terrain → action → effect → principle string).
**When to address:** When new terrain types or event types are added.

### W007 — CommanderKnowledge snapshot field scope creep
**Risk:** snapshot.py could become a dumping ground if future developers
add fields without discipline. Each added field increases what the brain
"knows" and could silently break the perception boundary.
**Mitigation:** CommanderKnowledge is a typed dataclass (not a dict) so
adding fields requires explicit code change visible in git. The import
constraint tests catch any attempt to bypass snapshot.py via battle.py.
**When to address:** Review before each new field addition. Ask: is this
something the General can genuinely observe without a scout report?

### W008 — player_general_relationship table not yet built
**Risk:** Third memory store described in architecture is empty.
Relational memory (trust level, betrayal count, cooperation history)
is tracked nowhere.
**Mitigation planned:** Build as Stage 3 component after integration test.
**When to address:** Stage 3 Candidate C.
