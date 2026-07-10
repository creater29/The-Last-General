# Session Handoff

## Date: 2026-06-28
## Stage: 3 (Live Pipeline)
## Tests: 402/402
## Handoff to: next session

---

## Candidate D Phase 6 — Facade cleanup (COMPLETE) — CANDIDATE D CLOSED

Final phase. Scoped as agreed: delegation verification, dead import/code
audit, conscious classification of every remaining `EpisodeLogger` method,
documentation updates, final integration verification. No new stores, no
registry, no redesign — held to that boundary throughout.

**Resolved (pre-committed decisions, not new scope):**
- `get_known_players()` (W010) — re-checked for a consumer at its own
  stated trigger point ("Candidate D"), still zero callers, deleted.
  Facade-stability baseline updated with the reason in the same commit.
  Moved to KNOWN_ISSUES as R008.
- `import uuid` — genuinely dead (confirmed via grep, not assumed),
  removed. `import json` verified still needed, left in place.
- D026 added — the `init_db()`/connection-lifecycle split (Phase 5
  review's "Issue A") was only ever in review prose, never tracked.

**The one genuine judgment call this phase surfaced:** `result_distribution()`
and `terrain_event_frequency()` are single-table queries — by table-count
alone they looked like they belonged in `EpisodeStore`/`ObservationStore`.
Presented as an open question rather than decided unilaterally. Supervisor
decision: don't move them — repository ownership means owning persistence
of domain objects, not every SQL statement touching that table; these
return derived aggregates, not records. Before implementing that decision,
stress-tested the reasoning against something already shipped:
`ObservationStore.get_observation_patterns()` (Phase 4) is structurally the
same kind of query, yet correctly stays in a repository. Checked real
callers to find the actual distinguishing test rather than trusting the
principle in the abstract: `get_observation_patterns()` is a genuine
pipeline dependency (`world_model.py` uses it to form beliefs
`DoctrineExtractor` promotes into doctrines); `terrain_event_frequency()`
is called only by a corpus-generation utility script; `result_distribution()`
has zero callers anywhere. Tracked as D027. Full reasoning now permanent in
ARCHITECTURE.md's new "EpisodeLogger Responsibility Classification" section.

**Internal-consistency check (per the post-Phase-5 retrospective request),
actually performed, not just asserted:**
- Verified the Phase-by-phase test-count table in PROGRESS.md sums
  correctly against the real historical total. It didn't on the first
  draft — 8+10+12+12+13 = 55, but the actual delta was 57. Found the gap:
  the 2 facade-stability tests, introduced alongside Phase 1 but not
  attributed to any store in the table. Fixed with an explicit
  reconciliation line rather than leaving a 2-test discrepancy for a future
  reader to puzzle over.
- Grepped for stale "six stores" language across all four state files.
  Found real hits in D014's Artifacts 2 and 3 (living, current-policy text
  — genuinely stale, since D024 later excluded `WorldModelStore` from
  Candidate D's actual scope) and fixed all five. Found the *original*
  pre-execution "What to do" plan (six modules including a
  `world_model_store.py` and `db_manager.py` that were never built, a
  "345 tests" target) and marked it SUPERSEDED rather than silently
  rewriting history to pretend the plan always matched what was actually
  built — pointed future readers to PROGRESS.md and ARCHITECTURE.md for
  what actually happened.
- Deliberately left "six stores" references inside SESSION_HANDOFF.md's
  earlier dated entries (e.g. the Phase 5 entry) untouched — those are
  point-in-time records of what was believed before D024's correction,
  not living spec text. Correcting them retroactively would misrepresent
  what was actually known at that point in the project's history.

**Final verification:**
- Test count: 402/402 (unchanged from Phase 5 — audit/cleanup phase, no
  new feature tests expected or added)
- Integration test: 9/9 PASS, verified live
- `logger.py`: 981 lines (Candidate D's trigger point) → 599 lines now
  (~39% reduction, with the actual logic moved into five independently
  tested files, not just deleted)

**Candidate D is closed.** Per the retrospective: resist reopening it
unless new evidence emerges. D023, D024, D025, D026, D027 each carry an
explicit, evidence-based re-evaluation trigger — none are timelines, none
imply eventual action is expected.

**Full history:** `git log --oneline` from `7ff3006` (Phase 5) through this
entry's commit covers Phase 5, the Artifact 1/4 separation, D024's wording
refinement, D025, the git-authentication resolution, Phase 6's partial
work, and the classification decision — 8 commits, one focused change per
commit, matching the discipline used throughout every phase.

---

## Candidate D Phase 5 — EpisodeStore + facade workflow restructure (COMPLETE)

The phase the entire Repository Independence revision (decided before
Phase 1 even began) was designed for. Both supervisor reviews flagged this
as the highest remaining risk in Candidate D — it owns the transaction
boundary for the whole logging pipeline.

**Core transformation:** `log_episode()` had inline SQL for the episode
INSERT, then called `_extract_observations()` (already moved to
`ObservationStore` in Phase 4), then committed once. That inline SQL is now
`EpisodeStore.insert_episode_row()` — non-committing, exactly like
`ObservationStore.insert_observations()`. The facade's `log_episode()` is
now pure orchestration: no inline SQL at all, just two store calls and one
commit. This is exactly the anti-pattern both reviews warned against
avoided: never `insert_episode_row() → commit(); insert_observations() →
commit()` (two transactions, breaks atomicity, violates the FK constraint
found in Phase 4) — always both inserts, then one commit, on the facade.

**MCP stall mid-edit, handled correctly:** the `edit_block` call
constructing `EpisodeStore` in `__init__` timed out with no result. Did not
assume it landed or failed either way. Once the server recovered, read the
live file directly first — confirmed the line was genuinely missing — then
redid the edit correctly. This is the same discipline used for every prior
MCP stall this session: verify the actual state, never guess.

**Caught a flaw in my own test, not the implementation:** the Repository
Independence check for `EpisodeStore` initially did a raw string search for
"ObservationStore" across the whole file — which flagged the module's own
docstring (which legitimately explains the design rationale by name) as if
it were a real import. Rewrote the test to walk the AST and check actual
`Import`/`ImportFrom` nodes instead of searching raw text. Same class of
mistake as the heuristic false-positives from the original D014 audit
earlier this session — a blunt text-matching check flagging documentation
as if it were code.

**Verification, most rigorous yet given this phase's centrality:**
13 standalone tests first (including a direct two-connection proof that
`insert_episode_row()` doesn't commit, and an explicit atomic-composition
test simulating the exact facade workflow) → facade wiring → full suite
(402/402) → integration test 9/9 → precise before/after delta against live
production DB (`episodes: 12023→12024 (+1), observations: 151358→151368
(+10)` — identical pattern to Phase 4) → verified `get_player_episodes()`
(the Phase 2 finding, now resolved) through its actual real caller
(`PlayerProfiler`, not just isolated tests): 24 real episodes, correctly
enriched, correctly ordered ASC.

**Files touched:**
- `src/simulator/stores/episode_store.py` (new, 170 lines)
- `src/simulator/logger.py` (import, construction, `log_episode()`
  rewritten as pure orchestration, five methods reduced to delegations,
  `get_episodes_by_terrain_event()` correctly left untouched — genuine
  cross-store JOIN, facade-level per Artifact 1)
- `tests/test_episode_store.py` (new, 13 tests)
- `state/PROGRESS.md`, `state/SESSION_HANDOFF.md`

**Next: Phase 6 — Facade cleanup.** Final phase. Per Artifact 4:
1. Confirm `EpisodeLogger` delegates cleanly to all six stores plus the
   facade-level methods (`get_episodes_by_terrain_event`, `summary`,
   `result_distribution`, `terrain_event_frequency`) — read each fresh,
   don't assume the earlier classification still matches without checking.
2. Check for now-unused imports in `logger.py` (`json`, `uuid` may no
   longer be directly needed now that all store bodies own their own
   json/uuid usage — verify with a real check, don't assume either way).
3. Revisit D023 (store-construction registry) now that all six stores
   exist in `__init__` — judge from the actual six-line block, not
   speculation, per D023's own stated trigger condition.
4. Final full-suite + integration test run, final facade-stability test
   confirmation, final PROGRESS.md/ARCHITECTURE.md update marking
   Candidate D fully complete.

---

## Candidate D Phase 4 — ObservationStore extraction (COMPLETE)

More significant than Phases 1-3: this is the first phase to touch
`log_episode()` itself — the central write path every battle goes through,
not an isolated CRUD method.

**The Repository Independence revision (decided before Phase 1 even began,
during the "one instruction above all others" review round) was exercised
for real here for the first time.** `ObservationStore` has zero reference
to episodes or `EpisodeStore`. `insert_observations()` (public rename of
the old private `_extract_observations()`) does not commit internally.
Verified this is deliberate, not an oversight, by finding
`observations.episode_id FOREIGN KEY REFERENCES episodes(id)`, enforced in
production via `PRAGMA foreign_keys=ON` in `_connect()`. The facade's
`log_episode()` still does: insert episode row → call
`self._observation_store.insert_observations(...)` → commit once — same
composition as before, just now explicitly the facade orchestrating two
independent stores rather than one store depending on another.

**Caught a real mistake mid-edit, not after:** during the three-method
replacement (`get_observation_count`/`get_observations_by_terrain`/
`get_observation_patterns`), a leftover `return [dict(row) for row in
rows]` line survived from the old body and sat as dead, unreachable code
right after the new delegation. Caught by reading the edit_block's own
output immediately after the call, before moving on — not by a later test
failure. Fixed before running the suite.

**Verification went beyond the standard bar given this phase's centrality:**
ran a precise before/after delta check against the LIVE production DB —
`episodes: 12021→12022 (+1), observations: 151338→151348 (+10)` — for one
specific integration test run. This confirms the atomic composition
produced exactly one episode row and exactly the right number of
observation rows for that one battle's actual terrain events, not just
"the totals went up by some amount." Also confirmed this matches the
integration script's actual design (only Battle 1/seed=42 calls
`log_episode()`; the feedback battle only calls `update_after_battle()`/
`record_battle_outcome()`), rather than assuming both battles should have
incremented the episode count.

**Files touched:**
- `src/simulator/stores/observation_store.py` (new, 160 lines)
- `src/simulator/logger.py` (import, construction, `log_episode()`'s body
  updated to call the new store, `_extract_observations()` removed
  entirely — not delegated, deleted, since it's now `ObservationStore`'s
  public method — three read methods reduced to delegations, one leftover
  dangling line caught and removed)
- `tests/test_observation_store.py` (new, 12 tests, including a
  two-connection test that directly proves non-commit behavior rather than
  inferring it from return values)
- `state/PROGRESS.md`, `state/SESSION_HANDOFF.md`

**Next: Phase 5 — EpisodeStore + facade workflow restructure.** This is
the phase the entire Repository Independence revision was originally
designed for. Per D014 Artifact 2 (Transaction Policy, revised): extract
the `episodes` table INSERT itself into `EpisodeStore.insert_episode_row()`
(no commit), and rewrite the facade's `log_episode()` to be pure
orchestration: call `EpisodeStore.insert_episode_row()`, call
`self._observation_store.insert_observations()` (already correct, from this
phase), commit once. `EpisodeStore` itself must have zero reference to
`ObservationStore` — verify this with the same standalone-independence
test pattern as every prior phase. Also: `get_player_episodes()` moves here
too (the Phase 2 finding — it queries `episodes` only, despite being used
by `PlayerProfiler`). Read every method fresh from the live file before
writing anything, per the pattern that has now caught something worth
catching in three of four phases so far (get_player_episodes
miscategorization, a return-statement inference gap, a leftover dangling
line) — this discipline is earning its cost.

---

## Candidate D Phase 3 — DoctrineStore extraction (COMPLETE)

Same protocol as Phases 1-2, plus additional scrutiny: supervisor review
flagged this as the first "behavior-critical" extraction (DoctrineStore
sits directly in DecisionEngine's read path) and required explicit
behavioral-equivalence verification, not just passing tests.

**Behavior-critical invariant found during the read-through, before writing
anything:** `upsert_doctrine()`'s `ON CONFLICT` clause deliberately excludes
`failure_count` and `exceptions` from the update — only `confidence`,
`episode_count`, `derived_principle`, `last_verified` change. This means a
re-extraction pass (which runs every integration test via
`extract_doctrines()`) never erases accumulated failure feedback from
`increment_doctrine_failure()`. Wrote two dedicated tests for this exact
invariant, and separately confirmed it against the LIVE production DB after
running the integration test: `failure_count=102` (accumulated across many
prior sessions) survived a fresh re-upsert without being reset to 0.

**Caught my own error before it mattered:** while writing `DoctrineStore`,
I added `return True` at the end of `increment_doctrine_failure()` based on
inferring from the docstring — my last direct read of the live file had cut
off exactly at `conn.commit()` and I never actually saw the return statement.
Went back and verified the live file directly before trusting my own draft.
It happened to be correct, but the process gap (inferring instead of
verifying) was real and worth catching regardless of the outcome.

**Structural difference from Phases 1-2, verified not assumed:**
`DoctrineStore` has no `migrate_*_schema()` method. Checked whether this was
an inconsistency to fix — it isn't. `migrate_relationship_schema()` and
`migrate_player_profiles()` exist for specific historical repair reasons
(R006, the `encounters` field) that never applied to `doctrines` — its
schema was correct from the original `CREATE TABLE`. Initial schema creation
stays a DBManager/facade concern (`init_db()`) per Artifact 1. The
standalone test file provides its own minimal schema-creation helper
(mirroring `init_db()`'s exact CREATE TABLE, copied not invented) rather
than adding an unneeded method to the store just for test convenience.

**Verification, in order:** 12 standalone tests first (including the two
behavior-critical invariant tests) → facade wiring → full suite (377/377)
→ integration test verbose, both doctrine-specific success criteria
explicitly confirmed at the same magnitudes as pre-Phase-3 runs → direct
live-DB inspection of `failure_count`/`confidence`/`decay_rate` after the
run, specifically to verify the conflict-clause invariant held in production
data, not just in an isolated in-memory test.

**Files touched:**
- `src/simulator/stores/doctrine_store.py` (new, 157 lines)
- `src/simulator/logger.py` (import, construction, four methods reduced to
  delegations, old inline SQL removed — 789 → 739 lines)
- `tests/test_doctrine_store.py` (new, 12 tests)
- `state/PROGRESS.md`, `state/SESSION_HANDOFF.md`

**Next: Phase 4 — ObservationStore.** Per Artifact 4, this is the one phase
with a real intra-logger structural coupling to watch for: the ORIGINAL
`log_episode()` calls `_extract_observations()` directly. Per the Repository
Independence revision (already made to the spec before Phase 1 began),
`ObservationStore` itself should have NO reference to `EpisodeStore` — the
orchestration moves to the facade in Phase 5, not here. For Phase 4 alone,
extract `_extract_observations()` (proposed rename: `insert_observations()`)
plus the three read methods (`get_observation_count`,
`get_observations_by_terrain`, `get_observation_patterns`) into
`ObservationStore`, keep it fully independent, and leave the facade's
`log_episode()` calling into it via a temporary direct reference until
Phase 5 formally moves that orchestration. Read every method fresh from the
live file before writing anything — do not reuse Artifact 1's signatures
without re-verifying, per the pattern that already caught two real
discrepancies (`get_player_episodes` in Phase 2, the `return True` inference
gap in Phase 3).

---

## Candidate D Phase 2 — PlayerProfileStore extraction (COMPLETE)

Same protocol as Phase 1, exactly. Read the four live methods
(`migrate_player_profiles`, `upsert_player_profile`, `get_player_profile`,
`get_all_player_profiles`) fresh from `logger.py` before writing anything —
not reused from the DEFERRED_ITEMS D014 Artifact 1 snapshot.

**Real finding during the read-through:** `get_player_episodes()` sits
physically between `migrate_player_profiles()` and `upsert_player_profile()`
in the file, and its docstring says "Used by PlayerProfiler" — but its body
only queries the `episodes` table. It belongs to `EpisodeStore` (Phase 5),
not `PlayerProfileStore`, despite sitting right next to these methods and
despite its stated caller. Corrected Artifact 1 in DEFERRED_ITEMS.md;
left the method itself untouched in `logger.py` (not this phase's job).

**Process note — MCP server instability this session:** Desktop Commander
went unresponsive twice during this phase's verification steps (even a
trivial `echo` command timed out identically both times). Both times: did
not guess at results, did not report anything as passing without direct
confirmation, told the user plainly what was verified vs. unknown, and
re-ran the affected step fresh once the server recovered. The second full
test suite run (365/365, clean summary line, no stall) is the one this
phase's completion is based on — not the earlier run that stalled mid-output.

**On the "Repository parity tests" recommendation from supervisor review:**
considered and consciously not added as a new mechanism. The pre-existing
facade-level tests in `test_logger.py` (unmodified since before Phase 1)
already serve this function — they exercise the same facade methods,
unchanged, and would fail on any behavioral drift. A separate old-vs-new
comparison harness would be redundant and would require temporarily keeping
the old implementation around, which conflicts with "remove immediately,
don't duplicate" — a principle the same review praised two paragraphs
earlier. Noted this reasoning explicitly rather than silently skipping the
recommendation or mechanically implementing something redundant.

**Verification, in order:** new store's 10 tests standalone first → facade
wiring → full suite (365/365, confirmed cleanly after an MCP stall required
a re-run) → integration test verbose, confirmed real numbers moved correctly
(`encounters=29, trust=-0.4000`) → git status checked before committing.

**Files touched:**
- `src/simulator/stores/player_profile_store.py` (new, 175 lines)
- `src/simulator/logger.py` (import, construction, four methods reduced to
  delegations, old inline SQL removed — 858 → 788 lines)
- `tests/test_player_profile_store.py` (new, 10 tests)
- `state/DEFERRED_ITEMS.md` (Artifact 1 corrected — `get_player_episodes()`
  moved to EpisodeStore's method list)
- `state/PROGRESS.md`, `state/SESSION_HANDOFF.md`

**Next: Phase 3 — DoctrineStore.** Same pattern: read
`upsert_doctrine`/`get_doctrine_by_id`/`get_all_doctrines`/
`increment_doctrine_failure` fresh from the live `logger.py` file before
writing anything — do not reuse Artifact 1's signatures without
re-verifying, exactly as this phase found a real discrepancy
(`get_player_episodes`) that the original audit missed. Watch specifically
for whether `increment_doctrine_failure`'s decay-rate formula references
anything outside the `doctrines` table (it shouldn't, per the verified
dependency graph, but verify directly rather than trust the graph blindly —
same discipline that caught the `get_player_episodes` miscategorization).

---

## Candidate D Phase 1 — RelationshipStore extraction (COMPLETE)

First actual store extraction, per the fully-specified D014 plan (4 artifacts,
all previously reviewed and committed). Routine implementation of an
already-approved spec — no new architectural decisions made during this phase.

**What happened:** Read the exact current `upsert_relationship`,
`get_relationship`, `migrate_relationship_schema` bodies from `logger.py`
fresh (not from memory, despite having touched this exact code multiple
times earlier in the session). Moved them verbatim into
`src/simulator/stores/relationship_store.py`. Confirmed `EpisodeLogger.__init__`
calls `init_db()` before anything else, which populates `self._conn` —
meaning `RelationshipStore` can be constructed eagerly in `__init__`, no
lazy-getter needed. Wired the facade to delegate via three one-line methods,
then removed the old inline SQL entirely (949 → 859 lines — extraction
reduced code, did not duplicate it).

**Also built the facade-stability test Artifact 3 had only promised in
prose:** captured `EpisodeLogger`'s full 27-method public signature list
immediately before Phase 1 began, hardcoded it as a baseline in
`tests/test_logger_facade_stability.py`, and asserted the live class matches
it exactly. This test now watches every future phase — if a phase changes
the facade's public surface without updating this baseline explicitly, it
fails loudly instead of drifting silently.

**Verification, in order:** ran the new store's 8 tests standalone first
(before touching logger.py at all) → wired the facade → ran full suite
(355/355) → ran integration test verbose and confirmed the relationship
numbers actually moved correctly through the new path
(`encounters: 21→22, trust: -0.33`), not just "exit code 0" → confirmed
Repository Independence directly (constructed `RelationshipStore` against a
fresh in-memory connection with zero other imports).

**Files touched:**
- `src/simulator/stores/__init__.py` (new)
- `src/simulator/stores/relationship_store.py` (new, 157 lines)
- `src/simulator/logger.py` (import added, store constructed in `__init__`,
  three methods reduced to one-line delegations, old inline SQL removed)
- `tests/test_relationship_store.py` (new, 8 tests)
- `tests/test_logger_facade_stability.py` (new, 2 tests)
- `state/PROGRESS.md`, `state/SESSION_HANDOFF.md`

**Next: Phase 2 — PlayerProfileStore.** Same pattern exactly: read current
`upsert_player_profile`/`get_player_profile`/`get_all_player_profiles`/
`migrate_player_profiles` bodies fresh from `logger.py` (do not reuse the
signatures already written in DEFERRED_ITEMS D014 Artifact 1 without
re-verifying against the live file — that artifact was written from a
snapshot that may have shifted since). Extract to
`src/simulator/stores/player_profile_store.py`. Same Definition of Done
checklist (Artifact 4): standalone test first, then facade delegation, then
full suite, then remove old inline code, then facade-stability test must
still pass unchanged.

---

## D014 Pre-Implementation Artifacts (this session, after the pre-audit above)

Per supervisor requirement: three artifacts produced and added to
DEFERRED_ITEMS.md D014 before any store file is written. No source code
changed in this step — pure documentation/contract work, verified against
actual current code, not assumed.

**Artifact 1 — Repository Interface Specification.** Six stores (Episode,
Observation, WorldModel, Doctrine, PlayerProfile, Relationship), each with
exact current method signatures, owned tables, and dependencies. Building
this caught one more real finding: `get_episodes_by_terrain_event()` does a
genuine SQL JOIN across `episodes` and `observations` — classified at the
facade level (same rule already applied to `summary()`), not inside either
store.

**Process note worth knowing:** an automated heuristic script (checking
which tables each method's body references) produced several false
positives — `upsert_doctrine` appearing to touch `observations`,
`migrate_player_profiles` appearing to touch `observations`, the relationship
methods appearing to touch `player_profiles`. All were traced to docstring
bleed-through or comments referencing other tables for documentation
consistency, not real code. Confirmed by reading each body directly before
including anything in the spec — the heuristic was a lead to check, not a
source of truth on its own.

**Artifact 2 — Transaction Ownership Policy.** Verified `_get_conn()` caches
one connection and returns it identically every call — this is *why*
`log_episode()`'s single `commit()` already atomically covers both the
episodes insert and every observations insert made inside
`_extract_observations()`. Policy: all six stores share one injected
connection; single-table methods keep self-committing as they do today;
`log_episode()` stays the sole exception, calling `ObservationStore`'s
non-committing extraction method directly and issuing one commit — exactly
mirroring current behavior, no new transaction abstraction invented ahead of
a second real use case.

**Artifact 3 — LoggerFacade Contract.** `EpisodeLogger` stays the only
external-facing class; zero call-site changes anywhere. Concrete
verification proposed (not just a promise): capture `EpisodeLogger`'s full
public method signature list before the split, add a test asserting it's
identical after.

**Full artifact text is in `state/DEFERRED_ITEMS.md` under "D014 —
Pre-Implementation Artifacts."** Candidate D implementation still has NOT
started — these are the proposed contracts, awaiting confirmation before any
store file is written.

**Refinement pass (same session, after supervisor review of the artifacts
above):** Added Artifact 4 (extraction order — Relationship → PlayerProfile →
Doctrine → Observation → Episode → facade cleanup, plus a hard rule to run
the full test suite after every phase, not just at the end) and a formal
"Logger public API unchanged" completion criterion tied to Artifact 3's
signature-comparison test. Also promoted three engineering principles to
ARCHITECTURE.md's new permanent "Engineering Process Principles" section:
heuristics identify candidates but implementation establishes truth;
repository boundaries follow data ownership not method-name grouping;
repositories own writes while facades own workflows. All three came directly
out of this session's work, not imposed from outside.

One precision correction made to the extraction-order recommendation before
adopting it: the order is ranked by consumer criticality / blast radius, NOT
by intra-logger dependency count — the verified dependency graph in Artifact
1 shows only one real store-to-store coupling (Episode→Observation).
DoctrineStore has zero technical dependencies but sits mid-order because
DecisionEngine reads through it on every decision. Kept both framings
explicit so Artifact 1 and Artifact 4 don't quietly contradict each other.

---

## Candidate D pre-audit (this session, after Candidate C + post-completion review)

Before starting Candidate D (logger repository split), ran the audit
SESSION_HANDOFF instructed. Found three things not in the original D014 plan;
resolved two, tracked one, and corrected D014's scope. **Candidate D
implementation itself has NOT started — this was prerequisite cleanup only.**

**1. D014's original scope was stale.** Written before Candidate C existed —
planned 4 stores (Episode/Observation/Doctrine/Profile), with "player
profiles, relationships" bundled into one `profile_store.py`. That would have
merged Player Profile and Relationship, violating the orthogonality rule.
Corrected to 6 stores (added WorldModelStore and RelationshipStore) — see
D014 in DEFERRED_ITEMS.md for the full corrected plan, including a verified
table-ownership dependency graph (not guessed — built from grepping every
FROM/INTO/UPDATE in logger.py against every table name).

**One more thing the dependency graph caught:** the original plan put
`terrain_knowledge` methods in `doctrine_store.py` ("they feed
doctrine_extractor"). But terrain_knowledge is WorldModel's domain — learned
environmental beliefs — not Doctrine's. DoctrineExtractor *reads* WorldModel's
beliefs to form doctrines; reading isn't owning. Reclassified to a
`world_model_store.py`. Same "who reads ≠ who owns" logic as Player Profile
vs. Relationship.

**Also found in passing:** a `counter_doctrines` table exists in the schema
with zero methods beyond a `COUNT` in `summary()` — same "schema-only,
unimplemented" pattern `player_general_relationship` had before Candidate C.
This is presumably the future Counter-Doctrine layer mentioned in
ARCHITECTURE.md. Out of scope for D014 — noted for whenever that becomes its
own Candidate. Did not build anything for it.

**2. Two fully dead, shadowed methods removed.** Pre-R006 `upsert_player_profile`
and `get_player_profile` — bare `player_id`, no `server_id`, unreachable
(Python only keeps the last definition of a method name; the real server-scoped
versions exist later in the file). Verified zero callers anywhere before
removing. logger.py: 981 → 950 lines. 345/345 still passing after removal.

**3. `get_known_players()` — orphaned, not fixed, not deleted.** Queries a
column (`encounter_count`) that doesn't exist in the current schema — would
crash if ever called. Zero callers anywhere. Checked all state files for any
documented plan needing "list all opponents" — none found. Rather than guess
whether it's needed, marked ORPHANED in its docstring and tracked as
KNOWN_ISSUES W010. Resolution deferred to Candidate D itself: if still no
consumer by then, delete; if one has emerged, redesign server-scoped.

**Files touched this pre-audit:**
- `src/simulator/logger.py` — dead methods removed, `get_known_players()`
  docstring updated to flag orphan status. 950 lines.
- `state/DEFERRED_ITEMS.md` — D014 fully rewritten: 6-store plan, dependency
  graph, terrain_knowledge reclassification, get_known_players resolution plan
- `state/KNOWN_ISSUES.md` — W010 added

**Candidate D implementation is now unblocked but NOT started.** Next session
should present an implementation plan for the 6-store split (per D014) and
wait for confirmation before writing any store files — this is a structural
change to the persistence layer every subsystem depends on, squarely
"architecture" territory per the Supervisor Interaction rule.

---

## Post-completion code review (same session, after Candidate C initially "done")

Two issues were found in a follow-up code review of the completed Candidate C
work — both verified against actual code before any fix was applied, per the
Documentation Verification Rule:

**1. `result: str` in `update_after_battle()` had no input validation.**
A typo like `"Win"` (wrong case) would silently fall through as a no-op
"draw" — no error, no signal anything was wrong. Fixed: added `_VALID_RESULTS
= {"win", "loss", "draw"}` and a `ValueError` raise at the top of the method
(atomic — fails before any DB read/write).

**Verification that mattered:** before adding that validation, checked what
values `BattleState.result` can actually hold. Its inline comment claimed
`# win | loss | draw | retreat | max_turns` — five values. Had the validation
been written against that comment, it would have accepted stale/wrong values
or rejected valid ones. Reading `_determine_result()` directly (the only
function that sets `.result`) showed it returns exactly three values, never
"retreat" or "max_turns". The comment was stale documentation, not reflecting
reality. Corrected the comment in `src/simulator/battle.py` (line ~112) as a
trivial, zero-behavior-change fix directly tied to the verification just done.

**2. Dead `risk_mod` variable in `_relationship_factor()`.**
Computed with the exact same formula as `commitment_mod`, never used in any
branch. This was architecturally significant, not just cleanup — `risk_modifier`
had been an explicitly named part of an earlier-approved three-modifier design
(risk / commitment / confidence), documented across ARCHITECTURE.md,
SESSION_HANDOFF.md, and PROGRESS.md. Removing it required a decision, not just
a deletion.

**Resolution:** Remove the *implementation* (dead code, no consumer, would sit
unused indefinitely). Keep the *architectural concept* documented (not
executable) in ARCHITECTURE.md and DEFERRED_ITEMS D022, with an explicit
reintroduction trigger: when D022 (IntentMetadata) exists and gives risk a
distinct value from commitment (e.g. SUPPLY_RAID: small raid = low risk/low
commitment vs. deep strike = high risk/high commitment — a distinction today's
intent category sets cannot express). This follows "evidence before
implementation" — the concept isn't lost, it just isn't code until something
needs it.

**Files touched in this follow-up:**
- `src/brain/relationship_manager.py` — `_VALID_RESULTS` validation added
- `src/simulator/battle.py` — stale `.result` comment corrected
- `src/brain/decision_engine.py` — `risk_mod` removed, docstring corrected
- `state/ARCHITECTURE.md` — interface rule section corrected to match
- `state/DEFERRED_ITEMS.md` — D022 extended with risk_modifier reintroduction note
- `tests/test_relationship_manager.py` — 4 new tests (invalid result, wrong
  case, no-mutation-on-reject, all-three-valid-accepted)
- Test count: 341 → 345, all passing. Integration test re-verified: 9/9, exit 0.

**Process note:** two of the edits to `relationship_manager.py` initially used
the wrong tool (generic sandbox `str_replace` instead of `Desktop Commander:
edit_block`) and silently wrote to a container copy that isn't the real file —
the same mistake made earlier with `create_file`. Caught by re-reading the file
after the "successful" edit and finding the old content still present. Redone
correctly with the right tool, then verified via the test suite. Recorded here
so this specific failure mode is recognized faster if it recurs.

---

## What was completed this session

**Stage 3 Candidate C — Player-General Relationship — COMPLETE and VERIFIED.**

Went through a multi-round architectural review before implementation (see
git log for the full chain). Key corrections made during review, BEFORE any
code was written:

1. RelationshipManager must NOT compute modifiers — only DecisionEngine
   interprets psychological state into decision-relevant factors.
2. RelationshipManager must NOT know intent names — ever, regardless of
   future intent taxonomy growth.
3. `confidence_modifier` deferred at 1.0 — betrayal_count measures trust,
   not confidence. Confidence needs its own evidence source (prediction
   accuracy) which doesn't exist yet.
4. `get_state()` returns `RelationshipState`, never `Optional`. Missing
   records normalize to `RelationshipState.neutral()` internally — same
   philosophy as CommanderKnowledge. The `encounters` field (not in the
   original spec) distinguishes "never met" (encounters=0) from "known
   neutral" (encounters>0, trust=0.0).
5. Intent categories in `_relationship_factor()` are explicitly temporary
   — documented in DEFERRED_ITEMS D022 for eventual replacement with
   per-intent metadata.

**Files built/modified:**
- `src/brain/relationship_manager.py` (new, 173 lines) — `RelationshipState`
  frozen dataclass + `RelationshipManager` (`get_state`, `update_after_battle`)
- `src/simulator/logger.py` — schema fix: added `encounters INTEGER NOT NULL
  DEFAULT 0` to `player_general_relationship`. Updated `upsert_relationship()`,
  `get_relationship()`, `migrate_relationship_schema()`. Migration run on
  production DB.
- `src/brain/decision_engine.py` — added `_relationship_factor()` module-level
  function (same pattern as `_doctrine_factor`/`_player_factor`). `__init__`
  takes optional `relationship_manager` param (backward-compatible — existing
  tests unaffected). `decide()` wires it in, adds `relationship_used` to
  return dict.
- `tests/test_relationship_manager.py` (new, 22 tests)
- `scripts/run_integration_test.py` — `RelationshipManager` added to brain
  setup, `update_after_battle()` called after both battles, 9th success
  criterion added (`relationship_updated`)

**Verification — 9/9 integration criteria PASS.**

Important operational note for future sessions: the integration test runs
against the **production DB**, so the relationship record for
`(integration_test_server, integration_test_player)` accumulates across every
run — same as doctrine `failure_count`. The feedback battle (seed=9) always
loses by design, so trust drifts downward each time the test runs. The
success criterion checks the delta (`encounters == before + 1`), not the
absolute trust value, so this accumulation does not cause false failures.
If you see `trust: -0.4000` or similar in output, that's accumulated history,
not a bug — check the delta, not the absolute number.

---

## Audit discipline — status update

Candidates A and B both had pre-written code discovered via audit. Candidate C
had NO pre-written code — audit confirmed `src/brain/relationship_manager.py`
did not exist, and no reference to `RelationshipManager`, `risk_modifier`, etc.
appeared anywhere in src/tests/scripts before this session. This was built
entirely from the ground up, following full architectural review first.

**Audit pattern remains standard procedure for every future candidate:**
```bash
ls src/brain/
grep -rn "<ClassName>\|<method_name>" src/ tests/ scripts/
python3 -m pytest tests/ --co -q 2>&1 | tail -3
```

---

## What to work on next

**Stage 3 is now fully complete: Candidates A, B, and C all done and verified.**

Remaining Stage 3 candidates (D, E) are both explicitly deferred:
- **D — Logger repository split**: trigger already hit (logger.py ~900+ lines
  after this session's additions). Deferred until after C — which is now done.
  This is the next reasonable candidate, OR:
- **E — Scout mechanics**: deferred until D is done.

**Recommend auditing D first before starting anything:**
```bash
wc -l src/simulator/logger.py
grep -n "class.*Repository" src/simulator/logger.py src/simulator/*.py
```
Logger.py has grown across three candidates now (B added
`increment_doctrine_failure`, C added relationship methods + `encounters`
migration). Check current line count before deciding whether the split is
now overdue or still borderline.

**Before starting D or E, present the audit findings and wait for direction —
per the new project operating instructions, do not assume which candidate to
start or how broad its scope should be.**

---

## New project operating instructions (as of this session)

A comprehensive "Lead Implementation Engineer" instruction set was adopted
this session. Core principles now in effect for all future work:

- **Golden rule: never assume.** If anything is uncertain, stop and ask.
- **Audit before build** — verify nothing exists before implementing.
- **Read before modify** — never edit against assumed APIs/schemas.
- **Implemented ≠ Completed** — completion requires impl + unit tests +
  integration tests + live verification + DB verification (if applicable)
  + documentation, in that order (docs last, always reflecting reality).
- **Candidate discipline** — no scope expansion mid-candidate. New work
  discovered mid-session gets documented in DEFERRED_ITEMS, not built.
- **Evidence before redesign** — no refactoring without measurable justification.
- **Clarification over inference** — present Option A/B with tradeoffs when
  multiple reasonable interpretations exist; wait for the decision.
- **End-of-session checklist** (see instructions) must be run before closing
  every session — this session's closeout followed it.

---

## Candidate status

| Candidate | Description | Status |
|-----------|-------------|--------|
| A | Live Integration Test | ✅ COMPLETE |
| B | Doctrine Feedback Loop | ✅ COMPLETE |
| C | Player-General Relationship | ✅ COMPLETE |
| D | Logger Repository Split | 🔲 NEXT — audit line count first |
| E | Scout Mechanics | 🔲 Deferred until D |

---

## DB state (as of session end)

5 doctrines (failure_count continues to accumulate across integration test runs):
```
doctrine_river_weather_flood           conf~1.00  fc=36  (accumulating)
doctrine_forest_cavalry_tree_fall      conf~1.00  fc=144 (accumulating)
doctrine_wall_siege_wall_collapse      conf=0.9999 fc=0
doctrine_frozen_lake_cavalry_ice_break conf=0.9989 fc=0
doctrine_frozen_lake_siege_ice_break   conf=0.9872 fc=0
```

Relationship record for `(integration_test_server, integration_test_player)`:
accumulating across runs, currently negative trust (feedback battle always
loses by design). This is expected — see verification note above.

---

## How to run the integration test

```bash
cd ~/Projects/general_brain
python3 scripts/run_integration_test.py            # full output, 2 battles
python3 scripts/run_integration_test.py --quiet    # summary only
python3 scripts/run_integration_test.py --seed 99  # different main battle seed
```

---

## Handoff verification prompt

```
I'm continuing development of "The Last General's Mind" project.
You have full terminal access to my local machine via Desktop Commander MCP.

Before doing anything else, run this verification:

    cd ~/Projects/general_brain && python3 -m pytest tests/ --tb=short -q

Then read these files in this exact order — fully, no skimming:
1. state/CLAUDE_BRIEFING.md
2. state/ARCHITECTURE.md
3. state/PROGRESS.md
4. state/KNOWN_ISSUES.md
5. state/SESSION_HANDOFF.md
6. state/DEFERRED_ITEMS.md

Once you have read all six files and confirmed 345/345 tests pass, tell me:
- Which Stage 3 candidates are complete and what was verified in each
- What the three memory systems orthogonality rule is and why it matters
- What D022 is and why it exists
- What candidate should reasonably come next, and what you would audit
  before starting it

Do not start writing any code until I confirm your understanding is correct.
```
