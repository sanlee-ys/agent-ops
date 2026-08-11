# ADR-016: An agentic loop does not inherit the standing merge authorization

**Status:** Accepted — 2026-08-11.

**Relates to** [ADR-012](ADR-012-capability-parity-and-the-guard-obligation.md),
which makes guard wiring the only safety control, and
[ADR-007](ADR-007-guard-the-invariant-not-the-verb.md), whose method this
decision reuses. The rule itself is
[`conventions/loop-safety.md`](../conventions/loop-safety.md).

## Context

The standing merge authorization says a session merges a green, revertible pull
request without asking. That rule removed a real cost: a parked pull request
hands unfinished work back to the operator, who must then read a session log to
learn what landed.

The rule was written for a supervised session. A session has one operator, one
summary at the end, and a person who reads it. An **agentic loop** has none of
those. A loop re-invokes the agent on the same prompt until a condition holds,
so its only memory between iterations is the repository state.

Two harness shapes now make loops easy to start: the Ralph pattern, and a
`/loop` slash command that re-runs a prompt on an interval. Neither of them
carries a review step. Both of them run inside a session that already holds the
merge authorization, so without a decision the authorization leaks into the
loop by default.

That leak has a specific failure. Iteration 3 introduces a defect that the test
suite does not cover. Iteration 4 sees a green suite, merges it, and the defect
becomes `main`. Iteration 5 reads `main` as the base state and builds on the
defect. **The loop merges its own drift, and each merge deletes the evidence
that the ground moved.** No iteration can detect this, because detecting it
needs a memory of the intended end state that survives the restart, and the
loop has thrown that memory away.

## Decision

**The standing merge authorization stops at the loop boundary.** A loop must
re-earn the right to merge through seven mechanical rails, and it merges only
under a two-part gate.

The rails, in full in [`conventions/loop-safety.md`](../conventions/loop-safety.md):
a `max_iterations` cap; a budget cap; both caps in the outer script rather than
the prompt; stuck detection that halts on three consecutive identical failures
and writes a state file; one git worktree per loop; pushes to the loop branch
only; and guard hooks wired, with no permission-bypass flag.

The gate: a loop **accumulates** pull requests for review by default, and may
merge one only when a **mechanical verifier passes** *and* the **diff stays
inside a blast-radius file set declared before the first iteration**.

## Why the caps live in the outer script

A cap in the prompt is a request addressed to the thing being bounded. The
model that drifts far enough to need the cap is the same model that is reading
the cap, and it has already shown it does not follow the prompt reliably. This
is the ADR-012 argument applied to spend: a restriction the agent enforces on
itself is not a control. The counter belongs in the code at the call site,
where the loop cannot reach it.

## Why the blast radius is a second, independent gate

A verifier answers whether the repository still works. It never answers whether
the change is the change that was asked for. A loop that edits an unrelated
module and keeps the suite green passes every automated check in the system,
and the only visible symptom is the file list.

Declaring the file set **before** the loop starts is what makes it a limit. A
set derived from the diff afterwards describes what happened; it does not bound
it. This is ADR-007's method: guard the invariant that must hold, not the verb
that usually breaks it.

## Alternatives rejected

**Let the loop merge, and rely on `git revert`.** Rejected. Revertibility is the
test in the standing authorization because a person notices the problem and
reverts it. In a loop, later iterations build on the merged commit, so a revert
stops being a single-commit operation within one or two iterations. The property
the authorization depends on decays with every pass.

**Forbid loops entirely.** Rejected. A loop is the right shape for bounded,
verifier-covered work — the L1 class in
[`delegation-policy.md`](../delegation-policy.md). The gate rule there already
says autonomy follows the strength of the verifier, so the correct answer is to
require the verifier, not to ban the shape.

**Require a human approval per iteration.** Rejected. That deletes the reason to
run a loop, and it reintroduces the exact cost the standing merge authorization
was written to remove.

**Write it as guidance rather than a convention plus an ADR.** Rejected. This
repo's throughline is that a behavioural rule earns a mechanical backstop. The
rails are written as script-level requirements precisely so a future change can
check them, rather than as advice a loop is asked to honour.

## Consequences

- A loop that cannot state its `max_iterations`, its budget cap, its worktree,
  its branch, and its blast-radius file set is not startable. The convention
  says so explicitly, so the refusal has a citation.
- The default loop output is a stack of open pull requests. Review cost moves
  to the operator, and that is the intended trade: it is bounded, and it is
  visible.
- **Unmeasured, deliberately.** No loop harness in this fleet enforces these
  rails today. This ADR states the contract that a harness must meet; it does
  not claim a harness meets it. The rails become credible when a script
  implements them and a test drives that script, in the same way the guard
  hooks earned their credit in [`security/posture.md`](../security/posture.md).
