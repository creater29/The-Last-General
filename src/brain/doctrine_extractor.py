"""
doctrine_extractor.py — Promotes terrain beliefs into military doctrines.

Reads the General's terrain beliefs from WorldModel and writes doctrine rows
to the database. A doctrine is an anonymous, reusable military principle
derived from observed battlefield patterns.

Design constraints:
  - Import ONLY from simulator.logger and brain.world_model.
  - No coordinates. No raw physics values. No simulator internals.
  - Doctrines are anonymous: no player_id anywhere in doctrine rows.
  - Promotion threshold: episode_count >= 5 (per ARCHITECTURE.md).
  - No rarity weighting — the balanced corpus solved the data problem.
    The extractor represents beliefs faithfully.
  - derived_principle is a deterministic template string, not LLM-generated.

Relationship to WorldModel:
  WorldModel aggregates observations → terrain beliefs (one row per
  terrain+action pair, with a list of observed effects).
  DoctrineExtractor expands those beliefs → doctrine rows (one row per
  terrain+action+effect triple), adding human-readable principle text.

Doctrine id format: "doctrine_{terrain_type}_{action_type}_{effect}"
  e.g. "doctrine_river_weather_flood"
  Deterministic so re-extraction upserts rather than duplicates.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from simulator.logger import EpisodeLogger
from brain.world_model import WorldModel


# ---------------------------------------------------------------------------
# Principle templates
# ---------------------------------------------------------------------------
# Maps (terrain_type, action_type, learned_effect) → human-readable doctrine.
# The fallback formula is used for combinations not listed here.

PRINCIPLE_TEMPLATES: Dict[tuple, str] = {
    ("river",        "weather",  "flood"):         "Rivers flood under heavy rain.",
    ("frozen_lake",  "cavalry",  "ice_break"):      "Heavy cavalry on frozen lakes risks ice breakage.",
    ("frozen_lake",  "siege",    "ice_break"):      "Siege engines on frozen lakes cause ice breakage.",
    ("wall",         "siege",    "wall_collapse"):  "Siege weapons can collapse fortifications.",
    ("forest",       "cavalry",  "tree_fall"):      "Cavalry combat in forests may fell trees.",
    ("forest",       "infantry", "tree_fall"):      "Infantry combat in forests may fell trees.",
}


def _derive_principle(terrain_type: str, action_type: str, effect: str) -> str:
    """
    Return a human-readable principle for this terrain+action+effect triple.
    Uses the template table when available; falls back to a generated string.
    """
    key = (terrain_type, action_type, effect)
    if key in PRINCIPLE_TEMPLATES:
        return PRINCIPLE_TEMPLATES[key]
    # Fallback: readable capitalised sentence
    terrain_label = terrain_type.replace("_", " ")
    action_label  = action_type.replace("_", " ")
    effect_label  = effect.replace("_", " ")
    return (
        f"{terrain_label.capitalize()} combined with {action_label} "
        f"may cause {effect_label}."
    )


# ---------------------------------------------------------------------------
# DoctrineExtractor
# ---------------------------------------------------------------------------

class DoctrineExtractor:
    """
    Reads terrain beliefs from WorldModel and promotes qualifying ones into
    doctrine rows. All writes go through EpisodeLogger.

    Promotion criteria (both must be met):
      - belief.confidence  >= min_confidence  (default 0.6)
      - belief.episode_count >= min_episode_count (default 5)

    One doctrine row is created per (terrain_type, action_type, effect) triple.
    A single belief with two observed_outcomes produces two doctrines.
    """

    def __init__(self, logger: EpisodeLogger, world_model: WorldModel) -> None:
        self._logger      = logger
        self._world_model = world_model

    # ------------------------------------------------------------------
    # Core extraction
    # ------------------------------------------------------------------

    def extract_doctrines(
        self,
        min_confidence:    float = 0.6,
        min_episode_count: int   = 5,
    ) -> int:
        """
        Promote qualifying terrain beliefs into doctrine rows.

        Reads from world_model.get_all_beliefs() — call
        world_model.update_from_observations() first if the belief table
        may be stale.

        Returns the number of doctrine rows upserted.
        """
        beliefs   = self._world_model.get_all_beliefs()
        timestamp = datetime.now(timezone.utc).isoformat()
        upserted  = 0

        for belief in beliefs:
            if belief["confidence"]    < min_confidence:
                continue
            if belief["episode_count"] < min_episode_count:
                continue

            terrain_type  = belief["terrain_type"]
            action_type   = belief["action_type"]
            confidence    = belief["confidence"]
            episode_count = belief["episode_count"]
            condition     = f"{terrain_type}+{action_type}"

            for effect in belief["observed_outcomes"]:
                doctrine_id = (
                    f"doctrine_{terrain_type}_{action_type}_{effect}"
                )
                principle = _derive_principle(terrain_type, action_type, effect)

                self._logger.upsert_doctrine(
                    doctrine_id       = doctrine_id,
                    abstraction_level = "terrain",
                    condition         = condition,
                    learned_effect    = effect,
                    confidence        = confidence,
                    episode_count     = episode_count,
                    derived_principle = principle,
                    last_verified     = timestamp,
                )
                upserted += 1

        return upserted

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_doctrines(self) -> List[Dict[str, Any]]:
        """All doctrine rows, ordered by confidence descending."""
        return self._logger.get_all_doctrines()

    def get_doctrine(
        self, terrain_type: str, action_type: str
    ) -> Optional[Dict[str, Any]]:
        """
        Return the highest-confidence doctrine for a terrain+action pair.
        Returns None if no doctrine exists for this combination.

        Uses max() on confidence explicitly rather than relying on the
        ordering of get_all_doctrines(), so the result is correct even
        if the query order ever changes.
        """
        condition = f"{terrain_type}+{action_type}"
        all_docs  = self._logger.get_all_doctrines()
        matches   = [d for d in all_docs if d["condition"] == condition]
        return max(matches, key=lambda d: d["confidence"]) if matches else None

    def doctrine_summary(self) -> Dict[str, Any]:
        """
        Snapshot of the current doctrine table.

        Returns:
            total_doctrines      — total rows in doctrines table
            effects_covered      — sorted list of distinct learned_effect values
            terrain_types        — sorted list of distinct terrain types
            avg_confidence       — mean confidence across all doctrines
            min_confidence       — lowest confidence in the table
            principles           — list of derived_principle strings
        """
        docs = self.get_doctrines()

        if not docs:
            return {
                "total_doctrines": 0,
                "effects_covered": [],
                "terrain_types":   [],
                "avg_confidence":  0.0,
                "min_confidence":  0.0,
                "principles":      [],
            }

        effects  = sorted({d["learned_effect"] for d in docs})
        terrains = sorted({d["condition"].split("+")[0] for d in docs})
        confs    = [d["confidence"] for d in docs]

        return {
            "total_doctrines": len(docs),
            "effects_covered": effects,
            "terrain_types":   terrains,
            "avg_confidence":  sum(confs) / len(confs),
            "min_confidence":  min(confs),
            "principles":      [d["derived_principle"] for d in docs],
        }
