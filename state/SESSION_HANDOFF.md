# Session Handoff

## OVERWRITE THIS COMPLETELY AT END OF EVERY SESSION

---

## Session: 2026-06-23 (Session 6 — Training profiles + corpus generation)

### FIRST THING TO DO IN NEW SESSION
```bash
cd ~/Projects/general_brain
python3 -m pytest tests/ --tb=short -q   # must be 169/169 before touching anything
```
Then read in this exact order:
1. state/CLAUDE_BRIEFING.md    ← critical, read fully
2. state/ARCHITECTURE.md       ← full design spec
3. state/PROGRESS.md           ← current status
4. state/KNOWN_ISSUES.md       ← known risks
5. state/SESSION_HANDOFF.md    ← this file (already reading)

Do not write any code until you have confirmed test count and understanding with Arman.

---

### Current State of Codebase

Stage 1 COMPLETE. Stage 2 in progress.

```
src/simulator/              ALL COMPLETE — minimally touch
    grid.py                 12 tests
    units.py                29 tests
    physics.py              23 tests
    battle.py               26 tests  (+weather_weights param added, BC)
    logger.py               27 tests  (+3 terrain_knowledge methods)
    training_profiles.py    0 direct tests (22 tests via test_training_profiles.py)

scripts/
    generate_corpus.py      COMPLETE — CLI tool

src/brain/
    __init__.py             empty (correct)
    world_model.py          COMPLETE — 30 tests

tests/
    test_training_profiles.py   COMPLETE — 22 tests
    test_world_model.py         COMPLETE — 30 tests

Total: 169/169 tests passing

data/episodes/general_brain.db  EXISTS with real data:
    episodes:          100 (from original run — NOT yet re-run with balanced profile)
    observations:      6526 (heavily flood-dominated: 6296 flood)
    terrain_knowledge: populated by WorldModel.update_from_observations()
```

---

### IMPORTANT: Corpus Is Still Skewed

The original 100-battle corpus has 6296 flood / 146 tree_fall / 78 wall_collapse / 6 ice_break.
The training profile system is now built and tested but the balanced corpus has NOT been generated yet.

**Before building doctrine_extractor.py, Arman should run:**
```bash
cd ~/Projects/general_brain
python3 scripts/generate_corpus.py --profile balanced --max-battles 5000
```
This will append to the existing DB until 1000 of each event type is reached.
It takes roughly 2-5 minutes depending on machine speed.

Alternatively, use anti_flood first to rapidly build up the rare events:
```bash
python3 scripts/generate_corpus.py --profile anti_flood --max-battles 2000
```

DO NOT build doctrine_extractor.py until the corpus is balanced.
Building it now would produce one flood doctrine and weak everything else,
making it impossible to tell whether the extractor works correctly.

---

### Training Profile System (already built — do not rebuild)

**`src/simulator/training_profiles.py`** — 5 profiles:
- `natural`: unbiased, floods dominate
- `anti_flood`: heavy_rain=0.0, cavalry+siege composition
- `terrain_learning`: ice_break + tree_fall focus, blizzard/wind weather
- `siege_learning`: double siege units, wall collapse focus
- `balanced`: all four events targeted at 1000 each

**`scripts/generate_corpus.py`** — CLI:
```
python3 scripts/generate_corpus.py --profile balanced --max-battles 5000
python3 scripts/generate_corpus.py --profile anti_flood --max-battles 2000
python3 scripts/generate_corpus.py --help
```
Stops automatically when all TARGET_COUNTS for the profile are met.
Progress bars print every 100 battles by default.

**`battle.py` change (backward compatible):**
- Added `weather_weights: Optional[Dict[str, float]] = None` to `BattleLoop.__init__`
- `_update_weather()` uses weighted random when weights are provided
- Weights of 0.0 fully disable that weather condition (e.g. heavy_rain=0.0 → no flood)
- All 26 existing battle tests pass unchanged

---

### Next Task: src/brain/doctrine_extractor.py

**Wait for balanced corpus first.** Then:

This is the second Stage 2 file. Do not start any other brain file first.

**What it does:**
Reads high-confidence terrain beliefs from WorldModel and promotes patterns
into doctrines — anonymous reusable military principles stored in the
`doctrines` table.

**Hard constraints (same as all brain files):**
- Import from `simulator.logger` and `brain.world_model` ONLY.
- No coordinates. No raw physics values. No simulator internals.
- Doctrines are anonymous: no player_id anywhere in doctrine rows.
- Promotion threshold: 5+ observations (per ARCHITECTURE.md).
- No rarity weighting in the extractor — world_model represents observations
  faithfully; the balanced corpus solves the data problem instead.

**Expected interface:**
```python
class DoctrineExtractor:
    def __init__(self, logger: EpisodeLogger, world_model: WorldModel)

    def extract_doctrines(self) -> int
    # Reads high-confidence beliefs from world_model
    # Promotes qualifying beliefs into doctrines table
    # Returns count of doctrines written

    def get_doctrines(self) -> List[dict]
    def get_doctrine(self, condition: str) -> Optional[dict]
    def doctrine_summary(self) -> dict
```

**`derived_principle` generation — CONFIRMED:**
Generate as template string now. Examples:
- frozen_lake + cavalry → ice_break  →  "Heavy cavalry on frozen lakes risks ice breakage."
- river + weather → flood             →  "Rivers flood under heavy rain."
- wall + siege → wall_collapse        →  "Siege weapons can collapse fortifications."
- forest + cavalry → tree_fall        →  "Cavalry combat in forests may fell trees."

Template: `"{terrain} + {action} → {effect}" → mapped to plain English`

**Doctrines table (already in DB):**
```sql
doctrines (
    id TEXT PRIMARY KEY,
    abstraction_level TEXT,
    condition TEXT,
    learned_effect TEXT,
    confidence REAL,
    episode_count INTEGER,
    failure_count INTEGER DEFAULT 0,
    derived_principle TEXT,
    exceptions JSON DEFAULT '[]',
    last_verified TEXT,
    decay_rate REAL DEFAULT 0.005
)
```

**Test file:** `tests/test_doctrine_extractor.py`
Same seed_observations helper pattern as test_world_model.py.

---

### Test Helper Pattern (seed_observations)

```python
def seed_observations(logger, terrain_context, observed_effect, count, episode_id="test_ep_001"):
    timestamp = datetime.now(timezone.utc).isoformat()
    conn = logger._get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO episodes (id, timestamp, player_id, age, result, turns_played, data) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (episode_id, timestamp, "test_player", 1, "win", 10, "{}"),
    )
    # Use full strings in tag — truncation causes obs_id collisions
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

---

### Open Question Before Coding doctrine_extractor.py
None — all design decisions are confirmed. Just run the balanced corpus first.
