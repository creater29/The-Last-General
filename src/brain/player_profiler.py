"""
player_profiler.py — Builds per-player profiles from observed episode data.

This is the first brain file that handles player-specific (non-anonymous) data.
Profiles are scoped to (server_id, player_id) so a player who joins a different
server starts with a clean slate — the General does not maintain a global
reputation database.

Design constraints:
  - Import ONLY from simulator.logger.
  - Profiles are derived solely from confirmed intel: episodes the General
    participated in. Hidden armies remain unknown and are never counted.
  - Raw evidence is persisted in the `data` field; derived metrics
    (aggression_index, adaptability_score) are computed and stored at write
    time so formula improvements only require a re-profile, not a DB replay.
  - Server-scoped: PRIMARY KEY (server_id, player_id).

Formula decisions:
  aggression_index  = aggressive_intents / total_intents (across all battles)
  adaptability_score = adaptations / max(1, loss_count)
      where adaptation = dominant_intent changed after a loss

  preferred_units    = {unit_type: {used: N, wins: W}}
  terrain_tendencies = {terrain: {count: N, wins: W, losses: L}}
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional

from simulator.logger import EpisodeLogger


# ---------------------------------------------------------------------------
# Intent classification
# ---------------------------------------------------------------------------

AGGRESSIVE_INTENTS = frozenset({
    "aggressive_push",
    "flanking",
    "siege",
    "terrain_exploit",
})

DEFENSIVE_INTENTS = frozenset({
    "defensive",
    "retreat",
    "hold",
    "ambush",   # ambush is deceptive but not attack; classified defensive
})


def _dominant_intent(intents: List[str]) -> str:
    """Return the most common intent in a turn-by-turn list. '' if empty."""
    if not intents:
        return ""
    return Counter(intents).most_common(1)[0][0]


# ---------------------------------------------------------------------------
# PlayerProfiler
# ---------------------------------------------------------------------------

class PlayerProfiler:
    """
    Computes and stores player profiles from episode history.

    All reads go through EpisodeLogger. The profiler never touches
    the database directly and never imports simulator internals.
    """

    def __init__(self, logger: EpisodeLogger) -> None:
        self._logger = logger

    # ------------------------------------------------------------------
    # Core update
    # ------------------------------------------------------------------

    def update_profile(self, server_id: str, player_id: str) -> dict:
        """
        Read all episodes for player_id, compute profile fields, and
        upsert into player_profiles under (server_id, player_id).

        Returns the updated profile dict.

        Note: episodes are stored by player_id only (no server_id in
        the episodes table). This is intentional — episode data is raw
        battlefield truth; server scope is applied at the profile layer.
        """
        episodes = self._logger.get_player_episodes(player_id)

        if not episodes:
            return {}   # No data — nothing to profile yet

        # ---- Basic counters ----
        total    = len(episodes)
        wins     = sum(1 for e in episodes if e["_result"] == "win")
        losses   = sum(1 for e in episodes if e["_result"] == "loss")
        draws    = total - wins - losses
        first_ts = episodes[0]["_timestamp"]
        last_ts  = episodes[-1]["_timestamp"]

        # ---- Intent evidence (raw) ----
        intent_counts: Dict[str, int] = {}
        for ep in episodes:
            for intent in ep.get("player_intents", []):
                intent_counts[intent] = intent_counts.get(intent, 0) + 1

        # ---- Aggression index ----
        total_intents  = sum(intent_counts.values())
        aggressive_n   = sum(
            v for k, v in intent_counts.items() if k in AGGRESSIVE_INTENTS
        )
        aggression_idx = aggressive_n / max(1, total_intents)

        # ---- Adaptability score ----
        # Count times player changed dominant intent after a loss.
        adaptations = 0
        strategy_switches = 0
        for i in range(len(episodes) - 1):
            prev_dom = _dominant_intent(episodes[i].get("player_intents", []))
            next_dom = _dominant_intent(episodes[i + 1].get("player_intents", []))
            if prev_dom != next_dom:
                strategy_switches += 1
                if episodes[i]["_result"] == "loss":
                    adaptations += 1

        adapt_score = adaptations / max(1, losses)

        # ---- Preferred units ----
        # {unit_type: {used: N, wins: W}}
        # Graceful: old episodes without unit_types return {} safely.
        unit_usage: Dict[str, Dict[str, int]] = {}
        for ep in episodes:
            unit_types = (
                ep.get("player_unit_summary", {}).get("unit_types", {})
            )
            won = ep["_result"] == "win"
            for ut, count in unit_types.items():
                if ut not in unit_usage:
                    unit_usage[ut] = {"used": 0, "wins": 0}
                unit_usage[ut]["used"] += count
                if won:
                    unit_usage[ut]["wins"] += count

        # ---- Terrain tendencies ----
        # {terrain: {count: N, wins: W, losses: L}}
        # One count per terrain type per episode (not per event).
        terrain_stats: Dict[str, Dict[str, int]] = {}
        for ep in episodes:
            seen = set()
            result = ep["_result"]
            for event in ep.get("terrain_events", []):
                terrain = event.get("terrain_at_site", "")
                if not terrain or terrain in seen:
                    continue
                seen.add(terrain)
                if terrain not in terrain_stats:
                    terrain_stats[terrain] = {"count": 0, "wins": 0, "losses": 0}
                terrain_stats[terrain]["count"] += 1
                if result == "win":
                    terrain_stats[terrain]["wins"]   += 1
                elif result == "loss":
                    terrain_stats[terrain]["losses"] += 1

        # ---- Raw evidence blob ----
        raw_data = {
            "intent_counts":    intent_counts,
            "strategy_switches": strategy_switches,
            "loss_recoveries":  adaptations,
            "unit_usage":       unit_usage,
            "terrain_stats":    terrain_stats,
        }

        self._logger.upsert_player_profile(
            server_id          = server_id,
            player_id          = player_id,
            first_seen         = first_ts,
            last_seen          = last_ts,
            total_battles      = total,
            win_count          = wins,
            loss_count         = losses,
            draw_count         = draws,
            preferred_units    = unit_usage,
            terrain_tendencies = terrain_stats,
            aggression_index   = round(aggression_idx, 4),
            adaptability_score = round(adapt_score, 4),
            raw_data           = raw_data,
        )

        return self._logger.get_player_profile(server_id, player_id)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_profile(
        self, server_id: str, player_id: str
    ) -> Optional[Dict[str, Any]]:
        """Return the player's profile for this server, or None."""
        return self._logger.get_player_profile(server_id, player_id)

    def get_all_profiles(
        self, server_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """All profiles, optionally filtered by server."""
        return self._logger.get_all_player_profiles(server_id)

    def profile_summary(
        self, server_id: str, player_id: str
    ) -> Dict[str, Any]:
        """
        Human-readable snapshot of a player's profile.

        Returns:
            player_id          — str
            server_id          — str
            total_battles      — int
            win_rate           — float  (wins / total_battles)
            aggression_index   — float
            adaptability_score — float
            top_units          — list of unit types sorted by usage
            terrain_comfort    — list of terrains sorted by win rate
        """
        profile = self.get_profile(server_id, player_id)
        if not profile:
            return {}

        top_units = sorted(
            profile["preferred_units"].keys(),
            key=lambda u: profile["preferred_units"][u]["used"],
            reverse=True,
        )

        def _win_rate(t: str) -> float:
            stats = profile["terrain_tendencies"][t]
            return stats["wins"] / max(1, stats["count"])

        terrain_comfort = sorted(
            profile["terrain_tendencies"].keys(),
            key=_win_rate,
            reverse=True,
        )

        return {
            "player_id":          player_id,
            "server_id":          server_id,
            "total_battles":      profile["total_battles"],
            "win_rate":           round(
                profile["win_count"] / max(1, profile["total_battles"]), 4
            ),
            "aggression_index":   profile["aggression_index"],
            "adaptability_score": profile["adaptability_score"],
            "top_units":          top_units,
            "terrain_comfort":    terrain_comfort,
        }
