"""
world_model.py — The General's terrain knowledge.

Reads observation patterns from the database and builds the General's
beliefs about how terrain behaves. This is the first Stage 2 file.

Design constraints (enforced by tests):
  - Import ONLY from simulator.logger. No grid, units, physics, or battle.
  - No coordinates in any output. Beliefs are typed by terrain and action.
  - No raw physics values (no thresholds, force constants, etc.).
  - observed_outcomes is a list of distinct effect types, not a count.
  - Confidence formula: episode_count / (episode_count + 1)

The General does not know WHY terrain behaves as it does. He knows only
what he has witnessed: when cavalry crossed a frozen lake, the ice broke.
He has seen it six times. He believes it happens, but not as law.

Flood dominance (W005 — river+weather overwhelming other patterns) is
NOT addressed here. This module represents observations accurately.
The doctrine_extractor handles weighting when forming principles.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Any

from simulator.logger import EpisodeLogger


class WorldModel:
    """
    Builds and queries the General's terrain beliefs.

    All reads and writes go through the EpisodeLogger — this class never
    touches the database directly and never imports simulator internals.
    """

    def __init__(self, logger: EpisodeLogger) -> None:
        self._logger = logger

    # ------------------------------------------------------------------
    # Core update
    # ------------------------------------------------------------------

    def update_from_observations(self, min_count: int = 3) -> int:
        """
        Read observation patterns and populate terrain_knowledge.

        For each (terrain_context, observed_effect) pair that appears at
        least min_count times, derive the General's belief about that
        terrain+action combination and write it to terrain_knowledge.

        Groups by terrain_context so that a single belief row captures ALL
        distinct effects the General has witnessed for that pair. For example,
        if "river+weather" has produced both "flood" and "unknown", the belief
        will carry observed_outcomes=["flood", "unknown"].

        Confidence is episode_count / (episode_count + 1): a Bayesian
        initialisation that asymptotically approaches 1.0 as the General
        accumulates more evidence. It never reaches certainty.

        Returns the number of beliefs upserted.
        """
        patterns = self._logger.get_observation_patterns(min_count=min_count)

        # Group by terrain_context → collect distinct effects and total count.
        # Each pattern row is one (terrain_context, observed_effect) pair.
        grouped: Dict[str, Dict[str, Any]] = {}
        for row in patterns:
            ctx = row["terrain_context"]
            effect = row["observed_effect"]
            count = row["count"]

            if ctx not in grouped:
                grouped[ctx] = {"effects": set(), "total_count": 0}
            grouped[ctx]["effects"].add(effect)
            grouped[ctx]["total_count"] += count

        upserted = 0
        for terrain_context, data in grouped.items():
            # terrain_context format: "terrain_type+action_type"
            # e.g. "river+weather" or "frozen_lake+cavalry"
            if "+" in terrain_context:
                terrain_type, action_type = terrain_context.split("+", 1)
            else:
                # Malformed context — treat whole string as terrain, action unknown.
                terrain_type = terrain_context
                action_type = "unknown"

            episode_count = data["total_count"]
            # Sort for deterministic ordering across runs.
            observed_outcomes: List[str] = sorted(data["effects"])
            confidence = episode_count / (episode_count + 1)

            self._logger.upsert_terrain_knowledge(
                terrain_type=terrain_type,
                action_type=action_type,
                observed_outcomes=observed_outcomes,
                confidence=confidence,
                episode_count=episode_count,
            )
            upserted += 1

        return upserted

    # ------------------------------------------------------------------
    # Belief queries
    # ------------------------------------------------------------------

    def get_terrain_belief(
        self, terrain_type: str, action_type: str
    ) -> Optional[Dict[str, Any]]:
        """
        Return the General's belief about a specific terrain+action pair.

        Returns None if no belief exists yet (update_from_observations has
        not been called, or this pair had too few observations to qualify).

        Example return value:
            {
                "terrain_type": "river",
                "action_type": "weather",
                "observed_outcomes": ["flood"],
                "confidence": 0.9998,
                "episode_count": 6296,
            }
        """
        return self._logger.get_terrain_knowledge(terrain_type, action_type)

    def get_all_beliefs(self) -> List[Dict[str, Any]]:
        """
        Return all terrain beliefs, ordered by confidence descending.

        An empty list is returned if update_from_observations has not been
        called yet.
        """
        return self._logger.get_all_terrain_knowledge()

    def get_high_confidence_beliefs(
        self, threshold: float = 0.6
    ) -> List[Dict[str, Any]]:
        """
        Return only beliefs where confidence >= threshold.

        Default threshold 0.6 corresponds to roughly 1.5+ observed episodes
        (confidence = n/(n+1) → 0.6 when n ≈ 1.5, so in practice n >= 2).
        With real data, even ice_break at 6 observations yields 0.857.

        Does not re-query the DB — filters the result of get_all_beliefs().
        """
        return [b for b in self.get_all_beliefs() if b["confidence"] >= threshold]

    def belief_summary(self) -> Dict[str, Any]:
        """
        Snapshot of the General's terrain knowledge state.

        Returns a dict with:
            total_beliefs        — total rows in terrain_knowledge
            high_confidence_beliefs — beliefs at or above default threshold (0.6)
            terrain_types        — sorted list of unique terrain types seen
            action_types         — sorted list of unique action types seen
            by_terrain           — {terrain_type: count_of_beliefs}

        Returns zeroed structure if no beliefs have been formed.
        """
        all_beliefs = self.get_all_beliefs()
        high = self.get_high_confidence_beliefs()

        terrain_types = sorted({b["terrain_type"] for b in all_beliefs})
        action_types = sorted({b["action_type"] for b in all_beliefs})

        by_terrain: Dict[str, int] = {}
        for b in all_beliefs:
            t = b["terrain_type"]
            by_terrain[t] = by_terrain.get(t, 0) + 1

        return {
            "total_beliefs": len(all_beliefs),
            "high_confidence_beliefs": len(high),
            "terrain_types": terrain_types,
            "action_types": action_types,
            "by_terrain": by_terrain,
        }
