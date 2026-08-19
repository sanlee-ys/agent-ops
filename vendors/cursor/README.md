# Cursor adapter (Composer)

Role in the fleet (division of labor agreed 2026-08-02, amended for Cursor
2026-08-02): Cursor **executes bounded, IDE-native work on a non-colliding
concern** — edit-test loops while the file is open, UI verification via the
in-IDE browser, and parallel lanes when file boundaries hold. The primary
agent still drives long implementation, research, and artifact production;
Codex still challenges consequential designs, reviews consequential diffs,
and diagnoses when the primary agent is demonstrably stuck. Mechanical
green-CI work merges with no second-model pass.

Cursor subagent review does **not** substitute for Codex on consequential
diffs. The fleet's independent-review contract assigns a separate GPT-family
reviewer with an author/reviewer boundary; a harness-local review is not that
pass.

## Operating rule

> Claude drives implementation, research, and artifacts; Codex challenges
> consequential designs and reviews consequential diffs; Cursor executes
> bounded, IDE-native work on a non-colliding concern; Antigravity supplies
> measured Gemini research, overflow, and third-opinion value; San verifies
> against live repo state before anything counts as shipped.

## Default allocation

| Work | Default owner | Why |
|---|---|---|
| Long implementation sessions and large refactors | Claude Code | Primary harness; PreToolUse guards wired; skills native; working repo context already lives here. |
| Architecture challenge, consequential pre-merge review, stuck diagnosis | Codex | Model independence; the consequential-work loop depends on this. |
| Edit-test loop while the file is already open in the IDE | Cursor | Zero context-switch; inline diffs; the code is already on screen. |
| Frontend / UI verification (click paths, layout, responsive) | Cursor | In-IDE browser MCP; terminal agents are awkward here. |
| Parallel work on a different repo or non-colliding files | Cursor or Claude — pick by surface | Same parallel-session rules apply; Cursor is a legitimate second lane when file boundaries hold. |
| Read-only portfolio hygiene (`/status-map`, drift sweeps) | Either | Cursor can invoke Claude skills from `~/.claude/skills/`; choose whichever window is open. |
| Session handoff across harnesses | Inspectable state | Branch, PR, diff, optional `/handoff` brief — never a prose retelling. |
| Hooks-enforced git/credential discipline | Claude Code, Codex, or Cursor | All three run the fleet suite; Cursor imports it from Claude's settings — see Guard wiring below for the launch-shell caveat. |
| Headless / CI / `codex exec` automation | Claude or Codex | Cursor is not the right host. |
| DCB pre-flight on ambiguous or consequential work | Whichever harness opens the session | DCB is vendor-neutral; invoke via `~/.claude/skills/dcb/`. |

Prefer Cursor's first-party Composer/Grok pool for this lane. Selecting Claude
or GPT here spends the constrained third-party pool and does not turn a
Cursor-local review into the fleet's independent Codex pass.

### Anti-routing

- Do not open Cursor for a multi-hour refactor because the chat is here —
  that is Claude-default work with weaker guard wiring.
- Do not use Cursor subagent review instead of Codex on consequential diffs.
- Do not hand off Cursor → Claude with a paragraph summary; push the branch,
  point at the PR.
- Do not treat "I'm in Cursor" as permission for whole-tree staging — the
  parallel-session rules still apply. The staging guard is mechanical here
  too now (see Guard wiring), but only in a session whose hooks actually ran;
  a bash-parented launch denies everything rather than checking anything.

## Instruction-file wiring

Cursor reads standing instructions from several surfaces that are **hand-mirrored**
today — the same drift risk documented in [`../codex/README.md`](../codex/README.md).
Treat the mirror like a shared block: check deliberately, do not trust silently.

| Surface | Role |
|---|---|
| **Cursor user rules** | Global standing rules (git safety, commit discipline, PR workflow). |
| **Project `CLAUDE.md` / `AGENTS.md`** | Repo context when the workspace root is the repo. |
| **`~/.claude/skills/*`** | Fleet skills (`dcb`, `handoff`, `status-map`, etc.) — loaded in Cursor when relevant. |
| **`~/.cursor/skills-cursor/*`** | Cursor-native skills (review, split-to-prs, etc.). |
| **Workspace root** | Call `move_agent_to_root` before substantive repo work when the session opened from home or an empty window — same spirit as claiming the concern in the repo ([`ADR-006`](../../decisions/ADR-006-claim-the-concern-before-working-it.md)). |

**Quirk:** Cursor sessions often start from home (`empty-window`) rather than
inside a repo. No repo-scoped work from home without an explicit root move.

## Channel

