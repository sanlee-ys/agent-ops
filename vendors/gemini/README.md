# Antigravity adapter (Gemini family)

Google Antigravity (`agy`) is the active consumer Gemini-family harness in the
fleet. Gemini CLI remains relevant only for Gemini Code Assist
Standard/Enterprise or API-key use; it is not the consumer subscription
surface.

Role in the fleet (ADR-010, amended by
[`ADR-012`](../../decisions/ADR-012-capability-parity-and-the-guard-obligation.md)):
Antigravity is a **measured Gemini-family lane** — parallel research, broad
audits, browser/Google-stack work, capacity overflow, and a Gemini third
opinion when Claude and Codex disagree. It is not the default implementer,
because Claude holds that role, not because Antigravity is held back from it.

**Capability is not the boundary.** Per ADR-012 this lane reads and writes
like every other. The earlier "read-only by default, prototypes in a
disposable worktree" posture is retired: it was a capability restriction
standing in for a control, and a restriction is not a control. What bounds
this lane now is guard wiring — see [Guard wiring](#guard-wiring) below,
which is an open obligation rather than a caveat.

## Operating rule

> Claude owns implementation and integration; Codex owns independent
> consequential challenge/review; Cursor owns bounded IDE/UI work;
> Antigravity supplies measured Gemini research, overflow, and third-opinion
> value; San verifies against live repository state.

### Anti-routing

- Do not route a long refactor to Antigravity merely to exercise the
  subscription.
- Do not use Claude or GPT inside Antigravity when model-family diversity is
  the reason for the handoff.
- Do not let Antigravity and another writer touch the same file or generated
  artifact in parallel.
- Do not use an Antigravity self-report as the verifier for its own work.
  This survives ADR-012 untouched: it is an author/reviewer independence
  rule, not a capability limit.

## Instruction-file wiring

- **Global standing instructions:** `~/AGENTS.md`.
- **Project instructions:** workspace-root `AGENTS.md` and `CLAUDE.md`.
- **Skills:** built-ins plus project `.agents/skills/`.

The global file is hand-mirrored across harnesses. Treat it like a shared
block: verify the compact fleet pointer and worktree instructions rather than
assuming another product's syntax applies here.

## Harness and channel

- **Harness:** Antigravity CLI and IDE (`agy`).
- **Models:** Gemini Flash/Pro for this lane; model identifiers evolve.
- **Subagent primitives:** `invoke_subagent`, `define_subagent`,
  `send_message`, and `manage_subagent`.
- **Inbound, headless:** `agy -p "<prompt>"` (aliases `--print` and
  `--prompt`), with `--output-format text|json|stream-json` when a caller
  needs structured capture.
- **Permissions:** the persisted store is `~/.gemini/antigravity-cli/settings.json`,
  holding `permissions.{Allow,Deny,Ask}`. All three are live — deny rules are
  CEL-evaluated with a dedicated denial reason, not decorative. The default
  `toolPermission=request-review` is an **LLM-based** reviewer that judges
  consequence rather than verb, so an explicit `Deny` floor is worth having
  beneath it (ADR-007).
- **Print mode ignores allow-rules.** In headless mode, tools requiring
  approval are auto-denied regardless of `Allow`, and the CLI directs the
  user to `--dangerously-skip-permissions`. Reasoning about `agy -p` from
  `settings.json` is reasoning about the wrong file. Never use a
  permission-bypass flag as fleet wiring.
- **`--sandbox` and `--mode plan` do not bound writes.** `--sandbox` is
  documented as *terminal* restrictions only; `--mode plan` was measured
  permitting a write. Neither is a containment mechanism — see
  [`debug-notes/2026-08-04-agy-flags-that-do-not-restrict.md`](../../debug-notes/2026-08-04-agy-flags-that-do-not-restrict.md).

## Transfer packet

```text
Repo:
Branch or PR (pushed):
Exact revision:
Concern:
Mode: research/audit | third opinion | implementation
Files in scope:
Out of scope:
Frozen brief or question:
Verification already run:
Return findings/artifacts to:
```

The source of truth is the branch, PR, diff, and exact revision. Findings go
to an inspectable file; San is never asked to relay prose between harnesses.

## Guard wiring

| Fleet policy | Claude Code | Antigravity |
|---|---|---|
| `credential-guard.py` | PreToolUse wired | **Not wired** |
| `git-staging-guard.py` | PreToolUse wired | **Not wired** |
| `published-history-guard.py` | PreToolUse wired | **Not wired** |
| `redline-guard.py` (pre-commit) | Applies at commit | Applies when the target repo has the hook |

**This table is the whole of the safety argument now.** Under ADR-012 the
read-only default that used to compensate for these gaps is gone, so each
**Not wired** row is an open obligation, not a caveat.

**The mechanism exists; it is unbuilt.** Antigravity supports `hooks.json`
with a `PreToolUse` event: a tool-name matcher, an external command handler
receiving the tool call as JSON on stdin, and a `"decision": "deny"` that
hard-blocks execution. The hook manager runs on every launch and reports
`loaded 0 named hooks from 0 hooks.json file(s)` — zero because none exist
here, not because none can. Guard parity is therefore a build task, and
ADR-010's "until tool-time guard parity exists" was never the blocker it
read as.

**Interim posture, stated honestly:** between ADR-012 and wired guards, this
lane has full capability and no tool-time controls. That is a known, dated
risk San accepted, not an oversight.

**The permission store is un-versioned machine state.** `settings.json` on a
given machine is the real policy; nothing in this repo constrains it. Per
the machine-state audit principle, a reference config belongs here once the
guard wiring defines what it should contain.

## Telltale

Antigravity is live in both telltale surfaces:

- the statusline reads vendor-reported model, context, quota buckets, agent
  state, branch, and folder from the documented stdin payload;
- the HUD reads session metadata from the on-disk corpus but does not invent
  quota or cost fields the store does not persist.

Telltale observes this lane. It does not decide when to invoke it.

## Delegation level

The gate is verifier strength, not vendor trust — the same rule
[`delegation-policy.md`](../../delegation-policy.md) applies to every
harness. Under ADR-012 these levels are keyed to what covers the work, not
to what this lane is allowed to touch:

- Research/audit with an inspectable report: L1 autonomous.
- Third opinion at a real fork: L0; San rules the decision.
- Implementation against a frozen contract: L1 when a deterministic verifier
  covers it. Integration by a different agent remains the rule for the same
  reason it always was — an agent's self-report does not verify its own
  work (see Anti-routing), not because this vendor is less trusted.
- Broad subagent fan-out: L2 with an explicit scope/cap and one integrator.

Rationale: [`ADR-010`](../../decisions/ADR-010-claude-led-four-vendor-orchestration.md).
Adapter contract: [`../README.md`](../README.md).

