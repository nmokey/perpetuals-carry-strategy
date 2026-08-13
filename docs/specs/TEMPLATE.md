# <TASK-ID> — <Title>

**Milestone:** M<n>
**Status:** Draft | In progress | Complete | Superseded
**Depends on:** <task IDs, and any OD-N that must be resolved first — with their current status>
**Design doc:** Section <n.n>

## Goal

One paragraph: what this task produces and why the project needs it. If this task's output feeds a
specific downstream decision (an entry threshold, a sizing rule, a reported number), say which.

## Acceptance criteria

Copied verbatim from the design doc Section 5 table:

> <criterion>

Expanded into checkable tests:

| # | Test | Where |
|---|---|---|
| 1 | <what is asserted, specifically> | `tests/...` or `cpp/tests/...` |

## Design

The approach, and the alternatives rejected with reasons. Include interfaces/signatures that other
tasks will depend on — those are the contract, and changing them later is expensive.

## Data

Inputs, outputs, schemas, and where they live on disk. Note any deviation from the schemas in
design doc Section 3, and why.

## Invariants this task must not break

Which of the north-star invariants are in play (look-ahead, determinism, calibrated-not-assumed
costs, stated approximations), and how this task's tests demonstrate they hold. Delete the ones
that genuinely do not apply — do not leave them unaddressed.

## Out of scope

What a reader might reasonably expect here but belongs to a later task. Name the task.

## Open questions

Anything unresolved. If it blocks the build, it also belongs in `blockers.md`.
