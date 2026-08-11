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
config directory. On this fleet that file is maintained as a mirror of the
Claude global instruction file plus a shared division-of-labor section.
Hand-mirroring drifts: a 2026-08-02 audit found instructions written for
Claude Code's permission engine sitting in the Codex file, where they were
at best noise and at worst wrong. Treat the mirror like a shared block —
check it deliberately, don't trust it silently.

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

## Guard wiring

The current fleet configuration mirrors and wires the credential, staging,
published-history, fan-out, formatting, and session hooks for Codex. This is
machine-local implementation truth, not a reason to relax the read-only
review boundary: independence depends on separating author and reviewer, not
only on permission controls.

The full four-vendor division-of-labor contract (allocation table,
subscription measurement gate) is kept privately, with compact pointer
sections in the harnesses' global instruction files.

Rationale:
[`ADR-010`](../../decisions/ADR-010-claude-led-four-vendor-orchestration.md).
