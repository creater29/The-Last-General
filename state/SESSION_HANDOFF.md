# Session Handoff

## Date: 2026-06-28
## Stage: 3 (Live Pipeline)
## Tests: 319/319
## Handoff to: next session

---

## What was completed this session

**Stage 3 Candidates A and B are both complete and verified.**

### Candidate A (recap)
`scripts/run_integration_test.py` wires the full pipeline:
  simulator → snapshot → brain → decision → battle → logging

### Candidate B — fully verified this session
Work done:
1. **Audit** revealed Candidate B implementation was pre-written (like D001).
   Code existed for W009 fix, `increment_doctrine_failure()`, `record_battle_outcome()`,
   and `_doctrine_factor()` decay application. 14 tests already in place.

2. **Schema fix** (not pre-written — done this session):
   `player_general_relationship` table lacked `server_id`. Fixed to composite
   `PRIMARY KEY (server_id, player_id)` — consistent with `player_profiles`.
   `upsert_relationship()` and `get_relationship()` updated to take `server_id`.
   `migrate_relationship_schema()` added and run on production DB.
   Server isolation test added → 319/319.

3. **Integration test wiring** — `record_battle_outcome()` added to
   `run_integration_test.py` as a second verification battle (seed=9, expected loss).
   Before/after doctrine DB state printed with exact field values.

4. **Verified 8/8 criteria PASS:**
   - Battle 1 (seed=42): WIN, 30 doctrine consultations
   - Battle 2 (seed=9):  LOSS, 30 increments applied by record_battle_outcome()
   - doctrine_forest_cavalry_tree_fall: failure_count 0→24, decay_rate 0.005000→0.001175
   - doctrine_river_weather_flood:      failure_count 0→6,  decay_rate 0.005000→0.000051
   - Unconsulted doctrines unchanged (selectivity confirmed)

5. **State files updated**: W009 closed (→R007), D001 moved to Completed,
   PROGRESS.md updated, CLAUDE_BRIEFING.md updated.

---

## Important: audit discipline

Both this session and the previous one discovered pre-written code/tests
that the state files didn't reflect. The audit pattern that found this:

```
grep -n "def <method_name>" src/brain/decision_engine.py
grep -n "def <method_name>" src/simulator/logger.py
python3 -m pytest tests/ --co  # collected count vs expected
```

Always run the collection count before assuming tests are missing.
Always grep for method names before assuming they need to be built.

---

## What to work on next

**Stage 3 Candidate C — Player-General Relationship**

The relationship table exists with the correct schema (server_id fixed this session).
The logger methods (`upsert_relationship`, `get_relationship`) exist and are tested.
What does NOT exist yet:

**`src/brain/relationship_manager.py`** — new file, analogous to `player_profiler.py`.

### What it must do

After each battle, update the relationship record:
```python
# On loss:   trust_level -= 0.05
# On win:    trust_level += 0.02
# On draw:   no change
# Always:    cooperation_count += 1 (if player chose cooperative action)
#            betrayal_count    += 1 (if player broke formation or exploited truce)
```

Trust level bounds: clamp to [-1.0, 1.0].

### How DecisionEngine uses it

After `_player_factor()`, a `_relationship_factor()` call adjusts the General's
psychological posture. RelationshipManager returns **psychological modifiers**,
not intent weights. DecisionEngine translates those modifiers into intent score
adjustments.

**Why modifiers, not intent weights:**
RelationshipManager must not know intent names. Today there are 8 intents.
Stage 5+ may have 40 or 100+. If RelationshipManager names intents, every new
intent requires editing relationship logic — that is coupling. Psychological
modifiers are independent of the intent taxonomy forever.

**RelationshipManager returns:**
```python
{
    "risk_modifier":        float,  # willingness to take risks [0.85–1.15]
    "commitment_modifier":  float,  # decisiveness — how committed the General is [0.85–1.15]
    "confidence_modifier":  float,  # trust in own read of the opponent [0.85–1.15]
}
```

**DecisionEngine interprets (owns the mapping):**
```python
# high risk_modifier (trust > 0.5, General willing to commit):
#   → mild boost to decisive intents (those that expose the General)
# low risk_modifier (trust < -0.5, General is wary):
#   → mild boost to cautious intents (those that protect position)
# DecisionEngine already knows which intents are "decisive" vs "cautious"
# RelationshipManager never needs to know intent names
```

