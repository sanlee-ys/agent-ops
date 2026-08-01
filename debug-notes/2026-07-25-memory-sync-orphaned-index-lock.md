# Postmortem: a killed SessionEnd hook wedged cross-machine memory sync — silently, for an hour

**Date:** 2026-07-25 | **Duration:** ~65 min wedged (09:14–10:19), diagnosed and fixed same morning | **Severity:** Low-Medium (no data loss; cross-machine memory sync silently dead, and a dirty shared git index left where an unrelated commit could have swept it up)
**Status:** Resolved as v4, then reopened and resolved again as v5 — the same root cause in a different window of the same sequence. See [Follow-up](#follow-up-the-same-root-cause-a-second-window-v5).
**Reclassified 2026-08-01:** debug note, not an incident — no data lost, no exposure, an hour of silent sync lag. Originally filed under `incidents/`; see [README.md](README.md) for the bar.

## Summary

A `SessionEnd` hook that syncs Claude Code's auto-memory into a private
config repo was killed part-way through its git work. It had already run
`git add`; it never finished `git commit`. git left `.git/index.lock`
behind — git never self-clears that file — with the memory files still
staged.

Because every git call in the hook was wrapped in a "best effort" helper
that swallowed failures and returned `None`, **nothing surfaced**. Every
subsequent sync ran, failed against the stale lock, and reported success by
saying nothing at all. Meanwhile the hook's file-copy half kept working
perfectly, mirroring memory files into the repo's working tree, so the
canonical directory on disk looked completely up to date. The repo was
wedged for an hour and was only noticed because an unrelated task happened
to need a commit in that same repo and hit the lock.

The fix is not the interesting part. The interesting part is that **two
plausible, well-reasoned fixes were both wrong**, and a ten-minute
empirical probe killed both.

## Impact

- Cross-machine memory sync was dead from 09:14 to 10:19. Nothing was lost —
  memory kept accumulating in the working tree — but none of it was
  committed or pushed, so a second machine would have seen none of it.
- Every git operation in that repo failed for the duration, for every
  session and every tool, not just the hook.
- Two files sat **staged** in the shared index the whole time. That is
  precisely the dirty-index condition that lets an unrelated `git commit`
  in a sibling session sweep up work that is not its own — a failure this
  operating layer has already had once, from a different cause.
- Zero telemetry. The hook had no log of any kind, so the timeline had to be
  reconstructed from file mtimes and a reflog.

## Root cause

**The proximate cause:** the hook stages and commits as two separate
subprocesses against the repo's *shared* index, so there is a window in
which a kill leaves a lock plus staged files. `SessionEnd` is exactly when
the session's process tree is being torn down, and the helper's own 30s
subprocess timeout *also* kills its child (Python kills the child on
timeout; git does not clean up its lock when killed). Two independent routes
into the same wreckage. Which one fired here is not recoverable — the four
files that would have distinguished them were overwritten by the next
successful sync an hour later.

**The cause that actually mattered:** the hook's stated contract was
*"worst case on any failure, sync just doesn't happen this round, which is
no worse than the status quo."* That was false. This failure mode does not
fail *open*, it fails *dirty*: it leaves persistent state (a lock file, a
staged index) that breaks every future attempt and every other consumer of
that repo. A "best effort, swallow everything" helper is only safe when
failures are **transient**. Here one failure was **self-perpetuating**, and
swallowing it converted a one-off crash into permanent silent breakage.

## The two wrong fixes

Worth recording, because both were plausible enough to ship.

**Wrong fix 1 — "drop the `add`; `git commit -- <pathspec>` stages for you."**
True but incomplete: a pathspec commit **ignores untracked files**. A probe
against a real repo confirmed it silently skipped a new file while correctly
recording a modification and a deletion. Shipping this would have stopped
every *new* memory file from ever syncing — the exact failure class of the
two previous bugs in this same hook.

**Wrong fix 2 — "stop touching the shared index; commit through a private
`GIT_INDEX_FILE`."** This was the recommended fix before it was tested, and
it is worse than the bug. Committing through a private index moves `HEAD`
while the shared index still reflects the old tree. For a *new* file the
shared index has no entry at all, so it then shows a **staged deletion** of
that file — leaving the repo one stray `git commit` away from deleting
memory. It would have converted a visible wedge into a silent data-loss
trap.

Both were killed by a throwaway probe that built a real repo and asserted on
real `git status` output. Cost: about ten minutes.

## Fixes applied

Hook v4:

- **Reap an abandoned `index.lock`** before touching the index, at *both*
  session start and session end, so whichever fires first heals the repo.
  Age-gated well beyond any legitimate hold (git holds that lock for
  milliseconds). Erring high is the safe direction: reaping a lock a live
  git still owns would corrupt that operation, whereas waiting only delays
  recovery.
- **Log every git failure to a file.** This incident was diagnosed from
  mtimes because there was no log at all.
- **A longer timeout on the commit** than on the read-only steps — it is the
  one call whose death orphans the lock.
- **Unstage our own pathspec when a commit fails**, so a survivable failure
  leaves no residue for a sibling's commit to sweep up.
- **Keep the `add`, and say why in the code.** Both rejected fixes are
  written into the module docstring so the next version doesn't re-derive
  them the hard way.

Plus a committed regression suite — 11 checks against real git repos and a
real bare remote, no mocking of git, since all three of this hook's bugs
lived in the seam between its file handling and git's actual behaviour,
which is what a mock would hide. Test 1 reconstructs the incident state
(stale lock + staged files) and asserts recovery.

## Follow-up: the same root cause, a second window (v5)

Later the same day the hook stranded memory again — three times — with none
of v4's symptoms. No stale lock. No line in the new failure log. v4's logging
worked exactly as designed and still said nothing, because **nothing failed**:
the process was killed outright, in a *different* window of the same git
sequence.

The sequence is `add` → `commit` → `fetch` → `merge --ff-only` → `push`. v4
hardened the `add`/`commit` window, because that is the one whose death leaves
a lock behind. But a kill *after* the commit and before the push leaves no
wreckage at all — and for observability that is worse, not better. The commit
sits on the local branch, the working tree is clean, `git log` looks perfectly
healthy, and the memory silently never reaches the other machine. The
condition self-heals only by accident: whenever some *later* run produces
another commit, its push carries the backlog along. That is why all three
strandings eventually reached the remote and not one of them was ever
reported.

**v5** applies this postmortem's own Lesson 4 to that second window: at the
next session start, if the local branch is ahead of its remote, push it. Two
guards keep a catch-up push from becoming a licence to push whatever it finds
— it is skipped unless *every* path touched by the unpushed commits lies
inside the hook's own narrow pathspec, and skipped if the branch has
**diverged** rather than merely advanced, since a fast-forward is the only
push it will ever make. A successful catch-up is logged *even though nothing
failed*, because it is the only evidence that the kill ever happened.

The pathspec guard earned its keep within the hour. While v5 was being built,
a parallel session in the same clone moved the checkout, and the fix's own
commit briefly landed on the local `main` branch — precisely the ahead-by-one
condition the catch-up fires on. The guard refused it: a hook-code change is
not memory. Without it, the next session start would have silently pushed
unreviewed code to `main`.

The regression suite grew from 11 checks to 21. The new ones assert against
the **bare remote** rather than a local tracking ref, because a tracking ref
can look correct when nothing was actually sent.

### What this changes about the lessons above

Lesson 4 was right, and was under-applied. This postmortem named "prefer
healing over preventing for teardown-time work" and then healed exactly one
window — the window that had just bitten. The generalisation it should have
drawn:

6. **When a teardown-time failure mode turns up in one window, enumerate
   every window in the sequence.** A kill can land between any two steps of a
   multi-step external-command sequence. The step whose death is *loudest* is
   the one you notice and fix; the step whose death is *silent* is the one
   that keeps costing you, and it will not announce itself next time either.
   Walk the whole sequence and ask of each step: "if the process dies here,
   what says so?" Where the answer is "nothing," that is the next incident.

## What went well

- The wedge was *loud once touched*. Any git write in that repo failed
  immediately and unmistakably. The silence was in the hook's reporting, not
  in git's.
- Removing the lock was gated on evidence, not impatience: no git process
  alive, lock an hour old, and a check that the real index (including a
  sibling session's staged work) survived removal. Deleting a lock some
  other process genuinely owns is how a bad hour becomes a bad week.
- The fix was tested before it was believed. Both candidate designs died on
  contact with a real repo.

## Lessons learned

1. **"Fails open" is a claim about persistent state, not about exceptions.**
   Catching every error only fails open if nothing is *left behind*. Any
   helper that swallows failures needs an explicit answer to "what does a
   half-finished run leave on disk, and does the next run recover from it?"
   Here the answer was "a lock that poisons everything, forever."
2. **A silent failure path in a background hook is a silent failure path
   forever.** The hook ran on every session for an hour, failing every time,
   and produced no signal. Automation that can fail needs somewhere to say
   so — a log line is cheap; reconstructing a timeline from file mtimes is
   not.
3. **Test the fix's *premise*, not just the fix.** Both wrong fixes rested
   on a confident belief about git's behaviour. One probe against a real
   repo falsified both. When a fix depends on "tool X does Y," check that
   X does Y before building on it.
4. **Prefer healing over preventing for teardown-time work.** A hook running
   during process-tree teardown cannot be guaranteed to finish, so designing
   for "never get killed mid-write" is hopeless. Designing so the *next* run
   cleans up after the last one is achievable — and it is the property this
   hook was missing.
5. **A hook with a history of concurrency bugs deserves a committed test
   suite.** This was the third such bug in the same file. The previous fix
   was verified by a script that was never committed, so its guarantees
   protected nothing. Verification that isn't checked in is verification
   that expires.
