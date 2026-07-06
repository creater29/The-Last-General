"""
logger.py — Episode persistence layer.

Writes completed BattleState episodes to SQLite.
This is the boundary between the simulator and the brain.
The brain reads from these tables. The simulator writes to them.
They never share code — only the database schema.

All 7 tables are initialized here.
The brain will query them directly in Stage 2.
"""

from __future__ import annotations
import sqlite3
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any

from simulator.battle import BattleState
from simulator.stores.relationship_store import RelationshipStore
from simulator.stores.player_profile_store import PlayerProfileStore


# ---------------------------------------------------------------------------
# Default DB path
# ---------------------------------------------------------------------------

DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "data" / "episodes" / "general_brain.db"


# ---------------------------------------------------------------------------
# Episode Logger
# ---------------------------------------------------------------------------

class EpisodeLogger:
    """
    Persists battle episodes and initializes all brain-facing database tables.

    The simulator calls log_episode() after every battle.
    The brain reads from get_episodes(), get_observations(), etc.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self.init_db()
        # Repository/store layer (Candidate D, D014) — each store owns one
        # table and is independently constructable/testable. See
        # state/DEFERRED_ITEMS.md D014 for the full extraction spec.
        self._relationship_store = RelationshipStore(self._conn)
        self._player_profile_store = PlayerProfileStore(self._conn)

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")   # safe concurrent writes
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = self._connect()
        return self._conn

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # ------------------------------------------------------------------
    # Schema initialization
    # ------------------------------------------------------------------

    def init_db(self) -> None:
        """Create all 7 tables if they don't exist."""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS episodes (
                id          TEXT PRIMARY KEY,
                timestamp   TEXT NOT NULL,
                player_id   TEXT NOT NULL,
                age         INTEGER NOT NULL,
                result      TEXT NOT NULL,
                turns_played INTEGER NOT NULL,
                data        JSON NOT NULL
            );

            CREATE TABLE IF NOT EXISTS observations (
                id              TEXT PRIMARY KEY,
                episode_id      TEXT NOT NULL,
                timestamp       TEXT NOT NULL,
                terrain_context TEXT NOT NULL,
                action_taken    TEXT NOT NULL,
                observed_effect TEXT NOT NULL,
                confidence      REAL NOT NULL DEFAULT 1.0,
                last_verified   TEXT NOT NULL,
                decay_rate      REAL NOT NULL DEFAULT 0.01,
                FOREIGN KEY (episode_id) REFERENCES episodes(id)
            );

            CREATE TABLE IF NOT EXISTS doctrines (
                id                TEXT PRIMARY KEY,
                abstraction_level TEXT NOT NULL,
                condition         TEXT NOT NULL,
                learned_effect    TEXT NOT NULL,
                confidence        REAL NOT NULL DEFAULT 0.5,
                episode_count     INTEGER NOT NULL DEFAULT 0,
                failure_count     INTEGER NOT NULL DEFAULT 0,
                derived_principle TEXT,
                exceptions        JSON NOT NULL DEFAULT '[]',
                last_verified     TEXT,
                decay_rate        REAL NOT NULL DEFAULT 0.005
            );

            CREATE TABLE IF NOT EXISTS player_profiles (
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
            );

            CREATE TABLE IF NOT EXISTS player_general_relationship (
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
            );

            CREATE TABLE IF NOT EXISTS terrain_knowledge (
                terrain_type      TEXT NOT NULL,
                action_type       TEXT NOT NULL,
                observed_outcomes JSON NOT NULL DEFAULT '[]',
                confidence        REAL NOT NULL DEFAULT 0.0,
                episode_count     INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (terrain_type, action_type)
            );

            CREATE TABLE IF NOT EXISTS counter_doctrines (
                id                  TEXT PRIMARY KEY,
                triggers_on_intent  TEXT NOT NULL,
                condition           TEXT NOT NULL,
                counter_action      TEXT NOT NULL,
                success_rate        REAL NOT NULL DEFAULT 0.0,
                confidence          REAL NOT NULL DEFAULT 0.0,
                last_verified       TEXT,
                decay_rate          REAL NOT NULL DEFAULT 0.005,
                episode_count       INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_episodes_player
                ON episodes(player_id);
            CREATE INDEX IF NOT EXISTS idx_episodes_age
                ON episodes(age);
            CREATE INDEX IF NOT EXISTS idx_episodes_result
                ON episodes(result);
            CREATE INDEX IF NOT EXISTS idx_observations_episode
                ON observations(episode_id);
            CREATE INDEX IF NOT EXISTS idx_observations_terrain
                ON observations(terrain_context);
            CREATE INDEX IF NOT EXISTS idx_observations_effect
                ON observations(observed_effect);
        """)
        conn.commit()

    # ------------------------------------------------------------------
    # Episode logging
    # ------------------------------------------------------------------

    def log_episode(self, state: BattleState) -> str:
        """
        Persist a completed battle to the episodes table.
        Also extracts and logs terrain observations for doctrine formation.
        Returns the episode id.
        """
        episode = state.to_episode()
        timestamp = datetime.now(timezone.utc).isoformat()

        conn = self._get_conn()
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

        # Extract terrain observations from this episode
        self._extract_observations(episode, timestamp)

        conn.commit()
        return episode["id"]

    def _extract_observations(self, episode: dict, timestamp: str) -> None:
        """
        Pull terrain events from an episode and store as observations.
        These are the raw evidence the doctrine extractor (Stage 2) will use.

        Each terrain event becomes one observation:
        - terrain_context: what terrain was present
        - action_taken: what intent was being executed
        - observed_effect: what happened (ice_break, wall_collapse, etc.)
        """
        conn = self._get_conn()
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

    # ------------------------------------------------------------------
    # Episode retrieval
    # ------------------------------------------------------------------

    def get_episode_count(self, player_id: Optional[str] = None) -> int:
        """Total number of logged episodes, optionally filtered by player."""
        conn = self._get_conn()
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
        """
        conn = self._get_conn()
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

    def get_episodes_by_terrain_event(
        self,
        event_type: str,
        limit: int = 50,
    ) -> List[dict]:
        """
        Retrieve episodes that contain a specific terrain event type.
        Used by the doctrine extractor to find supporting evidence.
        """
        conn = self._get_conn()
        # Episodes linked to observations of this event type
        rows = conn.execute(
            """
            SELECT DISTINCT e.data
            FROM episodes e
            JOIN observations o ON o.episode_id = e.id
            WHERE o.observed_effect = ?
            ORDER BY e.timestamp DESC
            LIMIT ?
            """,
            (event_type, limit),
        ).fetchall()
        return [json.loads(row["data"]) for row in rows]

    def get_episode_by_id(self, episode_id: str) -> Optional[dict]:
        """Retrieve a single episode by ID."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT data FROM episodes WHERE id = ?",
            (episode_id,),
        ).fetchone()
        return json.loads(row["data"]) if row else None

    # ------------------------------------------------------------------
    # Observation retrieval
    # ------------------------------------------------------------------

    def get_observation_count(self) -> int:
        conn = self._get_conn()
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
        conn = self._get_conn()
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
        conn = self._get_conn()
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

    # ------------------------------------------------------------------
    # Player profile management
    # ------------------------------------------------------------------

    def get_known_players(self) -> List[str]:
        """
        List all player IDs the General has encountered.

        ORPHANED API — zero callers anywhere in the codebase as of 2026-06-28
        audit. Also currently broken: queries `encounter_count`, a column
        that does not exist in the current player_profiles schema (would
        raise sqlite3.OperationalError if ever called). Not repaired because
        no consumer has been identified yet — see KNOWN_ISSUES for tracking.
        Do not call this method until it is either fixed with a demonstrated
        use case, or removed.
        """
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT player_id FROM player_profiles ORDER BY encounter_count DESC"
        ).fetchall()
        return [row["player_id"] for row in rows]

    # ------------------------------------------------------------------
    # Relationship record management
    # Delegates to RelationshipStore (Candidate D, D014, Phase 1).
    # ------------------------------------------------------------------

    def upsert_relationship(self, server_id: str, player_id: str, data: dict) -> None:
        """Insert or update the General's relationship with a player.

        Uses composite key (server_id, player_id) — consistent with player_profiles.
        Cross-server isolation: Steve on Server A and Steve on Server B are distinct.
        """
        return self._relationship_store.upsert_relationship(server_id, player_id, data)

    def get_relationship(self, server_id: str, player_id: str) -> Optional[dict]:
        """Return the General's relationship record with a specific player.

        Uses composite key (server_id, player_id) — consistent with player_profiles.
        """
        return self._relationship_store.get_relationship(server_id, player_id)

    def migrate_relationship_schema(self) -> None:
        """
        Migrate player_general_relationship from player_id-only PK to
        composite (server_id, player_id) PK — consistent with player_profiles.

        Safe to call on an empty table (no data to preserve).
        Idempotent: if the table already has the correct schema this is a no-op.

        Run once on the production DB after this code is deployed:
            python3 -c "
            import sys; sys.path.insert(0, 'src')
            from simulator.logger import EpisodeLogger
            EpisodeLogger().migrate_relationship_schema()
            print('Done.')
            "
        """
        return self._relationship_store.migrate_relationship_schema()

    # ------------------------------------------------------------------
    # Stats / diagnostics
    # ------------------------------------------------------------------

    def summary(self) -> dict:
        """Quick health check — counts across all tables."""
        conn = self._get_conn()
        return {
            "episodes":       conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0],
            "observations":   conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0],
            "doctrines":      conn.execute("SELECT COUNT(*) FROM doctrines").fetchone()[0],
            "player_profiles": conn.execute("SELECT COUNT(*) FROM player_profiles").fetchone()[0],
            "relationships":  conn.execute("SELECT COUNT(*) FROM player_general_relationship").fetchone()[0],
            "terrain_knowledge": conn.execute("SELECT COUNT(*) FROM terrain_knowledge").fetchone()[0],
            "counter_doctrines": conn.execute("SELECT COUNT(*) FROM counter_doctrines").fetchone()[0],
            "db_path":        str(self.db_path),
        }

    def result_distribution(self) -> dict:
        """How many wins/losses/draws across all episodes."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT result, COUNT(*) as count FROM episodes GROUP BY result"
        ).fetchall()
        return {row["result"]: row["count"] for row in rows}

    def terrain_event_frequency(self) -> dict:
        """How often each terrain event type appears in observations."""
        conn = self._get_conn()
        rows = conn.execute(
            """
            SELECT observed_effect, COUNT(*) as count
            FROM observations
            GROUP BY observed_effect
            ORDER BY count DESC
            """
        ).fetchall()
        return {row["observed_effect"]: row["count"] for row in rows}

    # ------------------------------------------------------------------
    # Terrain knowledge (written by WorldModel, read by brain)
    # ------------------------------------------------------------------

    def upsert_terrain_knowledge(
        self,
        terrain_type: str,
        action_type: str,
        observed_outcomes: List[str],
        confidence: float,
        episode_count: int,
    ) -> None:
        """
        Insert or replace a terrain knowledge belief.

        Called by WorldModel.update_from_observations().
        observed_outcomes is a list of distinct effect types seen for this
        terrain+action pair — e.g. ["flood"] or ["ice_break"].
        On conflict, replaces the existing row with fresh computed values
        because update_from_observations always reads from full observation
        history and recomputes from ground truth.
        """
        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO terrain_knowledge
                (terrain_type, action_type, observed_outcomes, confidence, episode_count)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(terrain_type, action_type) DO UPDATE SET
                observed_outcomes = excluded.observed_outcomes,
                confidence        = excluded.confidence,
                episode_count     = excluded.episode_count
            """,
            (
                terrain_type,
                action_type,
                json.dumps(observed_outcomes),
                confidence,
                episode_count,
            ),
        )
        conn.commit()

    def get_terrain_knowledge(
        self, terrain_type: str, action_type: str
    ) -> Optional[Dict[str, Any]]:
        """
        Return the General's belief about a specific terrain+action pair.
        Returns None if no belief has been formed yet.
        """
        conn = self._get_conn()
        row = conn.execute(
            """
            SELECT terrain_type, action_type, observed_outcomes, confidence, episode_count
            FROM terrain_knowledge
            WHERE terrain_type = ? AND action_type = ?
            """,
            (terrain_type, action_type),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["observed_outcomes"] = json.loads(result["observed_outcomes"])
        return result

    def get_all_terrain_knowledge(self) -> List[Dict[str, Any]]:
        """
        Return all terrain beliefs, ordered by confidence descending.
        Used by WorldModel.get_all_beliefs().
        """
        conn = self._get_conn()
        rows = conn.execute(
            """
            SELECT terrain_type, action_type, observed_outcomes, confidence, episode_count
            FROM terrain_knowledge
            ORDER BY confidence DESC
            """
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["observed_outcomes"] = json.loads(d["observed_outcomes"])
            result.append(d)
        return result

    # ------------------------------------------------------------------
    # Doctrines (written by DoctrineExtractor, read by decision_engine)
    # ------------------------------------------------------------------

    def upsert_doctrine(
        self,
        doctrine_id:       str,
        abstraction_level: str,
        condition:         str,
        learned_effect:    str,
        confidence:        float,
        episode_count:     int,
        derived_principle: str,
        last_verified:     str,
        decay_rate:        float = 0.005,
    ) -> None:
        """
        Insert or update a doctrine row.

        On conflict, updates confidence, episode_count, derived_principle,
        and last_verified — the fields that may change as more observations
        accumulate. failure_count and exceptions are left unchanged so
        accumulated feedback is not erased by a re-extraction.
        """
        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO doctrines
                (id, abstraction_level, condition, learned_effect, confidence,
                 episode_count, failure_count, derived_principle, exceptions,
                 last_verified, decay_rate)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                confidence        = excluded.confidence,
                episode_count     = excluded.episode_count,
                derived_principle = excluded.derived_principle,
                last_verified     = excluded.last_verified
            """,
            (
                doctrine_id, abstraction_level, condition, learned_effect,
                confidence, episode_count, 0, derived_principle,
                "[]", last_verified, decay_rate,
            ),
        )
        conn.commit()

    def get_doctrine_by_id(self, doctrine_id: str) -> Optional[Dict[str, Any]]:
        """Return one doctrine row by id, or None if not found."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM doctrines WHERE id = ?", (doctrine_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["exceptions"] = json.loads(d["exceptions"])
        return d

    def get_all_doctrines(self) -> List[Dict[str, Any]]:
        """
        Return all doctrine rows ordered by confidence descending.
        Used by DoctrineExtractor.get_doctrines().
        """
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM doctrines ORDER BY confidence DESC"
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["exceptions"] = json.loads(d["exceptions"])
            result.append(d)
        return result

    def increment_doctrine_failure(self, doctrine_id: str) -> bool:
        """
        Increment failure_count for a doctrine and recompute decay_rate.

        Called by DecisionEngine.record_battle_outcome() when a doctrine-backed
        decision was made in a battle the General lost.

        decay_rate = failure_count / (episode_count + failure_count)
        This means: a doctrine seen 100 times with 10 failures → decay_rate 0.091
        Applied in _doctrine_factor() as: effective_confidence = confidence * (1 - decay_rate)

        Returns True if the doctrine was found and updated, False otherwise.
        """
        conn = self._get_conn()
        row = conn.execute(
            "SELECT failure_count, episode_count FROM doctrines WHERE id = ?",
            (doctrine_id,),
        ).fetchone()

        if not row:
            return False

        new_failure = row["failure_count"] + 1
        total       = row["episode_count"] + new_failure
        new_decay   = round(new_failure / max(1, total), 6)

        conn.execute(
            "UPDATE doctrines SET failure_count = ?, decay_rate = ? WHERE id = ?",
            (new_failure, new_decay, doctrine_id),
        )
        conn.commit()
        return True

    # ------------------------------------------------------------------
    # Player profiles (written by PlayerProfiler)
    # ------------------------------------------------------------------

    def migrate_player_profiles(self) -> None:
        """
        Drop and recreate player_profiles with the server-scoped schema.

        Safe to call on the production DB: player_profiles is always empty
        before player_profiler.py runs for the first time. Episodes and
        observations are untouched.
        """
        return self._player_profile_store.migrate_player_profiles()

    def get_player_episodes(self, player_id: str) -> List[Dict[str, Any]]:
        """
        Return all episodes for a player, enriched with the DB timestamp.
        Used by PlayerProfiler to compute profile fields.

        Each returned dict is the full episode data payload plus:
          _timestamp  — ISO timestamp from the episodes table row
          _result     — result string (also in payload, duplicated for convenience)
        """
        conn = self._get_conn()
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
        return self._player_profile_store.upsert_player_profile(
            server_id, player_id, first_seen, last_seen,
            total_battles, win_count, loss_count, draw_count,
            preferred_units, terrain_tendencies,
            aggression_index, adaptability_score, raw_data,
        )

    def get_player_profile(
        self, server_id: str, player_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Return a player's profile for a specific server, or None.
        """
        return self._player_profile_store.get_player_profile(server_id, player_id)

    def get_all_player_profiles(
        self, server_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Return all profiles, optionally filtered by server.
        Ordered by total_battles descending (most experienced players first).
        """
        return self._player_profile_store.get_all_player_profiles(server_id)
