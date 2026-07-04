"""
decision_engine.py — The General's reasoning pipeline.

Given a CommanderKnowledge snapshot of the current battle, produces a
reasoned intent decision using terrain doctrines, player profile, and
situational assessment.

Pipeline (hierarchical, not flat scoring):

    CommanderKnowledge
          │
          ▼
    1. Situation Filter — eliminate physically impossible intents
          │
          ▼
    2. Doctrine Evaluation — boost intents supported by high-confidence beliefs
          │
          ▼
    3. Player Adaptation — counter-strategy from observed player tendencies
          │
          ▼
    4. Situation Fit — weather, health, and turn-based adjustments
          │
          ▼
    5. Final Ranking — multiplicative scoring, choose highest

Scoring model: score = doctrine_factor × player_factor × situation_factor
Each factor is in [0.5, 1.5]; neutral = 1.0 when no information available.
Multiplicative because factors are conditional, not independent.

Import rule (Rule 3 extended):
    from simulator.logger   import EpisodeLogger
    from simulator.snapshot import CommanderKnowledge
    from brain.*            import (any brain module)
    NO other simulator imports.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from simulator.logger   import EpisodeLogger
from simulator.snapshot import CommanderKnowledge
from brain.world_model        import WorldModel
from brain.doctrine_extractor import DoctrineExtractor
from brain.player_profiler    import PlayerProfiler
from brain.relationship_manager import RelationshipManager, RelationshipState


# ---------------------------------------------------------------------------
# Intent definitions
# Match GeneralIntent enum values in simulator/battle.py exactly.
# The engine works with strings to avoid importing from battle.py.
# ---------------------------------------------------------------------------

ALL_INTENTS: List[str] = [
    "AGGRESSIVE_PUSH",
    "DEFENSIVE_HOLD",
    "FLANK_ATTEMPT",
    "TERRAIN_EXPLOIT",
    "SUPPLY_RAID",
    "AMBUSH",
    "RETREAT",
    "SIEGE",
]

FALLBACK_INTENT = "DEFENSIVE_HOLD"

# Which terrain types each intent operates on (for doctrine lookup)
INTENT_TERRAIN_RELEVANCE: Dict[str, List[str]] = {
    "TERRAIN_EXPLOIT": ["frozen_lake", "river"],
    "SIEGE":           ["wall"],
    "AMBUSH":          ["forest"],
}

# Intents countered by an aggressive player (player rushes → General punishes)
COUNTER_AGGRESSIVE: List[str] = ["DEFENSIVE_HOLD", "AMBUSH", "TERRAIN_EXPLOIT"]
# Intents that suit taking initiative vs a passive player
INITIATIVE_INTENTS: List[str] = ["AGGRESSIVE_PUSH", "FLANK_ATTEMPT", "TERRAIN_EXPLOIT"]


# ---------------------------------------------------------------------------
# Step 1 — Situation Filter
# ---------------------------------------------------------------------------

def _filter_intents(
    knowledge: CommanderKnowledge,
) -> Tuple[List[str], List[str]]:
    """
    Remove intents that are physically impossible given current knowledge.
    Returns (available_intents, rejected_reasons).
    """
    available = []
    rejected  = []

    features = knowledge.battlefield_features
    friendly = knowledge.known_friendly_state

    for intent in ALL_INTENTS:
        if intent == "SIEGE":
            if not features.get("has_walls", False):
                rejected.append("SIEGE: no fortifications on battlefield")
                continue
            if not friendly.get("has_siege", False):
                rejected.append("SIEGE: no siege units in friendly force")
                continue

        elif intent == "TERRAIN_EXPLOIT":
            if not features.get("has_hazard", False):
                rejected.append(
                    "TERRAIN_EXPLOIT: no exploitable terrain "
                    "(requires frozen lake or river)"
                )
                continue

        elif intent == "AMBUSH":
            if "forest" not in knowledge.visible_terrain:
                rejected.append("AMBUSH: no forest cover available")
                continue

        available.append(intent)

    # Always guarantee at least the fallback
    if not available:
        available = [FALLBACK_INTENT]

    return available, rejected


# ---------------------------------------------------------------------------
# Step 2 — Doctrine Evaluation
# ---------------------------------------------------------------------------

def _doctrine_factor(
    intent:    str,
    doctrines: List[Dict[str, Any]],
    knowledge: CommanderKnowledge,
) -> Tuple[float, List[str], List[str]]:
    """
    Return (factor, reasoning_lines, matched_doctrine_ids) based on how well
    doctrines support this intent given current visible terrain.

    factor = 1.0 (neutral) if no relevant doctrine exists.
    factor in [0.8, 1.5] otherwise, computed from effective_confidence
    which applies decay_rate: effective = confidence * (1 - decay_rate).

    The third return value contains the real DB id(s) of matched doctrines —
    these are what DecisionEngine.record_battle_outcome() increments on loss.
    """
    terrain_types = INTENT_TERRAIN_RELEVANCE.get(intent, [])
    if not terrain_types:
        return 1.0, [], []

    visible = set(knowledge.visible_terrain)
    relevant = [
        d for d in doctrines
        if d["condition"].split("+")[0] in terrain_types
        and d["condition"].split("+")[0] in visible
    ]
    if not relevant:
        return 1.0, [], []

    best = max(relevant, key=lambda d: d["confidence"])

    # Apply decay_rate: doctrines that have failed repeatedly lose influence
    decay_rate           = best.get("decay_rate", 0.005)
    effective_confidence = round(best["confidence"] * (1.0 - decay_rate), 4)

    # Linearly map effective_confidence [0.6, 1.0] → factor [1.0, 1.5]
    raw    = 1.0 + (effective_confidence - 0.6) * 1.25
    factor = round(max(0.8, min(1.5, raw)), 3)

    notes = [
        f"Doctrine: {best['derived_principle']} "
        f"(confidence {effective_confidence:.4f}"
        + (f", decay {decay_rate:.4f}" if decay_rate > 0.005 else "")
        + ")"
    ]
    return factor, notes, [best["id"]]


# ---------------------------------------------------------------------------
# Step 3 — Player Adaptation
# ---------------------------------------------------------------------------

def _player_factor(
    intent:    str,
    profile:   Optional[Dict[str, Any]],
    knowledge: CommanderKnowledge,
) -> Tuple[float, List[str]]:
    """
    Adjust intent score based on observed player tendencies.

    Counter-aggressive: boost DEFENSIVE_HOLD / AMBUSH / TERRAIN_EXPLOIT
    when player aggression_index is high.
    Exploit terrain weakness: boost TERRAIN_EXPLOIT on terrain where the
    player has a poor win rate.
    """
    if not profile:
        return 1.0, ["No player profile — player adaptation neutral."]

    aggression  = profile.get("aggression_index",   0.5)
    tendencies  = profile.get("terrain_tendencies", {})
    adaptability = profile.get("adaptability_score", 0.5)
    notes: List[str] = []
    factor = 1.0

    # Counter an aggressive player
    if aggression > 0.65:
        if intent in COUNTER_AGGRESSIVE:
            boost = 1.0 + (aggression - 0.65) * 1.4   # up to ~1.49
            factor *= round(min(1.5, boost), 3)
            notes.append(
                f"Player aggression {aggression:.2f} — "
                f"{intent} counters aggressive rush."
            )
        elif intent in ("AGGRESSIVE_PUSH", "FLANK_ATTEMPT"):
            penalty = 1.0 - (aggression - 0.65) * 0.8
            factor *= round(max(0.6, penalty), 3)
            notes.append(
                f"Player aggression {aggression:.2f} — "
                f"head-on attack risky against aggressive opponent."
            )

    # If player rarely adapts, they'll repeat patterns — counter their habit
    if adaptability < 0.3 and aggression > 0.6 and intent in COUNTER_AGGRESSIVE:
        factor *= 1.1
        notes.append(
            f"Player adaptability {adaptability:.2f} — "
            f"unlikely to adjust after losses, counter-intent reliable."
        )

    # Exploit terrain where player has poor win rate
    if intent == "TERRAIN_EXPLOIT":
        for terrain in knowledge.visible_terrain:
            stats = tendencies.get(terrain, {})
            count = stats.get("count", 0)
            if count >= 3:
                win_rate = stats.get("wins", 0) / count
                if win_rate < 0.4:
                    factor *= 1.2
                    notes.append(
                        f"Player wins only {win_rate:.0%} on {terrain} "
                        f"({count} encounters) — terrain exploitation advantageous."
                    )
                    break

    return round(factor, 3), notes


# ---------------------------------------------------------------------------
# Step 4 — Situation Fit
# ---------------------------------------------------------------------------

def _situation_factor(
    intent:    str,
    knowledge: CommanderKnowledge,
) -> Tuple[float, List[str]]:
    """
    Adjust intent score based on weather, turn, and force health.
    """
    weather  = knowledge.weather
    turn     = knowledge.turn
    friendly = knowledge.known_friendly_state
    avg_health = friendly.get("avg_health", 1.0)
    notes: List[str] = []
    factor = 1.0

    # --- Weather effects ---
    if weather == "fog":
        if intent == "AMBUSH":
            factor *= 1.4
            notes.append("Fog reduces enemy visibility — ambush highly effective.")
        elif intent == "AGGRESSIVE_PUSH":
            factor *= 0.8
            notes.append("Fog degrades coordination for aggressive push.")
        elif intent == "TERRAIN_EXPLOIT":
            factor *= 1.15
            notes.append("Fog masks terrain manoeuvre.")

    elif weather == "blizzard":
        if intent in ("AGGRESSIVE_PUSH", "FLANK_ATTEMPT"):
            factor *= 0.7
            notes.append("Blizzard hampers offensive manoeuvres.")
        elif intent == "DEFENSIVE_HOLD":
            factor *= 1.2
            notes.append("Blizzard favours prepared defensive positions.")
        elif intent == "TERRAIN_EXPLOIT" and "frozen_lake" in knowledge.visible_terrain:
            factor *= 1.2
            notes.append("Blizzard weakens ice — frozen lake exploitation timely.")

    elif weather == "heavy_rain":
        if intent == "TERRAIN_EXPLOIT" and "river" in knowledge.visible_terrain:
            factor *= 1.35
            notes.append("Heavy rain — river flood imminent, terrain exploit critical.")
        elif intent in ("AGGRESSIVE_PUSH", "SUPPLY_RAID"):
            factor *= 0.85
            notes.append("Heavy rain slows movement — offensive pace reduced.")

    elif weather == "wind":
        if intent == "AMBUSH":
            factor *= 1.1
            notes.append("Wind masks movement noise — ambush cover improved.")

    # --- Force health ---
    if avg_health < 0.3:
        if intent == "RETREAT":
            factor *= 1.5
            notes.append(
                f"Friendly forces critically low ({avg_health:.0%} health) — "
                f"retreat strongly indicated."
            )
        elif intent in ("AGGRESSIVE_PUSH", "FLANK_ATTEMPT", "SIEGE"):
            factor *= 0.55
            notes.append(
                f"Friendly forces critically low ({avg_health:.0%}) — "
                f"offensive intent inadvisable."
            )
    elif avg_health < 0.5:
        if intent == "RETREAT":
            factor *= 1.2
            notes.append(f"Health below half ({avg_health:.0%}) — withdrawal worth considering.")

    # --- Turn-based reasoning ---
    if turn <= 5 and intent == "SUPPLY_RAID":
        factor *= 0.7
        notes.append("Early battle — supply raid premature, forces not yet engaged.")
    if turn > 20 and intent == "RETREAT":
        factor *= 0.85
        notes.append("Late battle — retreat concedes hard-fought position.")

    return round(factor, 3), notes


# ---------------------------------------------------------------------------
# Relationship factor
# ---------------------------------------------------------------------------

# Temporary intent category tables (explicit: will be replaced by IntentMetadata
# when intent count exceeds 15 or category maintenance becomes a burden).
# See DEFERRED_ITEMS.md — intent metadata system.
#
# Categories reflect the General's psychological posture, not tactics:
#   HIGH_COMMITMENT: intents that expose the General's forces to risk
#   CAUTIOUS:        intents that protect position and minimise exposure
#   NEUTRAL:         intents driven by terrain/situation, not commitment level
#
# SUPPLY_RAID is NEUTRAL here because its risk profile depends on execution
# context (small raid vs. deep strike) that the current model cannot represent.
# Classification deferred until intent metadata exists.

_HIGH_COMMITMENT = {"AGGRESSIVE_PUSH", "FLANK_ATTEMPT", "SIEGE"}
_CAUTIOUS        = {"DEFENSIVE_HOLD",  "RETREAT"}
_NEUTRAL         = {"TERRAIN_EXPLOIT", "AMBUSH", "SUPPLY_RAID"}


def _relationship_factor(
    intent: str,
    state:  RelationshipState,
) -> Tuple[float, List[str]]:
    """
    Compute a relationship-derived factor for a single intent.

    DecisionEngine owns this translation from RelationshipState to per-intent
    factor. RelationshipManager never touches intent names.

    Modifier derivation (from trust_level only — confidence deferred):
        risk_modifier       = clamp(1.0 + trust * 0.15, 0.85, 1.15)
        commitment_modifier = clamp(1.0 + trust * 0.15, 0.85, 1.15)
        confidence_modifier = 1.0  (deferred — awaits prediction accuracy data)

    Intent mapping:
        HIGH_COMMITMENT intents → commitment_modifier
        CAUTIOUS intents        → inverse of commitment_modifier (2.0 - cm)
        NEUTRAL intents         → 1.0 (no adjustment)
    """
    notes: List[str] = []
    trust  = state.trust_level
    enc    = state.encounters

    if enc == 0:
        # First encounter — no psychological history, factor is neutral
        return 1.0, []

    risk_mod       = round(max(0.85, min(1.15, 1.0 + trust * 0.15)), 4)
    commitment_mod = round(max(0.85, min(1.15, 1.0 + trust * 0.15)), 4)
    # confidence_modifier = 1.0 — deferred until prediction accuracy exists

    if intent in _HIGH_COMMITMENT:
        factor = commitment_mod
        if trust > 0.2:
            notes.append(
                f"Relationship trust={trust:.2f} — General is willing to commit "
                f"(commitment_mod={commitment_mod})."
            )
        elif trust < -0.2:
            notes.append(
                f"Relationship trust={trust:.2f} — General is wary; "
                f"high-commitment intent penalised (commitment_mod={commitment_mod})."
            )
    elif intent in _CAUTIOUS:
        factor = round(2.0 - commitment_mod, 4)
        if trust < -0.2:
            notes.append(
                f"Relationship trust={trust:.2f} — General is cautious; "
                f"defensive posture favoured (factor={factor:.4f})."
            )
        elif trust > 0.2:
            notes.append(
                f"Relationship trust={trust:.2f} — General is committed; "
                f"cautious intent slightly penalised (factor={factor:.4f})."
            )
    else:
        # NEUTRAL — no relationship-driven adjustment
        factor = 1.0

    return round(factor, 4), notes


# ---------------------------------------------------------------------------
# DecisionEngine
# ---------------------------------------------------------------------------

class DecisionEngine:
    """
    Produces intent decisions from a CommanderKnowledge snapshot.

    Uses a hierarchical reasoning pipeline: filter impossible intents,
    score remaining ones with doctrine × player × situation factors,
    return the highest-scoring intent with a full reasoning trace.

    The General defaults to DEFENSIVE_HOLD when knowledge is insufficient
    or all scoring is inconclusive, and says so explicitly.
    """

    def __init__(
        self,
        logger:               EpisodeLogger,
        world_model:          WorldModel,
        doctrine_extractor:   DoctrineExtractor,
        player_profiler:      PlayerProfiler,
        relationship_manager: Optional[RelationshipManager] = None,
    ) -> None:
        self._logger               = logger
        self._world_model          = world_model
        self._doctrine_extractor   = doctrine_extractor
        self._player_profiler      = player_profiler
        self._relationship_manager = relationship_manager

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def decide(self, knowledge: CommanderKnowledge) -> Dict[str, Any]:
        """
        Run the full reasoning pipeline and return a decision dict.

        Returns:
            intent              — chosen GeneralIntent string
            confidence          — normalised [0, 1] score of chosen intent
            reasoning           — list of reasoning strings (why this intent)
            rejected            — list of eliminated intents with reasons
            alternatives        — [(intent, confidence)] for top runners-up
            doctrines_consulted — doctrine ids that influenced the decision
            profile_used        — True if a player profile was available
            relationship_used   — True if a relationship record was available
        """
        # Load current beliefs, doctrines, and player profile from DB
        doctrines = self._doctrine_extractor.get_doctrines()
        profile   = self._player_profiler.get_profile(
            knowledge.server_id, knowledge.player_id
        )

        # Load relationship state (neutral if no history exists)
        rel_state: Optional[RelationshipState] = None
        if self._relationship_manager is not None:
            rel_state = self._relationship_manager.get_state(
                knowledge.server_id, knowledge.player_id
            )

        # Step 1 — Situation filter
        available, rejected = _filter_intents(knowledge)

        # Steps 2-4 — Score each available intent
        scores:   Dict[str, float]       = {}
        traces:   Dict[str, List[str]]   = {}
        doc_refs: Dict[str, List[str]]   = {}

        for intent in available:
            d_factor, d_notes, d_ids = _doctrine_factor(intent, doctrines, knowledge)
            p_factor, p_notes        = _player_factor(intent, profile, knowledge)
            s_factor, s_notes        = _situation_factor(intent, knowledge)

            r_factor = 1.0
            r_notes: List[str] = []
            if rel_state is not None:
                r_factor, r_notes = _relationship_factor(intent, rel_state)

            score = round(d_factor * p_factor * s_factor * r_factor, 4)
            scores[intent]   = score
            traces[intent]   = d_notes + p_notes + s_notes + r_notes
            doc_refs[intent] = d_ids   # real doctrine IDs from DB

        # Step 5 — Rank and select
        if not scores:
            return self._fallback_response(rejected, bool(profile))

        best_intent = max(scores, key=lambda i: scores[i])
        max_score   = scores[best_intent]
        min_score   = min(scores.values())
        score_range = max_score - min_score

        # Normalise confidence to [0, 1] relative to the candidate field
        if score_range > 0:
            confidence = round((scores[best_intent] - min_score) / score_range, 4)
        else:
            confidence = 0.5   # all equal — low confidence

        # Alternatives: top 2 runners-up
        sorted_intents = sorted(scores, key=lambda i: scores[i], reverse=True)
        alternatives = [
            (i, round((scores[i] - min_score) / max(score_range, 1e-9), 4))
            for i in sorted_intents[1:3]
        ]

        # Collect doctrine ids that actually influenced the chosen intent
        consulted = doc_refs.get(best_intent, [])

        return {
            "intent":               best_intent,
            "confidence":           confidence,
            "reasoning":            traces.get(best_intent, []) or [
                "No specific doctrine or profile signal — highest situational score."
            ],
            "rejected":             rejected,
            "alternatives":         alternatives,
            "doctrines_consulted":  consulted,
            "profile_used":         bool(profile),
            "relationship_used":    rel_state is not None and rel_state.encounters > 0,
        }

    def choose_intent(self, knowledge: CommanderKnowledge) -> str:
        """Convenience wrapper — returns only the intent string."""
        return self.decide(knowledge)["intent"]

    def record_battle_outcome(
        self,
        result:         str,
        decisions_made: List[Dict[str, Any]],
    ) -> int:
        """
        After a battle ends, penalise doctrines that backed decisions in a loss.

        Called once per battle with:
          result         — "win" | "loss" | "draw"
          decisions_made — list of decide() output dicts, one per turn

        Only "loss" triggers failure increments. Win and draw leave doctrines
        unchanged (they will be re-verified naturally by extract_doctrines()).

        Returns the number of failure_count increments applied.
        """
        if result != "loss":
            return 0

        increments = 0
        for decision in decisions_made:
            for doc_id in decision.get("doctrines_consulted", []):
                if doc_id:
                    updated = self._logger.increment_doctrine_failure(doc_id)
                    if updated:
                        increments += 1
        return increments

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fallback_response(
        self,
        rejected: List[str],
        profile_used: bool,
    ) -> Dict[str, Any]:
        return {
            "intent":               FALLBACK_INTENT,
            "confidence":           0.0,
            "reasoning":            [
                "Insufficient knowledge — defaulting to defensive posture."
            ],
            "rejected":             rejected,
            "alternatives":         [],
            "doctrines_consulted":  [],
            "profile_used":         profile_used,
        }
