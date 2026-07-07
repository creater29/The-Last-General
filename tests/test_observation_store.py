"""
Tests for ObservationStore (Candidate D, D014, Phase 4).

Includes a Repository Independence test: ObservationStore must be
constructable and fully usable with nothing but a raw sqlite3.Connection —
no EpisodeLogger, no EpisodeStore, no other store.

Note: these tests deliberately do NOT enable PRAGMA foreign_keys=ON (the
default sqlite3 behavior), so observation rows can be inserted with an
arbitrary episode_id without a real episodes table existing. In production,
_connect() DOES enable this pragma — see module docstring in
observation_store.py for why insert_observations() never commits internally.
"""

from __future__ import annotations

import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from simulator.stores.observation_store import ObservationStore


def _create_observations_table(conn: sqlite3.Connection) -> None:
    """
    Test-only schema setup, mirroring init_db()'s CREATE TABLE for
    observations exactly (copied from the live logger.py). ObservationStore
    has no migrate_*_schema() method — same reasoning as DoctrineStore: the
    schema was correct from the original creation, no repair was ever needed.
    """
    conn.execute("""
        CREATE TABLE observations (
            id              TEXT PRIMARY KEY,
            episode_id      TEXT NOT NULL,
            timestamp       TEXT NOT NULL,
            terrain_context TEXT NOT NULL,
            action_taken    TEXT NOT NULL,
            observed_effect TEXT NOT NULL,
            confidence      REAL NOT NULL DEFAULT 1.0,
            last_verified   TEXT NOT NULL,
            decay_rate      REAL NOT NULL DEFAULT 0.01
        )
    """)
    conn.commit()


def temp_store() -> ObservationStore:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _create_observations_table(conn)
    return ObservationStore(conn)


