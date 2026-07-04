"""
relationship_manager.py — The General's psychological history with opponents.

Owns the third memory store: player_general_relationship.

Responsibility boundary (Three Memory Systems Orthogonality Rule):
  Doctrine Memory   -> military knowledge ("what works on the battlefield")
  Player Profile    -> tactical behaviour ("how this commander usually fights")
  Relationship      -> psychological state ("what is my history with this commander")

RelationshipManager answers ONLY: what is the relationship state?
It returns RelationshipState -- raw relationship data.
DecisionEngine interprets that state into RelationshipModifiers.
RelationshipManager never computes modifiers, never names intents.

See ARCHITECTURE.md: "Three Memory Systems -- Orthogonality Rule"
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from simulator.logger import EpisodeLogger


# ---------------------------------------------------------------------------
# Domain objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RelationshipState:
    """
    Immutable snapshot of the General's relationship with one opponent.

    Returned by RelationshipManager.get_state() -- always a valid object,
    never None. Unknown opponents return a neutral state with encounters=0.

    Distinguishing "never met" from "known neutral":
      encounters == 0  -> never encountered this commander
      encounters >  0, trust_level == 0.0 -> known, currently neutral

    Fields:
        trust_level:             [-1.0, 1.0]. Negative = distrust, positive = trust.
        betrayal_count:          Times this commander broke an implicit agreement.
        cooperation_count:       Times this commander acted cooperatively.
        times_attempted_capture: Times this commander tried to capture the General.
        known_deceptions:        Verified deceptions by this commander.
        encounters:              Total battles against this commander.
    """
    trust_level:              float
    betrayal_count:           int
    cooperation_count:        int
    times_attempted_capture:  int
    known_deceptions:         int
    encounters:               int

    @classmethod
    def neutral(cls) -> "RelationshipState":
        """Return a neutral state for a previously unencountered opponent."""
        return cls(
            trust_level=0.0,
            betrayal_count=0,
            cooperation_count=0,
            times_attempted_capture=0,
            known_deceptions=0,
            encounters=0,
        )


# ---------------------------------------------------------------------------
# RelationshipManager
# ---------------------------------------------------------------------------

# Verified against simulator.battle.BattleLoop._determine_result(): these are
# the only three values BattleState.result can ever hold.
_VALID_RESULTS = {"win", "loss", "draw"}


class RelationshipManager:
    """
    Manages the General's psychological relationship with specific opponents.

    Public API:
        get_state(server_id, player_id)  -> RelationshipState
        update_after_battle(server_id, player_id, result, events=None) -> None

    This class never computes RelationshipModifiers -- that is DecisionEngine's
    responsibility. It only stores and retrieves relationship records.
    """

    def __init__(self, logger: "EpisodeLogger") -> None:
        self._logger = logger

    def get_state(self, server_id: str, player_id: str) -> RelationshipState:
        """
        Return the General's relationship state with a specific opponent.

        Always returns a valid RelationshipState. If no record exists for
        (server_id, player_id), returns RelationshipState.neutral() with
        encounters=0, indicating this opponent has never been encountered.

        DecisionEngine never sees None -- storage concerns stay in this layer.
        """
        record = self._logger.get_relationship(server_id, player_id)
        if record is None:
            return RelationshipState.neutral()

        return RelationshipState(
            trust_level=float(record.get("trust_level", 0.0)),
            betrayal_count=int(record.get("betrayal_count", 0)),
            cooperation_count=int(record.get("cooperation_count", 0)),
            times_attempted_capture=int(record.get("times_attempted_capture", 0)),
            known_deceptions=int(record.get("known_deceptions", 0)),
            encounters=int(record.get("encounters", 0)),
        )

    def update_after_battle(
        self,
        server_id: str,
        player_id: str,
        result:    str,
        events:    list | None = None,
    ) -> None:
        """
        Update the relationship record after a battle concludes.

        Trust update rules:
            loss  -> trust_level - 0.05  (clamped to -1.0)
            win   -> trust_level + 0.02  (clamped to +1.0)
            draw  -> no change

        encounters is always incremented regardless of result.

        events parameter is reserved for future battle event vocabulary
        (betrayal, cooperation, deception, etc.) and is safely ignored today.
        No current battle event types are defined -- do not add interpretations
        until the event vocabulary is established at the simulator level.
        See DEFERRED_ITEMS.md for planned event-aware extension.

        Raises:
            ValueError: if result is not exactly "win", "loss", or "draw".
                Verified against simulator.battle.BattleLoop._determine_result(),
                the only producer of BattleState.result -- it returns exactly
                these three values (never "retreat" or "max_turns"; a stale
                comment on that field suggesting otherwise was corrected
                separately). Validating here prevents a case-typo (e.g. "Win")
                from silently falling through as a no-op "draw".
        """
        if result not in _VALID_RESULTS:
            raise ValueError(
                f"Invalid battle result: {result!r}. "
                f"Must be one of {sorted(_VALID_RESULTS)}."
            )

        record = self._logger.get_relationship(server_id, player_id)

        if record is None:
            data: dict = {
                "trust_level":             0.0,
                "betrayal_count":          0,
                "cooperation_count":       0,
                "times_attempted_capture": 0,
                "known_deceptions":        0,
                "encounters":              0,
                "notable_events":          [],
            }
        else:
            data = dict(record)
            if isinstance(data.get("notable_events"), str):
                data["notable_events"] = json.loads(data["notable_events"])
            elif data.get("notable_events") is None:
                data["notable_events"] = []

        # Trust update
        trust = float(data.get("trust_level", 0.0))
        if result == "loss":
            trust = max(-1.0, trust - 0.05)
        elif result == "win":
            trust = min(1.0, trust + 0.02)
        # draw: no change

        data["trust_level"] = round(trust, 6)
        data["encounters"]  = int(data.get("encounters", 0)) + 1

        # events: reserved for future vocabulary -- not yet interpreted.
        # When battle event types are formally defined in the simulator,
        # update betrayal_count, cooperation_count, etc. here.

        self._logger.upsert_relationship(server_id, player_id, data)
