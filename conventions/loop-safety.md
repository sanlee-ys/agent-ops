# Agentic loops do not inherit merge authorization (hard rule)

An **agentic loop** is any harness that re-invokes an agent on the same prompt
until a condition holds. The Ralph pattern and a `/loop` slash command are both
examples. A loop is not a long session. It is a session that restarts, and each
restart loses the judgement the last one built.

The standing merge authorization says: when the checks are green and a revert
undoes the change, merge the pull request without asking. That rule is safe for
a human-supervised session, because a person reads the summary at the end. **A
loop has no such end.** Give a loop the same authorization and it merges its
own drift: iteration 4 merges the mistake that iteration 3 introduced, then
iteration 5 builds on the merged mistake and calls it the base state. Nothing
in the loop can see that the ground moved, because the loop's only memory of
the last iteration is the repository itself.

So the rule is a subtraction, not an extension:

> **A loop never inherits the standing merge authorization. The authorization
> stops at the loop boundary and must be re-earned by the rails below.**

## The rails

A loop may run only with all seven. They are not a menu.

1. **A `max_iterations` cap.** The loop stops after a stated number of
   iterations, whatever it has achieved.
2. **A budget cap.** The loop stops after a stated spend or token count.
3. **Both caps live in the outer script, not in the prompt.** A prompt is an
   instruction to the thing being bounded, so it is a request, not a limit. The
   model that ignores the rest of the prompt ignores the cap in it. Put the
   counter in the code that calls the model, and make the call site enforce it.
4. **Stuck detection.** The loop compares each iteration's failure signature
   with the last two. On three consecutive identical failures the loop halts
   and writes a state file — the failing command, its output, the iteration
   number, and the branch. A loop that repeats one failure is not converging;
   it is spending the budget to learn nothing.
5. **Worktree isolation.** Each loop runs in its own git worktree. A loop that
   shares a working tree with a live session stages that session's uncommitted
   work, which is the failure
   [`hooks/git-staging-guard.py`](../hooks/git-staging-guard.py) exists to
   block. See [`parallel-sessions.md`](parallel-sessions.md).
6. **The loop pushes to its own branch only, never to `main`.** A direct push
   to `main` removes the last review surface the loop has.
7. **The guard hooks stay wired.** A loop must not run behind a
   permission-bypass flag. A bypass flag is a fleet redline under
   [`ADR-012`](../decisions/ADR-012-capability-parity-and-the-guard-obligation.md),
   and a loop is the worst place to remove a guard: it repeats the blocked
   action instead of reconsidering it.

## What a loop may do with its output

A loop has two permitted end states.

**Accumulate.** The loop opens pull requests and merges none of them. A human
or a supervising session reviews the stack. This is the default, and it is the
correct choice whenever the work has no mechanical verifier.

**Merge under a mechanical gate.** The loop may merge one pull request only if
**both** conditions hold:

- a **mechanical verifier passes** — a test suite, a linter, a schema check, or
  an eval with a threshold. A green CI run that only proves the job started is
  not a verifier; see
  [`agent-success-signals.md`](agent-success-signals.md); and
- the **diff stays inside the declared blast-radius files**. The loop declares
  the file set before the first iteration. A diff that touches a file outside
  that set halts the loop, even when the verifier is green. Scope growth is the
  drift signature, and it appears before the tests break.

Either condition alone is not enough. A verifier proves the change works. The
blast radius proves the change is the change that was asked for.

## Why the blast radius is a hard gate and not a warning

The verifier answers "does the repository still work?". It never answers "is
this the task?". A loop that rewrites an unrelated module and keeps the suite
green passes every automated check that exists, and the failure is only visible
as a file list. That is why the file set is declared **first**, by the operator,
and compared mechanically — a set derived from the diff after the fact is a
description of what happened, not a limit on it.

This is the same shape as
[`ADR-007`](../decisions/ADR-007-guard-the-invariant-not-the-verb.md): guard the
invariant that must hold, not the verb that usually breaks it.

## The check

Before you start a loop, name its `max_iterations`, its budget cap, its
worktree, its branch, and its blast-radius file set. If you cannot state all
five in one sentence each, the work is not ready for a loop. Run it as a
session instead.

The decision and the alternatives weighed are in
[`../decisions/ADR-016-loops-do-not-inherit-merge-authorization.md`](../decisions/ADR-016-loops-do-not-inherit-merge-authorization.md).
