"""
Tests for DoctrineStore (Candidate D, D014, Phase 3).

Phase 3 is the first "behavior-critical" extraction — DoctrineStore sits
directly in DecisionEngine's read path. Tests here specifically verify the
behavioral subtleties found during the pre-extraction audit, not just CRUD.

Includes a Repository Independence test: DoctrineStore must be constructable
and fully usable with nothing but a raw sqlite3.Connection.
"""

from __future__ import annotations

import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from simulator.stores.doctrine_store import DoctrineStore


def _create_doctrines_table(conn: sqlite3.Connection) -> None:
    """
    Test-only schema setup, mirroring init_db()'s CREATE TABLE for doctrines
    exactly (copied from the live logger.py, not invented). DoctrineStore
    itself intentionally has no migrate_*_schema() method — initial schema
    creation is a DBManager/facade concern (see DEFERRED_ITEMS D014
    Artifact 1) — so standalone tests provide their own setup rather than
    inventing an unneeded method on the store just for test convenience.
    """
    conn.execute("""
        CREATE TABLE doctrines (
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
        )
    """)
    conn.commit()


def temp_store() -> DoctrineStore:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _create_doctrines_table(conn)
    return DoctrineStore(conn)


def _doctrine_kwargs(**overrides):
    base = dict(
        doctrine_id="doctrine_test_1",
        abstraction_level="terrain",
        condition="forest+cavalry",
        learned_effect="tree_fall",
        confidence=0.9,
        episode_count=50,
        derived_principle="Cavalry combat in forests may fell trees.",
        last_verified="2026-06-28T00:00:00",
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Repository Independence
# ---------------------------------------------------------------------------

def test_repository_independence_no_other_imports_needed():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _create_doctrines_table(conn)
    store = DoctrineStore(conn)
    store.upsert_doctrine(**_doctrine_kwargs())
    result = store.get_doctrine_by_id("doctrine_test_1")
    assert result["confidence"] == 0.9


# ---------------------------------------------------------------------------
# upsert / get — basic CRUD
# ---------------------------------------------------------------------------

def test_upsert_new_doctrine():
    store = temp_store()
    store.upsert_doctrine(**_doctrine_kwargs())
    result = store.get_doctrine_by_id("doctrine_test_1")
    assert result is not None
    assert result["confidence"] == 0.9
    assert result["failure_count"] == 0
    assert result["exceptions"] == []

def test_get_unknown_doctrine_returns_none():
    store = temp_store()
    assert store.get_doctrine_by_id("nonexistent") is None

def test_get_all_doctrines_ordered_by_confidence_desc():
    store = temp_store()
    store.upsert_doctrine(**_doctrine_kwargs(doctrine_id="low",  confidence=0.3))
    store.upsert_doctrine(**_doctrine_kwargs(doctrine_id="high", confidence=0.95))
    all_doctrines = store.get_all_doctrines()
    assert all_doctrines[0]["id"] == "high"
    assert all_doctrines[1]["id"] == "low"

def test_get_all_doctrines_empty_db():
    store = temp_store()
    assert store.get_all_doctrines() == []


# ---------------------------------------------------------------------------
# BEHAVIOR-CRITICAL: upsert_doctrine must NOT touch failure_count/exceptions
# on conflict — this is the single most important invariant from the audit.
# ---------------------------------------------------------------------------

def test_upsert_on_conflict_does_not_reset_failure_count():
    """
    A doctrine with accumulated failures must keep them after a
    re-extraction pass (upsert_doctrine called again with the same id).
    """
    store = temp_store()
    store.upsert_doctrine(**_doctrine_kwargs())
    store.increment_doctrine_failure("doctrine_test_1")
    store.increment_doctrine_failure("doctrine_test_1")
    before = store.get_doctrine_by_id("doctrine_test_1")
    assert before["failure_count"] == 2

    # Re-extraction: upsert again with updated confidence/episode_count
    store.upsert_doctrine(**_doctrine_kwargs(confidence=0.97, episode_count=75))
    after = store.get_doctrine_by_id("doctrine_test_1")
    assert after["confidence"] == 0.97       # updated
    assert after["episode_count"] == 75      # updated
    assert after["failure_count"] == 2       # PRESERVED — the critical invariant

def test_upsert_on_conflict_updates_only_specific_fields():
    """Confidence, episode_count, derived_principle, last_verified update.
    Everything else (failure_count, exceptions, decay_rate) does not."""
    store = temp_store()
    store.upsert_doctrine(**_doctrine_kwargs(decay_rate=0.005))
    store.increment_doctrine_failure("doctrine_test_1")  # bumps decay_rate

    mid = store.get_doctrine_by_id("doctrine_test_1")
    assert mid["decay_rate"] != 0.005  # confirm it actually changed

    store.upsert_doctrine(**_doctrine_kwargs(
        confidence=0.99, episode_count=200,
        derived_principle="Updated principle.",
        last_verified="2026-07-01T00:00:00",
        decay_rate=0.005,  # attempting to reset — should be ignored on conflict
    ))
    after = store.get_doctrine_by_id("doctrine_test_1")
    assert after["confidence"] == 0.99
    assert after["episode_count"] == 200
    assert after["derived_principle"] == "Updated principle."
    assert after["decay_rate"] == mid["decay_rate"]  # NOT reset to 0.005


# ---------------------------------------------------------------------------
# increment_doctrine_failure
# ---------------------------------------------------------------------------

def test_increment_failure_returns_true_when_found():
    store = temp_store()
    store.upsert_doctrine(**_doctrine_kwargs())
    assert store.increment_doctrine_failure("doctrine_test_1") is True

def test_increment_failure_returns_false_when_not_found():
    store = temp_store()
    assert store.increment_doctrine_failure("nonexistent") is False

def test_increment_failure_computes_decay_rate_correctly():
    """decay_rate = failure_count / (episode_count + failure_count)"""
    store = temp_store()
    store.upsert_doctrine(**_doctrine_kwargs(episode_count=90))
    store.increment_doctrine_failure("doctrine_test_1")  # failure_count: 0->1
    result = store.get_doctrine_by_id("doctrine_test_1")
    assert result["failure_count"] == 1
    # decay = 1 / (90 + 1) = 0.010989...
    assert result["decay_rate"] == pytest.approx(1 / 91, abs=1e-5)

def test_increment_failure_accumulates():
    store = temp_store()
    store.upsert_doctrine(**_doctrine_kwargs(episode_count=100))
    for _ in range(5):
        store.increment_doctrine_failure("doctrine_test_1")
    result = store.get_doctrine_by_id("doctrine_test_1")
    assert result["failure_count"] == 5
    assert result["decay_rate"] == pytest.approx(5 / 105, abs=1e-5)


# ---------------------------------------------------------------------------
# exceptions JSON roundtrip
# ---------------------------------------------------------------------------

def test_exceptions_defaults_to_empty_list():
    store = temp_store()
    store.upsert_doctrine(**_doctrine_kwargs())
    result = store.get_doctrine_by_id("doctrine_test_1")
    assert result["exceptions"] == []