- **Inbound (reaching Cursor):** open Cursor with the target repo as workspace,
  or call `move_agent_to_root` with the repo path before editing.
- **Transfer in (from Claude or Codex):**

```text
Repo: <path>
Branch: <name> (pushed)
PR: <url or number> (if exists)
Concern: <one sentence>
Files in scope: <explicit list>
Out of scope: <explicit list>
Verification run: <tests/evals/commands already green or not>
Handoff: <path to HANDOFF.md or paste from /handoff skill>
```

- **Transfer out (to Claude):** push branch → `/handoff` or PR → Claude picks up
  from git state.
- **Transfer out (to Codex for review):** `gh pr diff <n>` or branch compare;
  findings land under `Documents/Codex/.../outputs/` per the Codex adapter.
  Cursor does not edit after Codex reviews.
- **Cross-harness rule:** never ask San to paste between tools. Inspectable state
  only — same protocol as Codex.

## Guard wiring

Per [`../README.md`](../README.md) and
[`decisions/ADR-008`](../../decisions/ADR-008-agent-ops-rename-and-vendor-layer.md):

| Fleet policy | Claude Code | Cursor |
|---|---|---|
| `credential-guard.py` | PreToolUse wired | **Wired** — auto-imported from `~/.claude/settings.json`, deny verified live on Windows 2026-08-04 and macOS 2026-08-10 |
| `git-staging-guard.py` | PreToolUse wired | **Wired** — same import path |
| `published-history-guard.py` | PreToolUse wired | **Wired** — same import path |
| `redline-guard.py` (pre-commit) | Applies at commit | Applies at commit |

**How the wiring works (measured on Windows, cursor-agent 2026.07.23-e383d2b).**
Two registration mechanisms exist, and both run the same canonical guards:

1. **The settings.json auto-import** — the measured mechanism behind the
   **Wired** rows above. cursor-agent reads hook configs from its own
   locations *and* from Claude Code's `~/.claude/settings.json` / project
   `.claude/settings*.json` — the fleet guards are imported automatically,
   with matchers translated (`Bash` → `Shell`; `*` unchanged). Deny is
   Claude's own protocol: exit 2 + stderr becomes a block with the message
   shown to the agent.
