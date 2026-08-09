# ADR-012: Capability parity across vendors, and the guard obligation it creates

**Status:** Accepted — 2026-08-04
**Amends:** ADR-010 decision 4 and its guard-posture table; ADR-009 decision 4

## Context

A probe of the Antigravity CLI's persisted permission store, run while
building telltale's council mode, found a posture nobody had written down:

- `permissions.Allow` ends in `command(*)` — blanket, unprompted shell.
- `permissions.Deny` and `permissions.Ask` are both **empty**. There is no
  floor of any kind beneath the allow list.
- `allowNonWorkspaceAccess: true` removes the workspace boundary for file
  tools, and the trusted-folder store trusts the whole home directory, not
  just the code root.
- None of the three fleet guards are wired.

Read together: an unprompted agent with home-directory reach, on the one
harness with no tool-time controls. The home directory contains `~/.ssh`,
and it contains `~/.claude/hooks/*`, which are symlinks into this repo — so
the least-guarded vendor sits upstream of the guards protecting the
best-guarded one.

The obvious response was to narrow the grants. San ruled the other way:
**all agents should have read/write capability.** That ruling is the premise
of this ADR, not a question it reopens.

What makes the ruling safe to accept is a second finding from the same
probe. Antigravity *does* have a tool-call interception mechanism — it was
simply never used. Verified in the shipped binary, not inferred from docs:
`hooks.json` supports a `PreToolUse` event with a tool-name matcher, an
external command handler receiving the tool call as JSON on stdin, and a
`"decision": "deny"` that hard-blocks execution. The hook manager runs on
every launch (`loaded 0 named hooks from 0 hooks.json file(s)` appears in
every session log — zero because none exist, not because none can). The
`Deny`/`Ask` arrays are likewise live code, CEL-evaluated with a dedicated
denial reason, not vestigial struct fields.

So the pre-existing contract had the dependency backwards. ADR-010 said
consequential writes stay out of Antigravity *until tool-time guard parity
exists*, treating parity as an unmet precondition. Parity was available the
whole time; nobody had built it.

## Decision

1. **Capability parity is the fleet default.** Every vendor may read and
   write. "Antigravity defaults to read-only" and "keep Cursor's writes
   bounded" are retired **as capability restrictions**. A lane is chosen for
   the value it adds, not for how little damage it can do.

2. **The mitigation moves from lane shape to guard wiring.** The previous
   posture leaned on a restriction as its control. Removing the restriction
   without naming a replacement would leave the guard gap documented and
   uncompensated, which is the failure mode ADR-008 exists to prevent. Guard
   wiring is now the load-bearing control, and it is the only one — **bounded,
   as corrected 2026-08-09, by the guard's own scope.** Measured on the Grok
   lane: a wired hook's deny held under `--permission-mode bypassPermissions`
   and blocked every direct read of a decoy `.env`, while a copy-then-read
   laundering move (out of the guard's scope at the time) still reached the
   credential. "A hook deny survives a permission bypass" is true and is not
   the same claim as "the redlines hold under one". The specific shape is
   closed in guard v2.9; the general point is not, so `bypassPermissions` is
   **not a supported configuration on any lane without a judgment layer above
   the guard**. See `security/posture.md` limit #8 and "What the copy rule does
   and does not buy".

3. **ADR-010's conditional is deliberately inverted, and the debt is
   recorded as debt.** The restriction is lifted *before* parity is built,
   which is a real risk taken knowingly. Between this ADR and wired guards,
   Antigravity and Cursor run with full capability and no tool-time
   controls. That interval is accepted, not overlooked, and it is the
   reason item 4 is an obligation rather than a suggestion.

4. **Antigravity guard parity is now an owed deliverable**, built against
   the `hooks.json` `PreToolUse` contract: a `deny` decision on the same
   redlines `credential-guard.py` already enforces. This is buildable today;
   the mechanism is confirmed present.

5. **Three existing boundaries are untouched by this ADR**, and none of them
   is a capability restriction:
   - **Codex stays read-only on review.** That constraint protects
     author/reviewer independence, not the filesystem. Do not sweep it away
     by keyword match.
   - **Model-family independence** still governs when independence is the
     reason for a handoff (ADR-010 decision 5).
   - **The redlines themselves** — credentials, published history,
     consequential mutations — remain fleet policy for every vendor. What
     changes is that they must be enforced mechanically per vendor rather
     than by keeping a vendor away from the work.

## Measured behavior worth recording

Three findings from the same probe, because each one falsifies a plausible
assumption someone would otherwise make:

- **`--sandbox` does not restrict file writes.** Its documented scope is
  *"a sandbox with terminal restrictions enabled"* — commands, not the
  filesystem. A file write landing under `--sandbox` is the flag working as
  documented, not failing. It is not a containment mechanism for writes.
- **`--mode plan` did not prevent a file write** in the observed probe.
  Unlike `--sandbox`, this one is a genuine discrepancy with the documented
  behavior of an execution mode. Recorded as measured-once and not
  re-verified; see `debug-notes/`.
- **In print mode, settings allow-rules do not apply.** The binary states
  that tools needing approval are auto-denied in headless mode and directs
  the user to `--dangerously-skip-permissions`. So `agy -p` is close to
  binary — heavily auto-denied, or fully unpermissioned. `command(*)` does
  not soften the middle, and the bypass flag is not fleet wiring.

One structural note: the default `toolPermission=request-review` is an
LLM-based permission reviewer, the same shape as Claude Code's semantic
classifier. It judges consequence, not verb — which is precisely why an
explicit `Deny` floor is worth having beneath it, exactly as ADR-007 argues
for guarding the invariant rather than the verb.

## Consequences

- ADR-010 decision 4 and the "Routing consequence" column of its guard
  table are superseded. The "Tool-time fleet guards" column stays true and
  becomes the whole of the argument.
- ADR-009 decision 4's "stays on Claude until parity exists" is superseded
  for the same reason.
- The guard-wiring tables in the vendor adapters are promoted from footnote
  to load-bearing. A **Not wired** row is now the only thing standing
  between a vendor and a redline, so it reads as an open obligation rather
  than a caveat.
- `security/posture.md` is silently Claude-scoped. Under a fleet where every
  vendor writes, that silence is a gap rather than a scoping choice. Naming
  it here; closing it is separate work.
- Delegation levels are unaffected. `delegation-policy.md` already gates on
  verifier strength rather than vendor trust, which is the framing this ADR
  adopts. The one outlier was the Antigravity adapter's own ladder, keyed to
  mode instead of verifier; that is corrected.

## Downstream surfaces

Swept and updated in this change: `vendors/README.md`,
`vendors/gemini/README.md`, `vendors/cursor/README.md`, `README.md`,
`operating-model.md`, `decisions/ADR-009`, `decisions/ADR-010`.

Known to carry the retired posture and **not** updated here — each needs its
own change:

- the global instruction files (`~/.claude/CLAUDE.md`, `~/AGENTS.md`) and
  their versioned copies
- the private fleet strategy document
- the public profile README, which frames Antigravity as research-only
- Cursor's user rules, which live in application storage rather than a file
  on disk and cannot be audited from a repo
