# CLAUDE.md

Guidance for AI agents working in **agent-ops** — the canonical home for the
agent operating layer, across every vendor in the fleet (see
[`decisions/ADR-002-public-first-canonicality.md`](decisions/ADR-002-public-first-canonicality.md)
for canonicality and
[`decisions/ADR-008`](decisions/ADR-008-agent-ops-rename-and-vendor-layer.md)
for the rename and vendor layout; fleet routing is
[`decisions/ADR-010`](decisions/ADR-010-claude-led-four-vendor-orchestration.md)).

- **Vendor adapters:** [`vendors/`](vendors/) — root is vendor-neutral
  canon; harness-specific material (skills, instruction-file wiring,
  inter-agent channels) lives per vendor. Contract:
  [`vendors/README.md`](vendors/README.md).

- **Operating model & session protocol:** [`operating-model.md`](operating-model.md).
- **Security posture & the credential guard:** [`security/posture.md`](security/posture.md),
  [`security/README.md`](security/README.md).
- **Conventions:** [`conventions/`](conventions/). Most are shared cross-repo
  blocks — single-sourced here, mirrored into sibling repos' `CLAUDE.md` as
  compressed pointers; propagate or drift-check with
  `python scripts/sync-shared-blocks.py [--check]`. A convention with no marker
  block is agent-ops-local, e.g.
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
  never frame JSONL with Node `readline`. And from a sweep that re-raised a
  closed question:
  [`settled-rulings-suppress-findings.md`](conventions/settled-rulings-suppress-findings.md)
  — a decided question is not a finding; drop it before it reaches a report,
  and never let a chip restate it as an open tradeoff. And from a rename that
  wedged the session that ran it:
  [`hooks-gate-their-own-repair.md`](conventions/hooks-gate-their-own-repair.md)
  — **this repo hosts live hooks.** `~/.claude/hooks/credential-guard.py`,
  `git-staging-guard.py` and `published-history-guard.py` are symlinks into
  [`security/`](security/) and [`hooks/`](hooks/) on provisioned machines, so
  moving, renaming or deleting this clone dangles them instantly, and a
  missing `PreToolUse` script is a hard error — `Bash`, `Read` and `Write` all
  start failing, and every possible repair is one of those calls. Re-point the
  links in the *same* command as the move, or move it from a shell outside the
  session.
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
