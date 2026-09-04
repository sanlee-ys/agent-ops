# Codex adapter

Role in the fleet (division of labor agreed 2026-08-02): Codex **challenges
designs, reviews consequential diffs, and diagnoses when the primary agent
is demonstrably stuck**. The primary agent drives implementation, research,
and artifact production; Cursor owns bounded IDE/UI work; Antigravity is a
measured Gemini research/overflow lane. Mechanical green-CI work merges with no
second-model pass — independence pays on design-mode work, and reviewing a
rename duplicates tokens while breaking merge-on-green cadence.

**Repo exception:** Codex may contribute directly to `agent-ops` on its own
branch; the read-only boundary below still applies when reviewing another
agent's branch.

"Demonstrably stuck" has a threshold: **two failed hypothesis-driven
attempts, or visible looping**. First friction is not an escalation.

## Instruction-file wiring

Codex reads global standing instructions from `AGENTS.md` in its home
config directory. A 2026-08-02 audit found that file hand-mirrored from
Claude's own instruction file, carrying text written for Claude Code's
permission engine — at best noise here, at worst wrong.

The fix is single-sourcing, not tighter hand-mirroring. The deployed file is
now assembled, never hand-edited: a short Codex-specific header
([`instructions/AGENTS.header.md`](instructions/AGENTS.header.md)) followed
by the canonical, vendor-neutral block
([`vendors/shared/AGENTS.md`](../shared/AGENTS.md)) that every vendor
shares. The division-of-labor section, the redlines, the cross-agent
channel, and the escalation packet all live in the canonical block now, so
a change to any of them reaches every vendor from one edit. Deploy commands:
[`vendors/README.md`](../README.md) under "Deploy".

## Plan-stage gate (design-mode work)

Before the first `Edit` on a real fork — a decision that is hard to
reverse, or that picks between designs with a real tradeoff — Claude writes
the plan to a file under the session's `outputs/` directory and runs it
through the existing `codex exec` channel with the fixed prompt below.
Reuse the escalation-packet format for any context the plan itself does not
carry; do not invent a new transfer shape for this gate. This adds no new
channel and no MCP server — it is the same `codex exec "<prompt>"` call
already documented above, pointed at a plan file instead of a diagnosis.

Fixed review prompt:

```text
Review the plan at <path>. Answer these four questions:
1. Gaps: what does the plan not cover that it needs to?
2. What could go wrong: name the specific failure modes.
3. A better approach: is there one, and why is it better?
4. Missed cases: what input, state, or edge case does the plan not handle?

Start your reply with exactly one verdict line: APPROVED or NEEDS_REVISION.
Then answer the four questions.
```

Cap this exchange at three rounds. If round three still returns
`NEEDS_REVISION`, stop and escalate to San rather than sending a fourth
round — a plan three rounds of review cannot approve is a design question,
not a Codex-shaped one.

## Channel

- **Inbound (reaching Codex):** `codex exec "<prompt>"` runs a
  non-interactive session and prints the reply. Useful flags:
  `--skip-git-repo-check` outside a repo; `--cd <dir>` and
  `--sandbox workspace-write` when Codex must write files. Each invocation
  is a fresh session — Codex CLI sessions share no memory with its app
  sessions, which is why standing agreements live in instruction files and
  repos, not in either tool's memory.
- **Transfer format:** inspectable state, not prose retellings. Reviews take
  a branch, PR, commit range, or diff at an exact revision; findings come
  back as markdown files in the session workspace's `outputs/` directory.
  Prose is for intent, constraints, and failed hypotheses — facts a diff
  cannot express.
- **Boundary:** Codex reviews read-only; it never edits the branch under
  review. Its findings are reconciled against live repo state before any
  are acted on — the branch may have moved since the review snapshot.
