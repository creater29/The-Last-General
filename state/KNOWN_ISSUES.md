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

### W002 — RESOLVED 2026-06-28 (Candidate B) — No feedback loop on doctrine quality
**Risk (as originally written):** failure_count and decay_rate fields exist in
doctrines table but are always 0. The General's doctrines never degrade after a
failed application, and never improve from repeated success.
**Superseded — found stale during the Stage 3 consolidation audit,
2026-09-04:** this entry described a pre-Candidate-B state and was never
updated once Candidate B actually built the feedback loop it worried
about. `DecisionEngine.record_battle_outcome()` and
`EpisodeLogger.increment_doctrine_failure()` exist and work — see R007
above, and re-verified directly (not assumed) during this session's
Stage 3 completion exercise: 504 real `failure_count` increments applied
across 18 battles, asserted to match `record_battle_outcome()`'s
reported total exactly.
**Status:** Resolved. Left in the Watch List (rather than moved to
Resolved Issues) only because it predates this file's current
categorization convention — content is otherwise identical to a Resolved
entry.

### W003 — Decision scoring weights are untested heuristics
**Risk:** Weather factors (×1.4 for fog+ambush, ×0.7 for blizzard+attack etc.)
and player adaptation multipliers were set by judgement, not calibration.
**Confirmed behavior:** Integration test showed confidence=1.0 for winner every
turn. Normalization (score-min)/range correctly reflects dominance, but
weights have not been calibrated against real outcomes.
**Mitigation planned:** Log every decide() call with all factors. Review factor
distributions after 1000 live decisions. Calibrate from observed outcomes.
**Tracked as D005/D017 in `DEFERRED_ITEMS.md`** (found during the Stage 3
consolidation audit, 2026-09-04, that this entry and those two deferred
items describe the same concern without cross-referencing each other —
this note closes that gap). Both remain correctly untriggered: the
1000-live-decision threshold has not been reached — production has
0 rows in `player_profiles` (all 12,000+ episodes came from corpus
generation, which never calls `decide()` through the live pipeline), and
the Stage 3 exercise's 18 battles don't change that by themselves.
**When to address:** After 1000+ live decisions are logged (see D005/D017
for the exact trigger) — no longer described as "Stage 3B or 3C," which
were never real sub-stage labels this project used.

### W004 — Turn-based to event-triggered upgrade
**Risk:** Simulator built turn-based may need significant refactoring
when upgrading to event-triggered execution.
**Mitigation:** Keep battle loop modular. The to_brain_snapshot() method
is the clean integration point — the engine receives a snapshot per turn,
which maps naturally to event-triggered: snapshot per event instead.
**Tracked as D009 in `DEFERRED_ITEMS.md`**, which is explicit that this is
**Stage 4** scope (start of Stage 4, before any Stage 4 features) — found
during the Stage 3 consolidation audit, 2026-09-04, that "Stage 3+" here
was vague and predates D009's precise scoping.
**When to address:** Start of Stage 4, per D009 — not "Stage 3 planning."

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
**Tracked as D020 in `DEFERRED_ITEMS.md`** (cross-reference added during
the Stage 3 consolidation audit, 2026-09-04). Re-verified live during the
same audit: still exactly 6 entries in `PRINCIPLE_TEMPLATES`
(`src/brain/doctrine_extractor.py`), well under the 20-entry trigger.
**When to address:** When entry count reaches 20, per D020.

### W007 — CommanderKnowledge snapshot field scope creep
**Risk:** snapshot.py could become a dumping ground if future developers
add fields without discipline. Each added field increases what the brain
"knows" and could silently break the perception boundary.
**Mitigation:** CommanderKnowledge is a typed dataclass (not a dict) so
adding fields requires explicit code change visible in git. The import
constraint tests catch any attempt to bypass snapshot.py via battle.py.
**Tracked as D021 in `DEFERRED_ITEMS.md`** (cross-reference added during
the Stage 3 consolidation audit, 2026-09-04) — a process-discipline item,
not a build task. Confirmed actually followed in practice: Candidate E's
`known_enemy_composition` field addition went through exactly this
review question before being added.
**When to address:** Review before each new field addition. Ask: is this
something the General can genuinely observe without a scout report?

