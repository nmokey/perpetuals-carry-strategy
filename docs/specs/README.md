# Specs

One spec per task from `design-doc.md` Section 5. The design doc is the seed; a spec is what a
task becomes when it is about to be built.

## Layout and naming

```
specs/M<n>/<TASK-ID>-<short-slug>.md      e.g. specs/M2/M2-T1-order-book-core.md
```

One file per task, in the subdirectory for its milestone. Keep the slug short and descriptive.

## Workflow

1. **Before writing a spec**, check the task's `Depends On` column. If it names a bolded
   `OD-N resolved`, confirm that OD's status in `decisions.md` first. If it is still `OPEN`,
   resolve it (recording a D-entry and updating the design doc) or log the blocker — do not write
   the spec around an unresolved decision (convention C4).
2. **Copy `TEMPLATE.md`** and fill it in. The design doc's acceptance criterion for the task is
   copied verbatim into the spec, then expanded into concrete, checkable tests (C6).
3. **While building**, keep the spec accurate. If the approach changes, the spec changes with it —
   a spec that describes a design nobody built is worse than no spec.
4. **When done**, mark the spec Complete, add a dated entry to `progress.md`, and log any
   decision or blocker that came out of the work.

Specs are written just-in-time, one milestone ahead at most. Writing all of M5's specs during M1
guarantees rewriting them.
