# ADR-013: Fleet redline guards are canonical here; machine-config hooks are canonical in the private machine-config repo

**Status:** Accepted — 2026-08-09.

**Extends** [ADR-002](ADR-002-public-first-canonicality.md), which moved
`credential-guard.py`'s canonical source into this repo but named only that one
file. **Relates to** [ADR-012](ADR-012-capability-parity-and-the-guard-obligation.md),
whose whole safety argument rests on guard wiring.

## Context

Four `PreToolUse`/`ConfigChange` hooks now enforce fleet redlines, and they are
not all canonical in the same place:

| Hook | Canonical today |
| --- | --- |
| `credential-guard.py` | this repo, `security/` (ADR-002 §4) |
| `git-staging-guard.py` | this repo, `hooks/` |
| `published-history-guard.py` | this repo, `hooks/` |
| `fanout-guard.py` | the private machine-config repo, `claude/hooks/` |

Nothing wrote down *why* the split falls where it does. ADR-002 decided one
file; the next two followed it by precedent; `fanout-guard.py` went the other
way with no recorded reason. So when `config-change-guard.py` was written
(2026-08-09) there was no rule to apply, and it landed nowhere: a deployed copy
at `~/.claude/hooks/` plus a derived copy under
[`vendors/claude/plugin/`](../vendors/claude/plugin/), a tree whose own README
declares it unversioned and draft. A guard whose entire subject is *whether the
guard chain is still wired* was itself the one guard with no canonical source.

That is not a filing problem. Per ADR-012 guard wiring is the whole of the
safety control, and a control with no system of record cannot be reviewed,
cannot be drift-checked, and cannot be provisioned onto a second machine.

## Decision

**The dividing line is what the hook protects, not what kind of file it is.**

1. **A hook that enforces a fleet redline is canonical in this repo.** Redlines
   are credentials and secret stores, published history, and consequential
   mutations — the class ADR-012 says must be enforced mechanically, per
   vendor. These live in [`hooks/`](../hooks/), except `credential-guard.py`,
   which stays in [`security/`](../security/) where ADR-002 put it and where its
   README and `posture.md` already sit.
2. **A hook that enforces a local preference, cost control, or machine
   convenience is canonical in the private machine-config repo.** It is a
   property of San's setup, not of the fleet's safety posture.
   `fanout-guard.py` is the worked example: it bounds *spend* against a
   personal subscription, which is a budget, not a redline. Its placement is
   hereby ratified rather than left as an accident.
3. **The machine-config repo keeps NO copy of a redline hook** — not even a
   condensed one. This is ADR-002's rule generalised. A hand-maintained partial
   copy of a security control drifts silently and gives false coverage, which
   is strictly worse than none; it is the drift class recorded as limit 6 in
   [`posture.md`](../security/posture.md). The setup scripts already implement
   the alternative for the other three: prefer a sibling clone of this repo,
   then fetch canonical from GitHub, then install nothing and say so loudly.
4. **`config-change-guard.py` is therefore canonical at
   [`hooks/config-change-guard.py`](../hooks/config-change-guard.py).** It
   enforces the integrity of the guard chain itself, which is the redline
   underneath every other redline.

## Why this repo, for a hook about a private machine's settings file

Two objections are worth answering, because both point the other way at first
glance.

**"It only ever reads a local settings file, so it is machine config."** What it
reads is local; what it *enforces* is not. Its `REQUIRED_GUARDS` list is a
literal enumeration of this repo's redline controls, and its block message cites
ADR-012 by name. Put it in the private repo and the rule and its rationale sit
in two repos that cannot reference each other — the public one cannot name the
private one at all (ADR-001).

**"Publishing it tells an attacker exactly which guard to unwire."** This is
`posture.md`'s founding question and the answer is unchanged: the threat model
is non-adversarial agent mistakes, and anyone with local code execution has
already won. The guard's value is that an agent tidying `settings.json` gets
stopped, not that the list of guards is secret — and that list is already public
in this repo's directory listing. Keeping the enforcement private while the
thing it enforces is public buys nothing and costs the review this repo exists
to invite.

The file is clean against the ADR-001 publication boundary: it names no private
repo, no employer term, no local user path, and no credential-shaped string.
`scripts/redline-guard.py` checks that mechanically at commit time.

## Consequences

- The setup scripts in the machine-config repo grow a fourth
  clone-then-fetch-then-warn block, identical in shape to the three that exist.
  Their existing settings-vs-filesystem audit covers the new path automatically,
  because it is derived from `settings.json` rather than from a hardcoded list.
- The derived copy under `vendors/claude/plugin/hooks/` stays, and is now a
  *derived* copy like the other four there rather than the only one. Its README
  table is updated to name this file as canonical, and its "should be promoted"
  note is discharged.
- `config-change-guard.py` lands with
  [`tests/test_config_change_guard.py`](../tests/test_config_change_guard.py) so
  the per-guard suite convention holds; CI picks it up through
  `unittest discover`, which executes the guard and so covers parsing too. The
  matching `py_compile` line in `ci.yml` was deliberately **not** in this change —
  a concurrent change was editing that same block, and one shared file is not
  worth a merge conflict for a check the suite already implies. **Discharged
  2026-08-09:** that change landed (`scripts/settings-toggle.py`), and the
  `hooks/config-change-guard.py` line now sits with its two siblings in the
  syntax-check step.
- **What this ADR does not settle:** whether the `ConfigChange` event actually
  fires and whether its block verdict actually vetoes on this harness. Both are
  unmeasured as of this date, for the reason recorded in
  [`hooks/README.md`](../hooks/README.md). Canonicality is a filing decision and
  does not depend on the answer; **crediting the guard in `posture.md` does**,
  and that credit is deliberately withheld until it is measured.
