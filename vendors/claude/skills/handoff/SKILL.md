---
name: handoff
description: Produce a paste-ready handoff brief capturing the LIVE state of the current work session, so another Claude Code window (which cannot read this one's transcript) or a future session can resume without losing the thread. Invoke via /handoff. Use when the user is pausing, switching windows/machines, ending a pairing session, or says things like "hand this off", "write a handoff", "I'm moving to the editor", "pick this up later". Distinct from DCB: DCB is a PRE-flight scaffold (Direction/Contracts/Bar set before work starts); handoff is a POST-flight snapshot (state captured to resume/transfer work already in progress). Do NOT use as a substitute for actually committing/pushing work, and skip it for trivial one-off questions where there is no in-progress state worth transferring.
---

# Session handoff

A separate Claude Code window cannot read this window's conversation — sessions are not
shared unless one spawned the other as an agent. So when the user pauses or switches, the
only way the next session picks up cleanly is a self-contained brief. This skill writes that
brief from **live, verified state**, not from what was said in chat.

The whole value is accuracy: a handoff that misstates the branch, the git status, or what
shipped is worse than none. Gather the real state first, then write.

## 1. Gather live state (verify, do not recall)

Before writing a word, read the actual state in the working repo(s):

- **Git:** current branch (`git branch --show-current`), working-tree status (`git status -sb`),
  position vs the remote (`git rev-list --left-right --count origin/main...HEAD`), and the last
  few commits (`git log --oneline -5`). If unsure whether local is fresh, `git fetch` first.
- **What shipped this session:** any PRs opened/merged (`gh pr list`, `gh pr view <n>`), the
  commits that landed, and whether the tree is clean or has uncommitted work.
- **Relevant memory:** the project's memory files already auto-load in any new session in the
  same repo — note which ones carry the durable plan so the next session leans on them.

If any check fails or can't be verified, say so in the brief rather than guessing.

## 2. Capture these sections

Keep each tight. Omit a section only if it genuinely doesn't apply.

- **What we're building** — the goal, with pointers to the governing spec/ADR/docs (paths).
- **What just shipped** — merged PRs, commits, with the one-line "why".
- **Git state (verified)** — branch, clean/dirty, synced/ahead/behind, any open branch/PR. Tell
  the next session to re-check with `git status -sb` before acting.
- **How we work together** — the pairing mode and any working-style preferences that matter
  (who drives, small-steps-and-checkpoint, teach-as-we-build, how the user runs things).
- **Discipline notes / gotchas** — anything that bit us this session and shouldn't again
  (e.g. verify the current branch before committing; a known environment flake).
- **Next steps, in order** — the immediate next concern, then what follows, each as its own
  branch/PR where that applies.

## 3. Output

Emit the brief as a **single self-contained block the user can copy-paste** into the next
window. Lead it with a one-line title (repo + what the session is about). End it with a
concrete first instruction for the receiving session (e.g. "read <spec> and confirm the plan
before writing code").

Then, in a normal sentence to the user, note two things: (a) memory is namespaced by the
project's working directory, so the receiving window only auto-loads it if rooted at the **same**
directory (a session opened in a subfolder sees a different, likely empty, memory store) — the
brief and the repo docs must therefore stand alone, never assume the other window has memory;
and (b) offer to persist the state durably (a repo doc, which any session in that repo can read)
if the work will span more than the next window — a pasted brief is ephemeral.

Do not create a file for the brief unless the user asks; the default is paste-ready text.
