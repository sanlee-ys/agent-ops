# Postmortem: graphify console-window flash — three separate root causes, one wrong diagnosis along the way

**Date:** 2026-07-03 to 2026-07-04 | **Duration:** ~1 day across three separate diagnostic passes | **Severity:** Low (UX annoyance — unexpected console windows popping during git/graphify operations, including mid-game; no data exposure)
**Status:** Resolved (one known durability gap remains, accepted as-is)
**Reclassified 2026-08-01:** debug note, not an incident — no exposure, no spend, nothing at risk beyond attention. Originally filed under `incidents/`; see [README.md](README.md) for the bar.

## Summary

A console window kept flashing at unpredictable moments — a Claude Code
session start, a scheduled background task, and git commit/checkout. It
looked like one bug with one fix ("use `pythonw.exe` instead of
`python.exe`"), and the first fix (the MCP server launch command) genuinely
worked. But the flash kept recurring from other triggers, because it was
actually **three unrelated processes** independently launching
console-subsystem binaries, each requiring a different fix. A fourth
surface was investigated and initially misdiagnosed as "already fine"
before a later pass corrected it.

## Impact

- Recurring, unpredictable console-window flashes during normal use of this
  machine (Claude Code sessions, a daily background task, git operations),
  including interrupting unrelated foreground activity (a game).
- No security or data impact — purely a UX/attention annoyance.
- Cost: three separate diagnostic passes before the full picture was clear,
  because each fix looked complete in isolation ("the flash is gone" after
  fixing surface 1 was true only until surface 2 or 3 fired next).

## Root cause

Three independent processes on this machine each launch a console-subsystem
binary, and each needed its own fix — swapping one binary name in one place
was never going to be a global fix, because the same underlying tool
(graphify, a codebase-graph MCP server) has multiple, structurally
different launch points.

**Surface 1 — the graphify MCP server (`~/.claude.json`).**
`mcpServers.graphify.command` pointed at console-mode `python.exe`, so every
Claude Code session start or MCP reconnect launched `graphify.serve` with a
real, visible console. Fix: point it at `pythonw.exe` instead — safe here
because this is a long-lived detached daemon whose stdout nobody reads.

**Surface 2 — the daily `graphify-global-refresh` scheduled task.**
`~/.graphify/refresh-global-graph.ps1` also used console-mode `python.exe`,
invoked roughly a dozen times in a loop (once per repo) plus a final
clustering pass. The task's own PowerShell host ran with `-WindowStyle
Hidden`, but each `python.exe` child still spawned its own conhost window
the hidden parent couldn't suppress — the random mid-task, sometimes
mid-game, flash. **The naive fix (swap this `python.exe` to `pythonw.exe`
too) was tested and rejected**: `pythonw.exe` is GUI-subsystem, so
PowerShell's `&` call operator neither waits for it nor captures its output
(measured: 2145ms plus captured output for `python.exe` vs 9ms and empty
output for `pythonw.exe` running the identical command). Swapping it would
have turned the sequential per-repo add loop into fire-and-forget and let
the final clustering step race the still-running adds against the same
graph JSON — corrupting output, not just hiding a window. The actual fix
was the scheduled task's *principal*: moving it to `LogonType: S4U`
(session 0) so its console children have no interactive desktop to flash
on, while leaving `python.exe` untouched so the script's wait/capture
semantics stay correct.

**Surface 3 — git `post-commit`/`post-checkout` hooks, and an earlier wrong
diagnosis.** An earlier pass concluded "the git hooks already use
`pythonw`, so they're not the problem" — true but incomplete. The hooks'
*rebuild subprocess* does correctly launch via `pythonw.exe` with
`DETACHED_PROCESS` flags. But the hooks themselves are `#!/bin/sh` scripts,
and Git for Windows must invoke its own bundled `sh.exe` — a
console-subsystem binary — just to *interpret* the shebang, regardless of
what that script launches internally. If `git.exe`'s parent process has no
attached console, that `sh.exe` invocation can itself flash one. This is a
layer above the python-vs-pythonw question entirely, and the original
"hooks are clean" conclusion missed it because it only checked what the
hook *launches*, not what *runs the hook script itself*. Fix:
`GRAPHIFY_SKIP_HOOK=1` set as a user environment variable, which both hooks
now check near the top (before any expensive work, including the
`sh.exe`-hosted logic that would otherwise run) and exit immediately.

## What went well

- **Tested before trusting a plausible-sounding fix.** The `pythonw.exe`
  swap for the scheduled task looked like the same fix as surface 1 — same
  tool, same symptom. It was tested empirically (wait/capture timing) before
  being applied, and that test caught a real corruption risk the "obviously
  correct" fix would have introduced.
- **Verified an inbound claim instead of trusting it, and it mattered.** A
  parallel side-session reported the `GRAPHIFY_SKIP_HOOK` fix alongside a
  second, unrelated claim (that a previously-fixed data-boundary issue in
  graphify's handling of a private repo was "not yet applied," with a
  specific stale node count). That second claim was checked live and found
  flatly false — already fixed and verified earlier the same day. Because
  one claim in that message was wrong, the other (the env var fix) was
  independently verified rather than taken on faith — which is what
  surfaced a real, separate gap: the env var was checked in `post-commit`
  but **not** `post-checkout`, so "confirmed working" for both commit and
  checkout wasn't accurate as reported.
- **Fixes verified live, not just by reading code.** Each fix was confirmed
  against actual running state: `LogonType: S4U` read back from
  `Get-ScheduledTask`, the env var read back from
  `[Environment]::GetEnvironmentVariable`, and the final hook patch
  smoke-tested both ways (exits silently with the var set, still launches
  normally with it unset) across all local repos with the hook installed —
  not assumed correct because the edit "looked right."

## Fixes applied

| Fix | What | Where |
|---|---|---|
| MCP server launch | `mcpServers.graphify.command` to `pythonw.exe` | `~/.claude.json` |
| Scheduled task principal | `New-ScheduledTaskPrincipal -LogonType S4U -RunLevel Limited` applied via `Set-ScheduledTask` (required an elevated shell — first attempt failed with an access-denied error from a non-elevated session) | `graphify-global-refresh` Windows Scheduled Task |
| Scheduled task provisioning | Registers the task with the S4U principal on fresh-machine setup; prints the elevated command if the setup run isn't elevated | a private config repo's Windows setup script |
| Scheduled task script tracked | Was live-only with no version control — the exact condition that let this bug hide from the first (MCP-only) fix sweep. Parameterized to the user's profile path, committed to the private config repo with a README explaining the repo-scope and the pythonw rejection | private config repo |
| Git hook env-var guard | Added a guard clause (`[ "${GRAPHIFY_SKIP_HOOK:-0}" = "1" ] && exit 0`) to `post-checkout` (already present in `post-commit`), same position: after the rebase/merge/cherry-pick guards, before Python-interpreter detection | `post-checkout` hook in all local repos with graphify installed |
| Verification | All repos confirmed byte-identical before and after (single checksum each way), syntax-checked, and behaviorally tested both ways | This machine |

## Lessons learned

**A fix scoped to one entry point doesn't generalize to a sibling entry
point for the same tool, even when the symptom and the "obvious" fix look
identical.** `python.exe` to `pythonw.exe` was correct for the MCP server
(a detached daemon) and actively wrong for the scheduled-refresh script (a
sequential, output-capturing pipeline) — same binary swap, opposite
correctness, because the two call sites have different requirements. The
generalizable move is "does anything wait on or read this process's
output" before reaching for the same fix twice.

**"Already checked, already clean" needs to specify what was checked.** The
git hooks genuinely were clean *for the thing that was checked* (the
rebuild subprocess's interpreter) — the miss was a layer nobody had looked
at yet (the shell interpreter running the hook script itself). A
"not the problem" conclusion is only as strong as the specific question it
answered.

**An inbound report can be partially right.** Treating "one claim in this
message was verifiably false" as a reason to re-verify the *other* claim
in the same message, rather than assuming the rest must be fine, is what
caught the post-checkout gap. The alternative (accept the parts that sound
plausible, since the sender seemed credible) would have left a real gap
undocumented and unfixed.

**A fix living in generated output, not the source template, is a fix on
loan.** The `post-checkout` patch lives in files generated by a
`graphify hook install` step from a template inside the installed graphify
package. Any future re-run of that install — a new repo, a reinstall —
regenerates the old, unpatched version and silently drops the fix. This
mirrors a GitHub MCP server registration not persisting and `python.exe`
reverting in `~/.claude.json` from other incidents the same week (see
incidents/2026-07-04-github-pat-read-grep-leak.md and
incidents/2026-07-03-credential-guard-interpreter-bypass.md): config and
generated files that live outside version control are exactly where fixes
go to quietly die. Accepted as a known gap here (the one-line fix is cheap
to reapply and is now documented) rather than patching third-party
installed-package source, which would itself be wiped by the next graphify
upgrade regardless.
