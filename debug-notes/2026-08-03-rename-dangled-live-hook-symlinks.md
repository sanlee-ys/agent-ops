# Renaming the repo that hosts the guard hooks disarmed the session doing the renaming

**Date:** 2026-08-03 | **Severity:** Low — no exposure, no spend; a live session was wedged until a human repaired it by hand
**Classification:** debug note, not an incident, per [README.md](README.md) — no credential or private data moved, no usage window was burned, and the control that stopped working stopped by failing *closed*. The damage was self-inflicted, immediate and fully visible.

## Summary

`~/code/claude-ops` was renamed to `~/code/agent-ops` on the MBP, from inside a
running Claude Code session, as part of the rename this repo had just adopted.

Three of that machine's global hooks are symlinks *into that directory*:

```
~/.claude/hooks/credential-guard.py       -> ~/code/<repo>/security/credential-guard.py
~/.claude/hooks/git-staging-guard.py      -> ~/code/<repo>/hooks/git-staging-guard.py
~/.claude/hooks/published-history-guard.py-> ~/code/<repo>/hooks/published-history-guard.py
```

The instant `mv` returned, all three dangled. They are `PreToolUse` hooks with a
broad matcher, and **a hook whose script is missing is a hard error, not a
skip** — so the tool call it gates is refused. Every subsequent `Bash`, `Read`
and `Write` failed with:

```
can't open file '/Users/<user>/.claude/hooks/credential-guard.py'
```

`Glob` and `Grep` were not available in that session, so nothing was left. The
agent could not create a symlink (needs `Bash`) and could not drop a shim at the
old path (needs `Write`, gated by the same hook). The owner ran three
`ln -sfn` commands in an outside shell to unblock it.

## What actually went wrong

**The move disarmed the only tool that could undo the move.** This is the whole
shape, and it is worth stating as a class rather than as a git anecdote: the
repair for a broken hook requires exactly the capability the broken hook
removes. There is no ordering of agent actions that recovers from it, because
every candidate repair is itself a gated tool call. The recovery path always
leaves the session.

**Nothing warned, because nothing was wrong yet at decision time.** At the
moment the command was composed, all three links resolved and the hooks passed.
The breakage is created by the command's own success, one filesystem operation
before anyone could observe it. A pre-flight check of hook health would have
been green.

**The blast radius came from the matcher, not from the rename.** These guards
are deliberately broad — they have to be, because the incident series that
produced them
([2026-07-03](../incidents/2026-07-03-credential-guard-interpreter-bypass.md),
[2026-07-04](../incidents/2026-07-04-github-pat-read-grep-leak.md)) is a story
of narrow matchers missing the surface that actually leaked. Broad matcher plus
hard-fail plus a missing script is total denial by construction. Each of those
three properties is individually correct.

**The guards were unenforced for the whole window.** This is the part worth
being precise about, because it is easy to wave away: nothing touched
credentials during the outage, but not because a guard stopped it — every call
was *rejected before executing*, which is not the same event. What the machine
actually had, for that window, was a `settings.json` claiming three security
controls and a `~/.claude/hooks` directory containing three dead links. Anything
that reached a tool by a path those hooks did not gate ran unguarded.

## The trade this failure exposes, and why the wedge is the right side of it

The obvious "fix" is to make a missing hook script a skip instead of an error.
Do not.

Fail-closed produced a session that could not do anything, on a machine whose
owner was sitting in front of it, within one tool call. Fail-open would have
produced a session that worked perfectly, indefinitely, with **no credential
guard, no staging guard and no published-history guard**, and no signal
whatsoever that the security posture the repo documents was fiction on that
machine. That is the same false-green shape as
[`../conventions/agent-success-signals.md`](../conventions/agent-success-signals.md):
a run that looks exactly like a healthy one is the worst available failure.

So the loud total wedge is the control working. The defect is not the hard
error; the defect is that a session was allowed to compose the command that
caused it.

## Fixes

- **The rule**, written up as
  [`../conventions/hooks-gate-their-own-repair.md`](../conventions/hooks-gate-their-own-repair.md):
  a directory that hosts live hooks cannot be moved by the session those hooks
  gate. Re-point in the *same* command as the move
  (`mv X Y && ln -sfn Y/... ~/.claude/hooks/...`), or move it from a shell
  outside the session.
- **A dangling-link check in the machine-provisioning script's audit step.**
  That script already cross-checks `settings.json` against the filesystem, and
  already warned when the sibling clone was missing at install time. What it did
  not detect is the inverse — an *installed* link pointing at a path that no
  longer exists. `[ -e ]` follows symlinks, so a dead link fails it while still
  passing `[ -L ]`; the two branches now report `DANGLING` and `MISSING`
  distinctly. That change lives in the private provisioning repo and is tracked
  there, not here.

Note what the second one is and is not. It is a *detective* control: it catches
the state on the next provisioning run, which is minutes-to-days later. It could
not have prevented this, and nothing mechanical on this side can — the
prevention is the convention, which is a behavioral rule. That is an honest
weaker answer than this repo usually accepts (see
[`ADR-002`](../decisions/ADR-002-public-first-canonicality.md) on behavioral
rules earning mechanical backstops), and it is written down as weaker rather
than dressed up.

## Lessons

1. **A capability that gates its own repair has no in-band recovery.** Before
   moving, renaming or deleting anything a live control resolves through, ask
   which tool the repair needs and whether that tool survives the change. If the
   answer is "the same one", the operation belongs outside the session.
2. **Symlinks make a rename a remote action.** `mv` reads as local and
   reversible. Every inbound symlink turns it into a change to some other
   system's configuration, applied instantly, with no reference back to the
   thing that moved. The rename was correct and the paths inside the repo were
   all updated; what broke was outside it, pointing in.
3. **Fail-closed is still right, and it should be loud enough to hurt.** The
   alternative here was not "a smaller failure" but "a machine that quietly
   stopped enforcing its security controls." A wedge that is fixed in thirty
   seconds beats a silence nobody measures.
4. **A control that is only wired at install time is unverified at every other
   moment.** The provisioning script's install-time warning was written for
   exactly this class of failure and did not fire, because the clone existed
   when it ran. Wiring is a point-in-time event; resolution is a continuous
   property.
