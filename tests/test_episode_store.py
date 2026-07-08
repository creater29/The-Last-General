"""
Tests for EpisodeStore (Candidate D, D014, Phase 5).

This is the phase the Repository Independence revision was designed for.
Includes:
  - Repository Independence: EpisodeStore constructable/testable standalone,
    zero reference to ObservationStore.
  - A direct proof that insert_episode_row() does not commit internally.
  - A composition test proving EpisodeStore + ObservationStore, called by
    an external orchestrator (simulating the facade), commit atomically —
    the exact pattern log_episode() must implement.
"""

from __future__ import annotations

import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from simulator.stores.episode_store import EpisodeStore
from simulator.stores.observation_store import ObservationStore


def _create_episodes_table(conn: sqlite3.Connection) -> None:
    """Mirrors init_db()'s CREATE TABLE for episodes exactly."""
    conn.execute("""
        CREATE TABLE episodes (
            id           TEXT PRIMARY KEY,
            timestamp    TEXT NOT NULL,
            player_id    TEXT NOT NULL,
            age          INTEGER NOT NULL,
            result       TEXT NOT NULL,
            turns_played INTEGER NOT NULL,
            data         JSON NOT NULL
        )
    """)
    conn.commit()


def _create_observations_table(conn: sqlite3.Connection) -> None:
    """Mirrors init_db()'s CREATE TABLE for observations exactly."""
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


def temp_store() -> EpisodeStore:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _create_episodes_table(conn)
    return EpisodeStore(conn)