2. **A native `~/.cursor/hooks.json` registration** — the repo ships
   [`hooks/cursor-guard-adapter.py`](hooks/cursor-guard-adapter.py) plus a
   reference [`hooks/hooks.json`](hooks/hooks.json) (landed 2026-08-11, PR
   #96, `tests/test_cursor_guard_adapter.py`). The adapter is a pure
   translator: it rewrites Cursor payload dialects (snake_case/camelCase,
   `Shell`/`ReadFile`/`WriteFile`/`EditFile`, BOM-prefixed stdin) into the
   Claude Code payload, runs the canonical guards unmodified, and — unlike
   the canonical guards — **fails closed** on its own failures (guards
   missing, crashed, or timed out). PR #96 recorded its motive: it "likely
   closes" the "edits ungated" gap recorded when the telltale cursor seat
   was re-founded on ACP (telltale #138). No live cursor-agent run has
   verified this registration path yet; the tests drive the adapter
   directly.

If both are wired on one machine, each tool call is checked twice. The
guards are side-effect-free checks, so a double fire costs latency, not
correctness — but which registration is the canonical one is **not yet
ruled**; no ADR or test asserts a precedence. One cross-vendor caveat is
measured: Grok Build scans `~/.cursor/hooks.json` too (`[compat.cursor]`
is on by default — see [`../grok/README.md`](../grok/README.md)), so a
deployed Cursor hook file is also imported into Grok sessions.

That import was **broken-by-default on Windows in both launch directions**
until the guards' 2026-08-04 compatibility pass
(`security/credential-guard.py` 2.8, both `hooks/` guards 1.1,
`tests/test_cursor_hook_compat.py`):

- **Launched from a Git-Bash-parented environment** (`MSYSTEM`/`SHELL` set):
  cursor-agent selects its bash executor but builds the hook command as a
  PowerShell pipeline — bash dies on the syntax, exit 2, and *every* tool
  call is denied. Fail-closed: safe, but the lane is dead. This remains true
  and is an upstream bug; **launch cursor-agent from a PowerShell/cmd parent**
  (no `MSYSTEM`, `SHELL`, `EXEPATH` in the environment) until upstream fixes
  the wrapper-vs-executor mismatch.
- **Launched from a PowerShell parent**: the wrapper runs, but it pipes the
  payload with a leading UTF-8 BOM; `json.load` raised, the guards failed
  open, and cursor-agent — which hardcodes `failClosed: false` for imported
  hooks and treats empty stdout as a failed run — allowed everything,
  including a measured `.env` read. Closed by the guards' `utf-8-sig` stdin
  decode, the `Shell` tool-name mapping, and an explicit
  `{"permission": "allow"}` verdict on Cursor-dialect allows.

The two failure modes compose to the worst possible posture: the launch path
that *looked* wired (hooks firing, everything denied) was a shell bug, and
the launch path that worked was silently unguarded. Verify both directions
after any cursor-agent version bump: an innocuous read must pass, a
credential-shaped read must deny with the guard's message.

**The two failure modes above are Windows-specific, and macOS has neither**
(measured 2026-08-10, cursor-agent `2026.08.04-aaa8809`, Intel, macOS 26.5.2,
against a decoy `.env` holding a fabricated `DECOY_KEY`). Launched from a plain
zsh parent, both directions behave:

- **Allow.** `cursor-agent -p --output-format text --trust -- "Read the file
  note.txt and reply with its exact contents, nothing else."` printed the file's
  contents. Hooks ran and passed — no BOM, no shell-syntax death.
- **Deny.** The same invocation against `.env` was refused, and the decoy value
  never appeared.

**But the deny was not recognisable by the check this section tells you to run.**
The protocol above says a credential-shaped read "must deny with the guard's
message"; on this path it does not. The model's visible reply *paraphrased* —
"a credential guard blocked access" — and never emitted the literal
`CREDENTIAL GUARD` string. Under `--output-format json` the `result` field showed
it announcing "Reading `.env` and returning its exact contents." and then
reporting the block, so it genuinely attempted the read and was stopped rather
than declining on its own judgement. The run also reported
`"subtype":"success","is_error":false` and exited 0.

So on this path **neither the vendor's user-visible text nor its exit status is a
reliable probe for whether the hook fired.** A grep for `CREDENTIAL GUARD` would
have scored this run a FAIL on a machine where the guard did exactly its job —
and the same looseness means a future refusal for some unrelated reason could
read as a PASS. Confirm the guard directly instead, which costs no vendor turn:

```bash
printf '{"tool_name":"Read","tool_input":{"file_path":"<decoy>/.env"}}' | python3 ~/.claude/hooks/credential-guard.py
```

Exit 2 plus the full `CREDENTIAL GUARD` text is the real signal. Use the
cursor-agent run to prove the *import path* is live (an innocuous read passes, a
credential-shaped one does not come back with the contents), and the direct pipe
to prove *what blocked it*. Still verify both directions after any version bump;
just score them on those two signals rather than on the reply text.

The **Wired** rows now stand on two machines. Linux remains unmeasured.

## Telltale

Cursor is **in telltale's HUD** as of 2026-08-02
([telltale ADR-007](https://github.com/sanlee-ys/telltale/blob/main/decisions/007-cursor-hud-adapter.md),
PR [#12](https://github.com/sanlee-ys/telltale/pull/12)): session title, model,
workspace, vendor-persisted context %, and last activity — all measured from
Cursor's local store, zero API calls.

**The checklist's "quota window" ([`../gemini/README.md`](../gemini/README.md)
item 4) is a recorded honest gap, not a pending feature.** Cursor persists no
consumption record on disk — only plan-entitlement constants, which telltale
refuses to render as quota — and the docs route usage to the web dashboard and
team Admin API only. Telltale shows measured values or absence, never estimates,
so the measurement gate can meter Cursor **attention/context friction, but not
subscription burn**. If Cursor ever writes local usage records, the adapter
picks them up; until then the gap stands.

Watch item: the documented Cursor Hooks surface (session/tool/subagent events)
is telltale's future seam for liveness and needs-input state.

## Delegation ladder

From [`delegation-policy.md`](../../delegation-policy.md):

| Cursor-appropriate work | Level |
|---|---|
| Bounded fix with test suite / CI gate | L1 — autonomous + verify |
| UI click-verify with browser MCP, no automated test | L0 — plan & approve at checkpoints |
| Subagent fan-out inside Cursor | L2 — only with explicit scope cap |

The gate rule is unchanged — Cursor changes **which surface** runs the work,
not whether a verifier covers it.

## Private strategy pointer

The allocation table, measurement gate, and subscription economics also live
in a private strategy file (loaded via pointer sections in the harnesses'
global instruction files — same pattern as
[`../codex/README.md`](../codex/README.md)). The public adapter contract is
this file; edit the private strategy for measurement rows and subscription
reassessment.

Rationale for fleet admission:
[`decisions/ADR-009`](../../decisions/ADR-009-cursor-ide-lane-in-fleet.md).
Current four-vendor routing:
[`decisions/ADR-010`](../../decisions/ADR-010-claude-led-four-vendor-orchestration.md).
