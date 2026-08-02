# Codex adapter

Role in the fleet (division of labor agreed 2026-08-02): Codex **challenges
designs, reviews consequential diffs, and diagnoses when the primary agent
is demonstrably stuck**. The primary agent drives implementation, research,
and artifact production. Mechanical green-CI work merges with no
second-model pass — independence pays on design-mode work, and reviewing a
rename duplicates tokens while breaking merge-on-green cadence.

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
  a branch, PR, commit range, or diff; findings come back as markdown files
  in the session workspace's `outputs/` directory. Prose is for intent,
  constraints, and failed hypotheses — facts a diff cannot express.
- **Boundary:** Codex reviews read-only; it never edits the branch under
  review. Its findings are reconciled against live repo state before any
  are acted on — the branch may have moved since the review snapshot.

## Escalation packet

```text
Goal:
Expected behavior:
Observed behavior:
What we tried (hypothesis, test, result for each attempt):
Relevant branch/PR/diff:
Relevant files:
Exact error:
Constraints:
Please diagnose only; don't modify files.
```

The full division-of-labor contract (allocation table, measurement gate) is
kept privately, with pointer sections in both vendors' global instruction
files.
