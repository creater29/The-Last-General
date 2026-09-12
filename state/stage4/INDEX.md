# Stage 4 — Index

Stage 4 is the event-driven battle-loop redesign (D009). This directory
holds Stage 4's own artefacts, kept separate from the top-level `state/`
files so a future session can load exactly what's relevant to the
current sub-stage without reconstructing prior scoping conversations.

## Artefacts

| ID | File | Status |
|---|---|---|
| S4-00 | `S4-00-D009-SPEC.md` | **Complete, approved.** The full D009 technical specification (Revision 6, final). Data structures, round ordering, validation, event capture, failure handling, compatibility guarantees, test matrix. |
| S4A | *(not yet created)* | Not started. Implementation plan for the **legacy compiler extraction and equivalence testing only** — decomposing today's intent handlers into `_compile_<intent>_actions()` + immediate-execute-all, proven canonicalized-identical to current `TURN_BASED` behavior across seeds, before any `EVENT_DRIVEN` scheduling logic is built on top of it. |
| S4B–S4E | *(not defined)* | Not scoped. Do not infer scope for these from S4-00 — they do not exist as artefacts yet. |

## Reading order for a new session starting Stage 4A

1. This file.
2. `S4-00-D009-SPEC.md` — the approved technical model 4A must implement
   the first slice of.
3. `../SESSION_HANDOFF.md` — current handoff state.
4. Only the top-level state files actually relevant to 4A (likely
   `ARCHITECTURE.md`'s brain-import-boundary section and
   `DEFERRED_ITEMS.md`'s D009 entry for cross-reference) — not the full
   Stage 1–3 history.

Do not reconstruct the scoping conversation that produced S4-00. It
went through six review revisions catching real defects (invented APIs,
double-counted events, silent behavior-change proposals, unguarded
`None` dereferences); the corrected, final state is fully captured in
S4-00 itself.
