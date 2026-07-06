"""
doctrine_store.py — Persistence for military doctrines (Candidate D, D014,
Phase 3).

Owns exactly one table: doctrines. (counter_doctrines is a separate,
schema-only, unimplemented table — out of scope, see DEFERRED_ITEMS D014.)

Repository Independence: constructable and fully testable standalone —
DoctrineStore(conn) — with no dependency on any other store. Unlike
RelationshipStore/PlayerProfileStore, this store has no migrate_*_schema()
method: the doctrines table was correct from its original creation and never
needed a schema repair (migrate_* on the first two stores existed for
specific historical reasons — R006, the encounters field — that never
applied here). Initial CREATE TABLE stays a DBManager/facade concern
(init_db()), consistent with Artifact 1.

This is a pure extraction from simulator/logger.py. Method bodies are
unchanged from the pre-extraction implementation (verified byte-for-byte
against the live logger.py before this file was written) — this phase moves
code, it does not change behavior.

BEHAVIOR-CRITICAL NOTE (verified during Phase 3 audit, must be preserved
exactly): upsert_doctrine()'s ON CONFLICT clause deliberately does NOT touch
failure_count or exceptions — only confidence, episode_count,
derived_principle, and last_verified update on conflict. This is intentional:
it means accumulated failure feedback (from increment_doctrine_failure) is
never erased by a later re-extraction pass. Do not "simplify" this update
clause to touch all fields.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional


class DoctrineStore:
    """
    Owns persistence for doctrines.

    Public API:
        upsert_doctrine(doctrine_id, abstraction_level, condition,
                         learned_effect, confidence, episode_count,
                         derived_principle, last_verified,
                         decay_rate=0.005) -> None
        get_doctrine_by_id(doctrine_id) -> Optional[dict]
        get_all_doctrines() -> List[dict]
        increment_doctrine_failure(doctrine_id) -> bool
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

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
        conn = self._conn
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
        conn = self._conn
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
        conn = self._conn
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
        conn = self._conn
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
