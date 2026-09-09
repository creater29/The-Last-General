"""
stage3_completion_exercise.py — Stage 3 Completion Multi-Player Exercise

Validates that PlayerProfiler and RelationshipManager accumulate
player-specific state and measurably influence DecisionEngine.decide()'s
output, using controlled synthetic archetypes run through the real
production pipeline (BattleLoop -> DecisionEngine -> feedback), against a
dedicated exercise database that is never the production database.

Design approved across a multi-round review (see state/PROGRESS.md,
Stage 3 Completion section, and state/SESSION_HANDOFF.md, 2026-09-04).

Phase A — deterministic doctrine bootstrap (generate_corpus.run() with a
          fixed seed, against the exercise DB only)
Phase B — 18 measured battles: 3 cohorts x 6 battles each
          (Aggressor, Mixed/Neutral, Terrain-exposure)

Isolation: the production DB's SHA-256 checksum is verified unchanged
before and after this entire script runs.
"""
from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from itertools import cycle
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import generate_corpus
from simulator.grid import Grid
from simulator.units import UnitType, make_unit
from simulator.battle import BattleLoop, PlayerIntent, GeneralIntent
from simulator.logger import EpisodeLogger, DEFAULT_DB_PATH
from brain.world_model import WorldModel
from brain.doctrine_extractor import DoctrineExtractor
from brain.player_profiler import PlayerProfiler
from brain.relationship_manager import RelationshipManager, RelationshipState
from brain.decision_engine import DecisionEngine, _player_factor, _relationship_factor
from simulator.snapshot import CommanderKnowledge


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BOOTSTRAP_SEED   = 20260904
BOOTSTRAP_MAX_BATTLES = 600
EXERCISE_DB_PATH = ROOT / "data" / "exercises" / "stage3_completion_2026-09-04.db"
SERVER_ID        = "stage3_exercise"

AGGRESSOR_PLAYER_ID = "exercise_aggressor"
MIXED_PLAYER_ID     = "exercise_mixed"
TERRAIN_PLAYER_ID   = "exercise_terrain"
DRAW_CONTROL_PLAYER_ID = "exercise_control_draw"

PILOT_CANDIDATE_BASE_SEEDS = [1, 2, 3, 4, 5]   # bounded search range
MIXED_BASE_SEED   = 1
TERRAIN_BASE_SEED = 1
LOW_TRUST_THRESHOLD = -0.2

ALL_PLAYER_INTENTS = [
    PlayerIntent.ATTACK_CENTER, PlayerIntent.ATTACK_FLANK,
    PlayerIntent.DEFEND, PlayerIntent.RETREAT,
    PlayerIntent.SIEGE, PlayerIntent.SUPPLY_PROTECT,
    PlayerIntent.AGGRESSIVE_RUSH,
]


def log(msg=""):
    print(msg, flush=True)