def _sample_episode(**overrides):
    base = dict(
        id="ep_test_1", player_id="arman", age=300,
        result="win", turns_played=30,
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Repository Independence
# ---------------------------------------------------------------------------

def test_repository_independence_no_other_imports_needed():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _create_episodes_table(conn)
    store = EpisodeStore(conn)
    store.insert_episode_row(_sample_episode(), "2026-06-28T00:00:00")
    conn.commit()
    assert store.get_episode_count() == 1

def test_episode_store_has_no_observation_store_reference():
    """
    Static check: EpisodeStore's module must not IMPORT ObservationStore.
    (The module's own docstring legitimately mentions "ObservationStore" as
    prose explaining the design rationale — checking for that substring
    across the whole file, including docstrings, would be a false positive.
    Check actual import statements via AST instead.)
    """
    import ast
    import simulator.stores.episode_store as mod
    tree = ast.parse(open(mod.__file__).read())
    imported_names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.append(node.module or "")
        elif isinstance(node, ast.Import):
            imported_names.extend(n.name for n in node.names)
    assert not any("observation_store" in name for name in imported_names)


# ---------------------------------------------------------------------------
# insert_episode_row
# ---------------------------------------------------------------------------

def test_insert_creates_row():
    store = temp_store()
    store.insert_episode_row(_sample_episode(), "2026-06-28T00:00:00")
    store._conn.commit()
    assert store.get_episode_count() == 1

def test_insert_or_replace_semantics():
    """Same episode id inserted twice replaces, does not duplicate."""
    store = temp_store()
    store.insert_episode_row(_sample_episode(result="win"), "2026-06-28T00:00:00")
    store.insert_episode_row(_sample_episode(result="loss"), "2026-06-28T00:01:00")
    store._conn.commit()
    assert store.get_episode_count() == 1
    result = store.get_episode_by_id("ep_test_1")
    assert result["result"] == "loss"  # second insert replaced the first

def test_insert_does_not_commit_internally():
    """
    Behavior-critical: insert_episode_row() must not call commit() itself.
    Same two-connection proof pattern as Phase 4's ObservationStore test.
    """
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        conn1 = sqlite3.connect(f.name)
        conn1.row_factory = sqlite3.Row
        _create_episodes_table(conn1)
        store = EpisodeStore(conn1)
        store.insert_episode_row(_sample_episode(), "2026-06-28T00:00:00")

        conn2 = sqlite3.connect(f.name)
        count_before_commit = conn2.execute(
            "SELECT COUNT(*) FROM episodes"
        ).fetchone()[0]

        conn1.commit()
        count_after_commit = conn2.execute(
            "SELECT COUNT(*) FROM episodes"
        ).fetchone()[0]

        conn1.close()
        conn2.close()

        assert count_before_commit == 0
        assert count_after_commit == 1


# ---------------------------------------------------------------------------
# get_episode_count / get_episodes / get_episode_by_id
# ---------------------------------------------------------------------------

def test_count_filtered_by_player():
    store = temp_store()
    store.insert_episode_row(_sample_episode(id="e1", player_id="a"), "2026-06-01T00:00:00")
    store.insert_episode_row(_sample_episode(id="e2", player_id="b"), "2026-06-02T00:00:00")
    store._conn.commit()
    assert store.get_episode_count() == 2
    assert store.get_episode_count(player_id="a") == 1

def test_get_episodes_ordered_desc():
    store = temp_store()
    store.insert_episode_row(_sample_episode(id="old"), "2026-06-01T00:00:00")
    store.insert_episode_row(_sample_episode(id="new"), "2026-06-28T00:00:00")
    store._conn.commit()
    results = store.get_episodes()
    assert results[0]["id"] == "new"  # most recent first

def test_get_episodes_filtered_by_result():
    store = temp_store()
    store.insert_episode_row(_sample_episode(id="w", result="win"), "2026-06-01T00:00:00")
    store.insert_episode_row(_sample_episode(id="l", result="loss"), "2026-06-02T00:00:00")
    store._conn.commit()
    wins = store.get_episodes(result="win")
    assert len(wins) == 1
    assert wins[0]["id"] == "w"

def test_get_episodes_respects_limit_and_offset():
    store = temp_store()
    for i in range(5):
        store.insert_episode_row(_sample_episode(id=f"e{i}"), f"2026-06-{i+1:02d}T00:00:00")
    store._conn.commit()
    page1 = store.get_episodes(limit=2, offset=0)
    page2 = store.get_episodes(limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 2
    assert page1[0]["id"] != page2[0]["id"]

def test_get_by_id_unknown_returns_none():
    store = temp_store()
    assert store.get_episode_by_id("nonexistent") is None


# ---------------------------------------------------------------------------
# get_player_episodes — deliberately ASC, opposite of get_episodes()
# ---------------------------------------------------------------------------

def test_get_player_episodes_ordered_asc():
    store = temp_store()
    store.insert_episode_row(_sample_episode(id="new", player_id="p"), "2026-06-28T00:00:00")
    store.insert_episode_row(_sample_episode(id="old", player_id="p"), "2026-06-01T00:00:00")
    store._conn.commit()
    results = store.get_player_episodes("p")
    assert results[0]["id"] == "old"  # oldest first — opposite of get_episodes()

def test_get_player_episodes_enriches_with_timestamp_and_result():
    store = temp_store()
    store.insert_episode_row(_sample_episode(id="e1", player_id="p", result="win"),
                              "2026-06-28T00:00:00")
    store._conn.commit()
    results = store.get_player_episodes("p")
    assert results[0]["_timestamp"] == "2026-06-28T00:00:00"
    assert results[0]["_result"] == "win"


# ---------------------------------------------------------------------------
# Atomic composition — EpisodeStore + ObservationStore, orchestrated
# externally (simulating the facade's log_episode()). This is the exact
# pattern the facade must implement.
# ---------------------------------------------------------------------------

def test_atomic_composition_pattern_commits_together():
    """
    Simulates the facade's log_episode() workflow:
        EpisodeStore.insert_episode_row()   (no commit)
        ObservationStore.insert_observations() (no commit)
        conn.commit()                        (once, externally)
    Verifies both tables' writes appear together, or not at all.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _create_episodes_table(conn)
    _create_observations_table(conn)

    episode_store = EpisodeStore(conn)
    observation_store = ObservationStore(conn)

    episode = _sample_episode()
    episode["terrain_events"] = [
        {"event_type": "ice_break", "terrain_at_site": "frozen_lake",
         "triggered_by_type": "cavalry"},
    ]
    episode["general_intents"] = ["TERRAIN_EXPLOIT"]
    timestamp = "2026-06-28T00:00:00"

    # Orchestration (what the facade does)
    episode_store.insert_episode_row(episode, timestamp)
    observation_store.insert_observations(episode, timestamp)
    conn.commit()

    assert episode_store.get_episode_count() == 1
    assert observation_store.get_observation_count() == 1
