# ADR-011: Headless automation and higher parallelism — a staged, gated push

**Status:** Proposed — 2026-08-03
**Extends:** ADR-010 (does not amend it; rule 8 stands until Stage 4's trigger fires)

## Context

ADR-010 settled *who* does the work: one control plane, three specialist
lanes, no orchestrator service. What it deliberately deferred is *how much of
the work runs without a human in the loop*. Rule 8 declined a dispatcher
"until repeated manual routing proves a need" — correct, but it never defined
what proof looks like, which leaves the question to be relitigated ad hoc.

Meanwhile the frontier among heavy agentic-coding users has moved to three
practices this fleet uses only case-by-case and interactively:

1. **Scheduled autonomous runs** — verifiers and sweeps that fire on a clock,
   not when someone remembers.
2. **Event-driven agents** — CI failures and review comments waking an agent
   that acts, rather than waiting in a queue for the next session.
3. **Higher session parallelism** — several concurrent lanes as the steady
   state, not the exception.

The fleet already owns every prerequisite: headless channels on three
harnesses, a delegation ladder gated on verifiers
([`delegation-policy.md`](../delegation-policy.md)), a hard rule for
authorizing CI-triggered agents
([`conventions/agent-trigger-authorization.md`](../conventions/agent-trigger-authorization.md)),
parallel-session rules
([`conventions/parallel-sessions.md`](../conventions/parallel-sessions.md)),
fan-out caps, and an observer (telltale). What is missing is a staged plan
that turns those pieces on without discarding the discipline that built them.

The goal is **throughput per human-minute, measured** — not novelty parity
with the community. The staging below closes the gap as a consequence of
chasing the metric, not instead of it.

## Decision — five stages, each gated on the one before it

### Stage 0 — the ruler (immediately, before anything is automated)

- **Metrics**, measured per week: human-minutes per shipped PR;
  autonomous-merge rate (PRs merged where a verifier, not a human read, was
  the effective gate); concurrent lanes in flight; incident and rollback
  count.
- **A routing log**: one line per dispatch — what, which surface, why,
  outcome. Telltale observes sessions; the log records *decisions*. This log
  is the evidence ADR-010 rule 8 demands before any dispatcher exists.

No stage below activates until the ruler is in place. An automation push that
cannot show its before/after is the uncapped-fan-out incident with a
scheduler attached.

### Stage 1 — scheduled read-only automation (delegation level L1)

Nightly or weekly headless runs of **verifiers that already exist**: the
shared-block drift check, the generated-file drift gate, link gates, eval
reporting arms in the repos that have them. Output is an inspectable report
(an issue, an artifact) — never a write to `main`.

These jobs take no external input — the schedule is self-originated — so the
trigger-authorization gate does not apply. The delegation gate does: every
job wraps an existing deterministic check, which is what makes L1 legal.

### Stage 2 — event-driven agents (headless proper)

The PR-steward pattern, on **one public, low-stakes repo first**: a CI
failure or review comment wakes an agent that diagnoses and pushes to its own
branch; the repo's verifier suite gates the merge.

Hard preconditions, all four, before the first steward turns on:

1. The four-check sender-authorization gate per
   [`conventions/agent-trigger-authorization.md`](../conventions/agent-trigger-authorization.md)
   — untrusted text never authorizes a run, and a check that could not run is
   not a pass.
2. An explicit budget cap per run, per the fan-out rule.
3. A kill switch that is a deliberate act to re-arm (e.g. removing the watch
   label stops the steward; re-labelling is a fresh authorization).
4. **Guard-wired harnesses only** — today Claude Code and Codex. Cursor and
   Antigravity do not get unattended write lanes; that boundary is ADR-010's
   and this ADR does not move it.

Expansion is repo-by-repo, each on a clean month of the previous one.

### Stage 3 — parallelism as steady state

Target: **3–5 concurrent non-colliding lanes** (cloud sessions and
worktrees) as the normal working mode, not the exception. The existing rules
carry over unchanged: concerns claimed before work starts
([ADR-006](ADR-006-claim-the-concern-before-working-it.md)), collision
hotspots serialized, partition by independent file or repo, generated and
aggregate artifacts updated once, last, by the **one integrator** — which
remains Claude Code per ADR-010.

Fan-out stays L2: explicit token caps, single integrator, verifier on the
result.

### Stage 4 — the dispatcher, earned

The trigger that ADR-010 rule 8 left undefined, now defined: the Stage 0
routing log shows the **same-shape manual route recurring ≥3 times per week
for 4 consecutive weeks**. When that fires, amend ADR-010 and build the
thinnest dispatcher that automates *only the proven routes*. Telltale remains
an observer either way — measurement and routing stay separate organs.

Until the trigger fires, no dispatcher is built, and the question is closed
rather than open (see
[`conventions/settled-rulings-suppress-findings.md`](../conventions/settled-rulings-suppress-findings.md)).

## Guardrails (unchanged by this ADR, restated because automation stresses them)

- **No autonomy without a verifier** — the delegation gate rule is the load
  the whole plan rests on.
- **Unattended write access only on guard-wired harnesses.**
- **Untrusted text never authorizes a run.**
- **Every automated lane has a cap and a kill switch.** Failures here meet
  the same incident bar as everywhere else.

## Measurement gate

Each stage gets a dated review roughly four weeks after activation, against
the Stage 0 metrics. A stage that has not moved them is **rolled back, not
accreted** — the same earn-its-keep discipline applied to vendors. "It runs
and nothing broke" is not a pass; the metric moving is the pass.

## Consequences

- ADR-010 rule 8 stands, and now has an explicit evidence trigger instead of
  an open question.
- The fleet gains scheduled and event-driven lanes with **no new shared
  mutable state**: git, CI, and deterministic verifiers remain the only
  coordination and acceptance surfaces.
- Standing costs appear: CI/API spend for scheduled runs and stewards, and
  the routing log is a manual habit until Stage 4 pays it back. Both are
  visible in the Stage 0 metrics, which is where the argument to keep or cut
  them lives.
- The community-comparison question ("are we behind?") becomes answerable
  with a number instead of a feeling — and stops mattering, which is the
  point.
