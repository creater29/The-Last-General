# Stage 3 Completion — Multi-Player Live Intelligence Exercise Report

**Date:** 2026-09-04 (corrected after supervisor review found a real
behavioral bug in the first run — see "W012 correction" below)
**Script:** `scripts/stage3_completion_exercise.py`
**Exercise DB:** `data/exercises/stage3_completion_2026-09-04.db` (gitignored, generated data)
**Reproducibility:** confirmed — repeated end-to-end runs produce
identical results (all battle outcomes, trust values, aggression indices,
terrain tendencies, controlled factor comparisons, production DB hash);
the only observed difference across runs is wall-clock timing noise.

---

## W012 correction — what changed since the first version of this report

The first version of this report claimed a verified `TERRAIN_EXPLOIT`
boost (factor 1.679 vs 1.399) as evidence of terrain-driven decision
influence. Supervisor review correctly identified this as **invalid**:
`player_profiler.py`'s `terrain_tendencies["wins"/"losses"]` was computed
from `BattleState.result`, which is the **General's** outcome, not the
player's. In the terrain-exposure cohort, the General lost all 6
battles — meaning the *player* won every encounter — but the stored data
showed `wins: 0`, and `_player_factor()` read that as the player's win
rate, boosting `TERRAIN_EXPLOIT` under the belief the player was weak on
that terrain when the opposite was true. This was a real decision-quality
bug (now W012, resolved), not a wording issue as I originally
mischaracterized it.

**Fix:** `player_profiler.py`'s terrain computation now correctly
increments `"wins"` on a General *loss* (player won) and `"losses"` on a
General *win* (player lost). Two explicit regression tests were added
using single, unambiguous known-outcome episodes. The exercise was
rerun in full after the fix.

**Corrected result:** with the bug fixed, the terrain-exposure cohort's
real data shows the player won 100% of its terrain encounters (matching
the fact that the General lost all 6 of those battles). Post-fix,
`TERRAIN_EXPLOIT` **correctly does not boost** for this dataset — the
factor is identical (1.399) whether or not relevant terrain is visible.
This is the honest outcome: the exercise's job is to find the truth about
whether the mechanism works, not to manufacture a positive result. The
mechanism itself is now verified correct, even though this particular
dataset doesn't trigger it.

---

## Isolation proof

```
Production DB SHA-256 (before): d44e5f9a749907f382842446d89cab39a83dd28d1173623542c8c97e7b3adda7
Production DB SHA-256 (after):  d44e5f9a749907f382842446d89cab39a83dd28d1173623542c8c97e7b3adda7
Production DB unchanged: True
```

---

## Phase A — Deterministic doctrine bootstrap

- `generate_corpus.run(profile_name="balanced", max_battles=600, seed=20260904, db_path=<exercise DB>)`
- Player ID: `curriculum_balanced` — never reused in Phase B
- Bootstrap completed without exceptions: **True** (script now hard-fails via `RuntimeError` if this is False or if 0 doctrines are promoted — not merely logged)

**Doctrine baseline:**
```
total_doctrines: 3
effects_covered: [ice_break, tree_fall, wall_collapse]
terrain_types:   [forest, frozen_lake, wall]
avg_confidence:  0.9925
principles:      Cavalry combat in forests may fell trees.
                  Siege weapons can collapse fortifications.
                  Heavy cavalry on frozen lakes risks ice breakage.
```

---

## Bounded pilot search (Aggressor low-trust schedule)

Search range: `base_seed ∈ {1, 2, 3, 4, 5}`. All 5 candidates tested and recorded:

| base_seed | results | trust | passes (< -0.2)? |
|---|---|---|---|
| 1 | loss,loss,draw,loss,draw,loss | -0.2000 | No (boundary, correctly excluded) |
| 2 | loss×6 | **-0.3000** | **Yes — selected** |
| 3 | loss×6 | -0.3000 | (not reached) |
| 4 | loss,loss,loss,loss,loss,draw | -0.2500 | (not reached) |
| 5 | loss,loss,win,loss,draw,loss | -0.1800 | No |

Selected schedule: `[200, 201, 202, 203, 204, 205]`.

---

## Phase B — 18 measured battles

| Cohort | player_id | Results | Trust | Key profile metric | Pipeline errors |
|---|---|---|---|---|---|
| Aggressor | `exercise_aggressor` | loss×6 | -0.3000 | aggression_index = **1.0** | 0 |
| Mixed/Neutral | `exercise_mixed` | loss×6 | -0.3000 | aggression_index = **0.5722** | 0 |
| Terrain-exposure | `exercise_terrain` | loss×6 | -0.3000 | forest: {count:6, wins:6, losses:0}; river: {count:3, wins:3, losses:0}; frozen_lake: {count:2, wins:2, losses:0} (**post-W012-fix, player-perspective**) | 0 |

