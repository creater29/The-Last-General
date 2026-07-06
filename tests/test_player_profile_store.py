"""
Tests for PlayerProfileStore (Candidate D, D014, Phase 2).

Includes a Repository Independence test: PlayerProfileStore must be
constructable and fully usable with nothing but a raw sqlite3.Connection —
no EpisodeLogger, no other store, no facade of any kind.
"""

from __future__ import annotations

import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from simulator.stores.player_profile_store import PlayerProfileStore


def temp_store() -> PlayerProfileStore:
    """Repository Independence: raw connection only, no other imports."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = PlayerProfileStore(conn)
    store.migrate_player_profiles()
    return store


SERVER  = "test_server"
SERVER2 = "other_server"
PLAYER  = "arman"


def _profile_kwargs(**overrides):
    base = dict(
        server_id=SERVER, player_id=PLAYER,
        first_seen="2026-01-01T00:00:00", last_seen="2026-01-01T00:00:00",
        total_battles=1, win_count=1, loss_count=0, draw_count=0,
        preferred_units={"cavalry": 3}, terrain_tendencies={"forest": 0.7},
        aggression_index=0.6, adaptability_score=0.5, raw_data={},
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Repository Independence
# ---------------------------------------------------------------------------

def test_repository_independence_no_other_imports_needed():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = PlayerProfileStore(conn)
    store.migrate_player_profiles()
    store.upsert_player_profile(**_profile_kwargs())
    result = store.get_player_profile(SERVER, PLAYER)
    assert result["total_battles"] == 1
    assert result["preferred_units"] == {"cavalry": 3}


# ---------------------------------------------------------------------------
# upsert / get
# ---------------------------------------------------------------------------

def test_upsert_new_profile():
    store = temp_store()
    store.upsert_player_profile(**_profile_kwargs())
    result = store.get_player_profile(SERVER, PLAYER)
    assert result is not None
    assert result["win_count"] == 1
    assert result["terrain_tendencies"] == {"forest": 0.7}

def test_upsert_overwrites_on_conflict():
    store = temp_store()
    store.upsert_player_profile(**_profile_kwargs(total_battles=1, win_count=1))
    store.upsert_player_profile(**_profile_kwargs(total_battles=5, win_count=3))
    result = store.get_player_profile(SERVER, PLAYER)
    assert result["total_battles"] == 5
    assert result["win_count"] == 3

def test_get_unknown_profile_returns_none():
    store = temp_store()
    assert store.get_player_profile(SERVER, "nobody") is None

def test_server_isolation():
    store = temp_store()
    store.upsert_player_profile(**_profile_kwargs(server_id=SERVER,  win_count=10))
    store.upsert_player_profile(**_profile_kwargs(server_id=SERVER2, win_count=0))
    result_a = store.get_player_profile(SERVER, PLAYER)
    result_b = store.get_player_profile(SERVER2, PLAYER)
    assert result_a["win_count"] == 10
    assert result_b["win_count"] == 0

def test_json_fields_roundtrip():
    store = temp_store()
    store.upsert_player_profile(**_profile_kwargs(
        preferred_units={"archer": 2, "infantry": 5},
        raw_data={"note": "aggressive early game"},
    ))
    result = store.get_player_profile(SERVER, PLAYER)
    assert result["preferred_units"] == {"archer": 2, "infantry": 5}
    assert result["data"] == {"note": "aggressive early game"}


# ---------------------------------------------------------------------------
# get_all_player_profiles
# ---------------------------------------------------------------------------

def test_get_all_profiles_ordered_by_total_battles():
    store = temp_store()
    store.upsert_player_profile(**_profile_kwargs(player_id="low",  total_battles=2))
    store.upsert_player_profile(**_profile_kwargs(player_id="high", total_battles=50))
    all_profiles = store.get_all_player_profiles()
    assert all_profiles[0]["player_id"] == "high"
    assert all_profiles[1]["player_id"] == "low"

def test_get_all_profiles_filtered_by_server():
    store = temp_store()
    store.upsert_player_profile(**_profile_kwargs(server_id=SERVER,  player_id="a"))
    store.upsert_player_profile(**_profile_kwargs(server_id=SERVER2, player_id="b"))
    server_profiles = store.get_all_player_profiles(server_id=SERVER)
    assert len(server_profiles) == 1
    assert server_profiles[0]["player_id"] == "a"

def test_get_all_profiles_empty_db():
    store = temp_store()
    assert store.get_all_player_profiles() == []


# ---------------------------------------------------------------------------
# migrate_player_profiles
# ---------------------------------------------------------------------------

def test_migrate_creates_correct_schema():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = PlayerProfileStore(conn)
    store.migrate_player_profiles()
    cols = {row["name"] for row in conn.execute(
        "PRAGMA table_info(player_profiles)"
    ).fetchall()}
    assert "server_id" in cols
    assert "player_id" in cols
    assert "total_battles" in cols
