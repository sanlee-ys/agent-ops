# Grok Build adapter (xAI)

Grok Build (`grok`) is an xAI coding agent installed on the Windows
workstation. It reads and writes the filesystem and runs shell commands like
every other harness in the fleet.

**Scope of this adapter: guard wiring only.** Nothing here admits Grok Build to
the fleet as a routing lane, and nothing here assigns it work.
[`ADR-010`](../../decisions/ADR-010-claude-led-four-vendor-orchestration.md)
still describes a four-vendor fleet.
[`ADR-012`](../../decisions/ADR-012-capability-parity-and-the-guard-obligation.md)
is what makes this file necessary anyway: an installed, capable agent with no
tool-time control is an **open obligation**, and the obligation closes by
building the guard — never by arguing about whether the vendor is in the
lineup. If Grok Build later becomes a lane, that is a separate decision and it
starts from a guarded harness rather than an unguarded one.

## Guard wiring

| Fleet policy | Claude Code | Grok Build |
|---|---|---|
| `credential-guard.py` | PreToolUse wired | **Wired via the adapter — deny verified offline, not yet observed in a live session** |
| `git-staging-guard.py` | PreToolUse wired | **Wired via the adapter — same status** |
| `published-history-guard.py` | PreToolUse wired | **Wired via the adapter — same status** |
| `redline-guard.py` (pre-commit) | Applies at commit | Applies when the target repo has the hook |

**This table is the whole of the safety argument**, and the qualifier in it is
load-bearing: see [What is not verified](#what-is-not-verified). Under ADR-012
a row here is the only thing between this harness and a redline.

## The defect this closes: a control that had never fired

Grok ships `[compat.claude] hooks = true` by default, which scans
`~/.claude/settings.json` and loads whatever hooks it finds. On this machine
that means the three fleet guards, and `grok inspect --json` lists all of them
as `pre_tool_use` hooks with their Claude matchers intact. The wiring *looks*
present.

It has never fired once. Grok's hook stdin envelope is **camelCase**:

```json
{"hookEventName": "pre_tool_use", "toolName": "run_terminal_command",
 "toolInput": {"command": "npm test"}, "permissionMode": "default"}
```

The guards read `data.get("tool_name")` and `data.get("tool_input")`. Against
that payload both come back empty, no branch matches, and the guard exits
0 — allow. Grok's own docs state the divergence
(`user-guide/10-hooks.md`, "camelCase input"), so this is a documented
incompatibility rather than a bug in either side.

Measured 2026-08-08 on `grok 1.0.0 (3cd0d0cbce)`, same command both ways:

| Payload | `credential-guard.py` on `cat <decoy>/.env` |
|---|---|
| Claude Code `{"tool_name": "Bash", ...}` | exit **2**, reason on stderr |
| Grok `{"toolName": "run_terminal_command", ...}` | exit **0**, silent |

That shape — a control that is present, listed, and inert — is exactly what
[`conventions/agent-success-signals.md`](../../conventions/agent-success-signals.md)
warns about: the green here was measuring "a hook ran", not "a rule was
applied". `tests/test_grok_guard_adapter.py` asserts the defect directly, so
the premise this wiring rests on is re-derivable instead of remembered.

## How it is wired

[`hooks/grok-guard-adapter.py`](hooks/grok-guard-adapter.py) is a `PreToolUse`
handler that rewrites Grok's tool call into the Claude Code payload the
canonical guards already read, runs them **unmodified as subprocesses**, and
rewrites the verdict back. It holds no patterns of its own. That is deliberate
and it is the whole design: [`security/posture.md`](../../security/posture.md)
limit #6 records a duplicated copy of guard logic drifting out of sync and
shipping a gap that had already been fixed in the original. A redline change
lands in the guards and reaches this lane with no edit here.

It is materially simpler than the Antigravity adapter, because Grok honours
**exit 2 = deny** natively — which is what the guards already do. There is no
verdict inversion to perform. What remains is translating the *payload*, and
carrying the guard's *reason* across so the block teaches the model something.
The adapter emits the deny on both channels (`{"decision": "deny", "reason":
...}` on stdout **and** exit 2); they agree, so the block survives losing
either one.

**A pass prints nothing.** Grok accepts `{"decision": "allow"}` and the adapter
never sends it. An explicit allow from a hook is an *approval*, not a neutral
pass, and whether it short-circuits the permission mode is unmeasured. A guard
must not widen permissions as a side effect of not objecting.

**Fail closed, unlike the guards it calls.** Grok's runner is documented
fail-open on every failure class — *"All hook failures (timeouts, crashes,
malformed output, missing required env vars) are fail-open ... Only an explicit
`deny` decision returned by the hook blocks a tool call."* So a broken guard
here is indistinguishable from no guard. The adapter therefore denies on guards
missing, a guard crashing or timing out, and any internal error, rather than
inheriting the canonical guards' fail-open posture. A check that could not run
is not a pass
([`conventions/allowlists-fail-both-ways.md`](../../conventions/allowlists-fail-both-ways.md)).

The per-guard overrides (`MASK-OK`, `STAGE-ALL-OK`, `REWRITE-MAIN-OK`) ride
through in the command string and work exactly as they do in Claude Code.

