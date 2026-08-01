# ADR-004: Git automation in a shared clone targets its ref explicitly, or refuses to act

**Status:** Accepted — 2026-07-25. Records the design of the memory-sync hook's
v6 fix and the rule generalised from it.
**Scope:** This repo (the Claude operating layer). Repo-local ADR per the
two-tier convention — a cross-repo SYS entry would be a follow-up, not part of
this ADR.
**Related:** [`debug-notes/2026-07-25-memory-sync-orphaned-index-lock.md`](../debug-notes/2026-07-25-memory-sync-orphaned-index-lock.md) (reclassified from `incidents/` 2026-08-01)
— the same hook, a **different** root cause. See
[Why this is a decision and not a second postmortem](#why-this-is-a-decision-and-not-a-second-postmortem).

## Context

The `SessionEnd` hook that mirrors Claude Code's auto-memory into a private
config repo does its git work in two halves. It commits with a pathspec commit
scoped to its own memory directory, and then pushes `origin main`.

Those two lines carry an assumption nobody wrote down:

- `git commit` lands on **whatever branch is checked out**.
- `git push origin main` sends the **local `main` ref**.

They are the same object only while `main` is the checkout. Nothing in the hook,
and nothing in git, enforces that. It is simply true most of the time, and
silently false the moment any session checks out a branch.

That assumption had been in the hook since v1 and went unnoticed through three
prior bugs and two rounds of hardening, because the condition that exposes it is
invisible in the code and only shows up in a shared clone.

Every session working a given project shares **one** clone, and those sessions
routinely run in parallel. A sibling session moving the checkout mid-session is
not a hypothetical — it is the normal working pattern. It happened on
2026-07-25: one session created a branch, a sibling checked out `main` underneath
it, and the first session's memory commit landed on `main` rather than on its own
branch. That is the **benign** polarity of the bug, and it is the only one that
has ever actually fired.

### The harmful direction

Reverse it and the same line of code destroys data:

1. The checkout moves **onto** a feature branch.
2. The memory commit lands on that branch.
3. `push origin main` pushes a `main` that does not contain the commit.
4. The v5 catch-up push compares `refs/heads/main` only, so it never sees the
   commit and never heals it — the exact self-healing mechanism written to
   recover stranded memory has no visibility into this strand.
5. A later squash-merge plus branch-delete **destroys the commit outright**.

Content survives only by the accident of being swept into someone's PR diff,
which is not a recovery mechanism — it is the *other* failure this operating
layer already has a guard against.

The same confusion sits in `merge --ff-only origin/main`, which appears in both
the session-start pull and the session-end push path. That merges into whatever
is checked out too, so on a feature branch it quietly fast-forwards a session's
branch onto `main` behind its back.

## Why this is a decision and not a second postmortem

Two reasons, both worth stating because the temptation was to append this to the
existing postmortem and be done.

**The root causes are different.** That postmortem — through both v4 and its v5
follow-up — is about **teardown kills**: a hook process dying part-way through a
multi-step git sequence, in one window and then in another. Every fix in it is a
healing fix, because a process being killed mid-write cannot be prevented. This
is a plain **wrong-target** bug. No kill is involved. The code does exactly what
it was written to do, on the wrong object. Filing it under the same postmortem
would blur two mechanisms that need different fixes and teach different lessons.

**Nothing was lost.** The bug is latent, and the one real observed event happened
to have the benign polarity. There is no impact section to write, no timeline to
reconstruct, no duration. Writing it as an incident would mean inventing severity
the record does not support. The honest shape is a decision note: here is an
invariant that was never true, here is what was chosen instead, here is the rule.

## Decision

**v6 gates the git half on the checkout.** When `HEAD` is not `main` — a feature
branch or a detached `HEAD`, which are not distinguished because the caller only
cares that it is *not* `main` — there is no add, no commit, no push.

Nothing is lost by skipping. The hook's file-mirroring half has already run and
written the memory files into the working tree, so the change simply waits there
for the next session that ends on `main`, which commits the whole accumulation.
The `merge --ff-only` is gated the same way in both places it appears.

**The v5 catch-up push is deliberately *not* gated.** It compares and pushes
`refs/heads/main` and never touches `HEAD`, so it is correct regardless of what
is checked out — a session sitting on a feature branch still heals a commit that
a killed sibling stranded on local `main`. Gating it would have removed working
recovery for no reason.

That asymmetry is the most useful thing in this ADR. The catch-up push was
written **ref-explicitly** when it was built, and it is the one piece of this
hook's git handling that needed no change at all. It was already immune. That is
not luck; it is what naming the ref buys.

**The skip is logged**, but only once past the check for pending changes, so an
idle session ending on a branch stays silent. A silent stall is precisely the
failure mode the previous two versions were about, so a gate that stalls sync
without saying so would have re-created the problem it was written to avoid.

## Options considered

**(a) Commit onto `main` regardless of the checkout.** Correct in every case,
via `commit-tree` / `update-ref` plumbing. Rejected as real machinery for a hook
whose whole design posture is "boring, fail-open, minimal". It is also the same
shape as the private-index approach the hook's own docstring already rejects,
for reasons recorded in the earlier postmortem's "two wrong fixes" section. The
seemingly cleaner variant — a second worktree pinned to `main` — degrades back
into plumbing anyway, since git refuses to check out `main` in a second worktree
while the primary already has it.

**(b) Skip the git half, keep the disk mirror. — CHOSEN.** Trivial, fails open,
and matches the file's existing posture. Its cost is real and accepted: sync
stalls for as long as a long-lived branch stays checked out. That cost is what
the log line exists to make visible.

**(c) Also push the current branch. — DISQUALIFIED.** Pushing a branch carries
the human's WIP commits along with the memory commit, and this hook's entire
promise is that it only ever moves its own narrow pathspec. An option that
breaks the tool's central guarantee is not a tradeoff, it is a different tool.

## The rule

Generalised, and the reason this is written down publicly rather than left in a
commit message:

> **In a shared clone, any automation that commits to `HEAD` but pushes a named
> ref carries an unstated invariant — that the named ref is the checkout.
> Nothing enforces it, and it is silently false whenever a branch is checked
> out. Either target the ref explicitly on both sides, or refuse to act when the
> invariant does not hold.**

Three things make this worth generalising beyond one hook:

1. **The failure is polarity-dependent, so testing finds it only half the time.**
   Same bug, same line; one direction is a harmless misfiling, the other is
   deletion at squash-merge time. Observing the benign one teaches you nothing
   about the severe one, and the benign one is what you are likely to observe
   first.
2. **A shared clone makes "which branch is checked out" someone else's
   variable.** Any reasoning of the form "this runs at session end, and *this*
   session is on `main`" is not a fact about the process — it is a fact about
   whatever a sibling session did most recently.
3. **Ref-explicit code is verifiably cheaper.** The catch-up push named
   `refs/heads/main` on both sides of its comparison and survived this bug
   without a line changed, while everything HEAD-relative in the same file
   needed a gate. That is direct evidence for the style, in the same file, on
   the same day.

The rule is deliberately an *either/or*. Targeting the ref explicitly is the
stronger answer and is right when the automation genuinely must act. Refusing to
act is the cheaper one, and is right when the work can safely wait — which, for
anything that has already been written to disk, it usually can.

## Verification

The committed regression suite grew from 21 checks to 34, all passing. The six
new cases assert against the **bare remote** rather than a local tracking ref,
because a tracking ref can look correct when nothing actually left the machine —
the same discipline the v5 tests adopted.

Verified by mutation, not just by passing: with both gates removed, 8 of the new
checks fail. One case demonstrates the loss concretely — a new memory file
committed while a feature branch is checked out never reaches `main` at all.

A test that passes against the fixed code proves nothing on its own. A test that
fails against the *unfixed* code is the one that will still be doing work in a
year.

## Consequences

- Memory sync now has a defined stall condition: it does nothing while a
  non-`main` checkout is in place. On a long-lived branch that window is long.
  The log line is the mitigation, and the accepted deal is a visible stall over
  an invisible strand.
- Cross-machine sync latency is now coupled to branch discipline — merge fast and
  delete the branch, which is already the standing rule for other reasons.
- The catch-up push remains the only part of the hook that acts while a branch is
  checked out. That is intentional, and it is safe **because** it names its ref.
  Any future change that makes it HEAD-relative reintroduces this bug.