def _sample_episode(**overrides):
    base = dict(
        id="ep_test_1",
        terrain_events=[
            {"event_type": "ice_break", "terrain_at_site": "frozen_lake",
             "triggered_by_type": "cavalry"},
            {"event_type": "tree_fall", "terrain_at_site": "forest",
             "triggered_by_type": "cavalry"},
        ],
        general_intents=["TERRAIN_EXPLOIT", "AMBUSH"],
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Repository Independence
# ---------------------------------------------------------------------------

def test_repository_independence_no_other_imports_needed():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _create_observations_table(conn)
    store = ObservationStore(conn)
    store.insert_observations(_sample_episode(), "2026-06-28T00:00:00")
    conn.commit()  # test calls commit itself since insert_observations() doesn't
    assert store.get_observation_count() == 2


# ---------------------------------------------------------------------------
# insert_observations
# ---------------------------------------------------------------------------

def test_insert_creates_one_row_per_terrain_event():
    store = temp_store()
    store.insert_observations(_sample_episode(), "2026-06-28T00:00:00")
    store._conn.commit()
    assert store.get_observation_count() == 2

def test_insert_skips_events_without_event_type():
    store = temp_store()
    episode = _sample_episode(terrain_events=[
        {"event_type": None, "terrain_at_site": "forest", "triggered_by_type": "cavalry"},
        {"event_type": "wall_collapse", "terrain_at_site": "wall", "triggered_by_type": "siege"},
    ])
    store.insert_observations(episode, "2026-06-28T00:00:00")
    store._conn.commit()
    assert store.get_observation_count() == 1

def test_insert_does_not_commit_internally():
    """
    Behavior-critical: insert_observations() must not call commit() itself
    — the facade owns the commit boundary (Transaction Policy, Artifact 2).
    Verify by using a second connection to the same file-backed db and
    confirming the insert isn't visible until this connection commits.
    """
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        conn1 = sqlite3.connect(f.name)
        conn1.row_factory = sqlite3.Row
        _create_observations_table(conn1)
        store = ObservationStore(conn1)
        store.insert_observations(_sample_episode(), "2026-06-28T00:00:00")

        conn2 = sqlite3.connect(f.name)
        count_before_commit = conn2.execute(
            "SELECT COUNT(*) FROM observations"
        ).fetchone()[0]

        conn1.commit()
        count_after_commit = conn2.execute(
            "SELECT COUNT(*) FROM observations"
        ).fetchone()[0]

        conn1.close()
        conn2.close()

        assert count_before_commit == 0  # not visible before commit
        assert count_after_commit == 2   # visible after commit

def test_terrain_context_format():
    store = temp_store()
    store.insert_observations(_sample_episode(), "2026-06-28T00:00:00")
    store._conn.commit()
    results = store.get_observations_by_terrain("frozen_lake+cavalry")
    assert len(results) == 1
    assert results[0]["observed_effect"] == "ice_break"

def test_intent_matched_by_position():
    store = temp_store()
    store.insert_observations(_sample_episode(), "2026-06-28T00:00:00")
    store._conn.commit()
    results = store.get_observations_by_terrain("forest+cavalry")
    assert results[0]["action_taken"] == "AMBUSH"

def test_intent_defaults_to_unknown_if_missing():
    store = temp_store()
    episode = _sample_episode(general_intents=[])  # no intents recorded
    store.insert_observations(episode, "2026-06-28T00:00:00")
    store._conn.commit()
    results = store.get_observations_by_terrain("frozen_lake+cavalry")
    assert results[0]["action_taken"] == "unknown"


# ---------------------------------------------------------------------------
# get_observation_count / get_observations_by_terrain
# ---------------------------------------------------------------------------

def test_count_empty_db():
    store = temp_store()
    assert store.get_observation_count() == 0

def test_get_by_terrain_ordered_by_timestamp_desc():
    store = temp_store()
    ep1 = _sample_episode(id="ep1", terrain_events=[
        {"event_type": "ice_break", "terrain_at_site": "frozen_lake", "triggered_by_type": "cavalry"}
    ], general_intents=["TERRAIN_EXPLOIT"])
    ep2 = _sample_episode(id="ep2", terrain_events=[
        {"event_type": "ice_break", "terrain_at_site": "frozen_lake", "triggered_by_type": "cavalry"}
    ], general_intents=["AMBUSH"])
    store.insert_observations(ep1, "2026-06-01T00:00:00")
    store.insert_observations(ep2, "2026-06-28T00:00:00")
    store._conn.commit()
    results = store.get_observations_by_terrain("frozen_lake+cavalry")
    assert results[0]["timestamp"] == "2026-06-28T00:00:00"  # most recent first

def test_get_by_terrain_respects_limit():
    store = temp_store()
    for i in range(5):
        ep = _sample_episode(id=f"ep{i}", terrain_events=[
            {"event_type": "ice_break", "terrain_at_site": "frozen_lake", "triggered_by_type": "cavalry"}
        ], general_intents=["TERRAIN_EXPLOIT"])
        store.insert_observations(ep, f"2026-06-{i+1:02d}T00:00:00")
    store._conn.commit()
    results = store.get_observations_by_terrain("frozen_lake+cavalry", limit=3)
    assert len(results) == 3


# ---------------------------------------------------------------------------
# get_observation_patterns
# ---------------------------------------------------------------------------

def test_patterns_respects_min_count():
    store = temp_store()
    for i in range(3):
        ep = _sample_episode(id=f"ep{i}", terrain_events=[
            {"event_type": "ice_break", "terrain_at_site": "frozen_lake", "triggered_by_type": "cavalry"}
        ], general_intents=["TERRAIN_EXPLOIT"])
        store.insert_observations(ep, f"2026-06-{i+1:02d}T00:00:00")
    store._conn.commit()
    assert store.get_observation_patterns(min_count=5) == []
    patterns = store.get_observation_patterns(min_count=3)
    assert len(patterns) == 1
    assert patterns[0]["count"] == 3

def test_patterns_ordered_by_count_desc():
    store = temp_store()
    # 2 occurrences of forest+cavalry, 4 of frozen_lake+cavalry
    for i in range(2):
        store.insert_observations(_sample_episode(
            id=f"a{i}",
            terrain_events=[{"event_type": "tree_fall", "terrain_at_site": "forest", "triggered_by_type": "cavalry"}],
            general_intents=["AMBUSH"],
        ), f"2026-06-{i+1:02d}T00:00:00")
    for i in range(4):
        store.insert_observations(_sample_episode(
            id=f"b{i}",
            terrain_events=[{"event_type": "ice_break", "terrain_at_site": "frozen_lake", "triggered_by_type": "cavalry"}],
            general_intents=["TERRAIN_EXPLOIT"],
        ), f"2026-06-{i+10:02d}T00:00:00")
    store._conn.commit()
    patterns = store.get_observation_patterns(min_count=1)
    assert patterns[0]["terrain_context"] == "frozen_lake+cavalry"
    assert patterns[0]["count"] == 4
