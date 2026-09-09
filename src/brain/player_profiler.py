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
      where adaptation = dominant_intent changed after a PLAYER loss, and
      loss_count is the PLAYER's loss count. (Corrected 2026-09-04, W013 —
      previously used the General's loss/win directly; see player_won()'s
      docstring in this file.)

  preferred_units    = {unit_type: {used: N, wins: W}}
  terrain_tendencies = {terrain: {count: N, wins: W, losses: L}}
      All wins/losses fields in this module (win_count/loss_count,
      preferred_units, terrain_tendencies) and adaptability_score are
      computed from the PLAYER's perspective via the canonical
      player_won()/player_lost() helpers defined once below — never
      from ep["_result"] directly, which is General-perspective. See
      KNOWN_ISSUES.md W012/W013 for the bugs this correction fixed on
      2026-09-04.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional

from simulator.logger import EpisodeLogger


# ---------------------------------------------------------------------------
# Intent classification
# ---------------------------------------------------------------------------

AGGRESSIVE_INTENTS = frozenset({
    "attack_center",
    "attack_flank",
    "aggressive_rush",
    "siege",
})

DEFENSIVE_INTENTS = frozenset({
    "defend",
    "retreat",
    "supply_protect",
})


def _dominant_intent(intents: List[str]) -> str:
    """Return the most common intent in a turn-by-turn list. '' if empty."""
    if not intents:
        return ""
    return Counter(intents).most_common(1)[0][0]


def player_won(ep: dict) -> bool:
    """
    True iff the PLAYER won this episode.

    ep["_result"] is BattleState.result, which is General-perspective
    (see simulator/battle.py _determine_result()). Every derived field
    in this module must be computed from the PLAYER's perspective, not
    the General's — this is the single, canonical definition point for
    that inversion, used consistently by every computation below.

    Found 2026-09-04 (Stage 3 completion exercise): terrain_tendencies
    (W012, fixed), then adaptability_score, win_count/loss_count, and
    preferred_units["wins"] (W013, initially misclassified as dormant —
    corrected: adaptability_score IS live in _player_factor(), so this
    was a real decision-quality defect, not cosmetic) were all found
    using ep["_result"] directly as though it were player-perspective.
    """
    return ep["_result"] == "loss"   # General lost -> player won


def player_lost(ep: dict) -> bool:
    """True iff the PLAYER lost this episode. See player_won()."""
    return ep["_result"] == "win"    # General won -> player lost


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
        # win_count/loss_count are the PLAYER's, via player_won()/player_lost()
        # (W013 fix, 2026-09-04) — previously used ep["_result"] directly,
        # which is General-perspective, silently storing the General's
        # record as though it were the player's.
        total    = len(episodes)
        wins     = sum(1 for e in episodes if player_won(e))
        losses   = sum(1 for e in episodes if player_lost(e))
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
        # Count times player changed dominant intent after a PLAYER loss
        # (W013 fix, 2026-09-04: this used episodes[i]["_result"] == "loss"
        # directly, which is a General loss — meaning the player WON that
        # battle. adaptability_score is live in _player_factor()'s
        # COUNTER_AGGRESSIVE boost condition, so this was a real
        # decision-quality defect, not dormant: the system could label a
        # player "unadaptable after losses" based on battles the player
        # actually won, and use that wrong score to boost counter-
        # aggressive decisions.)
        adaptations = 0
        strategy_switches = 0
        for i in range(len(episodes) - 1):
            prev_dom = _dominant_intent(episodes[i].get("player_intents", []))
            next_dom = _dominant_intent(episodes[i + 1].get("player_intents", []))
            if prev_dom != next_dom:
                strategy_switches += 1
                if player_lost(episodes[i]):
                    adaptations += 1

        adapt_score = adaptations / max(1, losses)

        # ---- Preferred units ----
        # {unit_type: {used: N, wins: W}}
        # Graceful: old episodes without unit_types return {} safely.
        #
        # "wins" is the PLAYER's, via player_won() (W013 fix, 2026-09-04).
        # Not currently consumed anywhere in decision_engine.py, but fixed
        # for consistency with win_count/adaptability_score/
        # terrain_tendencies — this module's whole job is player
        # profiling, so every derived field must share one canonical
        # perspective, not just the fields already wired into a factor.
        unit_usage: Dict[str, Dict[str, int]] = {}
        for ep in episodes:
            unit_types = (
                ep.get("player_unit_summary", {}).get("unit_types", {})
            )
            won = player_won(ep)
            for ut, count in unit_types.items():
                if ut not in unit_usage:
                    unit_usage[ut] = {"used": 0, "wins": 0}
                unit_usage[ut]["used"] += count
                if won:
                    unit_usage[ut]["wins"] += count

        # ---- Terrain tendencies ----
        # {terrain: {count: N, wins: W, losses: L}}
        # One count per terrain type per episode (not per event).
        #
        # wins/losses are from the PLAYER's perspective, via player_won()/
        # player_lost() (W012 fix, 2026-09-04 — see player_won()'s
        # docstring for the full history of this pattern across the
        # module).
        terrain_stats: Dict[str, Dict[str, int]] = {}
        for ep in episodes:
            seen = set()
            for event in ep.get("terrain_events", []):
                terrain = event.get("terrain_at_site", "")
                if not terrain or terrain in seen:
                    continue
                seen.add(terrain)
                if terrain not in terrain_stats:
                    terrain_stats[terrain] = {"count": 0, "wins": 0, "losses": 0}
                terrain_stats[terrain]["count"] += 1
                if player_won(ep):
                    terrain_stats[terrain]["wins"]   += 1
                elif player_lost(ep):
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
