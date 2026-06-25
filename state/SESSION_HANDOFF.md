# Session Handoff

## OVERWRITE THIS COMPLETELY AT END OF EVERY SESSION

---

## Session: 2026-06-25 (Session 8 — doctrine_extractor.py complete)

### FIRST THING TO DO IN NEW SESSION
```bash
cd ~/Projects/general_brain
python3 -m pytest tests/ --tb=short -q   # must be 207/207 before touching anything
```
Then read in this exact order:
1. state/CLAUDE_BRIEFING.md
2. state/ARCHITECTURE.md
3. state/PROGRESS.md
4. state/KNOWN_ISSUES.md
5. state/SESSION_HANDOFF.md  ← this file

Do not write any code until you have confirmed test count and understanding with Arman.

---

### Current State of Codebase

```
src/simulator/                 ALL COMPLETE — do not modify
    grid.py                    12 tests
    units.py                   29 tests
    physics.py                 23 tests
    battle.py                  26 tests
    logger.py                  27 tests
    training_profiles.py       (covered by test_training_profiles.py)

scripts/
    generate_corpus.py         COMPLETE

src/brain/
    __init__.py                empty (correct)
    world_model.py             COMPLETE — 30 tests
    doctrine_extractor.py      COMPLETE — 36 tests

tests/
    test_training_profiles.py  COMPLETE — 22 tests  (was 20, +2 this session)
    test_world_model.py        COMPLETE — 30 tests
    test_doctrine_extractor.py COMPLETE — 36 tests

Total: 207/207 tests passing
```

### DB State
```
data/episodes/general_brain.db
    episodes:          2000+
    observations:
        flood:         118,124
        tree_fall:      20,396
        wall_collapse:  11,597
        ice_break:       1,011
    terrain_knowledge: populated
    doctrines:         populated after WorldModel + DoctrineExtractor run
    player_profiles:   0  ← next task
    player_general_relationship: 0
```

---

### What doctrine_extractor.py Does (already built — do not rebuild)

Reads terrain beliefs from WorldModel and promotes qualifying ones into
anonymous doctrine rows.

Promotion criteria:
  - belief.confidence    >= min_confidence    (default 0.6)
  - belief.episode_count >= min_episode_count (default 5)

One doctrine per (terrain_type, action_type, effect) triple.
Doctrine id: `f"doctrine_{terrain_type}_{action_type}_{effect}"` — deterministic.

`derived_principle` uses PRINCIPLE_TEMPLATES (6 known combos) with a
plain-English fallback for unknown combinations. No LLM, no physics values.

Logger methods added this session (end of logger.py):
  - upsert_doctrine(...)
  - get_doctrine_by_id(id)
  - get_all_doctrines()

---

### Next Task: src/brain/player_profiler.py

This is the third Stage 2 brain file.

**What it does:**
Observes player behaviour across episodes and builds a per-player profile
stored in the `player_profiles` table. This is the first file that handles
player-specific (non-anonymous) data.

**Import constraint (Rule 3):**
- May import from `simulator.logger` ONLY.
- No grid, units, physics, battle, world_model, or doctrine_extractor imports.
- player_profiler reads episode data from the logger; it does not need beliefs
  or doctrines.

**Three-store memory architecture (from ARCHITECTURE.md):**
  1. player_profiles     ← player_profiler writes here  (player-specific)
  2. doctrines           ← doctrine_extractor wrote here (anonymous)
  3. player_general_relationship ← written later by decision_engine or separate module

**player_profiles table schema (already in DB):**
```sql
player_profiles (
    player_id          TEXT PRIMARY KEY,
    first_seen         TEXT,
    last_seen          TEXT,
    total_battles      INTEGER DEFAULT 0,
    win_count          INTEGER DEFAULT 0,
    loss_count         INTEGER DEFAULT 0,
    draw_count         INTEGER DEFAULT 0,
    preferred_units    JSON    DEFAULT '[]',
    terrain_tendencies JSON    DEFAULT '{}',
    aggression_index   REAL    DEFAULT 0.5,
    adaptability_score REAL    DEFAULT 0.5,
    data               JSON    DEFAULT '{}'
)
```

**Expected interface:**
```python
class PlayerProfiler:
    def __init__(self, logger: EpisodeLogger)

    def update_profile(self, player_id: str) -> dict
    # Reads all episodes for player_id from logger
    # Computes profile fields from episode history
    # Upserts player_profiles row
    # Returns updated profile dict

    def get_profile(self, player_id: str) -> Optional[dict]
    def get_all_profiles(self) -> List[dict]
    def profile_summary(self, player_id: str) -> dict
```

**Logger methods to add (same pattern as terrain_knowledge and doctrines):**
  - upsert_player_profile(player_id, first_seen, last_seen, total_battles,
                           win_count, loss_count, draw_count, preferred_units,
                           terrain_tendencies, aggression_index, adaptability_score)
  - get_player_profile(player_id) → Optional[dict]
  - get_all_player_profiles() → List[dict]
  - get_episodes_for_player(player_id) → List[dict]  (may already exist — check)

**Key design decisions to confirm with Arman before coding:**
1. aggression_index: how is it derived? (ratio of attack intents to total intents?
   ratio of offensive moves to total moves? derive from episode data?)
2. adaptability_score: how is it derived? (how much the player changes strategy
   across battles? needs at least 2 battles to be non-trivial)
3. preferred_units: list of unit types that appear most often in player's armies?
   Or types that appear in winning battles?
4. terrain_tendencies: dict of terrain_type → frequency? Or terrain_type → outcome?

**Test file:** tests/test_player_profiler.py
Same pattern as test_doctrine_extractor.py but seeding episodes rather than
observations (player_profiler reads episode-level data).

---

### Test Helper Pattern for Episodes

player_profiler reads from episodes table (player wins/losses/draws).
To seed test data, use logger.log_episode() or insert directly:

```python
def seed_episode(logger, player_id, result, turns=20, episode_id=None):
    import uuid
    from datetime import datetime, timezone
    timestamp = datetime.now(timezone.utc).isoformat()
    eid = episode_id or str(uuid.uuid4())[:12]
    conn = logger._get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO episodes "
        "(id, timestamp, player_id, age, result, turns_played, data) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (eid, timestamp, player_id, 1, result, turns, "{}"),
    )
    conn.commit()
    return eid
```

---

### Open Questions for player_profiler.py
Confirm with Arman before writing any code:
1. aggression_index derivation
2. adaptability_score derivation
3. preferred_units definition
4. terrain_tendencies definition
