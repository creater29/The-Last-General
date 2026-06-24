# Session Handoff

## OVERWRITE THIS COMPLETELY AT END OF EVERY SESSION

---

## Session: 2026-06-24 (Session 7 — corpus balanced, ready for doctrine)

### FIRST THING TO DO IN NEW SESSION
```bash
cd ~/Projects/general_brain
python3 -m pytest tests/ --tb=short -q   # must be 169/169 before touching anything
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
    battle.py                  26 tests  (+ weather_weights param, BC)
    logger.py                  27 tests  (+ 3 terrain_knowledge methods)
    training_profiles.py       (covered by test_training_profiles.py)

scripts/
    generate_corpus.py         COMPLETE — do not modify

src/brain/
    __init__.py                empty (correct)
    world_model.py             COMPLETE — 30 tests

tests/
    test_training_profiles.py  COMPLETE — 22 tests
    test_world_model.py        COMPLETE — 30 tests

Total: 169/169 tests passing
```

### DB State (ready for doctrine extraction)
```
data/episodes/general_brain.db
    episodes:          2000+
    observations:
        flood:         118,124   (pre-existing; high confidence)
        tree_fall:      20,396   (target met: 1000 ✅)
        wall_collapse:  11,597   (target met: 1000 ✅)
        ice_break:       1,011   (target met: 1000 ✅)
    terrain_knowledge: populated (run WorldModel.update_from_observations() to refresh)
    doctrines:         0 (next task)
```

All four event types are well above the 5-observation doctrine promotion threshold.
The corpus is ready. Do NOT run generate_corpus.py again unless there is a new
event type to populate — the current data is sufficient for doctrine extraction.

---

### Next Task: src/brain/doctrine_extractor.py

This is the second Stage 2 brain file. Build this next, before player_profiler
or decision_engine.

**What it does:**
Reads the General's terrain beliefs from WorldModel and promotes high-confidence
patterns into anonymous doctrines stored in the `doctrines` table.

**Import constraint (Rule 3 — strictly enforced):**
- May import from `simulator.logger` and `brain.world_model` ONLY.
- No grid, units, physics, or battle imports anywhere in the file.
- Test enforces this by inspecting source code.

**Confirmed design decisions (do not re-open these):**
- Promotion threshold: episode_count >= 5 observations
- No rarity weighting in the extractor — the balanced corpus solved the data
  problem; accurate representation is correct here
- `derived_principle` generated now as a deterministic template string
- Doctrines are anonymous: no player_id anywhere in doctrine rows
- Confidence sourced from WorldModel beliefs, not recomputed from raw observations

**Template strings for derived_principle:**
```python
PRINCIPLE_TEMPLATES = {
    ("river",       "weather",  "flood"):         "Rivers flood under heavy rain.",
    ("frozen_lake", "cavalry",  "ice_break"):      "Heavy cavalry on frozen lakes risks ice breakage.",
    ("frozen_lake", "siege",    "ice_break"):      "Siege engines on frozen lakes cause ice breakage.",
    ("wall",        "siege",    "wall_collapse"):  "Siege weapons can collapse fortifications.",
    ("forest",      "cavalry",  "tree_fall"):      "Cavalry combat in forests may fell trees.",
    ("forest",      "infantry", "tree_fall"):      "Infantry combat in forests may fell trees.",
}
# Fallback for unknown combinations:
# f"{terrain.replace('_',' ').title()} combined with {action} may cause {effect}."
```

**Expected class interface:**
```python
class DoctrineExtractor:
    def __init__(self, logger: EpisodeLogger, world_model: WorldModel)

    def extract_doctrines(self, min_confidence: float = 0.6) -> int
    # Reads beliefs from world_model.get_all_beliefs()
    # Promotes those with confidence >= min_confidence and episode_count >= 5
    # Writes to doctrines table via logger
    # Returns count of doctrines upserted

    def get_doctrines(self) -> List[dict]
    def get_doctrine(self, terrain_type: str, action_type: str) -> Optional[dict]
    def doctrine_summary(self) -> dict
```

**Doctrines table schema (already in DB):**
```sql
doctrines (
    id               TEXT PRIMARY KEY,    -- e.g. "doctrine_river_weather"
    abstraction_level TEXT,               -- "terrain"
    condition         TEXT,               -- "river+weather"
    learned_effect    TEXT,               -- "flood"
    confidence        REAL,
    episode_count     INTEGER,
    failure_count     INTEGER DEFAULT 0,
    derived_principle TEXT,
    exceptions        JSON    DEFAULT '[]',
    last_verified     TEXT,
    decay_rate        REAL    DEFAULT 0.005
)
```

**Logger methods to add (same pattern as terrain_knowledge):**
- `upsert_doctrine(id, abstraction_level, condition, learned_effect, confidence,
                   episode_count, derived_principle, last_verified)`
- `get_doctrine_by_id(id)` → Optional[dict]
- `get_all_doctrines()` → List[dict]

**Test file:** `tests/test_doctrine_extractor.py`
Same seed_observations + WorldModel.update_from_observations() pattern.
See test_world_model.py for the helper — copy seed_observations exactly.

---

### Test Helper Pattern (copy into test_doctrine_extractor.py)

```python
def seed_observations(logger, terrain_context, observed_effect, count,
                      episode_id="test_ep_001"):
    from datetime import datetime, timezone
    timestamp = datetime.now(timezone.utc).isoformat()
    conn = logger._get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO episodes "
        "(id, timestamp, player_id, age, result, turns_played, data) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (episode_id, timestamp, "test_player", 1, "win", 10, "{}"),
    )
    tag = f"{terrain_context}_{observed_effect}".replace("+", "_").replace(" ", "_")
    for i in range(count):
        obs_id = f"{tag}_{i:05d}"
        conn.execute(
            "INSERT OR IGNORE INTO observations "
            "(id, episode_id, timestamp, terrain_context, action_taken, "
            "observed_effect, confidence, last_verified, decay_rate) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (obs_id, episode_id, timestamp, terrain_context, "charge",
             observed_effect, 1.0, timestamp, 0.01),
        )
    conn.commit()
```

IMPORTANT: Always use full strings in the tag (no truncation). See world_model
test notes — truncation caused obs_id collisions between contexts sharing a prefix.

---

### Open Questions
None. All design decisions are confirmed. Build doctrine_extractor.py.
