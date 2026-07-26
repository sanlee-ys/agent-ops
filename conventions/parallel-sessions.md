# Working across parallel sessions (hard rule)

Canonical home for the parallel-session coordination rule shared across the
repo fleet. Consumer repos carry a compressed inline restatement wrapped in
`<!-- shared:parallel-sessions -->` markers plus a pointer back here; this file
is the full text and rationale. Edit here, then propagate with
[`../scripts/sync-shared-blocks.py`](../scripts/sync-shared-blocks.py).

Extracted 2026-07-26 from two repos that had each grown their own near-identical
copy. The rule itself is older: it was written after parallel sessions in the
classifier repo built the same CI workflow three times (PRs #4/#5/#6) and forked
off a stale `main`, causing conflicts that cost more than the workflow did.

## The premise everything follows from

A session — web, desktop, or a second window — runs in its own container and
**cannot see another session's uncommitted work**. Two sessions asked the same
question will independently reach the same answer and independently build it.
`main` is the only shared coordination point, so anything not on `main` does not
exist as far as another session is concerned.

## The rules

1. **One concern per session → one branch → one PR.** If the deliverable doesn't
   fit in a sentence, it's two sessions. Don't wander into adjacent cleanup.
2. **Check open PRs and branches before starting.** A ten-second look prevents a
   duplicate build. This is the step that would have caught #4/#5/#6.
3. **Branch from fresh `main`, merge fast, delete the branch on merge.**
   Short-lived branches are the whole game — the longer a branch lives, the more
   it drifts.
4. **Serialize the collision hotspots; parallelize only genuinely independent
   work.** Each repo names its own hotspots, but the shape is constant:
   dependency and lock files, the README, workflow files, and anything that
   restructures layout.
5. **Parallelize by independent *file*, not by *task*.** Cut a session per file
   that nothing else touches — never one session per task when the tasks collide
   on one file.
6. **Generated or aggregated files can't be merged.** Build outputs, indexes,
   registries, generated HTML/SVG: when several pieces of work feed one, author
   the content in parallel but keep the *wiring* in one hand — a single
   integrator does the registration and the rebuild once, after the content
   lands.
7. **If many sessions run at once, designate an integrator** that owns merging
   to `main` and keeping it green; the others stay feature-scoped and rebase on
   its merges.

## On branch names

The original rule said to name branches by intent (`fix-industry-labels`), not by
a session slug. That holds **where you control the name** — it makes duplicate
work obvious at a glance in `gh pr list`. It does not hold in hosted sessions,
which are assigned a branch by the harness and cannot rename it. Treat it as a
preference that yields to the environment, not a rule the environment is
violating.
