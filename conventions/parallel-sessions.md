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
8. **Diverged from `main`? Rebase onto it. Never reset back to where you
   started.** See below — this is the rule that was missing on 2026-07-26.

## Recovering from a diverged branch

Added 2026-07-26, after two sessions in one clone raced on `main` and one of them
destroyed the other's pushed commit. That repo is direct-to-main by its own house
rule, so no PR gate stood between the mistake and the remote.

A session that started from an older `main` and finds the remote has moved has
exactly one correct move:

```bash
git -C <repo> pull --rebase        # replay your work on top of theirs
git -C <repo> log --oneline -5     # confirm BOTH sides survived
git -C <repo> push                 # a plain push now suffices
```

**`git reset` back to your starting point is not a recovery from divergence.**
It looks like one — the tree ends up clean and your work is still staged — but
it silently drops whatever landed on the branch while you were working, and the
force-push that necessarily follows is what publishes the loss. That is the
2026-07-26 sequence exactly: a `--soft` reset (locally harmless, correctly
allowed by every gate) followed three minutes later by a
`push --force-with-lease` that erased a sibling session's commit.

Two things follow from that incident, and both are counter-intuitive enough to
be worth stating:

- **`--force-with-lease` is not a safety net here.** Its lease compares the
  remote-tracking ref, and background fetches refresh that ref, so the lease
  passes and the clobber proceeds. Verify with `git ls-remote` — the actual
  remote — or don't claim to have verified.
- **Never `git reset` past a commit you did not author.** In a shared clone you
  cannot tell by looking, so the operative habit is: before any reset that moves
  the branch pointer backwards on `main`, run `git log --oneline @{u}..` and
  `git ls-remote origin main` and know what is in the range.

This is enforced, not just written down: `hooks/published-history-guard.py`
blocks both shapes when the discarded range holds a published commit, with a
`REWRITE-MAIN-OK` override for deliberate rewrites. The reasoning, the options
weighed, and what the permission layer actually did that day are in
[`../decisions/ADR-007-guard-the-invariant-not-the-verb.md`](../decisions/ADR-007-guard-the-invariant-not-the-verb.md).

## On branch names

The original rule said to name branches by intent (`fix-industry-labels`), not by
a session slug. That holds **where you control the name** — it makes duplicate
work obvious at a glance in `gh pr list`. It does not hold in hosted sessions,
which are assigned a branch by the harness and cannot rename it. Treat it as a
preference that yields to the environment, not a rule the environment is
violating.
