# Session Handoff

## OVERWRITE THIS COMPLETELY AT END OF EVERY SESSION.

---

## Current Handoff: 2026-06-27 — Stage 3 Start

---

## MANDATORY FIRST STEPS IN NEW SESSION

```bash
cd ~/Projects/general_brain
python3 -m pytest tests/ --tb=short -q
# Must show: 304 passed
```

Then read ALL FIVE state files in this exact order — fully, no skimming:
1. state/CLAUDE_BRIEFING.md     ← rules + architecture + structure
2. state/ARCHITECTURE.md        ← full design spec
3. state/PROGRESS.md            ← what is built
4. state/KNOWN_ISSUES.md        ← bugs and watch items
5. state/SESSION_HANDOFF.md     ← this file

After reading all five files, state your understanding of the next task
to Arman and wait for his explicit confirmation before writing any code.

---

## What Is Complete

Stage 1 (Simulator) and Stage 2 (Brain Core) are both complete.

```
src/simulator/
    grid.py                 — 12 tests  COMPLETE
    units.py                — 29 tests  COMPLETE
    physics.py              — 23 tests  COMPLETE
    battle.py               — 26 tests  COMPLETE + to_brain_snapshot()
    logger.py               — 31 tests  COMPLETE
    snapshot.py             — 20 tests  COMPLETE (CommanderKnowledge)
    training_profiles.py    — 22 tests  COMPLETE

src/brain/
    world_model.py          — 30 tests  COMPLETE
    doctrine_extractor.py   — 36 tests  COMPLETE
    player_profiler.py      — 35 tests  COMPLETE
    decision_engine.py      — 43 tests  COMPLETE

scripts/
    generate_corpus.py      COMPLETE

Total: 304/304 tests passing
```

---

## What The Brain Can Currently Do

1. **WorldModel**: Reads observation patterns from DB, builds terrain beliefs.
   Call `wm.update_from_observations()` then `wm.get_all_beliefs()`.

2. **DoctrineExtractor**: Reads beliefs from WorldModel, promotes qualifying
   ones (confidence ≥ 0.6, episode_count ≥ 5) into doctrine rows.
   Call `de.extract_doctrines()` to populate the doctrines table.

3. **PlayerProfiler**: Reads episode history for a player, computes aggression,
   adaptability, preferred units, terrain tendencies.
   Call `pp.update_profile(server_id, player_id)`.

4. **DecisionEngine**: Given a CommanderKnowledge snapshot, runs the hierarchical
   pipeline (filter → doctrine → player → situation) and returns a decide() dict:
   {intent, confidence, reasoning, rejected, alternatives, doctrines_consulted, profile_used}

---

## What Has NOT Been Built Yet (Stage 3 Candidates)

These are NOT assigned — confirm with Arman which to build next.

### Candidate A: Live Integration Test (RECOMMENDED FIRST)
Wire a complete battle where to_brain_snapshot() feeds the DecisionEngine
in real time each turn. This is the end-to-end proof that the pipeline
works before adding complexity.

What it would look like:
```python
loop = BattleLoop(grid, general_units, player_units, player_id=player_id)
engine = DecisionEngine(logger, wm, de, pp)

def brain_intent_fn(state):
    knowledge = loop.to_brain_snapshot(server_id, player_id)
    decision  = engine.decide(knowledge)
    return GeneralIntent[decision["intent"]]

state = loop.run(general_intent_fn=brain_intent_fn)
```

This requires: mapping decision["intent"] string back to GeneralIntent enum.
That mapping belongs in the integration layer, not in the brain.

### Candidate B: Doctrine Feedback Loop
Wire failure_count and decay_rate so doctrines degrade after failed
applications. The fields exist in the DB but are always 0.
Requires: logging which doctrine backed each decision and its outcome.

### Candidate C: player_general_relationship table
Third memory store. Trust level, betrayal count, cooperation history.
Currently empty — the architecture references it but nothing writes to it.

### Candidate D: Logger splitting into repositories
Logger is ~850 lines. Split into:
- EpisodeRepository
- ObservationRepository
- DoctrineRepository
- ProfileRepository
Each becomes a class; logger becomes a coordinator.
Deferred from ChatGPT review — right time is after integration test.

### Candidate E: Scout mechanics
Hidden armies, scout report success/failure, intel confidence.
Requires touching Stage 1 (battle.py, grid.py).
This is the "what is the General allowed to know" extension.
Stage 3+ scope.

---

## Key Technical Facts (to avoid hallucination)

**Intent strings in decision_engine.py** match GeneralIntent enum values
in battle.py exactly. The engine uses strings — NO GeneralIntent import.
Valid values: AGGRESSIVE_PUSH, DEFENSIVE_HOLD, FLANK_ATTEMPT, TERRAIN_EXPLOIT,
SUPPLY_RAID, AMBUSH, RETREAT, SIEGE

**player_profiles PRIMARY KEY** is (server_id, player_id) — composite.
Every profiler method requires server_id. This was migrated on 2026-06-25.

**Confidence formula** (world_model.py): episode_count / (episode_count + 1)
Asymptotic. Never reaches 1.0. Intentional.

**Doctrine ids** are deterministic: "doctrine_{terrain_type}_{action_type}_{effect}"
e.g. "doctrine_frozen_lake_cavalry_ice_break"

**seed_observations test helper** uses FULL strings in tag (no truncation):
tag = f"{terrain_context}_{observed_effect}".replace("+", "_").replace(" ", "_")
Truncation causes obs_id collisions — this was R005.

**to_brain_snapshot()** is on BattleLoop (not BattleState) because BattleLoop
owns the live state (weather, turn, alive units). BattleState is the finished record.

**balanced training profile** has heavy_rain=0.0 and does NOT target flood.
It targets: ice_break=1000, wall_collapse=1000, tree_fall=1000.

---

## DB Schema Quick Reference

```sql
episodes (id, timestamp, player_id, age, result, turns_played, data JSON)
observations (id, episode_id, timestamp, terrain_context, action_taken,
              observed_effect, confidence, last_verified, decay_rate)
terrain_knowledge (terrain_type, action_type, observed_outcomes JSON,
                   confidence, episode_count,
                   PRIMARY KEY (terrain_type, action_type))
doctrines (id, abstraction_level, condition, learned_effect, confidence,
           episode_count, failure_count, derived_principle, exceptions JSON,
           last_verified, decay_rate)
player_profiles (server_id, player_id, first_seen, last_seen,
                 total_battles, win_count, loss_count, draw_count,
                 preferred_units JSON, terrain_tendencies JSON,
                 aggression_index, adaptability_score, data JSON,
                 PRIMARY KEY (server_id, player_id))
player_general_relationship (empty — not yet built)
counter_doctrines (empty — not yet built)
```

---

## Hardware / Environment
MacBook Air M1, 8GB RAM, macOS Sequoia 15.7.3
Python 3.12.4, numpy 1.26.4, pytest 9.0.2, SQLite 3.45.3
Project: ~/Projects/general_brain
GitHub: https://github.com/creater29/The-Last-General
Desktop Commander MCP: active (primary tool for file ops + terminal)
MacOS MCP: active (screen, notifications, system)
