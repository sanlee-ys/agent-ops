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
which as of 2026-08-04 is built and measured rather than owed.

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
| `credential-guard.py` | PreToolUse wired | **PreToolUse wired** (via the adapter) |
| `git-staging-guard.py` | PreToolUse wired | **PreToolUse wired** (via the adapter) |
| `published-history-guard.py` | PreToolUse wired | **PreToolUse wired** (via the adapter) |
| `redline-guard.py` (pre-commit) | Applies at commit | Applies when the target repo has the hook |

**This table is the whole of the safety argument.** Under ADR-012 the
read-only default that used to compensate for these gaps is gone, so a row
here is the only thing between this lane and a redline.

### How it is wired

[`hooks/agy-guard-adapter.py`](hooks/agy-guard-adapter.py) is a PreToolUse
handler that translates Antigravity's tool call into the Claude Code payload
the canonical guards already read, runs them **unmodified as subprocesses**,
and translates the verdict back. It holds no patterns of its own. That is
deliberate and it is the whole design: `security/posture.md` limit #6 records
a duplicated copy of guard logic drifting out of sync and shipping a gap that
had already been fixed in the original, so a redline change lands in the
guards and reaches this lane with no edit here. The per-guard overrides
(`MASK-OK`, `STAGE-ALL-OK`, `REWRITE-MAIN-OK`) ride through in the command
string and work exactly as they do in Claude Code.

Deploy by copying [`hooks.json`](hooks.json) to `~/.gemini/config/hooks.json`
and pointing its `command` at the checkout (or leaving the `~/code/agent-ops`
path and setting `AGENT_OPS_ROOT`). **The global root is the only one that
works** — a workspace `.agents/hooks.json` is not picked up by the CLI, so it
cannot carry a fleet guard.

Cost: roughly 0.8s per shell tool call and 0.6s per other call on this
machine, synchronous, since hooks block the agent loop.

### Measured hook semantics

Every line below was observed on 2026-08-04, not read off the vendor docs.
The `deny` path had never been exercised anywhere before this change.

- **`deny` survives `--dangerously-skip-permissions`.** That flag's strings
  speak only to the permission system; the hook is a separate code path
  upstream of it. Verified against a decoy credentials file holding a
  fabricated value: the read was blocked with the bypass flag set, and the
  guard's message reached the model verbatim. **This guard is a real floor,
  not a speed bump.**
- **Empty stdout is the pass-through, and `{}` is not.** A well-formed
  response carrying no `decision` is read as a *deny with an empty reason* —
  it killed every tool call in the probe run. `{"decision": "allow"}` is
  worse: it auto-approves, bypassing the `request-review` permission
  reviewer. Silence is the only neutral answer, which is why the adapter
  prints nothing when it passes.
- **A hook that errors fails OPEN.** A command that cannot be launched logs
  `pre-tool hook failed` and the tool call proceeds. This inverts Claude
  Code, where a missing PreToolUse script is a hard error (see
  [`conventions/hooks-gate-their-own-repair.md`](../../conventions/hooks-gate-their-own-repair.md)).
  Here a broken guard is indistinguishable from no guard, so the adapter
  fails **closed** on every failure it can see — guards missing, a guard
  crashing or timing out, an internal error — rather than inheriting the
  guards' own fail-open posture. A check that could not run is not a pass.
- **A stray top-level key voids the whole file.** Every top-level key is a
  hook *name*, so there is no comment mechanism. A `_comment` array made the
  CLI log `cannot unmarshal array into ... JSONHookSpec` and load **zero**
  hooks while the session carried on unguarded. One decorative key silently
  removes every guard in the file; `tests/test_agy_guard_adapter.py` asserts
  the shape for this reason.
- **Quotes in the `command` are passed through literally** rather than
  consumed by a shell, so a quoted path fails to launch — which, per the
  fail-open rule above, silently removes the guard.

### Residual gaps

- **The adapter cannot guard its own absence.** If the file is deleted or its
  path in `hooks.json` stops resolving, the hook command fails to launch and
  Antigravity fails open. Nothing running inside the hook can catch that.
  Recorded rather than papered over; it is the one case the fail-closed rule
  cannot reach.
- **Parity includes inherited gaps.** The adapter delivers commands faithfully,
  so this lane gets the canonical guard's *documented* out-of-scope classes
  too. Measured: asked to print a dotenv file, the agent reached for
  `Get-ChildItem <dir> | ForEach-Object { Get-Content $_.FullName }`, which
  names no sensitive path and is the runtime-assembled-path class
  `credential-guard.py` bounds out of scope. It was allowed — and the same
  command is allowed for Claude Code, which is parity working as specified,
  not an adapter defect. Whether that class should be narrowed is a question
  about the canonical guard, not about this lane.
- **`hooks.json` and `settings.json` remain machine state.** The versioned
  [`hooks.json`](hooks.json) here is a reference, not an enforcement: nothing
  in this repo can prove a given machine deployed it. `settings.json`
  (`permissions.{Allow,Deny,Ask}`) is untouched by this change — ADR-012
  ruled against narrowing grants, and this adds a control rather than
  restricting capability.

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

