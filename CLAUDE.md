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
  — output from a run that hit a limit is suspect even where it parses. Three
  more came from a second pass over the same project:
  [`agent-facing-contracts.md`](conventions/agent-facing-contracts.md) — an
  agent-facing doc is executed, so say agree/disagree before the diff and draw
  the idempotency line inside every runbook;
  [`agent-trigger-authorization.md`](conventions/agent-trigger-authorization.md)
  — four independent checks before external input reaches a capable agent, and
  a check that could not run is not a pass;
  [`jsonl-splits-on-lf-only.md`](conventions/jsonl-splits-on-lf-only.md) —
  never frame JSONL with Node `readline`.
- **Reference shelf:** [`reference/`](reference/) — worked designs for problems
  this fleet does not have yet (a custom file-edit tool's matching algorithm; a
  hand-written terminal renderer). Not rules; nothing there needs doing. Read
  one only when about to build the thing it describes.
- **Stale-generated-file gate** — reusable CI check for repos that commit
  build output: [`scripts/check-generated-drift.py`](scripts/check-generated-drift.py)
  + the `workflow_call` wrapper in `.github/workflows/generated-drift.yml`
  (consumer wiring: [`scripts/README.md`](scripts/README.md)).
- **Delegation policy** — task classes × autonomy levels, each gated on a
  verifier: [`delegation-policy.md`](delegation-policy.md).
- **Decisions:** [`decisions/`](decisions/). **Incidents:** [`incidents/`](incidents/) —
  held to a severity bar (real exposure, real spend, or a live control
  failing); write-ups below that bar go in [`debug-notes/`](debug-notes/),
  and new entries get classified against that bar at filing time.

This repo is public and guarded by a pre-commit redline check
(`scripts/redline-guard.py`): no credentials, private-repo names, or local
user paths reach a commit.
