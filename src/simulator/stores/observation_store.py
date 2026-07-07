"""
observation_store.py — Persistence for raw terrain-event evidence extracted
from episodes (Candidate D, D014, Phase 4).

Owns exactly one table: observations.

Repository Independence: constructable and fully testable standalone —
ObservationStore(conn) — with NO dependency on EpisodeStore or any other
store. This is a deliberate revision from the original D014 draft (which had
EpisodeStore holding a reference to ObservationStore) — see Transaction
Policy in DEFERRED_ITEMS.md D014 Artifact 2. The orchestration of
log_episode() (episode insert + observation extraction + single commit)
stays on the facade (EpisodeLogger) until Phase 5 formally restructures it;
for now, the facade's existing log_episode() body calls
self._observation_store.insert_observations(...) directly — that is the
facade composing two independent stores, not one store depending on another.

This is a pure extraction from simulator/logger.py. Method bodies are
unchanged from the pre-extraction implementation (verified byte-for-byte
against the live logger.py before this file was written) — this phase moves
code, it does not change behavior. insert_observations() is a rename of the
original _extract_observations() — same body, public name (it's no longer
a private implementation detail of EpisodeLogger, it's this store's public
write method).

BEHAVIOR-CRITICAL NOTE (verified during Phase 4 audit): insert_observations()
does NOT call commit() internally — this is deliberate, not an oversight.
The observations table has `FOREIGN KEY (episode_id) REFERENCES episodes(id)`,
enforced in production (PRAGMA foreign_keys=ON, set in _connect()). The
calling facade method must insert the parent episode row first, then call
this method, then commit once — both for atomicity (Transaction Policy) and
because the FK constraint would reject observation rows referencing an
episode_id that hasn't been committed/inserted yet in the same transaction
scope. Do not add a commit() call to this method.
"""

from __future__ import annotations

import sqlite3
import uuid
from typing import List


class ObservationStore:
    """
    Owns persistence for observations.

    Public API:
        insert_observations(episode, timestamp) -> None
            [renamed from _extract_observations; does NOT commit — caller
             (currently the facade's log_episode()) must commit after
             inserting the parent episode row]
        get_observation_count() -> int
        get_observations_by_terrain(terrain_context, limit=100) -> List[dict]
        get_observation_patterns(min_count=5) -> List[dict]
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert_observations(self, episode: dict, timestamp: str) -> None:
        """
        Pull terrain events from an episode and store as observations.
        These are the raw evidence the doctrine extractor (Stage 2) will use.

        Each terrain event becomes one observation:
        - terrain_context: what terrain was present
        - action_taken: what intent was being executed
        - observed_effect: what happened (ice_break, wall_collapse, etc.)

        Does NOT commit — see module docstring (FK constraint + atomicity
        with the parent episode insert).
        """
        conn = self._conn
        episode_id = episode["id"]

        terrain_events = episode.get("terrain_events", [])
        general_intents = episode.get("general_intents", [])

        # Match events to the intent that was active that turn
        for i, event in enumerate(terrain_events):
            event_type = event.get("event_type")
            if not event_type:
                continue

            # Best-effort intent matching by position
            intent = general_intents[i] if i < len(general_intents) else "unknown"
            terrain = event.get("terrain_at_site", "unknown")
            trigger = event.get("triggered_by_type", "unknown")

            obs_id = str(uuid.uuid4())[:12]
            conn.execute(
                """
                INSERT OR IGNORE INTO observations
                    (id, episode_id, timestamp, terrain_context,
                     action_taken, observed_effect,
                     confidence, last_verified, decay_rate)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    obs_id,
                    episode_id,
                    timestamp,
                    f"{terrain}+{trigger}",   # e.g. "frozen_lake+cavalry"
                    intent,
                    event_type,               # e.g. "ice_break"
                    1.0,
                    timestamp,
                    0.01,
                ),
            )

    def get_observation_count(self) -> int:
        """Total number of observations logged."""
        conn = self._conn
        return conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]

    def get_observations_by_terrain(
        self,
        terrain_context: str,
        limit: int = 100,
    ) -> List[dict]:
        """
        Get all observations for a terrain context.
        e.g. terrain_context = "frozen_lake+cavalry"
        Used by doctrine extractor to find patterns.
        """
        conn = self._conn
        rows = conn.execute(
            """
            SELECT * FROM observations
            WHERE terrain_context = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (terrain_context, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_observation_patterns(self, min_count: int = 5) -> List[dict]:
        """
        Find (terrain_context, observed_effect) pairs that occur
        at least min_count times. These are candidates for doctrine formation.
        This is the key query the doctrine extractor will use.
        """
        conn = self._conn
        rows = conn.execute(
            """
            SELECT terrain_context, observed_effect,
                   COUNT(*) as count,
                   AVG(confidence) as avg_confidence
            FROM observations
            GROUP BY terrain_context, observed_effect
            HAVING COUNT(*) >= ?
            ORDER BY count DESC
            """,
            (min_count,),
        ).fetchall()
        return [dict(row) for row in rows]
