"""
episode_store.py — Persistence for battle episodes (Candidate D, D014,
Phase 5).

Owns exactly one table: episodes.

Repository Independence: constructable and fully testable standalone —
EpisodeStore(conn) — with NO dependency on ObservationStore or any other
store. This is the phase the entire Repository Independence revision
(decided before Phase 1 began) was designed for.

This is a pure extraction from simulator/logger.py. Method bodies are
unchanged from the pre-extraction implementation (verified byte-for-byte
against the live logger.py before this file was written) — this phase moves
code, it does not change behavior.

BEHAVIOR-CRITICAL NOTE (the single biggest risk both supervisor reviews
flagged for this phase): insert_episode_row() does NOT call commit()
internally. This is deliberate, not an oversight. The facade
(EpisodeLogger.log_episode()) must call insert_episode_row() first, then
ObservationStore.insert_observations() (also non-committing, from Phase 4),
then commit exactly once. The anti-pattern to avoid:
    EpisodeStore.insert_episode_row() -> commit()
    ObservationStore.insert_observations() -> commit()
That would silently destroy atomicity (two separate transactions instead of
one) and would also violate the FK constraint discovered in Phase 4
(observations.episode_id references episodes.id — if EpisodeStore committed
and then something failed before ObservationStore's insert, you'd have an
episode with no observations, silently, with no error).

Ordering note: get_episodes() returns results ORDER BY timestamp DESC (most
recent first). get_player_episodes() returns results ORDER BY timestamp ASC
(oldest first — used by PlayerProfiler to reconstruct a player's history in
chronological order). These are DIFFERENT orderings for similarly-named
methods — verified directly, not assumed identical, and preserved exactly.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional


class EpisodeStore:
    """
    Owns persistence for episodes.

    Public API:
        insert_episode_row(episode, timestamp) -> None
            [does NOT commit — caller (the facade's log_episode()) must
             commit after also inserting observations, exactly once]
        get_episode_count(player_id=None) -> int
        get_episodes(player_id=None, result=None, limit=100, offset=0) -> List[dict]
        get_episode_by_id(episode_id) -> Optional[dict]
        get_player_episodes(player_id) -> List[dict]
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert_episode_row(self, episode: dict, timestamp: str) -> None:
        """
        Insert (or replace) one row into episodes.

        Does NOT commit — see module docstring. The facade owns the
        transaction boundary because this write must be atomic with the
        subsequent observation extraction (FK constraint + Transaction
        Policy, DEFERRED_ITEMS D014 Artifact 2).
        """
        conn = self._conn
        conn.execute(
            """
            INSERT OR REPLACE INTO episodes
                (id, timestamp, player_id, age, result, turns_played, data)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                episode["id"],
                timestamp,
                episode["player_id"],
                episode["age"],
                episode["result"],
                episode["turns_played"],
                json.dumps(episode),
            ),
        )

    def get_episode_count(self, player_id: Optional[str] = None) -> int:
        """Total number of logged episodes, optionally filtered by player."""
        conn = self._conn
        if player_id:
            row = conn.execute(
                "SELECT COUNT(*) FROM episodes WHERE player_id = ?",
                (player_id,)
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()
        return row[0]

    def get_episodes(
        self,
        player_id: Optional[str] = None,
        result: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[dict]:
        """
        Retrieve episodes, optionally filtered.
        Returns list of episode dicts (the brain-facing payload).
        Ordered by timestamp DESCENDING (most recent first).
        """
        conn = self._conn
        conditions = []
        params: List[Any] = []

        if player_id:
            conditions.append("player_id = ?")
            params.append(player_id)
        if result:
            conditions.append("result = ?")
            params.append(result)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params += [limit, offset]

        rows = conn.execute(
            f"SELECT data FROM episodes {where} "
            f"ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            params,
        ).fetchall()

        return [json.loads(row["data"]) for row in rows]

    def get_episode_by_id(self, episode_id: str) -> Optional[dict]:
        """Retrieve a single episode by ID."""
        conn = self._conn
        row = conn.execute(
            "SELECT data FROM episodes WHERE id = ?",
            (episode_id,),
        ).fetchone()
        return json.loads(row["data"]) if row else None

    def get_player_episodes(self, player_id: str) -> List[Dict[str, Any]]:
        """
        Return all episodes for a player, enriched with the DB timestamp.
        Used by PlayerProfiler to compute profile fields.

        Each returned dict is the full episode data payload plus:
          _timestamp  — ISO timestamp from the episodes table row
          _result     — result string (also in payload, duplicated for convenience)

        Ordered by timestamp ASCENDING (oldest first) — deliberately the
        opposite of get_episodes()'s DESC ordering, since PlayerProfiler
        reconstructs history chronologically.
        """
        conn = self._conn
        rows = conn.execute(
            "SELECT timestamp, result, data FROM episodes "
            "WHERE player_id = ? ORDER BY timestamp ASC",
            (player_id,),
        ).fetchall()
        result = []
        for row in rows:
            d = json.loads(row["data"])
            d["_timestamp"] = row["timestamp"]
            d["_result"]    = row["result"]
            result.append(d)
        return result
