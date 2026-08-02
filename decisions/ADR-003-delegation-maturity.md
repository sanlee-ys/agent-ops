# ADR-003: Path to full delegation maturity ("getting to 10")

**Status:** Accepted — 2026-07-06.
**Scope:** This repo (the Claude operating layer). Repo-local ADR per the
two-tier convention — cross-repo decisions live in the public `architecture`
repo as SYS-NNN; a SYS entry pointing here would be a follow-up, not part of
this ADR.

## Context

A 2026-07-06 session rated the current state of Claude-operating maturity at
**9/10**, on evidence across this repo: the `incidents/` postmortems (the four
credential-exposure events in one week and the mechanical guard that ended
them, plus the private-repo annexes that carry the redacted specifics), the
fan-out cost-control guard (incident
[`2026-07-02-uncapped-premium-fanout.md`](../incidents/2026-07-02-uncapped-premium-fanout.md)),
the parallel-session coordination protocol in
[`operating-model.md`](../operating-model.md), and the
[credential-guard](../security/credential-guard.py) postmortems.

This ADR captures the plan to close the remaining point, plus a deliberately
deferred backlog **not to start until it's closed**.

## Definition of 10

A new-shaped failure gets caught by a control that was built *proactively*, not
discovered by a postmortem afterward — and a defined class of work can be
delegated at high autonomy with a measured, acceptable rework rate.

The 9→10 gap is discipline and verification, not tooling surface. Every phase
below trades prose for a mechanical control or a measured number.

## Phase 1 — Kill the secrets class structurally

The credential-exposure series (three of the four events the *same* PAT leaking
through a *different* tool or command shape each time) is the only remaining
gap with **live risk attached**. Close it structurally rather than one leak
shape at a time.

**Status as of 2026-07-07:** primary desktop migrated (PAT off plaintext,
platform keystore blob + wrapper, verified live). The laptop's migration script
is written and dry-tested, not yet run. Guard rewrite and adversarial CI suite
not started (blocked earlier on this repo's access in one session; unblocked
now).

1. **Secret out of every plaintext file, on every machine.** Desktop done,
   laptop pending — the private config repo's handoff doc and migration branch
   record the exact state and scripts.
2. **Rewrite the credential guard from a command-shape denylist to a
   path-based default-deny.** Block on the *target path* being read
   (`~/.claude.json`, `.env*`, SSH keys, etc.) regardless of which tool or
   command shape reaches for it. Must cover content-mode `Grep` specifically,
   not just `Read`/`Bash` — a 2026-07-04 postmortem finding
   ([`2026-07-04-github-pat-read-grep-leak.md`](../incidents/2026-07-04-github-pat-read-grep-leak.md)).
3. **Adversarial test suite in CI:** one test per bypass shape from the four
   2026-07-02..04 incidents, so a future bypass is caught by CI, not by a fifth
   incident.

**Exit criterion:** secret material in no plaintext file anywhere; guard test
suite green in CI; 30 days of live use with zero credential prints.

## Phase 2 — Rule-surface diet

Every rule in a `CLAUDE.md` is context a session carries every turn *and* prose
that must be kept in sync by hand. The link-verification block currently
copy-pasted into eleven repos' `CLAUDE.md` files is the visible symptom.

1. **Single-source shared blocks.** Extend the hook-sync script (or a sibling)
   to manage `CLAUDE.md` sections the same way it manages hooks: canonical text
   in one place, marker comments in consumers, a `--check` drift mode wired into
   CI. **Decided in build (2026-07-06):** the canonical home is *this repo*
   (`conventions/`), public — not the private config repo the draft assumed.
   Six consumers are public and a public `CLAUDE.md` pointing at a private repo
   both 404s for outsiders and discloses that the private repo exists; claude-ops
   is already the operating-layer canon (ADR-002) and resolves for everyone.
2. **Prune by the enforcement test.** For every rule, ask whether it's
   mechanically enforced (hook / CI / pre-commit). If yes, shrink the prose to a
   one-line pointer at the enforcer. If no and it matters, build the enforcer
   first, *then* shrink the prose. Unenforced prose duplicating a control is
   exactly how a provisioning script's stale embedded copy went undetected.
3. **Measure it.** Token-count each `CLAUDE.md`, set a per-repo budget, and
   track it over time like an eval metric instead of letting rule mass grow
   silently.

**Exit criterion:** shared blocks single-sourced with a drift check; zero rules
duplicating a mechanical control; total `CLAUDE.md` token mass down materially.

