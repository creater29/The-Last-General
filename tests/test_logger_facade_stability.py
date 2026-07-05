"""
Facade stability test for EpisodeLogger (Candidate D — Artifact 3).

Captures the exact public method signature list of EpisodeLogger as it
existed BEFORE the repository split began (2026-06-28, pre-Phase-1 baseline).
Every phase of the store extraction (D014) must keep this test green — it is
the concrete verification that "LoggerFacade contract" promise, not just a
documented intention.

If this test fails after a phase, either:
  (a) a public method's signature changed unintentionally — fix it, or
  (b) a public method was intentionally added/removed/changed — update this
      baseline explicitly, in the same commit, with a clear reason in the
      commit message. Never let this drift silently.
"""

from __future__ import annotations

import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from simulator.logger import EpisodeLogger


# Captured 2026-06-28, before Phase 1 (RelationshipStore) extraction began.
BASELINE_SIGNATURES = {
    "close": "(self) -> 'None'",
    "get_all_doctrines": "(self) -> 'List[Dict[str, Any]]'",
    "get_all_player_profiles": "(self, server_id: 'Optional[str]' = None) -> 'List[Dict[str, Any]]'",
    "get_all_terrain_knowledge": "(self) -> 'List[Dict[str, Any]]'",
    "get_doctrine_by_id": "(self, doctrine_id: 'str') -> 'Optional[Dict[str, Any]]'",
    "get_episode_by_id": "(self, episode_id: 'str') -> 'Optional[dict]'",
    "get_episode_count": "(self, player_id: 'Optional[str]' = None) -> 'int'",
    "get_episodes": "(self, player_id: 'Optional[str]' = None, result: 'Optional[str]' = None, limit: 'int' = 100, offset: 'int' = 0) -> 'List[dict]'",
    "get_episodes_by_terrain_event": "(self, event_type: 'str', limit: 'int' = 50) -> 'List[dict]'",
    "get_known_players": "(self) -> 'List[str]'",
    "get_observation_count": "(self) -> 'int'",
    "get_observation_patterns": "(self, min_count: 'int' = 5) -> 'List[dict]'",
    "get_observations_by_terrain": "(self, terrain_context: 'str', limit: 'int' = 100) -> 'List[dict]'",
    "get_player_episodes": "(self, player_id: 'str') -> 'List[Dict[str, Any]]'",
    "get_player_profile": "(self, server_id: 'str', player_id: 'str') -> 'Optional[Dict[str, Any]]'",
    "get_relationship": "(self, server_id: 'str', player_id: 'str') -> 'Optional[dict]'",
    "get_terrain_knowledge": "(self, terrain_type: 'str', action_type: 'str') -> 'Optional[Dict[str, Any]]'",
    "increment_doctrine_failure": "(self, doctrine_id: 'str') -> 'bool'",
    "init_db": "(self) -> 'None'",
    "log_episode": "(self, state: 'BattleState') -> 'str'",
    "migrate_player_profiles": "(self) -> 'None'",
    "migrate_relationship_schema": "(self) -> 'None'",
    "result_distribution": "(self) -> 'dict'",
    "summary": "(self) -> 'dict'",
    "terrain_event_frequency": "(self) -> 'dict'",
    "upsert_doctrine": "(self, doctrine_id: 'str', abstraction_level: 'str', condition: 'str', learned_effect: 'str', confidence: 'float', episode_count: 'int', derived_principle: 'str', last_verified: 'str', decay_rate: 'float' = 0.005) -> 'None'",
    "upsert_player_profile": "(self, server_id: 'str', player_id: 'str', first_seen: 'str', last_seen: 'str', total_battles: 'int', win_count: 'int', loss_count: 'int', draw_count: 'int', preferred_units: 'dict', terrain_tendencies: 'dict', aggression_index: 'float', adaptability_score: 'float', raw_data: 'dict') -> 'None'",
    "upsert_relationship": "(self, server_id: 'str', player_id: 'str', data: 'dict') -> 'None'",
    "upsert_terrain_knowledge": "(self, terrain_type: 'str', action_type: 'str', observed_outcomes: 'List[str]', confidence: 'float', episode_count: 'int') -> 'None'",
}


def _current_public_signatures() -> dict[str, str]:
    sigs = {}
    for name, method in inspect.getmembers(EpisodeLogger, predicate=inspect.isfunction):
        if not name.startswith("_"):
            sigs[name] = str(inspect.signature(method))
    return sigs


def test_facade_public_method_names_unchanged():
    """No public method has been added or removed since the baseline."""
    current = set(_current_public_signatures().keys())
    baseline = set(BASELINE_SIGNATURES.keys())
    missing = baseline - current
    added = current - baseline
    assert not missing, f"Public methods removed from EpisodeLogger: {missing}"
    assert not added, (
        f"Public methods added to EpisodeLogger: {added}. "
        f"If intentional, update BASELINE_SIGNATURES explicitly with a reason."
    )


def test_facade_public_method_signatures_unchanged():
    """Every public method's signature is byte-identical to the pre-split baseline."""
    current = _current_public_signatures()
    mismatches = []
    for name, baseline_sig in BASELINE_SIGNATURES.items():
        current_sig = current.get(name)
        if current_sig != baseline_sig:
            mismatches.append(f"{name}: baseline={baseline_sig!r} current={current_sig!r}")
    assert not mismatches, "Signature drift detected:\n" + "\n".join(mismatches)
