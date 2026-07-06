"""
player_profile_store.py — Persistence for per-player tactical behaviour
profiles (Candidate D, D014, Phase 2).

Owns exactly one table: player_profiles.

Repository Independence: constructable and fully testable standalone —
PlayerProfileStore(conn) — with no dependency on any other store.

This is a pure extraction from simulator/logger.py. Method bodies are
unchanged from the pre-extraction implementation (verified byte-for-byte
against the live logger.py before this file was written, not against the
DEFERRED_ITEMS D014 spec snapshot) — this phase moves code, it does not
change behavior.

NOTE: get_player_episodes() was found sitting near these methods in
logger.py during the Phase 2 audit, but it queries the `episodes` table
only — it belongs to EpisodeStore (Phase 5), not here, despite being used
by PlayerProfiler. See DEFERRED_ITEMS.md D014 Artifact 1 for the correction.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional


class PlayerProfileStore:
    """
    Owns persistence for player_profiles.

    Public API:
        upsert_player_profile(server_id, player_id, first_seen, last_seen,
                               total_battles, win_count, loss_count,
                               draw_count, preferred_units,
                               terrain_tendencies, aggression_index,
                               adaptability_score, raw_data) -> None
        get_player_profile(server_id, player_id) -> Optional[dict]
        get_all_player_profiles(server_id=None) -> List[dict]
        migrate_player_profiles() -> None
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def migrate_player_profiles(self) -> None:
        """
        Drop and recreate player_profiles with the server-scoped schema.

        Safe to call on the production DB: player_profiles is always empty
        before player_profiler.py runs for the first time. Episodes and
        observations are untouched.
        """
        conn = self._conn
        conn.execute("DROP TABLE IF EXISTS player_profiles")
        conn.execute("""
            CREATE TABLE player_profiles (
                server_id          TEXT NOT NULL,
                player_id          TEXT NOT NULL,
                first_seen         TEXT,
                last_seen          TEXT,
                total_battles      INTEGER NOT NULL DEFAULT 0,
                win_count          INTEGER NOT NULL DEFAULT 0,
                loss_count         INTEGER NOT NULL DEFAULT 0,
                draw_count         INTEGER NOT NULL DEFAULT 0,
                preferred_units    JSON NOT NULL DEFAULT '{}',
                terrain_tendencies JSON NOT NULL DEFAULT '{}',
                aggression_index   REAL NOT NULL DEFAULT 0.5,
                adaptability_score REAL NOT NULL DEFAULT 0.5,
                data               JSON NOT NULL DEFAULT '{}',
                PRIMARY KEY (server_id, player_id)
            )
        """)
        conn.commit()

    def upsert_player_profile(
        self,
        server_id:          str,
        player_id:          str,
        first_seen:         str,
        last_seen:          str,
        total_battles:      int,
        win_count:          int,
        loss_count:         int,
        draw_count:         int,
        preferred_units:    dict,
        terrain_tendencies: dict,
        aggression_index:   float,
        adaptability_score: float,
        raw_data:           dict,
    ) -> None:
        """
        Insert or update a player profile row.

        On conflict, replaces all fields — the profiler always recomputes
        from the full episode history so overwriting is safe.
        """
        conn = self._conn
        conn.execute(
            """
            INSERT INTO player_profiles
                (server_id, player_id, first_seen, last_seen,
                 total_battles, win_count, loss_count, draw_count,
                 preferred_units, terrain_tendencies,
                 aggression_index, adaptability_score, data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(server_id, player_id) DO UPDATE SET
                first_seen         = excluded.first_seen,
                last_seen          = excluded.last_seen,
                total_battles      = excluded.total_battles,
                win_count          = excluded.win_count,
                loss_count         = excluded.loss_count,
                draw_count         = excluded.draw_count,
                preferred_units    = excluded.preferred_units,
                terrain_tendencies = excluded.terrain_tendencies,
                aggression_index   = excluded.aggression_index,
                adaptability_score = excluded.adaptability_score,
                data               = excluded.data
            """,
            (
                server_id, player_id, first_seen, last_seen,
                total_battles, win_count, loss_count, draw_count,
                json.dumps(preferred_units), json.dumps(terrain_tendencies),
                aggression_index, adaptability_score, json.dumps(raw_data),
            ),
        )
        conn.commit()

    def get_player_profile(
        self, server_id: str, player_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Return a player's profile for a specific server, or None.
        """
        conn = self._conn
        row = conn.execute(
            "SELECT * FROM player_profiles WHERE server_id = ? AND player_id = ?",
            (server_id, player_id),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["preferred_units"]    = json.loads(d["preferred_units"])
        d["terrain_tendencies"] = json.loads(d["terrain_tendencies"])
        d["data"]               = json.loads(d["data"])
        return d

    def get_all_player_profiles(
        self, server_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Return all profiles, optionally filtered by server.
        Ordered by total_battles descending (most experienced players first).
        """
        conn = self._conn
        if server_id:
            rows = conn.execute(
                "SELECT * FROM player_profiles WHERE server_id = ? "
                "ORDER BY total_battles DESC",
                (server_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM player_profiles ORDER BY total_battles DESC"
            ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["preferred_units"]    = json.loads(d["preferred_units"])
            d["terrain_tendencies"] = json.loads(d["terrain_tendencies"])
            d["data"]               = json.loads(d["data"])
            result.append(d)
        return result
