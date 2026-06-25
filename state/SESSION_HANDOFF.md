# Session Handoff

## OVERWRITE THIS COMPLETELY AT END OF EVERY SESSION

---

## Session: 2026-06-25 (Session 9 — player_profiler.py complete)

### FIRST THING TO DO IN NEW SESSION
```bash
cd ~/Projects/general_brain
python3 -m pytest tests/ --tb=short -q   # must be 242/242 before touching anything
```
Then read in this exact order:
1. state/CLAUDE_BRIEFING.md
2. state/ARCHITECTURE.md
3. state/PROGRESS.md
4. state/KNOWN_ISSUES.md
5. state/SESSION_HANDOFF.md

Do not write any code until confirmed with Arman.

---

### Current State of Codebase

```
src/simulator/                 ALL COMPLETE
    grid.py                    12 tests
    units.py                   29 tests
    physics.py                 23 tests
    battle.py                  26 tests  (+unit_types in _unit_summary)
    logger.py                  31 tests  (+player profile methods)
    training_profiles.py       (covered by test_training_profiles.py)

scripts/
    generate_corpus.py         COMPLETE

src/brain/
    world_model.py             COMPLETE — 30 tests
    doctrine_extractor.py      COMPLETE — 36 tests
    player_profiler.py         COMPLETE — 35 tests

Total: 242/242 tests passing
```

### DB State
```
data/episodes/general_brain.db
    episodes:          2000+
    observations:      150,000+
    terrain_knowledge: populated
    doctrines:         populated (re-run DoctrineExtractor to refresh)
    player_profiles:   0 rows — schema migrated, ready to write
                       PRIMARY KEY (server_id, player_id)
```

---

### Architecture Decisions Made This Session (do not re-open)

**Server-scoped profiles:**
player_profiles PRIMARY KEY is (server_id, player_id). Same player on a
different server starts with a clean slate. Episodes table has no server_id
(raw battlefield truth is server-agnostic); server scope is applied at the
profile layer only.

**Persist facts, derive metrics:**
- `data` JSON blob: raw evidence (intent_counts, strategy_switches,
  loss_recoveries, unit_usage, terrain_stats)
- Computed columns stored at write time: aggression_index, adaptability_score,
  preferred_units, terrain_tendencies
- Formula improvement → re-profile, no DB replay needed

**Formulas (confirmed, do not change without explicit discussion):**
```
aggression_index   = aggressive_intents / total_intents
adaptability_score = adaptations_after_loss / max(1, loss_count)
preferred_units    = {unit_type: {used: N, wins: W}}
terrain_tendencies = {terrain: {count: N, wins: W, losses: L}}
  — counted once per terrain type per episode, not per event
```

**Hidden armies:** Profiles built only from episodes the General participated
in. Hidden armies not visible. Flagged for future scout-intel layer (Stage 3+).

---

### Next Task: src/brain/decision_engine.py

This is the fourth Stage 2 brain file and the last core one.

**What it does:**
Given the current battle state, the General queries his terrain beliefs,
active doctrines, and the player's profile to select the best intent
for this turn.

**Import constraint (Rule 3):**
- May import from `simulator.logger`, `brain.world_model`,
  `brain.doctrine_extractor`, and `brain.player_profiler`.
- No simulator internals (grid, units, physics, battle).

**Expected interface:**
```python
class DecisionEngine:
    def __init__(
        self,
        logger:    EpisodeLogger,
        world_model: WorldModel,
        doctrine_extractor: DoctrineExtractor,
        player_profiler: PlayerProfiler,
    )

    def choose_intent(
        self,
        server_id:   str,
        player_id:   str,
        battle_state_summary: dict,   # brain-facing snapshot from BattleState
    ) -> str
    # Returns intent name string: "aggressive_push", "defensive", etc.
    # Uses doctrines + player profile to rank available intents
    # Returns best intent or "defensive" as safe fallback

    def explain_choice(
        self,
        server_id: str,
        player_id: str,
        battle_state_summary: dict,
    ) -> dict
    # Same as choose_intent but also returns reasoning:
    #   {intent, confidence, reasoning: [...], doctrines_consulted: [...]}
```

**Design questions to confirm with Arman before coding:**
1. What is `battle_state_summary`? The BattleState.to_episode() output minus
   terrain_events and combat_results (those are post-battle). Probably: result,
   battlefield_features, current weather, current turn count.
2. How does the engine rank intents? Candidate design:
   - Start with all GeneralIntents as candidates
   - Boost intents supported by high-confidence doctrines for current terrain
   - Adjust for player profile (if player is aggressive, defend more; if
     player avoids river, use TERRAIN_EXPLOIT near rivers)
   - Return highest-scored intent
3. How is player profile used? Counter-strategy: if player aggression_index > 0.7,
   prefer DEFENSIVE or AMBUSH. If player terrain_tendencies shows river avoidance,
   TERRAIN_EXPLOIT becomes more attractive.

**Test file:** tests/test_decision_engine.py
