"""
relationship_store.py — Persistence for the General's psychological
relationship with specific opponents (Candidate D, D014, Phase 1).

Owns exactly one table: player_general_relationship.

Repository Independence: this class is constructable and fully testable
standalone — RelationshipStore(conn) — with no dependency on any other
store. See state/DEFERRED_ITEMS.md D014 Artifact 1/2/4.

This is a pure extraction from simulator/logger.py. Method bodies are
unchanged from the pre-extraction implementation (verified byte-for-byte
against logger.py before this file was written) — this phase moves code,
it does not change behavior.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Optional


class RelationshipStore:
    """
    Owns persistence for player_general_relationship.

    Public API:
        upsert_relationship(server_id, player_id, data) -> None
        get_relationship(server_id, player_id) -> Optional[dict]
        migrate_relationship_schema() -> None
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert_relationship(self, server_id: str, player_id: str, data: dict) -> None:
        """Insert or update the General's relationship with a player.

        Uses composite key (server_id, player_id) — consistent with player_profiles.
        Cross-server isolation: Steve on Server A and Steve on Server B are distinct.
        """
        conn = self._conn
        existing = conn.execute(
            "SELECT player_id FROM player_general_relationship "
            "WHERE server_id = ? AND player_id = ?",
            (server_id, player_id),
        ).fetchone()

        notable = json.dumps(data.get("notable_events", []))
        if existing:
            conn.execute(
                """
                UPDATE player_general_relationship
                SET trust_level = ?,
                    betrayal_count = ?,
                    cooperation_count = ?,
                    times_attempted_capture = ?,
                    known_deceptions = ?,
                    encounters = ?,
                    predicted_next_intent = ?,
                    prediction_confidence = ?,
                    notable_events = ?
                WHERE server_id = ? AND player_id = ?
                """,
                (
                    data.get("trust_level", 0.0),
                    data.get("betrayal_count", 0),
                    data.get("cooperation_count", 0),
                    data.get("times_attempted_capture", 0),
                    data.get("known_deceptions", 0),
                    data.get("encounters", 0),
                    data.get("predicted_next_intent"),
                    data.get("prediction_confidence", 0.0),
                    notable,
                    server_id,
                    player_id,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO player_general_relationship
                    (server_id, player_id, trust_level, betrayal_count,
                     cooperation_count, times_attempted_capture, known_deceptions,
                     encounters, predicted_next_intent, prediction_confidence,
                     notable_events)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    server_id,
                    player_id,
                    data.get("trust_level", 0.0),
                    data.get("betrayal_count", 0),
                    data.get("cooperation_count", 0),
                    data.get("times_attempted_capture", 0),
                    data.get("known_deceptions", 0),
                    data.get("encounters", 0),
                    data.get("predicted_next_intent"),
                    data.get("prediction_confidence", 0.0),
                    notable,
                ),
            )
        conn.commit()

    def get_relationship(self, server_id: str, player_id: str) -> Optional[dict]:
        """Return the General's relationship record with a specific player.

        Uses composite key (server_id, player_id) — consistent with player_profiles.
        """
        conn = self._conn
        row = conn.execute(
            "SELECT * FROM player_general_relationship "
            "WHERE server_id = ? AND player_id = ?",
            (server_id, player_id),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["notable_events"] = json.loads(result["notable_events"])
        return result

    def migrate_relationship_schema(self) -> None:
        """
        Migrate player_general_relationship from player_id-only PK to
        composite (server_id, player_id) PK — consistent with player_profiles.

        Safe to call on an empty table (no data to preserve).
        Idempotent: if the table already has the correct schema this is a no-op.
        """
        conn = self._conn
        cols = {row["name"] for row in conn.execute(
            "PRAGMA table_info(player_general_relationship)"
        ).fetchall()}
        if "server_id" in cols and "encounters" in cols:
            return  # already at current schema — no-op

        # Drop and recreate: table is empty so no data loss
        conn.execute("DROP TABLE IF EXISTS player_general_relationship")
        conn.execute("""
            CREATE TABLE player_general_relationship (
                server_id               TEXT NOT NULL,
                player_id               TEXT NOT NULL,
                trust_level             REAL NOT NULL DEFAULT 0.0,
                betrayal_count          INTEGER NOT NULL DEFAULT 0,
                cooperation_count       INTEGER NOT NULL DEFAULT 0,
                times_attempted_capture INTEGER NOT NULL DEFAULT 0,
                known_deceptions        INTEGER NOT NULL DEFAULT 0,
                encounters              INTEGER NOT NULL DEFAULT 0,
                predicted_next_intent   TEXT,
                prediction_confidence   REAL NOT NULL DEFAULT 0.0,
                notable_events          JSON NOT NULL DEFAULT '[]',
                PRIMARY KEY (server_id, player_id)
            )
        """)
        conn.commit()
