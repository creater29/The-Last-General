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
                player_id       TEXT PRIMARY KEY,
                encounter_count INTEGER NOT NULL DEFAULT 0,
                first_seen_age  INTEGER,
                last_seen_age   INTEGER,
                data            JSON NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS player_general_relationship (
                player_id               TEXT PRIMARY KEY,
                trust_level             REAL NOT NULL DEFAULT 0.0,
                betrayal_count          INTEGER NOT NULL DEFAULT 0,
                cooperation_count       INTEGER NOT NULL DEFAULT 0,
                times_attempted_capture INTEGER NOT NULL DEFAULT 0,
                known_deceptions        INTEGER NOT NULL DEFAULT 0,
                predicted_next_intent   TEXT,
                prediction_confidence   REAL NOT NULL DEFAULT 0.0,
                notable_events          JSON NOT NULL DEFAULT '[]'
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

    def upsert_player_profile(self, player_id: str, data: dict, age: int = 1) -> None:
        """Insert or update a player profile."""
        conn = self._get_conn()
        existing = conn.execute(
            "SELECT encounter_count, first_seen_age FROM player_profiles WHERE player_id = ?",
            (player_id,),
        ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE player_profiles
                SET encounter_count = encounter_count + 1,
                    last_seen_age = ?,
                    data = ?
                WHERE player_id = ?
                """,
                (age, json.dumps(data), player_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO player_profiles
                    (player_id, encounter_count, first_seen_age, last_seen_age, data)
                VALUES (?, 1, ?, ?, ?)
                """,
                (player_id, age, age, json.dumps(data)),
            )
        conn.commit()

    def get_player_profile(self, player_id: str) -> Optional[dict]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM player_profiles WHERE player_id = ?",
            (player_id,),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["data"] = json.loads(result["data"])
        return result

    def get_known_players(self) -> List[str]:
        """List all player IDs the General has encountered."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT player_id FROM player_profiles ORDER BY encounter_count DESC"
        ).fetchall()
        return [row["player_id"] for row in rows]

    # ------------------------------------------------------------------
    # Relationship record management
    # ------------------------------------------------------------------

    def upsert_relationship(self, player_id: str, data: dict) -> None:
        """Insert or update the General's relationship with a player."""
        conn = self._get_conn()
        existing = conn.execute(
            "SELECT player_id FROM player_general_relationship WHERE player_id = ?",
            (player_id,),
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
                    predicted_next_intent = ?,
                    prediction_confidence = ?,
                    notable_events = ?
                WHERE player_id = ?
                """,
                (
                    data.get("trust_level", 0.0),
                    data.get("betrayal_count", 0),
                    data.get("cooperation_count", 0),
                    data.get("times_attempted_capture", 0),
                    data.get("known_deceptions", 0),
                    data.get("predicted_next_intent"),
                    data.get("prediction_confidence", 0.0),
                    notable,
                    player_id,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO player_general_relationship
                    (player_id, trust_level, betrayal_count, cooperation_count,
                     times_attempted_capture, known_deceptions,
                     predicted_next_intent, prediction_confidence, notable_events)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    player_id,
                    data.get("trust_level", 0.0),
                    data.get("betrayal_count", 0),
                    data.get("cooperation_count", 0),
                    data.get("times_attempted_capture", 0),
                    data.get("known_deceptions", 0),
                    data.get("predicted_next_intent"),
                    data.get("prediction_confidence", 0.0),
                    notable,
                ),
            )
        conn.commit()

    def get_relationship(self, player_id: str) -> Optional[dict]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM player_general_relationship WHERE player_id = ?",
            (player_id,),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["notable_events"] = json.loads(result["notable_events"])
        return result

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
