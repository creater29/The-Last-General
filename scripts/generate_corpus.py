"""
generate_corpus.py — Targeted battle corpus generation.

Runs battles under a named TRAINING_PROFILE until all TARGET_COUNTS
for that profile are met (or --max-battles is exceeded).
Appends results to the production DB.

Usage:
    python scripts/generate_corpus.py --profile balanced
    python scripts/generate_corpus.py --profile anti_flood --max-battles 2000
    python scripts/generate_corpus.py --profile natural --max-battles 500

After generation, switch back to gameplay with TRAINING_PROFILE="natural".
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

# Ensure src/ is on the path regardless of where the script is invoked.
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from simulator.grid import Grid
from simulator.units import UnitType, make_unit
from simulator.battle import BattleLoop
from simulator.logger import EpisodeLogger
from simulator.training_profiles import PROFILES, TARGET_COUNTS, validate_profile


# ---------------------------------------------------------------------------
# Unit factory
# ---------------------------------------------------------------------------

def _make_army(
    unit_type_names: list[str],
    owner: str,
    start_y: int,
    seed: int,
) -> list:
    """
    Create an army from a list of unit type name strings.
    Units are spaced 3 cells apart along x, fixed y.
    """
    rng = random.Random(seed)
    units = []
    for i, name in enumerate(unit_type_names):
        unit_type = UnitType[name.upper()]
        x = 20 + i * 3
        y = start_y + rng.randint(-2, 2)   # small jitter so units don't stack
        unit = make_unit(unit_type, owner, (x, y))
        units.append(unit)
    return units


DEFAULT_GENERAL_TYPES = ["infantry", "cavalry", "archer", "siege", "infantry"]
DEFAULT_PLAYER_TYPES  = ["infantry", "infantry", "cavalry", "archer"]


# ---------------------------------------------------------------------------
# Current event counts from DB
# ---------------------------------------------------------------------------

def get_current_counts(logger: EpisodeLogger, event_keys: list[str]) -> dict[str, int]:
    freq = logger.terrain_event_frequency()
    return {k: freq.get(k, 0) for k in event_keys}


def all_targets_met(current: dict[str, int], targets: dict[str, int]) -> bool:
    return all(current.get(k, 0) >= v for k, v in targets.items())


# ---------------------------------------------------------------------------
# Progress display
# ---------------------------------------------------------------------------

def _progress_bar(current: dict[str, int], targets: dict[str, int]) -> str:
    parts = []
    for k, target in targets.items():
        got = current.get(k, 0)
        pct = min(100, int(100 * got / max(1, target)))
        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
        parts.append(f"  {k:<14} {got:>5}/{target:<5}  [{bar}] {pct:>3}%")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main generation loop
# ---------------------------------------------------------------------------

def run(
    profile_name: str = "balanced",
    max_battles: int = 5000,
    report_every: int = 100,
    db_path: Path | None = None,
) -> None:
    validate_profile(profile_name)
    profile = PROFILES[profile_name]
    targets = TARGET_COUNTS.get(profile_name, {})

    if not targets:
        print(f"[generate_corpus] Profile '{profile_name}' has no TARGET_COUNTS "
              f"defined — running {max_battles} battles and stopping.")

    logger = EpisodeLogger(db_path=db_path)
    weather_weights = profile.get("weather_weights")
    general_types   = profile.get("general_unit_types") or DEFAULT_GENERAL_TYPES
    player_types    = profile.get("player_unit_types")  or DEFAULT_PLAYER_TYPES

    print(f"\n{'='*60}")
    print(f" Training profile : {profile_name}")
    print(f" Description      : {profile['description']}")
    print(f" Max battles      : {max_battles}")
    if targets:
        print(f" Targets          :")
        for k, v in targets.items():
            print(f"   {k}: {v}")
    print(f"{'='*60}\n")

    event_keys      = list(targets.keys()) if targets else []
    current_counts  = get_current_counts(logger, event_keys)
    battles_run     = 0
    start_time      = time.time()
    rng             = random.Random()   # non-seeded for diversity

    if targets:
        print("Starting counts:")
        print(_progress_bar(current_counts, targets))
        print()

    while True:
        # Stopping conditions
        if targets and all_targets_met(current_counts, targets):
            print("\n✅  All targets met — stopping generation.\n")
            break
        if battles_run >= max_battles:
            print(f"\n⚠️  Reached max_battles={max_battles} — stopping.\n")
            break

        seed = rng.randint(0, 2_000_000)

        grid            = Grid(seed=seed)
        general_units   = _make_army(general_types,  "general", start_y=75, seed=seed)
        player_units    = _make_army(player_types,   "player",  start_y=25, seed=seed + 1)

        loop = BattleLoop(
            grid=grid,
            general_units=general_units,
            player_units=player_units,
            player_id=f"curriculum_{profile_name}",
            seed=seed,
            weather_seed=seed + 42,
            weather_weights=weather_weights,
        )
        state = loop.run()
        logger.log_episode(state)

        battles_run += 1

        if battles_run % report_every == 0:
            current_counts = get_current_counts(logger, event_keys)
            elapsed = time.time() - start_time
            rate    = battles_run / max(elapsed, 0.001)
            print(f"[Battle {battles_run:>5}]  {elapsed:.1f}s  ({rate:.1f} battles/s)")
            if targets:
                print(_progress_bar(current_counts, targets))
            print()

    # Final report
    elapsed = time.time() - start_time
    print(f"{'='*60}")
    print(f" Battles run   : {battles_run}")
    print(f" Time elapsed  : {elapsed:.1f}s")
    if battles_run > 0:
        print(f" Rate          : {battles_run / elapsed:.1f} battles/s")
    print()

    final_freq = logger.terrain_event_frequency()
    print("Final event distribution:")
    for event, count in sorted(final_freq.items(), key=lambda x: -x[1]):
        print(f"  {event:<16} {count:>6}")

    if targets:
        print("\nTarget status:")
        final_counts = get_current_counts(logger, event_keys)
        print(_progress_bar(final_counts, targets))

    print(f"{'='*60}\n")
    logger.close()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate a targeted battle corpus for The Last General."
    )
    parser.add_argument(
        "--profile",
        default="balanced",
        choices=list(PROFILES.keys()),
        help="Training profile to use (default: balanced)",
    )
    parser.add_argument(
        "--max-battles",
        type=int,
        default=5000,
        help="Hard cap on number of battles to run (default: 5000)",
    )
    parser.add_argument(
        "--report-every",
        type=int,
        default=100,
        help="Print progress every N battles (default: 100)",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Path to DB file. Defaults to production DB.",
    )
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else None
    run(
        profile_name=args.profile,
        max_battles=args.max_battles,
        report_every=args.report_every,
        db_path=db_path,
    )
