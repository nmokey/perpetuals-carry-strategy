# Conventions

Accumulated lessons. **Read this before starting work and apply every rule; append a new entry
whenever a lesson is learned, corrected, or reversed.** A convention only earns its place here if
violating it already caused, or would clearly cause, real rework — this is not a style guide.

Format: rule, why it exists, how to apply it.

---

## C1 — Never take remote actions without explicit approval

**Rule.** No `git push`, no PR or issue creation, no release, no tag push, no writes to any
external service — ever — without asking first and getting a yes. Read-only remote calls
(`git fetch`, `git ls-remote`) are fine. Approval is per-action: a yes for one push is not a
standing yes for the next.

**Why.** Remote actions are the hard-to-reverse ones. A pushed commit is public and may be
mirrored, cached, or pulled before it can be corrected.

**How to apply.** Commit locally as normal. Then run the C2 audit, then present the audit result
and ask. Wait for approval. Only then push.

---

## C2 — Adversarial self-audit before requesting a push

**Rule.** Before asking to push, audit the committed changes as a hostile reviewer would, and
report what the audit found — including anything it did *not* clear.

**Why.** Catching a problem before it is published costs one edit; catching it after costs a
public follow-up commit and undermines the "rigor" the project is trying to demonstrate.

**How to apply.** Work the full checklist, then state findings honestly (including "found
nothing" only if the checklist actually ran):

1. **Read the actual diff**, not your memory of it: `git diff origin/main..HEAD`. Review it
   hunk by hunk.
2. **Nothing that shouldn't ship:** no secrets or API keys, no `data/` contents, no build
   artifacts, no absolute local paths (`/Users/...`), no committed notebooks with output blobs.
3. **Claims are verified, not assumed.** Every test asserted to pass was actually run in this
   session and its output seen. If a command was not run, say so.
4. **Each convention in this file is checked against the diff.** Name the ones that applied.
5. **Acceptance criteria met.** For each design-doc task the change claims to complete, the
   stated acceptance criterion is genuinely satisfied — not approximately.
6. **Commit message is accurate.** It claims nothing the diff does not contain, and omits nothing
   the diff does contain.
7. **Anticipate reviewer feedback.** What would a skeptical quant reviewer flag? Common hits:
   silent fallbacks that mask failure, untested branches, magic numbers without provenance,
   nondeterminism, anything that could smuggle in look-ahead, over-broad `except`, an
   approximation presented as exact.
8. **Docs current:** `progress.md` has a dated entry, and any new decision or blocker is logged
   in `decisions.md` / `blockers.md`.

---

## C3 — Keep the orchestration docs current as part of the work

**Rule.** Finishing a unit of work includes updating `progress.md` (dated entry), plus
`decisions.md` and `blockers.md` when either changed. Not a separate cleanup pass later.

**Why.** These files are the memory across agent sessions. Stale files are worse than absent
ones, because they are trusted.

**How to apply.** Use real dates (`YYYY-MM-DD`), newest entry first. Never write a relative date
like "yesterday" — it becomes meaningless on re-read.

---

## C4 — Surface design-doc gaps; never silently work around them

**Rule.** When the design doc is ambiguous, internally inconsistent, or blocked on an `OPEN`
design decision, say so and log it. Do not quietly pick an interpretation and proceed as if the
doc had specified it.

**Why.** The doc is the spec of record. An undocumented divergence between doc and code is a
defect that surfaces much later, usually as a wrong result rather than a build error.

**How to apply.** Log the gap in `blockers.md` (if it blocks) or `decisions.md` (if resolvable
now with a stated default). If the resolution changes what the design doc says, update the doc's
Status line in the same change.

---

## C5 — Don't implement ahead of the milestone; stub honestly

**Rule.** Build what the current milestone's task specifies. A placeholder must be obviously a
placeholder — never a plausible-looking implementation that has not been validated.

**Why.** Milestones are ordered so each one is independently demonstrable (Risk R3). A
half-finished M4 living inside M2 destroys that property and hides which parts are actually tested.

**How to apply.** If a stub is needed for the toolchain to work end to end (as `version()` does
for the C++ core), keep it trivially small and say in the surrounding docs that it is a stub.

---

## C6 — Tests encode the design doc's acceptance criteria

**Rule.** Each task's acceptance criterion from Section 5 becomes at least one test, asserting
the thing the criterion actually states.

**Why.** It makes "is this task done?" mechanically checkable instead of a judgment call, and it
is the mechanism by which the rigor claims (no look-ahead, determinism) stay true over time.

**How to apply.** Reference the task ID in the test module docstring, so a reader can trace test
back to spec.

---

## C7 — Everything runs through `uv run`

**Rule.** CMake, Ninja, ctest, pytest, and ruff all live in `.venv` and are invoked as
`uv run <tool>`. There is no expectation of a system CMake.

**Why.** CMake was not installed system-wide on this machine; making the toolchain a project
dependency keeps the build reproducible for anyone who clones the repo with only `uv` present.

**How to apply.** `uv run cmake ...`, `uv run ctest ...`. If a bare `cmake` invocation appears in
docs or CI, it is a bug.

---

## C8 — Rebuild the extension explicitly after touching `cpp/`

**Rule.** Run `uv sync --reinstall-package perpcarry`. Do not re-enable
`editable.rebuild` in `pyproject.toml`.

**Why.** scikit-build-core's rebuild-on-import writes a CMake cache pointing into uv's ephemeral
build-isolation environment. uv deletes that environment after the sync, so the next import fails
on a stale `ninja` path. This was hit and diagnosed on 2026-08-12.

**How to apply.** Python tests that exercise C++ behavior are only meaningful after a reinstall;
if a C++ change appears to have no effect, this is the first thing to check.

---

## C9 — `data/` and `build/` never enter git

**Rule.** Everything under `data/` is re-derivable from the M1 ingestion scripts and stays
gitignored. Same for build output.

**Why.** Exchange data is large and re-downloadable; committing it bloats the repo permanently
and invites accidental redistribution of licensed vendor data (relevant if OD-2 resolves to a
paid tick-data vendor).

**How to apply.** Point tests at `tmp_path` or override `PERPCARRY_DATA_ROOT`; never write test
fixtures into `data/`.

---

## C10 — A rigor claim that CI does not run is a claim about the past

**Rule.** Every invariant the project asserts — no look-ahead, fixed-seed determinism, both build
paths working — is encoded as a check CI runs, not as a one-off manual verification. Keep the
per-PR tier fast and network-free; heavy or network-dependent checks go to the nightly tier.

**Why.** M0's criteria were verified once by hand on one machine, and nothing would have caught a
regression. The project's entire value proposition is demonstrated rigor; an unenforced checklist
is exactly the thing a skeptical reviewer discounts. Equally, CI that is slow or flaky stops being
believed, which is the same failure in a different costume (design doc R6, R7).

**How to apply.** Mark network tests (`@pytest.mark.network`) and deselect them by default. When
adding a test that demonstrates an invariant, confirm it runs in the per-PR tier — or, if too
slow, that it is wired into nightly rather than nowhere.

---

## C11 — Verify CI steps locally before trusting them

**Rule.** Run each workflow step's exact command locally before committing the workflow. Do not
reason about whether a step works.

**Why.** Writing `FETCHCONTENT_BASE_DIR` as a workflow `env:` var looked correct and would have
passed CI green forever while caching an empty directory — CMake does not read that variable from
the environment, only from `-D`. A green run is not evidence that a step does what it claims;
only running it and inspecting the result is.

**How to apply.** Export the same variables the workflow sets, run the commands verbatim, and
check the *side effects* (did the cache directory actually get populated?), not just the exit code.
