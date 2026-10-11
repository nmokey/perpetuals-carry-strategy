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

**How to apply.** `tests/conftest.py` has an autouse fixture repointing `PERPCARRY_DATA_ROOT` at a
per-test tmp directory, so this holds by construction rather than by discipline. Do not remove it,
and do not bypass it by passing an explicit path into `data/`.

**Why it is enforced structurally.** Anything calling `cached_fetch` writes into `data/.cache/`
under the *archive's own filename*. A test serving a synthetic payload therefore leaves a file a
later real backfill will happily reuse — fabricated trades entering the research corpus, named and
shaped exactly like genuine archive data. This happened during M1-T1: a 199-row punched fixture sat
in `data/.cache/0GUSDT-trades-2026-08.zip` until the pre-push review found it. Checksum
verification would catch it for sources that publish one, but that is a second line of defence, not
the first.

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

---

## C12 — Prove a test fails on the defect it exists to catch

**Rule.** A passing test is not evidence of anything. Before trusting a test, break the code it
covers and confirm it goes red. Prefer assertions with every tolerance switched off.

**Why.** The original M0-T4 round-trip test passed while every float in storage was silently
perturbed. Two defaults did it: `assert_frame_equal` uses `check_exact=False` (rtol 1e-5), and the
test coerced dtypes with `.astype(...)` before comparing — so it could not see a precision loss or
a dtype regression. Demonstrated on 2026-08-12 by injecting a 1e-9 relative error: the old suite
reported 7 passed, the rewritten one caught it. For a project whose output is numbers, a storage
layer that quietly perturbs the fifth significant figure is exactly the defect that survives to
the writeup.

**Read detections, not failure counts.** A mutation is caught if at least one test fails *and* its
name identifies the cause. A single defect tripping five tests is overlap — five tests sharing a
code path — not five independent checks, and it is not evidence of better coverage.

**A fix needs its own mutation check.** Code added in response to a review is exactly as likely to
be under-tested as code written the first time — arguably more, since it arrives without a spec.
Three fixes from the M1-T1 review shipped with tests that passed while the fix was deleted.

**How to apply.** Round-trip and equality assertions use `check_exact=True` and `check_dtype=True`.
Never coerce or normalise a value before comparing it — if the code under test changes something,
assert *that specific change* explicitly so a future change in the behaviour fails loudly. When
adding tests for a new component, mutate the implementation in a scratch copy and confirm each
test fails; revert before committing.

---

## C13 — Test the rendering where rendering is the property

Learned 2026-08-20, from M1-T5's one surviving mutation.

Some values matter for how they are *written*, not only for what they *are*. A derived step size
of `Decimal("1.0")` equals `Decimal("1")` and `Decimal("1E-4")` equals `Decimal("0.0001")`, so no
equality assertion can distinguish them — but the value is written into a committed file that is
reviewed in diffs, and unstable rendering is noise on the one artifact whose job is to be stable.

**The trap is subtler than it looks.** The first attempt at a test for this read the *committed
JSON file* and asserted its strings were canonical. That file already held the normalised text, so
it passed whether or not the code still normalised — it was asserting a property of a stored
artifact, not of the code that produces it. The test that actually catches the defect derives a
fresh value and pins `format(value, "f")`.

**How to apply.** When the property under test is formatting, serialisation, ordering, or any
other choice that equality cannot see, assert it on freshly produced output, never on a stored
artifact that a previous good run wrote. Ask: *if I deleted the line that does this, would the
fixture still make my test pass?* See also [[C12]] — this is the same failure mode as a mutation
surviving, found the same way.

---

## C14 — Cheap invariants pay out where you did not aim them

Learned 2026-08-20, from M1-T3.

`fetch_book` checks that every row in a downloaded day carries that day's UTC date. It was written
for one reason: the whole file is written into a single Hive partition directory, so a stray row
would be misfiled rather than landing in its own partition. That is a narrow, slightly paranoid
guard against something the vendor was already verified not to do.

What it actually caught was a **caching bug two layers away**. Every Tardis URL for a symbol ends
in the same basename — the date is in the path — so a filename-keyed download cache served June's
file for July. Nothing about that is a date-column problem, and no schema, checksum or integrity
check could see it: the file was a perfectly valid book day, just the wrong one. The stray-day
guard tripped because the rows said June and the request said July.

**How to apply.** When a check is cheap and the property is genuinely invariant, write it even when
the failure it names looks impossible — its value is not confined to the mode you had in mind. Two
corollaries: state the invariant in terms of *what must be true*, not *what you fear went wrong*,
because that is what makes it catch unrelated causes; and when such a guard fires, do not assume
the cause is the one in its error message. See [[C12]] for the complementary discipline — proving a
test fails on the defect it was aimed at.

---

## C15 — Derive test fixtures from the code under test, not from a parallel copy of it

Learned 2026-08-20, from M1-T4.

`validate_data` located funding partitions with `fetch_funding.DATASET`, which is `"fundingRate"` —
the *archive's* name for the dataset, the one that appears in URLs. The fetcher stores under
`funding/`. The validator therefore looked in a directory that had never existed, found no
partitions, and reported the corpus healthy.

The whole suite passed, **including a test written specifically to assert that every check actually
runs against a populated corpus** — because the fixture had independently hard-coded the same wrong
path. Two copies of the same mistaken assumption agreed with each other, and the disagreement with
reality was invisible until a real corpus was pointed at the code.