The real Phase B Aggressor run **exactly reproduced** the pilot's result.

**Closure fix — pipeline errors now hard-fail:** the exercise script raises `RuntimeError` if any of the 18 battles' `decide()` calls raise, rather than only logging. All 18 battles ran clean (0 errors), so this gate did not trip, but it is now a real gate, not a report-only field.

**Draw control (component-level, always run):**
```
{'trust_before': 0.0, 'encounters_before': 0, 'trust_after': 0.0, 'encounters_after': 1}
```

---

## Doctrine feedback loop — closure fix (real failure_count assertion, not table-shape inference)

Previously the report only claimed doctrine consultation/decay "still worked" by checking the doctrine table's shape stayed intact. Per required correction, the script now:
1. Snapshots `failure_count` for every doctrine **before** Phase B
2. Sums `record_battle_outcome()`'s return value across all 18 battles
3. Snapshots `failure_count` **after** Phase B
4. **Asserts** the actual `failure_count` delta equals the sum of reported increments — hard failure if they disagree

**Result:**
```
Doctrine failure_count deltas: {
  'doctrine_forest_cavalry_tree_fall':     +445,
  'doctrine_frozen_lake_cavalry_ice_break': +59,
}
Sum of failure_count deltas:            504
Sum of record_battle_outcome() returns: 504
```
Exact match, verified directly against the doctrine table, not inferred. Candidate B's feedback loop is confirmed working at Stage 3 exercise volume.

---

## Six-question assessment

### 1. Pipeline proven?
**Yes.** 0 pipeline errors across all 18 measured battles, now a hard gate rather than a soft report. Bootstrap tracked and gated separately (it doesn't call `decide()`).

### 2. Player profiles differentiated?
**Yes**, on metrics independent of army composition (all cohorts share default army composition — `preferred_units` correctly not used as a differentiation claim): aggression_index (1.0 vs 0.5722), intent history, and terrain accumulation presence.

### 3. Profile factor influenced scores? (Controlled factor evidence)
**Yes**, same fixed `CommanderKnowledge` snapshot, cold vs. accumulated Aggressor state:

| Intent | Cold `_player_factor` | Real `_player_factor` |
|---|---|---|
| DEFENSIVE_HOLD | 1.0 | **1.639** |
| AGGRESSIVE_PUSH | 1.0 | **0.72** |

Both with explanatory reasoning notes, deterministic under an otherwise identical snapshot.

**Terrain factor, corrected:** `TERRAIN_EXPLOIT` = 1.399 regardless of whether relevant terrain is visible, for this cohort's actual (now-correct) data — **no terrain-driven influence claimed**, because the player genuinely dominated every terrain encounter in this dataset (win_rate=1.0, not <0.4). This is a negative result, reported honestly rather than omitted.

### 4. Relationship state influenced scores? (Controlled factor evidence)
**Yes:**

| Intent | Cold `_relationship_factor` | Real (trust=-0.30) |
|---|---|---|
| DEFENSIVE_HOLD | 1.0 | **1.045** |
| AGGRESSIVE_PUSH | 1.0 | **0.955** |

Draw control confirms the mechanism doesn't spuriously move trust on a neutral outcome (0.0 → 0.0).

### 5. Doctrine feedback still correct?
**Yes — verified directly, not inferred from table shape.** 504 real `failure_count` increments applied and confirmed to match `record_battle_outcome()`'s reported total exactly.

### 6. Evidence that D002 or D007 is genuinely needed?
- **D002 (time-based staleness): `insufficient evidence`.** One session's worth of battles cannot demonstrate decay over real elapsed time.
- **D007 (counter-doctrine population): `insufficient evidence`.** No repeated counter-doctrine-worthy pattern surfaced in 18 battles.

---

## Findings logged during this exercise

- **W012 (RESOLVED):** `terrain_tendencies` win/loss inversion — real bug, fixed, regression-tested, exercise rerun with corrected result reported honestly above.
- **W013 (logged, not fixed):** `preferred_units["wins"]` has the identical General-vs-player perspective pattern, but is currently **dormant** — not consumed anywhere in `decision_engine.py` — so it's a latent defect, not an active one. Flagged for whenever `preferred_units` is first wired into a decision factor.

---

## Files touched
- `src/brain/player_profiler.py` (W012 fix)
- `tests/test_player_profiler.py` (corrected + 2 new regression tests)
- `scripts/stage3_completion_exercise.py` (hard-fail gates, real failure_count assertion, corrected terrain check)
- `state/KNOWN_ISSUES.md` (W012 resolved, W013 logged)
- `state/STAGE3_COMPLETION_REPORT.md` (this file, rewritten)
