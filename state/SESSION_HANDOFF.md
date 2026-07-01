# Session Handoff

## Date: 2026-06-29
## Stage: 3 (Live Pipeline)
## Tests: 318/318
## Handoff to: next session

---

## What was completed this session

**Stage 3 Candidate B — Doctrine Feedback Loop** is complete.

### Part 1 — W009 Fixed (decision_engine.py)

`_doctrine_factor()` now returns a 3-tuple `(factor, notes, matched_ids)`.
`matched_ids` contains the real doctrine DB id (e.g. `'doctrine_river_weather_flood'`).
The synthetic `doc_refs` block in `decide()` was removed and replaced with
`doc_refs[intent] = d_ids` collected directly from `_doctrine_factor()`.

`doctrines_consulted` in every `decide()` output now contains real IDs
that resolve to actual rows in the doctrines table.

Verified: integration test Turn 1 trace shows `['doctrine_river_weather_flood']`.

### Part 2 — Failure feedback wired

**logger.py** — `increment_doctrine_failure(doctrine_id) -> bool`:
- Increments `failure_count` on the doctrine row
- Recomputes `decay_rate = failure_count / (episode_count + failure_count)`
- Returns True if found+updated, False if doctrine_id not in DB

**decision_engine.py** — `_doctrine_factor()` now applies decay:
- `effective_confidence = confidence * (1.0 - decay_rate)`
- Factor computed from `effective_confidence` not raw `confidence`
- Reasoning note shows decay value when `decay_rate > 0.005`

**decision_engine.py** — `record_battle_outcome(result, decisions_made) -> int`:
- Only acts on `result == "loss"`
- Calls `increment_doctrine_failure()` for every real doctrine id in decisions
- Returns count of increments applied

### Test additions
- 14 new tests (4 W009, 4 decay_rate, 4 logger, 2+ record_battle_outcome)
- All 4 existing `_doctrine_factor` tests updated to unpack 3-tuple
  and include `"id"` and `"decay_rate"` in fixture doctrine dicts
- Integration test still passes 7/7 success criteria

---

## Current state of codebase

```
src/simulator/
    grid.py               COMPLETE — 12 tests
    units.py              COMPLETE — 29 tests
    physics.py            COMPLETE — 23 tests
    battle.py             COMPLETE — 26 tests
    logger.py             COMPLETE — 35 tests  (+4 increment_doctrine_failure)
    snapshot.py           COMPLETE — 20 tests
    training_profiles.py  COMPLETE — 22 tests

src/brain/
    world_model.py        COMPLETE — 30 tests
    doctrine_extractor.py COMPLETE — 36 tests
    player_profiler.py    COMPLETE — 35 tests
    decision_engine.py    COMPLETE — 57 tests  (+14 new)

scripts/
    generate_corpus.py       COMPLETE
    run_integration_test.py  COMPLETE — 7/7 pass (unchanged)

Total: 318/318 tests passing
```

---

## Stage 3 candidate status

| Candidate | Description | Status |
|-----------|-------------|--------|
| A | Live Integration Test | ✅ COMPLETE |
| B | Doctrine Feedback Loop | ✅ COMPLETE |
| C | Player-General Relationship | 🔲 NEXT |
| D | Logger Repository Split | 🔲 Deferred |
| E | Scout Mechanics | 🔲 Deferred |

---

## What to work on next

**Stage 3 Candidate C — Player-General Relationship**

The `player_general_relationship` table exists in the schema and is created
by `logger.py` but has zero rows and no write path. This is the General's
personal memory of specific players — trust, betrayal, cooperation history.
Distinct from `player_profiles` (what the player does) and `doctrines`
(what war teaches). This is: what is MY history with THIS person.

See `state/DEFERRED_ITEMS.md` D008 for full spec.

Minimum viable implementation for Stage 3:
1. `logger.py` — confirm `upsert_relationship()` and `get_relationship()` exist
   (check if they survived the server-scoped migration, or need updating)
2. A `RelationshipManager` class in `src/brain/relationship_manager.py`:
   - `update_after_battle(player_id, server_id, battle_result, decisions_made)`
     → updates trust_level based on outcome and any notable events
   - `get_trust(player_id, server_id)` → float [-1.0, 1.0]
   - `get_relationship_summary(player_id, server_id)` → dict
3. Wire into `DecisionEngine.decide()`: if trust_level < -0.5, boost DEFENSIVE_HOLD
   and AMBUSH; if trust_level > 0.5, slight boost to FLANK_ATTEMPT (earned respect)
4. Wire `update_after_battle()` into the integration test post-battle block

Trust update rules (simple for Stage 3):
  loss  → trust_level -= 0.05  (player is dangerous)
  win   → trust_level += 0.02  (General has measure of this player)
  draw  → no change
  Any doctrine-backed decision that produced a win → notable_event logged

---

## How to run integration test

```bash
cd ~/Projects/general_brain
python3 scripts/run_integration_test.py           # seed=42, verbose
python3 scripts/run_integration_test.py --seed 99
python3 scripts/run_integration_test.py --quiet
```

---

## Key API reminders for next session

**record_battle_outcome signature:**
```python
engine.record_battle_outcome(
    result="loss",           # str: "win" | "loss" | "draw"
    decisions_made=[...],    # List[dict]: decide() outputs, one per turn
) -> int                     # number of failure increments applied
```

**increment_doctrine_failure:**
```python
logger.increment_doctrine_failure(doctrine_id: str) -> bool
# Returns True if found and updated
# decay_rate is automatically recomputed on each call
```

**doctrine dict now includes decay_rate and id:**
```python
{
    "id":              "doctrine_river_weather_flood",
    "condition":       "river+weather",
    "learned_effect":  "flood",
    "confidence":      1.0,
    "decay_rate":      0.005,   # rises as failure_count grows
    "failure_count":   0,
    "episode_count":   2000,
    "derived_principle": "Rivers flood under heavy rain.",
    ...
}
```

---

## Files Claude must read at session start
1. state/CLAUDE_BRIEFING.md
2. state/ARCHITECTURE.md
3. state/PROGRESS.md
4. state/KNOWN_ISSUES.md
5. state/SESSION_HANDOFF.md  (this file)
6. state/DEFERRED_ITEMS.md   (check D008 before designing Candidate C)
7. src/brain/decision_engine.py  (understand current pipeline before extending)
8. src/simulator/logger.py       (check relationship methods before writing new ones)
