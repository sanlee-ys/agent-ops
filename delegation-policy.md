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

If the experiment log ever restarts, it restarts here with the missing axis
named in the original recalibration: outcomes across multiple sessions and
executor models, not another single-day sample.
