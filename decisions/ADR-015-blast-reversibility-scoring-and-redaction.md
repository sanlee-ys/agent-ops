# ADR-015: Blast × reversibility scoring, the exit-2 backstop, and redact-and-allow

**Status:** Accepted — 2026-08-11. Records the design of
`hooks/destructive-command-guard.py` and `security/secret-redaction-guard.py`.
**Scope:** This repo (the guard chain). Repo-local ADR per the two-tier
convention.
**Related:** [`ADR-007`](ADR-007-guard-the-invariant-not-the-verb.md) — the
invariant rule this design must not contradict;
[`ADR-013`](ADR-013-guard-canonicality-line.md) — canonicality of the guard
files.

## Attribution

The three designs here are ported from the public
[secguard](https://github.com/random1st/secguard) project (Apache-2.0 with the
Commons Clause). We ported the designs and the calibration data. We did not
copy the Rust code; both guards are original Python, written for this repo's
hook conventions (stdin JSON payload, fail-open parse, per-command override
tokens, Cursor stdout compatibility).

## Context

The guard chain judged a command in two ways, and a gap sat between them:

1. `published-history-guard.py` asks the repository whether a command drops a
   published commit (ADR-007). It covers only that invariant.
2. The auto-mode semantic classifier judges the command text. It judges by
   verb, so `git reset --soft` and `git reset --hard` look alike. The
   2026-07-26 incident record shows both errors: the classifier blocks safe
   resets in some sessions, and it allowed the reset that started the
   incident.

Local destruction — a working-tree wipe, `git clean -f`, a recursive delete —
has no repository invariant to ask. The damage is to state that no ref
records. That class needs its own guard, and a one-severity verb list is the
design ADR-007 rejects. Separately, the credential guard could only refuse; a
literal secret inside `tool_input` failed the call when a rewrite could save
it.

## Decision

### 1. A blast × reversibility scoring matrix

`hooks/destructive-command-guard.py` gives each rule id a two-axis score:
`blast` (0-4, scope of damage) and `reversibility` (0-4, recovery cost).
`risk = blast + (4 - reversibility)`. Risk buckets into allow (<=1), warn
(2-3), confirm (4-5), and block (>=6). The construction is monotone on both
axes. The headline: `git reset --soft` scores (0, 4) and is allowed;
`git reset --hard` scores (1, 0) and asks for confirmation.

Overrides are configurable per rule, per cell, and per score, through
`guard-scoring.json` next to the deployed hook (or the path in
`AGENT_OPS_GUARD_SCORING`). A config that does not parse is ignored with a
stderr note, so a bad config cannot wedge the shell.

**How this sits next to ADR-007.** ADR-007 stands: where an invariant exists,
ask the repository, and this guard never duplicates the published-history
check. The scoring table covers the class where no invariant exists. There,
the honest options are a verb list with one severity or a verb list with a
calibrated, testable damage estimate per rule. We chose the second. The rule
ids make each estimate explicit, and the test suite pins all 25 matrix cells
and both monotonicity properties.

### 2. The exit-2 backstop

Claude Code honours hook exit code 2 in every permission mode, including
`bypassPermissions`, where it ignores JSON ask/deny verdicts. So a
block-bucket verdict must do both: print the JSON deny verdict for harnesses
that read stdout, write the reason to stderr, and `sys.exit(2)`. Both new
guards do this. The three existing redline guards already exited 2 on a
block, so this codifies existing behaviour as policy rather than changing it.
A confirm (`ask`) verdict degrades to allow under `bypassPermissions`; that
limit is recorded in the hook docstring, not hidden.

### 3. Redact-and-allow for secret values

`security/secret-redaction-guard.py` closes the value half of the credential
posture. `credential-guard.py` judges credential *paths* and must block — a
redacted path breaks the command. This guard judges credential *values*: it
recursively walks `tool_input`, replaces each matched secret with
`[REDACTED:<rule_id>]`, and returns an allow verdict with
`hookSpecificOutput.updatedInput` set to the rewritten input and a
`permissionDecisionReason` naming the count and the types. The call proceeds
without the secret.

The pattern set is high-precision and prefix-anchored (AKIA…, ghp_…,
sk-ant-…, a private-key block, a user:password URL). No entropy heuristics: a
false redaction silently corrupts a tool call, and the path guard still
stands behind this one. Emitted markers never re-match, so a double scan is
idempotent.

**Vendor split.** Rewrite-and-allow needs a hook contract that honours
`updatedInput`. Codex does not, and it ignores `ask`, so `--target codex`
turns a finding into a deny verdict plus the exit-2 backstop. The target is a
deploy-time flag, per vendor.

**Placement.** The chip asked for a mode on the credential guard. We put the
value scanner in a sibling file instead of inside `credential-guard.py`
(2,000 hardened lines, nine measured revisions). The two guards judge
different objects (paths vs. values) with different verdicts (block vs.
rewrite), and a separate file keeps each independently testable and
deployable. The posture is one chain; the files are two.

### 4. Two rollout behaviours, both guards

- **Shadow mode.** `AGENT_OPS_GUARD_SHADOW` truthy: log the `would <action>`
  decision to stderr and enforce nothing. Values are never logged, only rule
  types. This is the safe-rollout path: run in shadow, read the log, arm.
- **Asymmetric fail-open.** An unparseable command segment allows, as every
  guard here does — except when its text contains a destructive trigger
  keyword (`rm -rf`, `--hard`, `clean -f`, `-delete`, …). That case escalates
  to confirm. Failing open on exactly the text that names a destructive
  operation is the one asymmetry worth paying for.

Override token for the destructive-command guard: `RISK-OK`, per-command,
matching `STAGE-ALL-OK` / `REWRITE-MAIN-OK` / `MASK-OK`.

## Verification

`python -m unittest discover -s tests` green. The new suites drive both
guards as the harness does — a real PreToolUse JSON payload on stdin — and
assert on exit codes, stderr, and the stdout JSON verdicts. Pinned: the
25-cell matrix snapshot, both monotonicity invariants, the soft/hard reset
split, the override token, shadow-mode truthy and falsy values, all three
config override layers plus the bad-config path, redaction idempotency, the
codex deny path, and the clean-prose negative cases.

Not verified, stated per posture limit 7: neither guard is wired on a live
machine yet. The machine-config repo's deploy step must add both files (and
the codex `--target` flag on that vendor's wiring) before any of this
enforces anything. `updatedInput` acceptance by the live harness is a doc
claim until it is measured — the same honest state `config-change-guard.py`
records.

## Consequences

- Locally destructive commands now carry a calibrated verdict instead of one
  classifier severity. Soft resets stop paying the hard-reset tax.
- A pasted secret no longer fails the call; the call proceeds redacted, and
  the reason string teaches what was caught.
- Two new files join the deploy set; a stale deployed copy is the standing
  drift hazard (posture limit 6) and now has two more chances to happen.
- The confirm bucket is advisory under `bypassPermissions`. Only the block
  bucket holds everywhere, via exit 2.
