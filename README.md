# The Last General's Mind

A standalone AI brain for The Last General — a centuries-old commander
who learns players across encounters, forms doctrines from battlefield
experience, and reasons like a commander rather than an optimizer.

---

## How to Resume Development (Every Session)

### Step 1 — Orient Claude
Give Claude these files to read in order:
1. state/ARCHITECTURE.md
2. state/PROGRESS.md
3. state/KNOWN_ISSUES.md
4. state/SESSION_HANDOFF.md

### Step 2 — Verify Environment
```bash
python3 --version
python3 -c "import sqlite3, numpy; print('deps ok')"
ls ~/general_brain/src/
```

### Step 3 — Check SESSION_HANDOFF for exact starting point
The handoff tells you exactly what to build next.
Never guess. Always read it first.

---

## Project Structure
```
general_brain/
├── state/
│   ├── ARCHITECTURE.md      # Design decisions (rarely changes)
│   ├── PROGRESS.md          # What's built, change log
│   ├── KNOWN_ISSUES.md      # Bugs, risks, watch list
│   └── SESSION_HANDOFF.md   # Where we stopped (overwrite each session)
├── src/
│   ├── simulator/           # Battle simulation (Stage 1)
│   │   ├── grid.py
│   │   ├── units.py
│   │   ├── physics.py
│   │   ├── battle.py
│   │   └── logger.py
│   ├── brain/               # General's intelligence (Stage 2)
│   │   ├── world_model.py
│   │   ├── doctrine_extractor.py
│   │   ├── player_profiler.py
│   │   ├── decision_engine.py
│   │   └── memory.py
│   └── api/                 # External interface (Stage 3+)
├── data/
│   ├── episodes/            # SQLite episode database
│   ├── doctrines/           # Doctrine library
│   └── profiles/            # Player profiles
├── models/                  # Saved model weights (Stage 3+)
├── logs/                    # Training history, decision logs
└── tests/
    ├── test_simulator.py
    └── test_brain.py
```

---

## Current Stage
**PRE-DEVELOPMENT**
See state/SESSION_HANDOFF.md for next action.

---

## Stack
- Python 3.11+
- SQLite (built-in)
- numpy
- pytest
- Platform: macOS M1, 8GB RAM, ~40GB available storage