**Measured (2026-07-06).** The 40% figure the draft floated assumed the rule
surface was bloated with duplication. The audit disproved that: across the 11
`CLAUDE.md` files (~9,885 tokens) there was exactly *one* truly fleet-wide
duplicated block (`links-verify`, in 10 repos); everything else is legitimate
per-repo content. Single-sourcing that block plus compressing the one remaining
rule that duplicated a mechanical control (career's fan-out cap) took the mass
down **~16%** without deleting a single useful doc. Reaching 40% would have
meant gutting real per-repo guidance — a worse outcome than a slightly higher
token count. So the revised target is qualitative, not 40%: the low percentage
reflects low duplication, not an unmet goal. The structural win — edit the rule
once, `--check` catches drift, no rule re-argues an enforced control — is the
deliverable; the token drop is a side effect. The one piece left is wiring
`--check` into automated CI (it runs locally today, like `sync-claude-hooks`).

## Phase 3 — Calibrated delegation

The actual last point. Autonomy level should be set by the strength of
*automated verification*, not by trust or feel — the public portfolio repo's
`mobile-qa.cjs` gate is the existing proof of the pattern (a verifier earns the
autonomy).

1. **Write a delegation policy:** task classes × autonomy levels
   (plan-and-approve → autonomous-with-verify → autonomous multi-session with
   an integrator), each level gated on which verifier covers it.
2. **Run it as an experiment** across the next ~10 substantive tasks: assign an
   autonomy level up front, log the outcome (accepted as-is / minor rework /
   major rework).
3. **Recalibrate on the data:** task classes with a clean record move up a
   level; classes generating rework get a verifier built before being trusted
   with more autonomy again.

**Exit criterion:** written policy grounded in ≥10 logged outcomes; at least one
task class running at full autonomy with <20% rework; every autonomy promotion
justified by a verifier, not a feeling.

**Status (2026-07-06): exit criterion met.**
[`delegation-policy.md`](../delegation-policy.md) holds the 3-rung ladder (plan →
autonomous+verify → orchestrated fan-out), a task-class-to-verifier table, and an
experiment log of **10 outcomes** with **Recalibration 1**. Security-control /
infra code is confirmed at full autonomy (L1) with 0% rework across 5 tasks; the
recalibration is deliberately conservative about the rest (single-session sample,
so promotions require n ≥ 3). Every confirmation is tied to a named verifier.
Phase 3 is closed on the build side.

## Deferred backlog — do not start until Phase 1–3 close

Explicitly scope-gated in the 2026-07-06 session as premature until the above
lands. Listed here so the idea isn't lost — **not** as a queued task:

- New Agent SDK projects / custom subagent types beyond what already exists.
- New Workflow-tool patterns beyond the ones already documented (adversarial
  verify, judge panel, loop-until-dry, multi-modal sweep, completeness critic).
- Additional Claude Code skills beyond the current set (handoff, fan-out cost
  estimation, hook-sync, etc.).

**Rationale for the gate:** none of these move the maturity number right now —
the gap is in discipline and verification, not in tooling surface. Revisit this
list only after Phase 1–3's exit criteria are all met.

### Backlog disposition — 2026-07-06 (gate now open)

Phases 1–3 are closed on the build side, so the gate above is lifted. A
follow-up brainstorm of candidate claude-ops scripts was triaged with San.
Open ≠ auto-queued, so each was dispositioned explicitly:

- **Generic stale-generated-file CI gate — QUEUED for a build session.**
  *Built 2026-07-10:* [`scripts/check-generated-drift.py`](../scripts/check-generated-drift.py)
  + the reusable `generated-drift.yml` workflow; consumer wiring in
  [`scripts/README.md`](../scripts/README.md).
  Generalizes the learning-notes fix (its `generated-files` CI job): run the
  repo's build, `git diff`, fail if committed generated artifacts drifted from
  source. Deterministic (no fuzzy judgment), reusable across every repo that
  commits build output (portfolio, the architecture portal, learning-notes,
  graphify outputs). The only per-repo variable is the build command + the
  watched paths — a small config, not new logic per repo. Low design risk;
  Sonnet/Opus build once scoped. It's a distinct multi-repo deliverable, so
  it's its own session, not folded into this one.
- **`redline-guard.py` portability — INVESTIGATED, parked.** Unlike
  `credential-guard.py` (which generalized cleanly — see PR packaging it for
  external use — because credential *shapes* are universal), redline-guard's
  policy is intrinsically owner-specific: the owner slug is hardcoded and its
  job is "don't leak *this* owner's identifiers into *this* public repo." The
  engine (scan staged diff → mask → block) is generic, but externalizing it
  means fully extracting owner-slug + all identifying terms into config (only
  half-done today via `.redlines.local`) and shipping engine + an example
  config — more surgery than the credential-guard packaging, for lower payoff.
  Not worth it now.
- **"Lint CLAUDE.md for unenforced rules" — REJECTED as a script; folded into
  the periodic assisted audit.** Deciding whether a natural-language "never X"
  rule *is* enforced by some hook/CI is a fuzzy mapping — an LLM-judge task,
  not a deterministic linter. A regex version would be false-positive soup and
  Goodhart bait (the exact failure mode this ADR is about). It belongs in the
  config/memory audit cadence as an assisted step, not a CI gate.

## Sequencing

**Phase 1 first.** It's the only phase with live risk attached (an active
credential-leak class) and is worth roughly half the remaining point on its
own. Phases 2 and 3 follow once the secrets class is structurally dead.
