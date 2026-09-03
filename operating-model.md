# Operating model

**Compressed 2026-08-01.** The long-form version of this document (239 lines)
is in git history (`git log --follow -- operating-model.md`). It was thinned
on a simple test: a practice that matters here either earned a mechanical
backstop (a hook, a CI gate, a synced convention) or gets invoked as a skill
— and those live in `hooks/`, `security/`, `conventions/`, and `vendors/claude/skills/`,
not in an essay. What follows is the part that is genuinely load-bearing as
prose.

## DCB: Direction, Contracts, Bar

The standing frame for directing any AI coding tool: **I set the direction,
the contracts, and the bar; the model does most of the typing; I verify the
output against the real repos before anything ships.** Direction — what the
work is for and what "done" means (not delegable). Contracts — the specific,
checkable rules the tool is bound to, named up front. Bar — what has to be
true before output counts as shipped, checked against the actual repo state,
never against confident prose. The three are no longer a separate pre-flight step.
Each one holds a fixed slot inside every playbook of the
[`work` skill](vendors/claude/skills/work/SKILL.md), which replaced the `dcb` skill on
2026-09-03.

## Fleet routing

One control plane owns integration; specialist lanes earn handoffs through a
different model family or a materially better surface. Harness and model
family are separate axes: moving the same model into another product changes
tools, not judgment independence. Routine work gets one agent plus a
deterministic verifier; consequential work gets independent challenge and
review. The four-vendor allocation is
[`ADR-010`](decisions/ADR-010-claude-led-four-vendor-orchestration.md); every
vendor reads and writes, and guard wiring rather than lane shape is what
bounds them
([`ADR-012`](decisions/ADR-012-capability-parity-and-the-guard-obligation.md)).
Telltale observes the fleet but never routes it.

## Session protocol

- **Pre-flight, every session:** sync main, check CI is green (report a red
  `main` unprompted), scan for the same work in flight, claim one concern →
  one branch → one PR, cut along files nothing else touches.
- **Two cadences:** ambiguous or consequential work runs in small steps with
  a stop after each; already-decided bounded work runs to completion and
  reports at the end. Picking the wrong cadence is itself the failure mode.
- **Parallel sessions** (multiple machines, shared remotes) can't see each
  other's uncommitted work; the remote main is the only coordination point.
  The rules that follow from that — and the two that earned mechanical
  backstops — are [`conventions/parallel-sessions.md`](conventions/parallel-sessions.md),
  [`conventions/branch-hygiene.md`](conventions/branch-hygiene.md),
  [`hooks/git-staging-guard.py`](hooks/git-staging-guard.py), and
  [`hooks/published-history-guard.py`](hooks/published-history-guard.py).

## Reasoning effort

Effort and model tier are independent knobs; effort is cheaper, reach for it
first, and match it to how expensive it is to be wrong, not how large the
task is. **Unmeasured heuristic** (recorded 2026-07-26, no A/B run): the
moment an effort choice justifies a decision rather than a setting, it gets
measured first, under
[`SYS-002`](https://github.com/sanlee-ys/architecture/blob/main/decisions/SYS-002-model-tier-standard.md)'s
bar. The top tier stays a last resort, un-defaulted rather than banned.
