# The Last General's Mind

A standalone AI brain for The Last General — a centuries-old commander
who learns players across encounters, forms doctrines from battlefield
experience, and reasons like a commander rather than an optimizer.

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
