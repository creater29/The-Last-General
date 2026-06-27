# Session Handoff

## OVERWRITE THIS COMPLETELY AT END OF EVERY SESSION

---

## Session: 2026-06-25 (Session 10 — decision_engine.py + snapshot complete)

### FIRST THING TO DO IN NEW SESSION
```bash
cd ~/Projects/general_brain
python3 -m pytest tests/ --tb=short -q   # must be 304/304
```
Then read: CLAUDE_BRIEFING.md → ARCHITECTURE.md → PROGRESS.md → KNOWN_ISSUES.md → SESSION_HANDOFF.md

---

### Current State of Codebase

```
src/simulator/
    grid.py                    12 tests
    units.py                   29 tests
    physics.py                 23 tests
    battle.py                  26 tests  (+to_brain_snapshot())
    logger.py                  31 tests
    training_profiles.py       (covered by test_training_profiles.py)
    snapshot.py                NEW — CommanderKnowledge dataclass

scripts/
    generate_corpus.py         COMPLETE

src/brain/
    world_model.py             30 tests
    doctrine_extractor.py      36 tests
    player_profiler.py         35 tests
    decision_engine.py         NEW — 43 tests

tests/
    test_snapshot.py           NEW — 20 tests
    test_decision_engine.py    NEW — 43 tests

Total: 304/304 tests passing
```

---

### Architecture Decisions Made This Session (do not re-open)

**Perception boundary (CommanderKnowledge):**
- `BattleState.to_episode()` → post-battle learning (full truth)
- `BattleLoop.to_brain_snapshot()` → live decision input (perception only)
- `CommanderKnowledge` fields: server_id, player_id, turn, weather,
  battlefield_features, known_enemy_presence (aggregate, no roster),
  known_friendly_state (count + has_siege + has_cavalry), visible_terrain
  (strings only, no coordinates), visible_events (events so far this battle)

**Rule 3 extended:**
Brain files may now import from `simulator.snapshot` in addition to
`simulator.logger`. No other simulator imports permitted.

**Decision pipeline (hierarchical):**
1. Situation Filter — eliminate physically impossible intents
   SIEGE: requires has_walls + has_siege
   TERRAIN_EXPLOIT: requires has_hazard (frozen_lake or river)
   AMBUSH: requires has_forest
2. Doctrine Evaluation — factor per intent based on relevant doctrine confidence
3. Player Adaptation — counter-aggression + terrain weakness exploitation
4. Situation Fit — weather, health, turn effects
5. Multiplicative scoring: doctrine_factor × player_factor × situation_factor
6. DEFENSIVE_HOLD is the guaranteed fallback

**decide() output format:**
```python
{
    "intent":               str,       # chosen GeneralIntent string
    "confidence":           float,     # normalised [0,1]
    "reasoning":            List[str], # why this intent was chosen
    "rejected":             List[str], # eliminated intents with reasons
    "alternatives":         List[tuple],# [(intent, confidence)] top 2
    "doctrines_consulted":  List[str], # doctrine ids consulted
    "profile_used":         bool,      # whether player profile was available
}
```

**Intent strings** match `GeneralIntent` enum values in battle.py exactly.
No GeneralIntent import in decision_engine.py — strings used throughout.

---

### Stage 2 Status

All four brain files are complete:
- world_model.py       ✅
- doctrine_extractor.py ✅
- player_profiler.py   ✅
- decision_engine.py   ✅

**Stage 2 is functionally complete.**

---

### What Comes Next (Stage 3 candidates — confirm with Arman)

1. **Integration test / live demo**: Wire up a complete battle where
   `to_brain_snapshot()` feeds the `DecisionEngine` in real time.
   Shows the full pipeline working end-to-end.

2. **Logger splitting**: Logger is now ~850 lines. Split into
   EpisodeRepository, ObservationRepository, DoctrineRepository,
   ProfileRepository. Deferred from ChatGPT review — right time is now.

3. **Scout mechanics**: Hidden armies, scout reports, intel confidence.
   Requires touching Stage 1 (battle.py, grid.py).

4. **PRINCIPLE_TEMPLATES extensibility**: 6 templates. Build a generation
   system when count reaches 20+.

5. **Player relationship history**: Third memory store from the architecture.
   Tracks General's cumulative read on a player beyond raw stats.

6. **Doctrine decay**: failure_count and decay_rate fields exist. Wire up
   the logic that reduces doctrine confidence after failed applications.

Recommended next task: **Integration test first** — proves the pipeline
works before adding new complexity.