**Architectural Rule (permanent — also in ARCHITECTURE.md):**
Relationship memory modifies the General's *psychological state*,
never the *specific battlefield tactic*. Tactical selection remains the
responsibility of doctrines, player profiling, and situation evaluation.

RelationshipManager must NEVER name or reference intent strings directly.
Intent mapping from psychological state belongs exclusively to DecisionEngine.

Factor range: [0.85, 1.15] per modifier — relationship is psychological background,
it must not dominate doctrine or player profile signals.

**Explanation trace this enables (five years from now):**
```
Why AMBUSH?
  Situation: Forest
  Doctrine:  Forest ambush successful (conf 0.93)     ← military knowledge
  Player:    Often overextends left flank              ← tactical read
  Relationship: trust=-0.6 → risk_modifier=0.88       ← psychological posture
                             commitment_modifier=0.91
  DecisionEngine: low commitment → cautious intents boosted → AMBUSH wins
  Decision: AMBUSH
```
Relationship produced modifiers. DecisionEngine chose the tactic.

### Files to touch
1. `src/brain/relationship_manager.py` — new file (~120 lines)
2. `src/brain/decision_engine.py` — add `_relationship_factor()`, wire into `decide()`
3. `src/simulator/logger.py` — no changes needed (methods already exist)
4. `tests/test_relationship_manager.py` — new test file (~25 tests)
5. `tests/test_decision_engine.py` — extend existing tests with relationship factor

**Do NOT build yet.** Audit first to check if relationship_manager.py was also
pre-written. Run:
```bash
ls src/brain/
grep -n "def test_" tests/test_decision_engine.py | wc -l  # currently 58
```

If relationship_manager.py exists → run tests, verify, update state files.
If it doesn't → plan with Arman, confirm design, then build.

---

## Candidate status

| Candidate | Description | Status |
|-----------|-------------|--------|
| A | Live Integration Test | ✅ COMPLETE |
| B | Doctrine Feedback Loop | ✅ COMPLETE |
| C | Player-General Relationship | 🔲 NEXT — audit first |
| D | Logger Repository Split | 🔲 Deferred (trigger hit, wait for C) |
| E | Scout Mechanics | 🔲 Deferred |

---

## DB state (as of session end)

5 doctrines in production DB (failure_count updated by verification battle):
```
doctrine_river_weather_flood           conf=1.0000  fc=6   decay=0.000051
doctrine_forest_cavalry_tree_fall      conf=1.0000  fc=24  decay=0.001175
doctrine_wall_siege_wall_collapse      conf=0.9999  fc=0   decay=0.005000
doctrine_frozen_lake_cavalry_ice_break conf=0.9989  fc=0   decay=0.005000
doctrine_frozen_lake_siege_ice_break   conf=0.9872  fc=0   decay=0.005000
```

Note: fc values above reflect the single verification battle (seed=9).
They will accumulate with each integration test run. This is correct behavior.

---

## How to run the integration test

```bash
cd ~/Projects/general_brain
python3 scripts/run_integration_test.py            # full output, 2 battles
python3 scripts/run_integration_test.py --quiet    # summary only
python3 scripts/run_integration_test.py --seed 99  # different main battle seed
```

---

## Handoff verification prompt

```
I'm continuing development of "The Last General's Mind" project.
You have full terminal access to my local machine via Desktop Commander MCP.

Before doing anything else, run this verification:

    cd ~/Projects/general_brain && python3 -m pytest tests/ --tb=short -q

Then read these files in this exact order — fully, no skimming:
1. state/CLAUDE_BRIEFING.md
2. state/ARCHITECTURE.md
3. state/PROGRESS.md
4. state/KNOWN_ISSUES.md
5. state/SESSION_HANDOFF.md

Once you have read all five files and confirmed 319/319 tests pass, tell me:
- Which Stage 3 candidates are complete and what was verified in each
- What the audit discipline rule is and why it matters
- What Candidate C requires, and what the first thing to do before writing
  any code for it is
- What the relationship_factor() trust thresholds are and what factor range
  it should operate in

Do not start writing any code until I confirm your understanding is correct.
```
