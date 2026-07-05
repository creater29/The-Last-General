"""
Tests for RelationshipStore (Candidate D, D014, Phase 1).

Critically includes a Repository Independence test: RelationshipStore must
be constructable and fully usable with nothing but a raw sqlite3.Connection
— no EpisodeLogger, no other store, no facade of any kind.
"""

from __future__ import annotations

import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from simulator.stores.relationship_store import RelationshipStore


def temp_store() -> RelationshipStore:
    """
    Repository Independence: construct RelationshipStore directly against a
    raw in-memory connection. No EpisodeLogger. No other store imported or
    constructed. This is the standalone-testability requirement itself,
    not just a convenience fixture.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RelationshipStore(conn)
    store.migrate_relationship_schema()  # creates the table fresh
    return store


SERVER  = "test_server"
PLAYER  = "test_player"
SERVER2 = "other_server"


# ---------------------------------------------------------------------------
# Repository Independence
# ---------------------------------------------------------------------------

def test_repository_independence_no_other_imports_needed():
    """
    This test's mere existence (and the fact the module imports only
    sqlite3 + RelationshipStore, nothing from logger.py or any other store)
    is the independence proof. Also exercise basic usage to confirm it
    isn't just importable but actually functional standalone.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RelationshipStore(conn)
    store.migrate_relationship_schema()
    store.upsert_relationship(SERVER, PLAYER, {"trust_level": 0.5, "encounters": 1})
    result = store.get_relationship(SERVER, PLAYER)
    assert result["trust_level"] == 0.5
    assert result["encounters"] == 1


# ---------------------------------------------------------------------------
# upsert / get
# ---------------------------------------------------------------------------

def test_upsert_new_record():
    store = temp_store()
    store.upsert_relationship(SERVER, PLAYER, {
        "trust_level": -0.3, "betrayal_count": 1, "cooperation_count": 0,
        "times_attempted_capture": 0, "known_deceptions": 0, "encounters": 1,
        "notable_events": ["fled at turn 12"],
    })
    result = store.get_relationship(SERVER, PLAYER)
    assert result is not None
    assert result["trust_level"] == -0.3
    assert result["betrayal_count"] == 1
    assert "fled at turn 12" in result["notable_events"]

def test_upsert_updates_existing_record():
    store = temp_store()
    store.upsert_relationship(SERVER, PLAYER, {"trust_level": 0.1, "encounters": 1})
    store.upsert_relationship(SERVER, PLAYER, {"trust_level": 0.4, "encounters": 2})
    result = store.get_relationship(SERVER, PLAYER)
    assert result["trust_level"] == 0.4
    assert result["encounters"] == 2

def test_get_unknown_player_returns_none():
    store = temp_store()
    assert store.get_relationship(SERVER, "nobody") is None

def test_server_isolation():
    store = temp_store()
    store.upsert_relationship(SERVER,  PLAYER, {"trust_level": 0.8, "encounters": 1})
    store.upsert_relationship(SERVER2, PLAYER, {"trust_level": -0.8, "encounters": 1})
    result_a = store.get_relationship(SERVER, PLAYER)
    result_b = store.get_relationship(SERVER2, PLAYER)
    assert result_a["trust_level"] == 0.8
    assert result_b["trust_level"] == -0.8

def test_notable_events_json_roundtrip():
    store = temp_store()
    store.upsert_relationship(SERVER, PLAYER, {
        "trust_level": 0.0, "encounters": 1,
        "notable_events": ["a", "b", "c"],
    })
    result = store.get_relationship(SERVER, PLAYER)
    assert result["notable_events"] == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# migrate_relationship_schema
# ---------------------------------------------------------------------------

def test_migrate_is_idempotent():
    """Calling migrate twice on an already-correct schema is a no-op."""
    store = temp_store()
    store.upsert_relationship(SERVER, PLAYER, {"trust_level": 0.5, "encounters": 3})
    store.migrate_relationship_schema()  # second call — must not wipe data
    result = store.get_relationship(SERVER, PLAYER)
    assert result["trust_level"] == 0.5
    assert result["encounters"] == 3

def test_migrate_creates_correct_columns():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = RelationshipStore(conn)
    store.migrate_relationship_schema()
    cols = {row["name"] for row in conn.execute(
        "PRAGMA table_info(player_general_relationship)"
    ).fetchall()}
    assert "server_id" in cols
    assert "encounters" in cols
