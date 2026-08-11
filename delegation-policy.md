# Delegation policy

**Compressed 2026-08-01.** The v0 policy (2026-07-06) carried a 10-outcome
experiment log and a first recalibration; both are in git history
(`git log --follow -- delegation-policy.md`). The log met
[ADR-003](decisions/ADR-003-delegation-maturity.md) Phase 3's exit criterion
but froze the same day it was written — all 10 outcomes came from one
session, one operator, one day, and no further outcomes were logged. Keeping
a stalled experiment dressed as a living policy was ceremony; what survives
is the rule that was actually being tested, because it is the one part other
repos rely on.

## The gate rule

The autonomy a class of work earns is set by the strength of the *automated
verifier* that covers it — not by trust or feel. A class with a strong
verifier (a test suite, a QA gate, an eval) can run autonomously because a
red build, not a human, catches the failure. A class with no verifier stays
at plan-and-approve, or gets a verifier built first.

## The ladder

- **L0 — plan & approve.** The human is the gate. Default when no verifier
  covers the work, and permanent home of novel design.
- **L1 — autonomous + verify.** Execute end-to-end; a verifier gates the
  result; the human reads the summary.
- **L2 — orchestrated fan-out.** Sub-agents under an explicit token cap
  (`fanout-guard.py` blocks an uncapped one), verifier plus a single
  integrator on the result.

Model tier follows the same measure-first discipline
([SYS-002](https://github.com/sanlee-ys/architecture/blob/main/decisions/SYS-002-model-tier-standard.md)):
escalate only where the task earns it.

## Review findings carry a disposition label

Added 2026-08-11. Design source: Kun Chen's "No Mistakes" pipeline, whose
working idea is that a review is only useful if each finding says **who acts on
it**, and says so at the moment it is written.

The gate rule above sets autonomy for a *class of work*. This applies the same
measure to a *single review finding*, because a finding is where autonomy is
actually spent. A review that returns a flat list makes the applying session
decide, finding by finding, whether to fix or to ask. That session is the
author of the code under review. It is the worst-placed party to make that
call, and it makes it under the pressure to finish.

**Every review finding carries exactly one of two labels.**

- **`auto-fix`** — the fix is safe, mechanical, and does not change what the
  code is meant to do. The applying session fixes it and does not ask. Examples:
  a wrong path in a link, a missed `None` check on a branch the tests already
  cover, a docstring that contradicts the signature above it, a duplicated
  constant.
- **`ask-user`** — the fix touches **intent**. It changes behaviour, a
  contract, an interface, an error message a caller may match on, a tradeoff,
  or anything the reviewer had to guess about. It is escalated, with the
  question stated. The applying session does not decide it.

### Four rules that make the label mean something

1. **The reviewer assigns the label, not the applying session.** This is the
   whole mechanism. Moving the decision to the author reproduces the problem
   the label exists to remove, and the author's bias runs one way: toward
   `auto-fix`, because `auto-fix` is the label that lets the work finish.
2. **An unlabelled finding is `ask-user`.** The default fails closed. A missing
   label is a reviewer who did not decide, and an undecided finding is not a
   licence to act.
3. **The label describes the *fix*, not the severity.** A critical crash with
   one obvious correct repair is `auto-fix`. A cosmetic rename is `ask-user`
   when the name is part of a published contract. Severity says how much the
   finding matters; the label says who is allowed to resolve it.
4. **`auto-fix` does not survive reconciliation failure.** Findings are already
   reconciled against live repo state before any are acted on, because the
   branch may have moved since the review snapshot
   ([`vendors/codex/README.md`](vendors/codex/README.md)). If a finding no
   longer matches the code, it is dropped — not re-derived and applied under
   its old label. The label was issued against a diff that no longer exists.

### Where this does not apply

A finding that matches a **settled ruling** is dropped silently before it is
labelled at all, and it never becomes either class. See
[`conventions/settled-rulings-suppress-findings.md`](conventions/settled-rulings-suppress-findings.md)
— relabelling a settled question as `ask-user` is the polite re-raise that
convention exists to stop, and relabelling it `auto-fix` is worse.

### The honest state

This is a written contract, not a mechanical one. Nothing checks that a review
returns labels, and nothing stops an applying session from treating an
`ask-user` finding as `auto-fix`. Per the gate rule, that means this class of
work stays at the human gate until a verifier covers it. The obvious verifier
is a schema on the review output file; it is not built.

If the experiment log ever restarts, it restarts here with the missing axis
named in the original recalibration: outcomes across multiple sessions and
executor models, not another single-day sample.
