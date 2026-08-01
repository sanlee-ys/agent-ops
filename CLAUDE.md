# CLAUDE.md

Guidance for AI agents working in **claude-ops** — the canonical home for the
Claude operating layer (see
[`decisions/ADR-002-public-first-canonicality.md`](decisions/ADR-002-public-first-canonicality.md)).

- **Operating model & session protocol:** [`operating-model.md`](operating-model.md).
- **Security posture & the credential guard:** [`security/posture.md`](security/posture.md),
  [`security/README.md`](security/README.md).
- **Conventions:** [`conventions/`](conventions/). Most are shared cross-repo
  blocks — single-sourced here, mirrored into sibling repos' `CLAUDE.md` as
  compressed pointers; propagate or drift-check with
  `python scripts/sync-shared-blocks.py [--check]`. A convention with no marker
  block is claude-ops-local, e.g.
  [`agent-success-signals.md`](conventions/agent-success-signals.md) — ask what
  an agent tool's green is actually measuring before trusting it — and
  [`branch-hygiene.md`](conventions/branch-hygiene.md) — `delete_branch_on_merge`
  cleans the remote ref only; sweep the local branches at session close. Three
  more are distilled from a read of the public
  [pi](https://github.com/earendil-works/pi) agent harness:
  [`allowlists-fail-both-ways.md`](conventions/allowlists-fail-both-ways.md) — an
  exception list must fail on a stale entry, not just on a violation;
  [`truncation-defers.md`](conventions/truncation-defers.md) — dual line/byte
  limits, direction chosen by where the information is, and always a path to the
  rest; [`truncated-producers-taint.md`](conventions/truncated-producers-taint.md)
  — output from a run that hit a limit is suspect even where it parses.
- **Delegation policy** — task classes × autonomy levels, each gated on a
  verifier: [`delegation-policy.md`](delegation-policy.md).
- **Decisions:** [`decisions/`](decisions/). **Incidents:** [`incidents/`](incidents/).

This repo is public and guarded by a pre-commit redline check
(`scripts/redline-guard.py`): no credentials, private-repo names, or local
user paths reach a commit.
