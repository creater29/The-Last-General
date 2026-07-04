#!/usr/bin/env python3
"""
run_integration_test.py — Stage 3 Candidate A: Live integration test.

Wires to_brain_snapshot() → DecisionEngine.decide() → GeneralIntent
in a real battle loop, proving the full pipeline composes correctly.

This is the first time the General actually plays:
  Simulator → Snapshot → Brain → Decision → Battle → Learning

Usage:
    python scripts/run_integration_test.py
    python scripts/run_integration_test.py --seed 99
    python scripts/run_integration_test.py --quiet

Success criteria (must ALL pass):
    [1] Pre-battle knowledge priming executed (WorldModel + DoctrineExtractor)
    [2] Doctrine influence detected (doctrines_consulted > 0 across battle)
    [3] Decision logged for every turn
    [4] All 8 intent strings → GeneralIntent enum mapping verified
    [5] Decision trace complete on all turns (reasoning field present)
    [6] Pipeline completed with 0 errors
    [7] Post-battle analysis pipeline executed successfully
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from simulator.battle import BattleLoop, GeneralIntent
from simulator.grid import Grid, TerrainType
from simulator.units import UnitType, make_unit
from simulator.logger import EpisodeLogger
from brain.world_model import WorldModel
from brain.doctrine_extractor import DoctrineExtractor
from brain.player_profiler import PlayerProfiler
from brain.decision_engine import DecisionEngine, ALL_INTENTS
from brain.relationship_manager import RelationshipManager


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SERVER_ID    = "integration_test_server"
PLAYER_ID    = "integration_test_player"
DEFAULT_SEED    = 42
FEEDBACK_SEED   = 9    # brain-driven loss — used for feedback loop verification
BATTLE_AGE   = 300   # The General is ancient
LINE         = "=" * 64


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------

def run(seed: int = DEFAULT_SEED, verbose: bool = True) -> bool:
    """
    Execute the full integration test.

    Returns True if all success criteria pass, False otherwise.
    Uses the production DB so actual corpus doctrines are available.
    A new episode is added to the DB as a side effect — this is intentional.
    """

    def log(msg: str = "") -> None:
        if verbose:
            print(msg)

    log(LINE)
    log("THE LAST GENERAL — LIVE INTEGRATION TEST")
    log(LINE)

    # -------------------------------------------------------------------
    # Step 1 — Instantiate brain components
    # -------------------------------------------------------------------
    logger = EpisodeLogger()          # production DB (DEFAULT_DB_PATH)
    wm     = WorldModel(logger)
    de     = DoctrineExtractor(logger, wm)
    pp     = PlayerProfiler(logger)
    rm     = RelationshipManager(logger)
    engine = DecisionEngine(logger, wm, de, pp, relationship_manager=rm)

    # -------------------------------------------------------------------
    # Step 2 — Pre-battle: prime the knowledge base from corpus
    # -------------------------------------------------------------------
    log("\n[PRE-BATTLE] Priming knowledge base from corpus...")

    beliefs_updated    = wm.update_from_observations()
    doctrines_upserted = de.extract_doctrines()
    all_doctrines      = de.get_doctrines()

    log(f"  update_from_observations() → {beliefs_updated} belief rows")
    log(f"  extract_doctrines()        → {doctrines_upserted} upserted, "
        f"{len(all_doctrines)} total")

    if all_doctrines:
        log("  Doctrine library:")
        for d in all_doctrines:
            log(f"    [{d['id']}]  conf={d['confidence']:.4f}  "
                f"\"{d['derived_principle']}\"")
    else:
        log("  WARNING: No doctrines found — decisions will score at "
            "neutral factor 1.0 (doctrine influence criterion will FAIL)")

    pre_battle_ok = True  # reached this point without exception

    # -------------------------------------------------------------------
    # Step 3 — Verify all 8 intent strings → GeneralIntent mapping
    # -------------------------------------------------------------------
    log(f"\n[SETUP] Verifying intent string → GeneralIntent mapping "
        f"({len(ALL_INTENTS)} intents)...")

    mapping_errors: list[str] = []
    for intent_str in ALL_INTENTS:
        try:
            mapped = GeneralIntent[intent_str]
            log(f"  {intent_str:22s} → {mapped!r}")
        except KeyError as exc:
            mapping_errors.append(f"{intent_str}: KeyError {exc}")
            log(f"  {intent_str:22s} → FAIL ({exc})")

    intent_mapping_ok = len(mapping_errors) == 0

    # -------------------------------------------------------------------
    # Step 4 — Build battlefield and forces
    # -------------------------------------------------------------------
    log(f"\n[SETUP] Battlefield (seed={seed}, 40×40 grid)...")

    grid     = Grid(40, 40, seed=seed)
    features = grid.battlefield_features()

    log(f"  has_frozen_lake: {features.get('has_frozen_lake', False)}")
    log(f"  has_river:       {features.get('has_river',       False)}")
    log(f"  has_walls:       {features.get('has_walls',       False)}")
    log(f"  has_forest:      {bool(grid.cells_of_type(TerrainType.FOREST))}")

    # Cavalry-heavy general so frozen_lake doctrine is relevant
    general_units = [
        make_unit(UnitType.CAVALRY,  "general", (8,  5)),
        make_unit(UnitType.CAVALRY,  "general", (10, 5)),
        make_unit(UnitType.INFANTRY, "general", (12, 5)),
        make_unit(UnitType.ARCHER,   "general", (14, 5)),
    ]
    player_units = [
        make_unit(UnitType.INFANTRY, "player", (8,  35)),
        make_unit(UnitType.INFANTRY, "player", (10, 35)),
        make_unit(UnitType.CAVALRY,  "player", (12, 35)),
        make_unit(UnitType.ARCHER,   "player", (14, 35)),
    ]

    log(f"  General: 2× cavalry, 1× infantry, 1× archer (no siege)")
    log(f"  Player:  2× infantry, 1× cavalry, 1× archer")

    loop = BattleLoop(
        grid          = grid,
        general_units = general_units,
        player_units  = player_units,
        player_id     = PLAYER_ID,
        age           = BATTLE_AGE,
        seed          = seed,
    )

    # -------------------------------------------------------------------
    # Step 5 — Per-turn tracking
    # -------------------------------------------------------------------
    turn_decisions:     list[dict] = []
    pipeline_errors:    list[str]  = []
    total_rejected            = 0
    total_doctrines_consulted = 0
    profiles_used_count       = 0
    relationship_used_count   = 0

    # -------------------------------------------------------------------
    # Step 6 — brain_intent_fn: the integration bridge
    # -------------------------------------------------------------------
    def brain_intent_fn(state):
        nonlocal total_rejected, total_doctrines_consulted, profiles_used_count, relationship_used_count
        try:
            knowledge = loop.to_brain_snapshot(SERVER_ID, PLAYER_ID)
            decision  = engine.decide(knowledge)

            # Accumulate
            total_rejected            += len(decision["rejected"])
            total_doctrines_consulted += len(decision["doctrines_consulted"])
            if decision["profile_used"]:
                profiles_used_count += 1
            if decision.get("relationship_used"):
                relationship_used_count += 1

            # Store full trace
            turn_decisions.append({
                "turn":                knowledge.turn,
                "weather":             knowledge.weather,
                "intent":              decision["intent"],
                "confidence":          decision["confidence"],
                "reasoning":           decision["reasoning"],
                "rejected":            decision["rejected"],
                "alternatives":        decision["alternatives"],
                "doctrines_consulted": decision["doctrines_consulted"],
                "profile_used":        decision["profile_used"],
            })

            if verbose:
                doc_mark = "●" if decision["doctrines_consulted"] else "○"
                alt_str  = (
                    f"alt={decision['alternatives'][0][0]}"
                    if decision["alternatives"] else ""
                )
                print(
                    f"  Turn {knowledge.turn:2d}  {decision['intent']:22s} "
                    f"conf={decision['confidence']:.2f}  {doc_mark}  "
                    f"rej={len(decision['rejected'])}  {alt_str}"
                )

            # Intent string → GeneralIntent enum — the live integration bridge
            return GeneralIntent[decision["intent"]]

        except Exception as exc:
            pipeline_errors.append(
                f"Turn {loop.turn}: {type(exc).__name__}: {exc}"
            )
            # Safe fallback — never crash the simulator
            return GeneralIntent.DEFENSIVE_HOLD

    # -------------------------------------------------------------------
    # Step 7 — Run the battle
    # -------------------------------------------------------------------
    log(f"\n[BATTLE] Running live battle...")
    log(f"  (● = doctrine consulted  ○ = neutral  rej = rejected intents)")
    log("")

    state = loop.run(general_intent_fn=brain_intent_fn)

    log("")
    log(f"[BATTLE 1] Concluded: {state.result.upper()} in {state.turns_played} turn(s)")

    # -------------------------------------------------------------------
    # Step 8 — Post-battle: log episode + re-run analysis pipeline
    # -------------------------------------------------------------------
    log(f"\n[POST-BATTLE] Logging episode to DB...")
    episode_id = logger.log_episode(state)
    log(f"  Episode id: {episode_id}")

    log(f"[POST-BATTLE] Re-running analysis pipeline...")
    post_beliefs   = wm.update_from_observations()
    post_doctrines = de.extract_doctrines()
    log(f"  update_from_observations() → {post_beliefs} belief rows")
    log(f"  extract_doctrines()        → {post_doctrines} doctrines upserted")

    log(f"[POST-BATTLE] Updating relationship record (Battle 1)...")
    rel_before_b1 = rm.get_state(SERVER_ID, PLAYER_ID)
    rm.update_after_battle(SERVER_ID, PLAYER_ID, state.result)
    rel_b1 = rm.get_state(SERVER_ID, PLAYER_ID)
    log(f"  encounters: {rel_before_b1.encounters} → {rel_b1.encounters}  "
        f"trust: {rel_b1.trust_level:.4f}")

    post_battle_ok = True  # reached this point without exception

    # -------------------------------------------------------------------
    # Step 9 — Feedback loop verification (seed=FEEDBACK_SEED → loss)
    # -------------------------------------------------------------------
    log(f"\n{LINE}")
    log(f"[FEEDBACK] Running verification battle (seed={FEEDBACK_SEED}, expected: loss)...")
    log(f"  This battle verifies record_battle_outcome() increments failure_count")
    log(f"  on the correct doctrine rows after a brain-driven loss.")
    log("")

    feedback_ok        = False
    feedback_details:  list[str] = []
    increments_applied = 0

    try:
        # Snapshot doctrine state BEFORE the feedback battle
        before_doctrines = {d["id"]: dict(d) for d in de.get_doctrines()}

        fb_grid = Grid(40, 40, seed=FEEDBACK_SEED)
        fb_general = [
            make_unit(UnitType.CAVALRY,  "general", (8,  5)),
            make_unit(UnitType.CAVALRY,  "general", (10, 5)),
            make_unit(UnitType.INFANTRY, "general", (12, 5)),
            make_unit(UnitType.ARCHER,   "general", (14, 5)),
        ]
        fb_player = [
            make_unit(UnitType.INFANTRY, "player", (8,  35)),
            make_unit(UnitType.INFANTRY, "player", (10, 35)),
            make_unit(UnitType.CAVALRY,  "player", (12, 35)),
            make_unit(UnitType.ARCHER,   "player", (14, 35)),
        ]
        fb_loop = BattleLoop(
            grid          = fb_grid,
            general_units = fb_general,
            player_units  = fb_player,
            player_id     = PLAYER_ID,
            age           = BATTLE_AGE,
            seed          = FEEDBACK_SEED,
        )

        fb_decisions: list[dict] = []
        fb_errors:    list[str]  = []

        def fb_intent_fn(state):
            try:
                knowledge = fb_loop.to_brain_snapshot(SERVER_ID, PLAYER_ID)
                decision  = engine.decide(knowledge)
                fb_decisions.append(decision)
                if verbose:
                    doc_mark = "●" if decision["doctrines_consulted"] else "○"
                    print(
                        f"  Turn {knowledge.turn:2d}  {decision['intent']:22s} "
                        f"conf={decision['confidence']:.2f}  {doc_mark}"
                    )
                return GeneralIntent[decision["intent"]]
            except Exception as exc:
                fb_errors.append(str(exc))
                return GeneralIntent.DEFENSIVE_HOLD

        fb_state = fb_loop.run(general_intent_fn=fb_intent_fn)

        log("")
        log(f"  Result: {fb_state.result.upper()} in {fb_state.turns_played} turn(s)")

        if fb_state.result != "loss":
            feedback_details.append(
                f"Expected loss with seed={FEEDBACK_SEED} but got {fb_state.result}. "
                f"Try a different FEEDBACK_SEED."
            )
        else:
            # Call record_battle_outcome() — the feedback loop
            increments_applied = engine.record_battle_outcome(
                fb_state.result, fb_decisions
            )

            # Snapshot doctrine state AFTER
            after_doctrines = {d["id"]: dict(d) for d in de.get_doctrines()}

            log(f"\n  BEFORE → AFTER  (failure_count | decay_rate):")
            changed = 0
            for doc_id, before in before_doctrines.items():
                after = after_doctrines.get(doc_id, {})
                fc_before = before.get("failure_count", 0)
                fc_after  = after.get("failure_count",  0)
                dr_before = before.get("decay_rate",    0.0)
                dr_after  = after.get("decay_rate",     0.0)

                if fc_after != fc_before:
                    changed += 1
                    log(
                        f"  ✓ [{doc_id}]\n"
                        f"    failure_count: {fc_before} → {fc_after}\n"
                        f"    decay_rate:    {dr_before:.6f} → {dr_after:.6f}"
                    )
                else:
                    log(f"  – [{doc_id}]  unchanged (not consulted in this battle)")

            log(f"\n  Doctrines changed: {changed}")
            log(f"  Increments applied by record_battle_outcome(): {increments_applied}")

            # Update relationship after feedback battle
            rel_before_b2 = rm.get_state(SERVER_ID, PLAYER_ID)
            rm.update_after_battle(SERVER_ID, PLAYER_ID, fb_state.result)
            rel_b2 = rm.get_state(SERVER_ID, PLAYER_ID)
            log(f"\n  Relationship after Battle 2 (loss):")
            log(f"    encounters: {rel_before_b2.encounters} → {rel_b2.encounters}  "
                f"trust: {rel_b2.trust_level:.4f}")

            relationship_updated = rel_b2.encounters == rel_before_b2.encounters + 1
            if not relationship_updated:
                feedback_details.append(
                    f"Expected encounters to increment by 1: "
                    f"{rel_before_b2.encounters} → {rel_b2.encounters}"
                )

            feedback_ok = (
                changed > 0
                and increments_applied > 0
                and len(fb_errors) == 0
                and relationship_updated
            )
            if not feedback_ok:
                if changed == 0:
                    feedback_details.append("No doctrine failure_counts changed.")
                if increments_applied == 0:
                    feedback_details.append("record_battle_outcome() returned 0 increments.")
                if fb_errors:
                    feedback_details.extend(fb_errors)

    except Exception as exc:
        feedback_details.append(f"{type(exc).__name__}: {exc}")
        feedback_ok = False

    # -------------------------------------------------------------------
    # Step 10 — Evaluate all success criteria
    # -------------------------------------------------------------------
    criteria = {
        "pre_battle_priming":    pre_battle_ok,
        "doctrine_influence":    total_doctrines_consulted > 0,
        "every_turn_decided":    len(turn_decisions) == state.turns_played,
        "intent_mapping_ok":     intent_mapping_ok,
        "trace_complete":        all("reasoning" in d for d in turn_decisions),
        "no_pipeline_errors":    len(pipeline_errors) == 0,
        "post_battle_ran":       post_battle_ok,
        "feedback_loop_verified": feedback_ok,
        "relationship_updated":  rel_b1.encounters == rel_before_b1.encounters + 1,
    }
    all_passed = all(criteria.values())

    # -------------------------------------------------------------------
    # Step 11 — Summary
    # -------------------------------------------------------------------
    log(f"\n{LINE}")
    log("INTEGRATION TEST SUMMARY")
    log(LINE)
    log(f"  Battle 1 result:            {state.result.upper()}")
    log(f"  Turns played:               {state.turns_played}")
    log(f"  Decisions made:             {len(turn_decisions)}")
    log(f"  Rejected intents (total):   {total_rejected}")
    log(f"  Doctrines consulted:        {total_doctrines_consulted}")
    log(f"  Turns profile was used:     {profiles_used_count}")
    log(f"  Turns relationship used:    {relationship_used_count}")
    log(f"  Pipeline errors:            {len(pipeline_errors)}")
    log(f"  Feedback increments:        {increments_applied}")

    criterion_labels = {
        "pre_battle_priming":    "Pre-battle knowledge priming executed",
        "doctrine_influence":    (
            f"Doctrine influence detected "
            f"({total_doctrines_consulted} consultations across battle)"
        ),
        "every_turn_decided":    (
            f"Decision logged every turn "
            f"({len(turn_decisions)}/{state.turns_played})"
        ),
        "intent_mapping_ok":     "All 8 intent strings → GeneralIntent enum verified",
        "trace_complete":        "Decision trace complete on all turns",
        "no_pipeline_errors":    "Pipeline completed with 0 errors",
        "post_battle_ran":       "Post-battle analysis pipeline executed",
        "feedback_loop_verified": (
            f"Doctrine DB updated after loss "
            f"({increments_applied} failure_count increments applied)"
        ),
        "relationship_updated":  (
            f"Relationship record updated after battle "
            f"(encounters={rel_b1.encounters}, trust={rel_b1.trust_level:.4f})"
        ),
    }

    log("\nSUCCESS CRITERIA:")
    for key, label in criterion_labels.items():
        mark = "✓" if criteria[key] else "✗"
        log(f"  [{mark}] {label}")

    if pipeline_errors:
        log("\nPIPELINE ERRORS:")
        for err in pipeline_errors:
            log(f"  {err}")

    if mapping_errors:
        log("\nINTENT MAPPING ERRORS:")
        for err in mapping_errors:
            log(f"  {err}")

    if feedback_details:
        log("\nFEEDBACK ERRORS:")
        for detail in feedback_details:
            log(f"  {detail}")

    # Sample traces — turn 1 and midpoint
    if turn_decisions:
        samples = [turn_decisions[0]]
        mid = len(turn_decisions) // 2
        if mid > 0:
            samples.append(turn_decisions[mid])

        for t in samples:
            log(f"\nSAMPLE TRACE — Turn {t['turn']} ({t['weather']}):")
            log(f"  Intent:    {t['intent']}  (confidence {t['confidence']:.3f})")
            if t["reasoning"]:
                log(f"  Reasoning:")
                for line in t["reasoning"]:
                    log(f"    • {line}")
            if t["rejected"]:
                log(f"  Rejected ({len(t['rejected'])}):")
                for r in t["rejected"][:4]:
                    log(f"    – {r}")
            if t["alternatives"]:
                log(f"  Alternatives: {t['alternatives']}")
            if t["doctrines_consulted"]:
                log(f"  Doctrines:    {t['doctrines_consulted']}")

    log(f"\n{LINE}")
    log(f"OVERALL: {'PASS ✓' if all_passed else 'FAIL ✗'}")
    log(LINE)

    return all_passed


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Stage 3 Candidate A — Live integration test. "
            "Wires the full simulator → brain pipeline in one battle."
        )
    )
    parser.add_argument(
        "--seed", type=int, default=DEFAULT_SEED,
        help=f"RNG seed for grid and battle (default: {DEFAULT_SEED})",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress per-turn output (summary only)",
    )
    args = parser.parse_args()

    success = run(seed=args.seed, verbose=not args.quiet)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
