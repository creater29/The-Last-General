# Known Issues

## Format
Each entry:
- Date discovered
- Component affected
- Description
- Attempted fixes (and whether they worked)
- Current status

---

## Open Issues
None currently.

---

## Resolved Issues

### R001 — Zone coordinates leaking to brain (FIXED 2026-06-21)
**Component:** grid.py, battle.py
**Description:** military_zones() was returning center_x/center_y in zone dicts,
which then passed through to_episode() into brain-facing data.
**Fix:** Prefixed internal keys with underscore (_center_x, _center_y).
to_episode() strips all underscore-prefixed keys before persisting.
_execute_general_intent() uses _center_x/_center_y internally only.
**Status:** Resolved. Test test_no_coordinates_in_stored_episode() enforces this.

### R002 — TERRAIN_EXPLOIT intent using old key name (FIXED 2026-06-21)
**Component:** battle.py _execute_general_intent()
**Description:** After R001 fix renamed center_x to _center_x, the
TERRAIN_EXPLOIT branch still used the old key name, causing KeyError at runtime.
**Fix:** Updated to use zone["_center_x"], zone["_center_y"].
**Status:** Resolved. All 117 tests pass.

### R003 — player_losses returned int 0 instead of float (FIXED 2026-06-21)
**Component:** battle.py _run_turn()
**Description:** When no combat results matched, sum() returned int 0,
but TurnRecord.player_losses typed as float caused test assertion failure.
**Fix:** Wrapped both loss calculations in float().
**Status:** Resolved.

### R004 — Grid too small for terrain zone generation (FIXED 2026-06-20)
**Component:** tests/test_units.py
**Description:** Test used Grid(20,20) but zone generation requires
min grid size ~28x28 (max_r=14 needs margin on both sides).
**Fix:** Removed Grid dependency from that test — used bare Cell directly.
**Status:** Resolved.

---

## Watch List (potential future problems, not yet issues)

### W001 — Episode batch memory on 8GB M1
**Risk:** Loading large episode batches for doctrine extraction
may pressure 8GB unified memory.
**Mitigation planned:** Stream episodes in batches of 1000 max.
Never load full database into memory.
**When to address:** When episode count exceeds 10,000.

### W002 — Doctrine extraction cold start
**Risk:** With fewer than 50 episodes per terrain type,
confidence scores will be too low to produce meaningful doctrines.
**Mitigation planned:** Run 500+ simulator battles before evaluating brain.
100 episodes currently in DB — run more before judging Stage 2.
**When to address:** Stage 2 start. Already partially mitigated: 6526 observations.

### W003 — Scoring weight initialization
**Risk:** Initial weights (0.4 doctrine, 0.3 counter_doctrine,
0.2 terrain, 0.1 risk) are untested guesses.
**Mitigation planned:** Log every decision with weights used.
Review after 1000 episodes. Adjust based on observed behavior.
**When to address:** Stage 2, decision_engine.py.

### W004 — Turn-based to event-triggered upgrade path
**Risk:** Simulator built turn-based may need significant
refactoring when upgrading to event-triggered execution.
**Mitigation planned:** Keep battle loop modular.
Isolate the tick/turn logic so it can be replaced.
**When to address:** Stage 3 planning.

### W005 — Flood dominates observation data (KNOWN 2026-06-21)
**Risk:** 96% of observations (6296/6526) are flood events from heavy_rain weather.
Only 6 ice_break events in 100 battles. Doctrine extractor may over-fit to flood.
**Mitigation planned:** In Stage 2, weight rare events higher. Consider
adjusting weather probability to generate more diverse terrain events.
Also run 500-1000 more battles before doctrine extraction.
**When to address:** doctrine_extractor.py in Stage 2.