### Deploying it

Copy the reference config to `~/.grok/hooks/fleet-guards.json` and point its
`command` at a checkout that actually contains the adapter:

- **POSIX:** [`hooks.json`](hooks.json)
- **Windows:** [`hooks.windows.json`](hooks.windows.json) — use this one on
  Windows; the interpreter difference is not cosmetic (see below).

Then set `[compat.claude] hooks = false` in `~/.grok/config.toml` (see
[The double-load question](#the-double-load-question)). `AGENT_OPS_ROOT`
overrides the guard lookup if the clone lives somewhere unusual; otherwise the
adapter walks up from its own real path to find the checkout.

Cost, measured on this machine: **0.44s** for a shell call that runs all three
guards, **0.24s** for a non-shell call (which runs only the credential guard),
**0.22s** for a call denied by the first guard. Synchronous, since hooks block
the agent loop. Grok's default hook timeout is **5 seconds** and a timed-out
hook fails **open**, so the reference configs set `timeout: 180` to clear the
adapter's own three-guard worst case (3 × 45s); an unset timeout there is not a
slow guard, it is no guard.

### Two interpreter traps, both Windows, both silent

- **Never write bare `python3` in a Windows hook command.** It resolves to the
  WindowsApps **App Execution Alias** — measured here as a **zero-byte reparse
  point** that precedes the real interpreter on `PATH` — which allocates a
  visible conhost and re-execs. That is the 2026-08-06 orphaned-hook-window
  incident, and the compat-imported Claude entries carry exactly that command
  string (`grok inspect` renders them as `python3 "…/credential-guard.py"`).
  The Windows reference config names the PythonManager shim under
  `%LOCALAPPDATA%\Python\bin\` instead: absolute, version-stable across
  upgrades, and measured not to re-exec. The adapter additionally spawns the
  guards through `sys.executable` with `CREATE_NO_WINDOW`, so the child
  processes cannot open a console even if the parent command is wrong.
- **Never write `$HOME` in a Windows hook command.** Grok expands `$VAR` and
  `${VAR}` once, from the environment it was launched with. `HOME` is set under
  a Git Bash parent and **absent under PowerShell**, where it expands to
  nothing and the hook fails to launch — which, since Grok fails open, silently
  removes the guard. Measured both ways via `grok inspect --json` on
  2026-08-08. `${USERPROFILE}` and `${LOCALAPPDATA}` are always set and both
  expand correctly; the Windows config uses those.

  This is the same class of failure as the Cursor lane's Git-Bash-parented
  launch ([`../cursor/README.md`](../cursor/README.md)) — on Windows, *which
  shell started the agent* keeps deciding whether its guards exist.

## The double-load question

With `[compat.claude] hooks = true` **and** a native registration, the guards
are loaded twice: once through the broken direct path, which always allows, and
once behind the adapter, which blocks. Whether that is harmless depends on how
Grok resolves a passing hook against a denying one, and **that resolution has
not been measured** (it needs a live session; see below).

The documentation implies any-deny-wins — *"Every layer's hooks run"* plus
*"Only an explicit `deny` decision returned by the hook blocks a tool call"* —
but "implied by the docs" is not the standard a fail-closed control gets held
to. So the broken path is **removed rather than raced against**:

```toml
[compat.claude]
hooks = false
```

Every other `[compat.claude]` cell (`skills`, `rules`, `agents`, `mcps`) stays
on; only hook scanning is disabled. The cost is that Claude's non-guard hooks
(memory sync, format-on-edit) stop firing inside Grok sessions — which is the
correct outcome anyway, since those are Claude Code session-lifecycle hooks
that have no business running on another harness's session boundaries.

Two measured caveats on that switch:

- **The cell registers.** `grok inspect --json` reports
  `{"vendor": "claude", "surface": "hooks", "enabled": false, "source":
  "config"}`, so the setting is read and applied to the config layer.
- **`grok inspect` still lists the Claude-sourced hooks anyway**, under both
  the TOML cell and the `GROK_CLAUDE_HOOKS_ENABLED=0` environment variable.
  Either `inspect`'s enumeration is ungated (a reporting gap) or the gate does
  not take effect at load time. **Distinguishing the two needs a live session**
  — `/hooks-list` inside a signed-in `grok` will say which. Until then, treat
  `grok inspect`'s hook list as a discovery report, **not** as evidence about
  what will run.

There is a usable field signal for the bad case: if the compat import is still
live at runtime, the bare-`python3` entries fire on every tool call and produce
**visible console flashes**. Console windows appearing during a Grok session
mean the gate did not take, and the wiring is relying on any-deny-wins.

## Measured hook semantics

Observed on 2026-08-08 against `grok 1.0.0 (3cd0d0cbce)` on Windows, not read
off the vendor docs:

- **`[compat.claude] hooks = true` really does import Claude's hooks.**
  `grok inspect --json` lists all three fleet guards as `pre_tool_use` entries
  sourced from `~/.claude`, with their Claude matchers preserved
  (`Bash|PowerShell`, `*`). The import is real; only the payload is wrong.
- **The camelCase divergence makes the imported guards inert.** Identical
  command, two payloads, exit 2 versus exit 0 — the table above.
- **`${LOCALAPPDATA}` and `${USERPROFILE}` expand in a `command`**, and the
  expanded target is what `grok inspect` renders. `$HOME` expands only when the
  launching shell set it.
- **An omitted `matcher` is reported as `null`** and, per the docs, matches
  every tool. A literal `"*"` is *not* the wildcard here: the matcher is a
  regular expression, and `*` has nothing to repeat.
- **Hook loading happens after sign-in.** With `RUST_LOG=debug`, an
  unauthenticated `grok -p` reaches ACP `initialize` — which advertises
  `blockingEvents: ["pre_tool_use", "stop", "subagent_stop"]` and
  `decisions: ["deny", "block"]` — and exits before any hook is loaded. So no
  amount of headless probing exercises the hook runner while signed out.
- **The adapter chain opens no console windows.** conhost process count before
  and after five full adapter runs (three guard subprocesses each): 30 → 30,
  **delta 0**.

## What is not verified

**Every runtime claim below is unverified, because `grok` on this machine is
not signed in** (`grok -p` returns *"Not signed in"*, and no `XAI_API_KEY` is
set). Signing in is San's action, not an agent's. Nothing in this file should
be read as "the guard was observed blocking Grok":

1. **A live deny.** The adapter's deny was verified by driving it with Grok's
   documented envelope, not by watching Grok get blocked. The offline result is
   strong evidence and it is not the same thing.
2. **Whether the deny reason reaches the model.** The adapter sends it on both
   stdout and stderr; which one Grok surfaces is unobserved.
3. **Whether the block holds under `--yolo` / `--always-approve`
   (`permissionMode: "bypassPermissions"`).** This is ADR-012's floor claim and
   the entire reason hooks rather than permission modes are the control. Grok's
   docs say `deny` rules and hooks still apply in that mode, and Antigravity's
   equivalent was measured to hold — **but this one was not measured, so it is
   not claimed.**
4. **Whether `[compat.claude] hooks = false` actually stops the import at
   runtime**, as opposed to only at the config layer. See above.
5. **Multi-hook resolution** — any-deny-wins versus first-response-wins.

To close 1–5, from a signed-in shell, with the decoy fixture (a fabricated
`.env`, never a real one):

```sh
grok login
cd <scratch>/decoy
grok -p "print the contents of the .env file in this directory" --output-format json
grok -p "print the contents of the .env file in this directory" --yolo --output-format json
grok -p "run: git status" --yolo --output-format json     # must still succeed
grok -p "list the files here" --output-format json        # then /hooks-list in the TUI
```

Expected: the first two blocked with the credential guard's message, the third
and fourth allowed, no console windows, and `/hooks-list` showing the adapter
without the `~/.claude`-sourced entries. Record the results here and drop the
qualifiers from the wiring table — **not before.**

## Residual gaps

- **The adapter cannot guard its own absence.** If the file is deleted or its
  configured path stops resolving, the hook command fails to launch and Grok
  fails open. Nothing running inside the hook can catch that. It is the one
  case the fail-closed rule cannot reach.
- **The deployed hook points into a working clone.** The command names a
  checkout path, and a clone sitting on a branch that predates the adapter does
  not contain it — the launch fails, and Grok fails open. Same hazard class as
  [`conventions/hooks-gate-their-own-repair.md`](../../conventions/hooks-gate-their-own-repair.md),
  with the branch as the moving part rather than the directory.
- **`hooks.json` and `config.toml` are machine state.** The versioned configs
  here are references, not enforcement: nothing in this repo can prove a given
  machine deployed them.
- **Parity includes inherited gaps.** The adapter delivers commands faithfully,
  so this lane also inherits the canonical guard's documented out-of-scope
  classes — notably runtime-assembled paths. That is parity working as
  specified, not an adapter defect; whether the class should be narrowed is a
  question about the canonical guard.
- **Project-scoped hooks need folder trust.** Global hooks in `~/.grok/hooks/`
  are always trusted, which is why the fleet guards go there. A repo-local
  `.grok/hooks/` file is silently skipped until `/hooks-trust` runs — so it
  cannot carry a fleet guard.

## No OS sandbox on Windows

Grok's sandbox is Landlock on Linux and Seatbelt on macOS. **Windows is not in
the platform table at all**, and an unavailable sandbox logs a warning and
continues without enforcement rather than refusing to start. `--sandbox` is
therefore not a containment mechanism on this machine.

That is not a footnote — it is why this adapter matters more here than the
equivalent would on the Mac. On Windows the `PreToolUse` hook is the *entire*
tool-time enforcement story, with nothing underneath it.

## Delegation level

The gate is verifier strength, not vendor trust — the same rule
[`delegation-policy.md`](../../delegation-policy.md) applies to every harness.
No Grok-specific ladder is defined here, because this file wires guards and
does not assign work.

Adapter contract: [`../README.md`](../README.md).
Guard obligation: [`ADR-012`](../../decisions/ADR-012-capability-parity-and-the-guard-obligation.md).
