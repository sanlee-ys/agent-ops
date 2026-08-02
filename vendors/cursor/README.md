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
diffs — same model family, no independence.

## Operating rule

> Claude drives implementation, research, and artifacts; Codex challenges
> consequential designs and reviews consequential diffs; Cursor executes
> bounded, IDE-native work on a non-colliding concern; San verifies against
> live repo state before anything counts as shipped.

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
| Hooks-enforced git/credential discipline | Claude Code | Guards are `PreToolUse` on Claude today — see guard gap below. |
| Headless / CI / `codex exec` automation | Claude or Codex | Cursor is not the right host. |
| DCB pre-flight on ambiguous or consequential work | Whichever harness opens the session | DCB is vendor-neutral; invoke via `~/.claude/skills/dcb/`. |

### Anti-routing

- Do not open Cursor for a multi-hour refactor because the chat is here —
  that is Claude-default work with weaker guard wiring.
- Do not use Cursor subagent review instead of Codex on consequential diffs.
- Do not hand off Cursor → Claude with a paragraph summary; push the branch,
  point at the PR.
- Do not treat "I'm in Cursor" as permission for whole-tree staging — the
  parallel-session rules still apply; guards are not mechanical here.

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
| `credential-guard.py` | PreToolUse wired | **Not wired** — behavioral only via user rules |
| `git-staging-guard.py` | PreToolUse wired | **Not wired** |
| `published-history-guard.py` | PreToolUse wired | **Not wired** |
| `redline-guard.py` (pre-commit) | Applies at commit | Applies at commit |

**Mitigation without pretending:** Cursor is appropriate for **bounded,
revertible work** where parallel-session prose rules and explicit-path staging
are sufficient. Consequential or credential-adjacent work stays on Claude until
Cursor gets hook parity or a documented equivalent.

## Telltale

Cursor subscription usage is **not** in telltale's Claude/Codex/Gemini HUD yet.
Routing decisions involving Cursor are not measured by the subscription
measurement gate until a telltale adapter exists. When built, follow the telltale
entry checklist in [`../gemini/README.md`](../gemini/README.md) item 4 — quota
window alongside the other vendors.

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
in a private strategy file (loaded via pointer sections in both vendors'
global instruction files — same pattern as
[`../codex/README.md`](../codex/README.md)). The public adapter contract is
this file; edit the private strategy for measurement rows and subscription
reassessment.

Rationale for fleet admission:
[`decisions/ADR-009`](../../decisions/ADR-009-cursor-ide-lane-in-fleet.md).
