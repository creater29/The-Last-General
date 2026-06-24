"""
training_profiles.py — Corpus generation profiles.

Controls the statistical distribution of terrain events during
batch generation. Switch to "natural" for live gameplay.

TRAINING_PROFILE options:
  "natural"          — unbiased, matches real battle statistics
  "anti_flood"       — heavy_rain disabled; all other events boosted
  "terrain_learning" — cavalry + siege on frozen lakes + forest fighting
  "siege_learning"   — siege-heavy; wall collapse focus
  "balanced"         — targets 1000 observations per event type

Usage in generate_corpus.py:
    profile = PROFILES["balanced"]
    targets = TARGET_COUNTS["balanced"]

Adding a new profile:
  1. Add an entry to PROFILES with weather_weights, general_unit_types,
     player_unit_types.
  2. Add a matching entry to TARGET_COUNTS.
  3. Add a test in test_training_profiles.py.
"""

from __future__ import annotations
from typing import Dict, List, Optional, Any


# ---------------------------------------------------------------------------
# Profile definitions
# ---------------------------------------------------------------------------

PROFILES: Dict[str, Dict[str, Any]] = {

    "natural": {
        "description": (
            "Unbiased natural generation. Matches the organic distribution "
            "of a real battle world. Flood will dominate."
        ),
        "weather_weights": {
            "clear":      4.0,
            "fog":        1.0,
            "heavy_rain": 2.0,
            "blizzard":   1.0,
            "wind":       1.0,
        },
        "general_unit_types": None,  # use default mix from generate_corpus
        "player_unit_types":  None,
    },

    "anti_flood": {
        "description": (
            "Suppress flood entirely by zeroing heavy_rain probability. "
            "Cavalry and siege units expose ice_break and wall_collapse."
        ),
        "weather_weights": {
            "clear":      8.0,
            "fog":        3.0,
            "heavy_rain": 0.0,   # flood disabled
            "blizzard":   2.0,
            "wind":       2.0,
        },
        "general_unit_types": ["cavalry", "cavalry", "siege", "infantry", "archer"],
        "player_unit_types":  ["infantry", "infantry", "cavalry", "archer"],
    },

    "terrain_learning": {
        "description": (
            "Frozen lake + cavalry -> ice_break. "
            "Forest combat -> tree_fall. "
            "No flooding so rarer events are discoverable."
        ),
        "weather_weights": {
            "clear":      5.0,
            "fog":        2.0,
            "heavy_rain": 0.0,
            "blizzard":   3.0,   # cold = frozen lake present; no flood
            "wind":       3.0,   # wind stresses trees; no flood
        },
        "general_unit_types": ["cavalry", "cavalry", "siege", "infantry", "archer"],
        "player_unit_types":  ["cavalry", "infantry", "infantry", "archer"],
    },

    "siege_learning": {
        "description": (
            "Siege-heavy general vs wall-defended player. "
            "Maximises wall_collapse observations."
        ),
        "weather_weights": {
            "clear":      8.0,
            "fog":        1.0,
            "heavy_rain": 0.0,
            "blizzard":   0.0,
            "wind":       2.0,
        },
        "general_unit_types": ["siege", "siege", "infantry", "cavalry", "archer"],
        "player_unit_types":  ["infantry", "infantry", "infantry", "archer"],
    },

    "balanced": {
        "description": (
            "Flood fully blocked (heavy_rain=0.0). Targets 1000 each of "
            "ice_break, wall_collapse, and tree_fall. Switch back to "
            "'natural' after doctrine_extractor is verified."
        ),
        "weather_weights": {
            "clear":      5.0,
            "fog":        2.0,
            "heavy_rain": 0.0,   # flood disabled — same as anti_flood
            "blizzard":   2.0,
            "wind":       2.0,
        },
        "general_unit_types": ["cavalry", "cavalry", "siege", "infantry", "archer"],
        "player_unit_types":  ["cavalry", "infantry", "infantry", "archer"],
    },
}


# ---------------------------------------------------------------------------
# Target observation counts per profile
# ---------------------------------------------------------------------------
# Generation stops when ALL targets in this dict are met.
# Omit an event type to not track it as a stopping condition.

TARGET_COUNTS: Dict[str, Dict[str, int]] = {

    "balanced": {
        "ice_break":     1000,
        "wall_collapse": 1000,
        "tree_fall":     1000,
    },

    "anti_flood": {
        "ice_break":    1000,
        "wall_collapse": 1000,
        "tree_fall":    1000,
    },

    "terrain_learning": {
        "ice_break":    500,
        "tree_fall":    500,
    },

    "siege_learning": {
        "wall_collapse": 500,
    },

    "natural": {
        "flood":         2000,
        "ice_break":     500,
        "wall_collapse": 500,
        "tree_fall":     500,
    },
}


# ---------------------------------------------------------------------------
# Validation helper
# ---------------------------------------------------------------------------

def validate_profile(name: str) -> None:
    """Raise ValueError if the profile is misconfigured."""
    if name not in PROFILES:
        raise ValueError(f"Unknown training profile: '{name}'. "
                         f"Valid options: {list(PROFILES.keys())}")
    profile = PROFILES[name]
    weights = profile.get("weather_weights", {})
    total = sum(weights.values())
    if total <= 0:
        raise ValueError(
            f"Profile '{name}': weather_weights must have at least one "
            f"positive weight. Got: {weights}"
        )