def sha256_of(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Phase A — deterministic doctrine bootstrap
# ---------------------------------------------------------------------------

def run_phase_a() -> dict:
    log("=" * 70)
    log("PHASE A — Deterministic doctrine bootstrap")
    log("=" * 70)

    EXERCISE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if EXERCISE_DB_PATH.exists():
        EXERCISE_DB_PATH.unlink()

    log(f"Exercise DB   : {EXERCISE_DB_PATH}")
    log(f"Bootstrap seed: {BOOTSTRAP_SEED}")
    log(f"Max battles   : {BOOTSTRAP_MAX_BATTLES}")
    log("")

    bootstrap_error = None
    try:
        generate_corpus.run(
            profile_name="balanced",
            max_battles=BOOTSTRAP_MAX_BATTLES,
            report_every=BOOTSTRAP_MAX_BATTLES + 1,
            db_path=EXERCISE_DB_PATH,
            seed=BOOTSTRAP_SEED,
        )
    except Exception as e:
        bootstrap_error = repr(e)

    logger = EpisodeLogger(db_path=EXERCISE_DB_PATH)
    wm     = WorldModel(logger)
    de     = DoctrineExtractor(logger, wm)

    updated   = wm.update_from_observations()
    promoted  = de.extract_doctrines()
    summary   = de.doctrine_summary()
    episode_count = logger.get_episode_count()

    log(f"Bootstrap completed without exceptions: {bootstrap_error is None}")
    if bootstrap_error:
        log(f"  ERROR: {bootstrap_error}")
    log(f"Episodes in exercise DB: {episode_count}")
    log(f"Beliefs updated:         {updated}")
    log(f"Doctrines promoted:      {promoted}")
    log(f"Doctrine summary:        {summary}")
    logger.close()

    return {
        "bootstrap_error":  bootstrap_error,
        "episode_count":    episode_count,
        "doctrine_summary": summary,
        "bootstrap_seed":   BOOTSTRAP_SEED,
        "max_battles":      BOOTSTRAP_MAX_BATTLES,
    }


# ---------------------------------------------------------------------------
# Battle runner — one battle, full lifecycle
# ---------------------------------------------------------------------------

def make_stack(db_path: Path):
    logger = EpisodeLogger(db_path=db_path)
    wm     = WorldModel(logger)
    de     = DoctrineExtractor(logger, wm)
    pp     = PlayerProfiler(logger)
    rm     = RelationshipManager(logger)
    engine = DecisionEngine(logger, wm, de, pp, relationship_manager=rm)
    return logger, wm, de, pp, rm, engine


def run_one_battle(engine, player_id, seed, grid_dims=(100, 100),
                    player_intent_fn=None, server_id=SERVER_ID):
    """Run a single battle with the General driven by the real
    DecisionEngine.decide(), collect this battle's own turn_decisions
    (not accumulated across battles), return (state, turn_decisions,
    pipeline_error)."""
    gw, gh = grid_dims
    grid = Grid(gw, gh, seed=seed)
    general_units = [make_unit(UnitType.INFANTRY, "general", (gw // 2, int(gh * 0.75))) for _ in range(5)] + \
                    [make_unit(UnitType.CAVALRY,  "general", (gw // 2, int(gh * 0.75))) for _ in range(2)]
    player_units  = [make_unit(UnitType.INFANTRY, player_id, (gw // 2, int(gh * 0.25))) for _ in range(5)] + \
                    [make_unit(UnitType.CAVALRY,  player_id, (gw // 2, int(gh * 0.25))) for _ in range(2)]
    loop = BattleLoop(grid=grid, general_units=general_units, player_units=player_units,
                       player_id=player_id, age=1, seed=seed)

    turn_decisions = []
    pipeline_error = None

    def brain_fn(state, loop=loop):
        nonlocal pipeline_error
        try:
            knowledge = loop.to_brain_snapshot(server_id, player_id)
            decision  = engine.decide(knowledge)
            turn_decisions.append(decision)
            return GeneralIntent(decision["intent"].lower())
        except Exception as e:
            pipeline_error = repr(e)
            return GeneralIntent.DEFENSIVE_HOLD

    state = loop.run(general_intent_fn=brain_fn, player_intent_fn=player_intent_fn)
    return state, turn_decisions, pipeline_error


def run_cohort_sequence(engine, pp, rm, logger, player_id, seeds,
                         grid_dims=(100, 100), player_intent_fn=None,
                         server_id=SERVER_ID):
    """Run len(seeds) sequential battles for one archetype, full lifecycle
    (log_episode -> update_profile -> update_after_battle ->
    record_battle_outcome) between every battle. Returns per-battle
    results and any pipeline errors encountered."""
    results = []
    pipeline_errors = []
    total_feedback_increments = 0
    for seed in seeds:
        state, turn_decisions, pipeline_error = run_one_battle(
            engine, player_id, seed, grid_dims=grid_dims,
            player_intent_fn=player_intent_fn, server_id=server_id,
        )
        if pipeline_error:
            pipeline_errors.append((seed, pipeline_error))

        logger.log_episode(state)
        pp.update_profile(server_id, player_id)
        rm.update_after_battle(server_id, player_id, state.result)
        total_feedback_increments += engine.record_battle_outcome(state.result, turn_decisions)

        results.append(state.result)

    return results, pipeline_errors, total_feedback_increments


# ---------------------------------------------------------------------------
# Bounded pilot search — find a 6-battle Aggressor schedule reaching
# trust < LOW_TRUST_THRESHOLD, against a PRIMED (post-bootstrap) DB copy.
# Pilot attempts are discarded, never counted among the 18 measured battles.
# ---------------------------------------------------------------------------

def run_pilot_search():
    log("\n" + "=" * 70)
    log("BOUNDED PILOT SEARCH — Aggressor low-trust schedule")
    log("=" * 70)

    attempts = []
    selected_schedule = None
    selected_trust    = None

    for base_seed in PILOT_CANDIDATE_BASE_SEEDS:
        pilot_path = Path(tempfile.mktemp(suffix=".db"))
        shutil.copy2(EXERCISE_DB_PATH, pilot_path)
        logger, wm, de, pp, rm, engine = make_stack(pilot_path)

        seeds = [base_seed * 100 + i for i in range(6)]

        def aggressive_fn(state):
            return PlayerIntent.AGGRESSIVE_RUSH

        results, pipeline_errors, _increments = run_cohort_sequence(
            engine, pp, rm, logger, "pilot_aggressor", seeds,
            player_intent_fn=aggressive_fn,
        )
        rel = rm.get_state(SERVER_ID, "pilot_aggressor")
        trust = rel.trust_level
        logger.close()
        pilot_path.unlink()

        attempts.append({
            "base_seed": base_seed, "seeds": seeds,
            "results": results, "trust": trust,
            "pipeline_errors": pipeline_errors,
        })
        log(f"  base_seed={base_seed}: {results}  trust={trust:.4f}"
            f"  (need < {LOW_TRUST_THRESHOLD})")

        if trust < LOW_TRUST_THRESHOLD and selected_schedule is None:
            selected_schedule = seeds
            selected_trust    = trust

    if selected_schedule is None:
        log("\n  NO candidate schedule reached low trust within the "
            "bounded search range. Aggressor cohort is INCONCLUSIVE.")
    else:
        log(f"\n  Selected schedule: {selected_schedule}  (trust={selected_trust:.4f})")

    return {
        "candidates_tested": attempts,
        "selected_schedule": selected_schedule,
        "selected_trust":    selected_trust,
    }


# ---------------------------------------------------------------------------
# Isolation check
# ---------------------------------------------------------------------------

def run_draw_control(exercise_db_path: Path) -> dict:
    """Component-level control: a single, isolated 'draw' outcome applied
    to a fresh RelationshipState (never-met opponent), checked before and
    after. Always run, regardless of whether a live draw occurs in the
    18 measured battles — a naturally-occurring draw is supplementary
    evidence only, not a substitute for this control."""
    logger, wm, de, pp, rm, _engine = make_stack(exercise_db_path)
    before = rm.get_state(SERVER_ID, DRAW_CONTROL_PLAYER_ID)
    rm.update_after_battle(SERVER_ID, DRAW_CONTROL_PLAYER_ID, "draw")
    after = rm.get_state(SERVER_ID, DRAW_CONTROL_PLAYER_ID)
    logger.close()
    return {
        "trust_before": before.trust_level, "encounters_before": before.encounters,
        "trust_after":  after.trust_level,  "encounters_after":  after.encounters,
    }


def controlled_factor_comparison(exercise_db_path: Path, aggressor_player_id: str):
    """Same fixed CommanderKnowledge snapshot, run through _player_factor()
    and _relationship_factor() twice: once cold (no profile/relationship
    history) and once with the actual accumulated Aggressor cohort state.
    Labeled controlled factor evidence - isolates the factor's effect from
    weather/doctrine/terrain variation that live battle traces carry."""
    logger, wm, de, pp, rm, _engine = make_stack(exercise_db_path)

    snapshot_kwargs = dict(
        server_id=SERVER_ID, player_id=aggressor_player_id, turn=5,
        weather="clear", battlefield_features={}, known_enemy_presence={},
        known_friendly_state={}, visible_terrain=[], visible_events=[],
        known_enemy_composition=None,
    )
    knowledge = CommanderKnowledge(**snapshot_kwargs)

    cold_profile  = None
    cold_rel      = RelationshipState(
        trust_level=0.0, betrayal_count=0, cooperation_count=0,
        times_attempted_capture=0, known_deceptions=0, encounters=0,
    )

    real_profile = pp.get_profile(SERVER_ID, aggressor_player_id)
    real_rel     = rm.get_state(SERVER_ID, aggressor_player_id)

    results = {}
    for intent in ["DEFENSIVE_HOLD", "AGGRESSIVE_PUSH"]:
        cold_pf, cold_pn = _player_factor(intent, cold_profile, knowledge)
        cold_rf, cold_rn = _relationship_factor(intent, cold_rel)
        real_pf, real_pn = _player_factor(intent, real_profile, knowledge)
        real_rf, real_rn = _relationship_factor(intent, real_rel)
        results[intent] = {
            "cold_player_factor": cold_pf, "cold_player_notes": cold_pn,
            "real_player_factor": real_pf, "real_player_notes": real_pn,
            "cold_relationship_factor": cold_rf, "cold_relationship_notes": cold_rn,
            "real_relationship_factor": real_rf, "real_relationship_notes": real_rn,
        }

    logger.close()
    return results


if __name__ == "__main__":
    exercise_start = datetime.now(timezone.utc).isoformat()
    prod_hash_before = sha256_of(DEFAULT_DB_PATH)
    log(f"Production DB SHA-256 (before): {prod_hash_before}")

    phase_a_result = run_phase_a()
    if phase_a_result["bootstrap_error"] is not None:
        raise RuntimeError(
            f"PHASE A BOOTSTRAP FAILED: {phase_a_result['bootstrap_error']}"
        )
    if phase_a_result["doctrine_summary"]["total_doctrines"] == 0:
        raise RuntimeError(
            "PHASE A BOOTSTRAP PRODUCED NO DOCTRINES — cannot proceed to "
            "Phase B; the exercise requires a primed, consultable DB."
        )

    pilot_result = run_pilot_search()

    log("\n" + "=" * 70)
    log("PHASE B — 18 measured battles")
    log("=" * 70)

    logger, wm, de, pp, rm, engine = make_stack(EXERCISE_DB_PATH)
    doctrines_before_b = {d["id"]: d["failure_count"] for d in de.get_doctrines()}

    phase_b = {}
    all_pipeline_errors = []
    total_feedback_increments = 0

    # --- Aggressor ---
    if pilot_result["selected_schedule"] is None:
        log("\nAggressor cohort: INCONCLUSIVE (no pilot schedule reached low trust)")
        phase_b["aggressor"] = {"status": "inconclusive"}
    else:
        def aggressive_fn(state):
            return PlayerIntent.AGGRESSIVE_RUSH
        results, errs, incr = run_cohort_sequence(
            engine, pp, rm, logger, AGGRESSOR_PLAYER_ID,
            pilot_result["selected_schedule"], player_intent_fn=aggressive_fn,
        )
        all_pipeline_errors.extend(errs)
        total_feedback_increments += incr
        rel = rm.get_state(SERVER_ID, AGGRESSOR_PLAYER_ID)
        prof = pp.get_profile(SERVER_ID, AGGRESSOR_PLAYER_ID)
        log(f"Aggressor:  {results}  trust={rel.trust_level:.4f}  "
            f"aggression_idx={prof.get('aggression_index')}  errors={errs}  "
            f"feedback_increments={incr}")
        phase_b["aggressor"] = {
            "status": "measured", "seeds": pilot_result["selected_schedule"],
            "results": results, "pipeline_errors": errs,
            "trust": rel.trust_level, "encounters": rel.encounters,
            "profile": prof, "feedback_increments": incr,
        }

    # --- Mixed / Neutral ---
    intent_cycle = cycle(ALL_PLAYER_INTENTS)
    def mixed_fn(state):
        return next(intent_cycle)
    mixed_seeds = [MIXED_BASE_SEED * 100 + i for i in range(6)]
    results, errs, incr = run_cohort_sequence(
        engine, pp, rm, logger, MIXED_PLAYER_ID, mixed_seeds, player_intent_fn=mixed_fn,
    )
    all_pipeline_errors.extend(errs)
    total_feedback_increments += incr
    rel = rm.get_state(SERVER_ID, MIXED_PLAYER_ID)
    prof = pp.get_profile(SERVER_ID, MIXED_PLAYER_ID)
    log(f"Mixed:      {results}  trust={rel.trust_level:.4f}  "
        f"aggression_idx={prof.get('aggression_index')}  errors={errs}  "
        f"feedback_increments={incr}")
    phase_b["mixed"] = {
        "status": "measured", "seeds": mixed_seeds, "results": results,
        "pipeline_errors": errs, "trust": rel.trust_level,
        "profile": prof, "feedback_increments": incr,
    }

    # --- Terrain-exposure ---
    terrain_seeds = [TERRAIN_BASE_SEED * 100 + i for i in range(6)]
    results, errs, incr = run_cohort_sequence(
        engine, pp, rm, logger, TERRAIN_PLAYER_ID, terrain_seeds,
        grid_dims=(40, 40), player_intent_fn=None,
    )
    all_pipeline_errors.extend(errs)
    total_feedback_increments += incr
    rel = rm.get_state(SERVER_ID, TERRAIN_PLAYER_ID)
    prof = pp.get_profile(SERVER_ID, TERRAIN_PLAYER_ID)
    log(f"Terrain:    {results}  trust={rel.trust_level:.4f}  "
        f"terrain_tendencies={prof.get('terrain_tendencies')}  errors={errs}  "
        f"feedback_increments={incr}")
    phase_b["terrain"] = {
        "status": "measured", "seeds": terrain_seeds, "results": results,
        "pipeline_errors": errs, "profile": prof, "feedback_increments": incr,
    }

    if all_pipeline_errors:
        raise RuntimeError(
            f"PHASE B PIPELINE ERRORS DETECTED (decide() raised): "
            f"{all_pipeline_errors}"
        )

    # --- Doctrine feedback loop verification: assert real failure_count
    # increments, not just that the doctrine table's shape stayed intact ---
    doctrines_after_b = {d["id"]: d["failure_count"] for d in de.get_doctrines()}
    all_doc_ids = set(doctrines_before_b) | set(doctrines_after_b)
    actual_failure_delta = sum(
        doctrines_after_b.get(d, 0) - doctrines_before_b.get(d, 0)
        for d in all_doc_ids
    )
    log(f"\nDoctrine failure_count deltas: "
        f"{ {d: doctrines_after_b.get(d,0) - doctrines_before_b.get(d,0) for d in all_doc_ids if doctrines_after_b.get(d,0) != doctrines_before_b.get(d,0)} }")
    log(f"Sum of failure_count deltas:        {actual_failure_delta}")
    log(f"Sum of record_battle_outcome() returns: {total_feedback_increments}")
    if actual_failure_delta != total_feedback_increments:
        raise RuntimeError(
            f"DOCTRINE FEEDBACK MISMATCH: record_battle_outcome() reported "
            f"{total_feedback_increments} increments applied, but the "
            f"doctrine table's failure_count only changed by "
            f"{actual_failure_delta}. The feedback loop is not behaving as "
            f"claimed."
        )
    if total_feedback_increments == 0:
        log("\n  WARNING: 0 doctrine feedback increments were applied across "
            "all 18 battles. Doctrine feedback loop presence cannot be "
            "confirmed by this run (informational, not a hard failure — "
            "0 increments is possible if no loss battle ever consulted a "
            "doctrine, though unlikely given the primed DB).")
    else:
        log(f"  CONFIRMED: {total_feedback_increments} real failure_count "
            f"increments applied and verified against the doctrine table "
            f"directly, not merely inferred from table shape.")

    doctrine_summary_after_b = de.doctrine_summary()
    logger.close()


    # --- Draw control (always run) ---
    log("\n" + "=" * 70)
    log("DRAW CONTROL (component-level)")
    log("=" * 70)
    draw_control = run_draw_control(EXERCISE_DB_PATH)
    log(str(draw_control))

    # --- Controlled factor comparison ---
    log("\n" + "=" * 70)
    log("CONTROLLED FACTOR COMPARISON (cold vs. accumulated Aggressor state)")
    log("=" * 70)
    if phase_b["aggressor"]["status"] == "measured":
        factor_comparison = controlled_factor_comparison(EXERCISE_DB_PATH, AGGRESSOR_PLAYER_ID)
        for intent, data in factor_comparison.items():
            log(f"\n  Intent: {intent}")
            log(f"    cold  player_factor={data['cold_player_factor']}  notes={data['cold_player_notes']}")
            log(f"    real  player_factor={data['real_player_factor']}  notes={data['real_player_notes']}")
            log(f"    cold  relationship_factor={data['cold_relationship_factor']}  notes={data['cold_relationship_notes']}")
            log(f"    real  relationship_factor={data['real_relationship_factor']}  notes={data['real_relationship_notes']}")
    else:
        factor_comparison = None
        log("  Skipped — Aggressor cohort inconclusive.")

    # --- Terrain-specific controlled check (post-W012-fix) ---
    log("\n" + "=" * 70)
    log("TERRAIN FACTOR CHECK (post-W012-fix, player-perspective win/loss)")
    log("=" * 70)
    t_logger, t_wm, t_de, t_pp, t_rm, _t_engine = make_stack(EXERCISE_DB_PATH)
    terrain_profile = t_pp.get_profile(SERVER_ID, TERRAIN_PLAYER_ID)
    log(f"terrain_tendencies (player-perspective): {terrain_profile.get('terrain_tendencies')}")
    k_river = CommanderKnowledge(
        server_id=SERVER_ID, player_id=TERRAIN_PLAYER_ID, turn=5, weather="clear",
        battlefield_features={}, known_enemy_presence={}, known_friendly_state={},
        visible_terrain=["river"], visible_events=[], known_enemy_composition=None,
    )
    k_none = CommanderKnowledge(
        server_id=SERVER_ID, player_id=TERRAIN_PLAYER_ID, turn=5, weather="clear",
        battlefield_features={}, known_enemy_presence={}, known_friendly_state={},
        visible_terrain=[], visible_events=[], known_enemy_composition=None,
    )
    terrain_factor_river, terrain_notes_river = _player_factor(
        "TERRAIN_EXPLOIT", terrain_profile, k_river
    )
    terrain_factor_none, terrain_notes_none = _player_factor(
        "TERRAIN_EXPLOIT", terrain_profile, k_none
    )
    log(f"TERRAIN_EXPLOIT factor (river visible):    {terrain_factor_river}  notes={terrain_notes_river}")
    log(f"TERRAIN_EXPLOIT factor (no relevant terrain): {terrain_factor_none}  notes={terrain_notes_none}")
    t_logger.close()

    # --- Isolation check ---
    prod_hash_after = sha256_of(DEFAULT_DB_PATH)
    log(f"\nProduction DB SHA-256 (after):  {prod_hash_after}")
    isolation_ok = prod_hash_before == prod_hash_after
    log(f"Production DB unchanged: {isolation_ok}")
    assert isolation_ok, "PRODUCTION DB WAS MODIFIED DURING THE EXERCISE"

    log("\n" + "=" * 70)
    log("EXERCISE COMPLETE")
    log("=" * 70)