### W008 — RESOLVED 2026-06-28 (Candidate C) — player_general_relationship table not yet built
**Risk (as originally written):** Third memory store described in
architecture is empty. Relational memory (trust level, betrayal count,
cooperation history) is tracked nowhere.
**Superseded — found stale during the Stage 3 consolidation audit,
2026-09-04:** Candidate C built exactly this — `src/brain/
relationship_manager.py`, `RelationshipManager`/`RelationshipState`, wired
into `decision_engine.py`'s `_relationship_factor()`. Verified live and
working again this session via the Stage 3 completion exercise's
controlled factor comparisons (trust=-0.30 measurably changing
`DEFENSIVE_HOLD`/`AGGRESSIVE_PUSH` scores with explanatory reasoning
notes).
**Status:** Resolved. Left in the Watch List, same reasoning as W002.

### W010 — Hardcoded absolute import path in test files (logged 2026-09-04, Candidate E E1 Step 2 review)
**Component:** tests/test_battle.py (confirmed), likely other test files —
not yet audited comprehensively.
**Description:** `sys.path.insert(0, "/Users/Arman/Projects/general_brain/src")`
hardcodes an absolute path rather than deriving it from `__file__`. This
contradicts the reproducibility claim made by `requirements.txt` +
`pyproject.toml` (added during Candidate E's supervisor review process) —
a fresh clone on another machine, another user account, or Linux would
fail this line even with dependencies correctly installed. Predates
Candidate E; discovered while extending `test_battle.py` for E1 Step 2,
flagged by supervisor review as out of scope for that step.
**Fix — RESOLVED 2026-09-04 (Stage 3 consolidation audit):** all five files
(`test_grid.py`, `test_battle.py`, `test_units.py`, `test_physics.py`,
`test_logger.py`) fixed, replaced with `sys.path.insert(0,
str(Path(__file__).parent.parent / "src"))`, matching the pattern already
correct elsewhere. Verified no hardcoded `/Users/` path remains anywhere
in `tests/`, `src/`, or `scripts/`.
**Status:** Resolved.

### W011 — decide()'s fallback response is missing documented return-dict keys (logged 2026-09-04, Candidate E E1 Step 3 planning)
**Component:** src/brain/decision_engine.py (`DecisionEngine._fallback_response()`)
**Description:** `decide()`'s docstring documents `relationship_used` as
part of its return contract ("True if a relationship record was
available"), but `_fallback_response()` — used when situation-filtering
leaves zero available intents — omits that key entirely. A caller relying
on the documented contract gets a `KeyError` on the fallback path
specifically, which is exactly the path most likely to occur when
knowledge is degraded (the scenario a caller most needs to handle
gracefully). Predates Candidate E; discovered while reading
`decision_engine.py` fresh for E1 Step 3, and directly relevant to Step 3
because the same question (does the fallback path need the new
`composition_used` key too?) came up for the new field. Resolved for the
new field only (Step 3 explicitly adds `composition_used: False` to the
fallback response, per supervisor decision, to avoid repeating this
exact mistake for a second field) — the pre-existing `relationship_used`
gap itself was left for a dedicated consolidation-audit pass (see fix
below, which is that pass).
**Fix — RESOLVED 2026-09-04 (Stage 3 consolidation audit):** added
`"relationship_used": False` to `_fallback_response()`'s return dict,
matching the pattern already established for `composition_used`. New
regression test `test_fallback_response_includes_relationship_used_false`.
**Status:** Resolved.

### W012 — RESOLVED 2026-09-04 — terrain_tendencies "wins"/"losses" were computed from the General's outcome, not the player's
**Component:** `src/brain/player_profiler.py` (`update_profile()`'s
`terrain_stats` computation)
**Description:** `terrain_tendencies[terrain]["wins"/"losses"]` was
computed directly from `ep["_result"]`, which is `BattleState.result` —
the **General's** win/loss outcome, not the player's. `_player_factor()`'s
`TERRAIN_EXPLOIT` boost reads this value as the player's win rate
(reasoning note: *"Player wins only X% on \<terrain\>..."*) and boosts
`TERRAIN_EXPLOIT` when that rate is low — i.e., when the General should
exploit a terrain the player struggles on.
**This was NOT cosmetic — it was a live decision-quality bug**, correctly
identified as such during supervisor review of the Stage 3 completion
exercise. Original report claimed the terrain factor was verified working
(`TERRAIN_EXPLOIT` 1.679 vs 1.399) using a dataset where the General had
in fact lost every battle on that terrain — meaning the *player* had won
every encounter, the exact opposite of what a "boost because the player
is weak here" signal should represent. With the inverted stored data, the
General would have been encouraged to exploit terrain where the player
was actually strongest.
**Fix:** `player_profiler.py`'s `terrain_stats` computation now increments
`"wins"` when `ep["_result"] == "loss"` (General lost -> player won) and
`"losses"` when `ep["_result"] == "win"` (General won -> player lost) —
inverted at the source, so `_player_factor()`'s existing logic and its
existing tests (which already encoded the *correct* intended semantics
with directly-constructed synthetic dicts) needed no changes.
**Regression tests added:** `test_terrain_tendencies_known_general_win_episode_records_player_loss`,
`test_terrain_tendencies_known_general_loss_episode_records_player_win` —
single-episode, unambiguous cases pinning the correct direction.
`test_terrain_tendencies_counts_wins_and_losses` (which previously pinned
the *wrong* direction as correct — the same failure pattern as the
AGGRESSIVE_INTENTS vocabulary bug earlier this session, a test asserting
buggy behavior is what let both bugs survive) corrected to match.
**Stage 3 completion exercise rerun after the fix:** the terrain-exposure
cohort's real data showed the player winning 100% of its terrain
encounters (General lost all 6 terrain-cohort battles) — so post-fix,
`TERRAIN_EXPLOIT` correctly does NOT boost for this dataset (factor
identical, 1.399, with or without relevant terrain visible). This is the
honest, corrected result — the exercise's job was to find the truth, not
manufacture a positive result. See `state/STAGE3_COMPLETION_REPORT.md`
for the corrected report.
**Commits:** bugfix + tests in the same commit as the corrected exercise
rerun, 2026-09-04.

### W013 — RESOLVED 2026-09-04 — adaptability_score, win_count/loss_count, and preferred_units["wins"] were all General-perspective, not player-perspective
**Component:** `src/brain/player_profiler.py` (`update_profile()`)
**Description:** Initially logged as "dormant" — that classification was
**wrong** and corrected by a second supervisor review pass. `grep` for
`preferred_units` in `decision_engine.py` does return no matches, so
*that one field* was genuinely dormant. But the same
General-perspective-used-directly pattern also affected `win_count`/
`loss_count` (top-level profile fields) and, critically,
**`adaptability_score`** — which **is** live, read directly inside
`_player_factor()`'s `COUNTER_AGGRESSIVE` boost condition
(`if adaptability < 0.3 and aggression > 0.6 and intent in
COUNTER_AGGRESSIVE: factor *= 1.1`). Before this fix, "adaptation" was
counted after `episodes[i]["_result"] == "loss"` — a **General** loss,
meaning the player had just **won** that battle. So the system could
label a player "unadaptable after losses" based on battles the player
actually won, and use that incorrect score to boost counter-aggressive
decisions. This was a real, live decision-quality defect, not dormant
data — exactly the same category of bug as W012, just not caught in the
first pass because the Stage 3 exercise's specific cohorts (Aggressor:
no intent variation at all; Terrain: not adaptability-focused) happened
not to expose it numerically, even though the underlying computation was
wrong.
**Fix:** `player_won(ep)`/`player_lost(ep)` defined once in
`player_profiler.py` (`ep["_result"] == "loss"` / `== "win"` respectively)
and used consistently for `win_count`/`loss_count`,
`adaptability_score`'s adaptation-counting and its denominator,
`preferred_units["wins"]`, and `terrain_tendencies` (refactored to use
the same helpers, no logic change there — W012's fix was already
correct). Module docstring updated to state the invariant explicitly:
every derived field in this module must go through these two helpers,
never `ep["_result"]` directly.
**Tests:** 4 new regression tests using single, unambiguous known-outcome
episodes — `test_win_count_known_general_loss_episode_records_player_win`,
`test_loss_count_known_general_win_episode_records_player_loss`,
`test_adaptability_known_general_win_then_switch_records_player_adaptation`,
`test_adaptability_known_general_loss_does_not_count_as_player_adaptation`.
Existing `test_win_loss_draw_counts_correct` and the three
`test_adaptability_*` tests corrected (they previously pinned the wrong
direction as correct — the same failure pattern as both prior bugs this
session).
**Stage 3 completion exercise:** rerun in full after the fix. Headline
numbers for this specific run are unchanged from the previous (W012-only)
run — the Aggressor cohort never switches intent (no adaptability signal
either way) and the Terrain cohort's `terrain_tendencies` was already
correct from the W012 fix — but the underlying model is now internally
consistent and verified directly by the 4 regression tests above, which
is the more rigorous proof; it should not require a specific dataset to
happen to expose a bug for the fix to be trusted.
**Commits:** fix + tests + exercise rerun, 2026-09-04.