- **Every finding carries a disposition label**, `auto-fix` or `ask-user`,
  assigned by the reviewer at the moment it is written. `auto-fix` is safe and
  mechanical and the applying session resolves it without asking; `ask-user`
  touches intent and is escalated. An unlabelled finding is `ask-user`. The
  reviewer assigns it because the applying session is the author, and the
  author's bias runs toward `auto-fix`. Full rule:
  [`delegation-policy.md`](../../delegation-policy.md).

## Escalation packet

```text
Goal:
Expected behavior:
Observed behavior:
What we tried (hypothesis, test, result for each attempt):
Relevant branch/PR/diff and exact revision:
Relevant files:
Exact error:
Constraints:
Please diagnose only; don't modify files.
```

## CI review

The channel above needs a session to invoke it. For a consequential diff,
that is not enough: the review must happen even when no session asks. The
workflow `.github/workflows/codex-review.yml` (PR #126) closes that gap.

- **Trigger:** add the label `codex-review` to a pull request. The workflow
  also re-runs on each push to a labeled PR. It does nothing on an unlabeled
  PR, which keeps the fleet rule that mechanical green-CI work merges without
  a second-model review.
- **What it posts:** one PR comment with findings. Each finding carries the
  same `auto-fix` or `ask-user` disposition the channel uses. It reviews
  bugs, regressions, requirement mismatches, missing or weakened tests, and
  scope fidelity. It never comments on style.
- **On success:** it applies the label `reviewed-by-codex`. The label is
  provenance for the current head: each run removes it first and re-applies
  it only when a review posted. A failed or skipped run leaves the PR
  without it. Codex itself found the persistence gap on the first live run.
- **Fail soft:** with no `OPENAI_API_KEY` repository secret, or on an API
  error, it prints a notice and exits 0. It posts nothing and blocks nothing.
- **Boundary:** it runs under `pull_request`, not `pull_request_target`, with
  `pull-requests: write` and `contents: read` only. It never pushes to a
  branch. A fork PR gets no secret and fails soft by design.
- **Model:** the one set in the local Codex config, `gpt-5.6-sol` on
  2026-09-03. Change it in the workflow when the lane's model changes.

The secret was added on 2026-09-04. The first labeled PR was the live test.

## Guard wiring

The current fleet configuration mirrors and wires the credential, staging,
published-history, fan-out, formatting, and session hooks for Codex. This is
machine-local implementation truth, not a reason to relax the read-only
review boundary: independence depends on separating author and reviewer, not
only on permission controls.

The full four-vendor division-of-labor contract (allocation table,
subscription measurement gate) is kept privately, with compact pointer
sections in the harnesses' global instruction files.

### Deploy the hook copies

No script copies the hook files into `~/.codex/hooks/`. Copy them by hand
after you edit a canonical hook, on each machine that runs Codex. Three
guards are canonical in this repo. The three session hooks
(`format-on-edit.py`, `memory-sync.py`, `unpushed-work-warning.py`) are
canonical in the owner's private config repo, in its `claude/hooks/`
directory. Run this from the root of this repo, on Windows:

```powershell
Copy-Item security\credential-guard.py, hooks\git-staging-guard.py, hooks\published-history-guard.py "$env:USERPROFILE\.codex\hooks\"
Copy-Item ..\<private-config-repo>\claude\hooks\format-on-edit.py, ..\<private-config-repo>\claude\hooks\memory-sync.py, ..\<private-config-repo>\claude\hooks\unpushed-work-warning.py "$env:USERPROFILE\.codex\hooks\"
```

Verify with the deployed-manifest check in that private config repo
(`scripts/check-deployed-manifest.py`). Its `-- codex --` section must show
no `MISMATCHED` line and no `STALE` line. A copy that drifts from the
canonical file is the drift class in
[`security/posture.md`](../../security/posture.md), limit 6; the manifest
check is the only thing that detects it.

Rationale:
[`ADR-010`](../../decisions/ADR-010-claude-led-four-vendor-orchestration.md).
