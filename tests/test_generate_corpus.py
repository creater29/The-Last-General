"""
test_generate_corpus.py — Focused coverage for generate_corpus.run()'s
seeded reproducibility (Stage 3 completion exercise prerequisite,
2026-09-04).

Does not test the full corpus-generation feature set (targets, profiles,
CLI) — only the narrow addition: seed=None preserves today's unseeded
behavior, seed=<int> makes generation fully deterministic. This is a
backward-compatible extension to an existing production script, not a
rewrite - full corpus semantics are exercised in production use, not here.
"""
import sys
import tempfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import generate_corpus
from simulator.logger import EpisodeLogger


def _run_small(seed, max_battles=5):
    """Run a tiny, fast corpus generation into a fresh temp DB, using a
    profile with no TARGET_COUNTS so max_battles is the only stopping
    condition - keeps the test fast and deterministic regardless of
    whatever specific targets a profile defines."""
    tmp = tempfile.mktemp(suffix=".db")
    generate_corpus.run(
        profile_name="natural",
        max_battles=max_battles,
        report_every=max_battles + 1,  # suppress progress printing
        db_path=Path(tmp),
        seed=seed,
    )
    logger = EpisodeLogger(db_path=Path(tmp))
    count = logger.get_episode_count()
    freq  = logger.terrain_event_frequency()
    logger.close()
    return count, freq


def test_seeded_generation_is_reproducible():
    """Same seed, two separate runs into two separate DBs -> identical
    episode count and identical terrain event frequency distribution."""
    count_a, freq_a = _run_small(seed=20260904)
    count_b, freq_b = _run_small(seed=20260904)
    assert count_a == count_b
    assert freq_a == freq_b


def test_different_seeds_produce_different_generation():
    """Sanity check: seed actually affects generation, not silently
    ignored. Different seeds should produce a different terrain event
    frequency distribution (battles, and therefore terrain outcomes,
    differ)."""
    _, freq_a = _run_small(seed=1)
    _, freq_b = _run_small(seed=2)
    assert freq_a != freq_b


def test_none_seed_preserves_default_unseeded_behavior():
    """seed=None (the default) must not raise and must behave like the
    pre-existing unseeded path - random.Random(None) is valid and
    equivalent to random.Random(). This is a regression guard: the
    default parameter value must remain None, not silently change."""
    count, freq = _run_small(seed=None, max_battles=3)
    assert count == 3
    assert isinstance(freq, dict)