**How to apply.** When a test needs to know where the code writes, what it names things, or how it
lays data out, get that from the code — call its `store()`, import its constant — rather than
restating it in the fixture. A restated layout is a second source of truth that can only ever agree
by luck, and it fails in the direction that looks like success. Where a value must be shared between
a writer and a reader, export it from the writer as a named constant so both sides import one thing.
Relatedly, prefer running at least one check against genuine data before believing a green suite —
see [[C12]] on tests that pass without exercising what they claim.

---

## C16 — Put fixture values off the boundary where two rules agree

Learned 2026-08-29, from M2-T3.

The clean-run sampler anchors its midday target to the UTC day the first compared image falls in,
not to that image's own timestamp. Both rules were plausible; only one is right, because a real
export opens a little *after* midnight (`0GUSDT` 2026-06-01 opens at 00:00:01.245) and a
first-image anchor drifts the target past the midday image.

The test fixture used a day starting at exactly 00:00:00.000. At that value the two rules compute
the identical target, so the test passed under either, and the mutation that swapped one for the
other **survived** — the only mutation of seven that did. Moving the fixture's open to
00:00:00.137, which is simply what real data looks like, made the two rules disagree and the
mutation was caught immediately.

**How to apply.** When a value in a fixture sits on a boundary — zero, an exact day or hour
boundary, an empty collection, the first or last element — ask whether the rule under test and its
plausible wrong twin would give the same answer there. If they would, the fixture cannot see the
property, however thorough the assertions look. Prefer values drawn from what the real input
actually looks like; the round-numbered ones are the ones that hide things. This is [[C12]]'s
discipline applied to fixture *values* rather than to whether a test exists at all, and it is why
C12 must be run rather than assumed: the survival is what exposed the degenerate fixture.
## C17 — Set datetime resolution before extracting integer timestamps

Learned 2026-10-09, while building the M6-T1 synthetic funding fixture.

**Rule.** Convert datetime arrays to their intended unit before using integer storage.
`DatetimeIndex.asi8` reflects the array's resolution; it is not guaranteed nanoseconds.

**Why.** The fixture divided `.asi8` by 1,000,000 assuming nanoseconds. On this environment's
pandas 3 datetime range that produced seconds labeled as milliseconds. Strict timestamp/date
checks caught the fixture before it could authorize any research input. A fixed divisor can
silently change meaning across datetime constructors or library versions.

**How to apply.** For millisecond epochs, use `times.as_unit("ms").asi8`. Retain integer
archive timestamps directly when their source unit is explicitly validated. Keep schema/date
and endpoint tests; the unit conversion alone does not establish chronological correctness.

## C18 — Predictive checks can fail on data generated by the true model

Learned 2026-10-09 during M6-T2 synthetic posterior checks.

**Rule.** Distinguish exact implementation assertions from probabilistic adequacy diagnostics.
Do not change a seed or widen an empirical acceptance interval merely to make every
posterior predictive check look favorable.

**Why.** A correctly simulated Gaussian AR(1) produced a residual minimum outside a 95%
conditional replication interval while parameter recovery, dispersion and residual dependence
checks passed. Some exclusions are expected even under a true model; demanding every
exploratory statistic pass encourages seed selection and hides the meaning of coverage.

**How to apply.** Pin algebra and units with roundoff-only tolerances; test known parameter
recovery with explicit synthetic seeds. Preserve and report all empirical checks, including
unfavorable ones. A descriptive tail-check exclusion does not imply broken posterior algebra,
and passing code tests do not establish predictive adequacy on the research corpus.

## C19 — Forecast before admitting the current settlement

Learned 2026-10-10 during M6-T3 rolling forecast verification.

**Rule.** In a causal forecast API, current and future funding values must remain opaque
until their observation is admitted. Keep retrospective scoring separate from inference.

**Why.** A path that updates or validates the current funding rate before producing its
forecast already depends on the outcome it predicts. Even rejecting a corrupt current
value before returning the prediction demonstrates that dependence. Validating a whole
archive for corpus admission is a separate operation from chronological model updates.

**How to apply.** Produce the forecast from prior observed history, then admit the current
settlement. Poison both a future suffix and the current target value, withhold future rows,
and shuffle future rows; predictions before admission must match exactly. Score cumulative
outcomes afterward, with explicit endpoint/cadence exclusions. Never use their future
availability to decide whether the earlier forecast is emitted.

## C20 — Keep PRs atomic by milestone task

User instruction, 2026-10-10, after accumulated M5–M7 work was published together.

**Rule.** One PR covers one named milestone task, such as M7-T4, with its implementation,
tests and directly related documentation. Combine tasks or milestones only at the user's
explicit request.

**Why.** The accumulated publication spanned 93 files and multiple milestones, making
review, attribution and selective rollback unnecessarily difficult.

**How to apply.** Isolate and commit each task as it is completed, before accumulating
the next task's changes. Name the task in its PR title and description, state its acceptance
checks and remaining gates, and keep unrelated cleanup or independently useful fixes in
separate PRs. Dependencies can use stacked task PRs; dependency order does not justify
bundling multiple tasks. This scope requirement does not grant standing permission to
push or create PRs; honor the user's existing authorization for each action.
