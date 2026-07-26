# ADR-007: Guard the invariant, not the verb — published commits don't get dropped from `main`

**Status:** Accepted — 2026-07-26. Records the design of
`hooks/published-history-guard.py` and the rule generalised from the incident
that produced it.
**Scope:** This repo (the Claude operating layer). Repo-local ADR per the
two-tier convention.
**Related:** [`ADR-004`](ADR-004-ref-explicit-git-in-shared-clones.md) — the
same shared-clone premise, the opposite half of the problem (that one is about
automation targeting the wrong ref; this one is about a session destroying a
ref another session owns). Convention text:
[`../conventions/parallel-sessions.md`](../conventions/parallel-sessions.md).

## Context

On 2026-07-26 two sessions worked one private repo in the same clone. That repo
is direct-to-main by its own house rule, so there is no PR gate anywhere in this
story.

| Time (EDT) | Session | Event |
|---|---|---|
| 14:33 | B | commits `3fbecdc` |
| 14:36 | B | commits `43bac69`, pushes it |
| 14:39 | A | commits `4278c51` on top of B's work, pushes it |
| 14:40:15 | B | `git -C <repo> reset --soft de133f2` |
| 14:41 | B | recommits its own work as `487ca61`, `9b513a6` |
| 14:42:56 | B | `git -C ... push --force-with-lease` — **`4278c51` is now gone from the remote** |
| 14:43 | A | notices only because an edit cannot find its own text; cherry-picks `4278c51` back as `19d1634` |

Two commits left `main` in that reset. `43bac69` was B's own and B recommitted
it. `4278c51` was A's, and it survived by reflog and luck.

## What actually happened at the permission layer

The global `CLAUDE.md` states that destructive git verbs — `reset`, `clean`,
`branch -D`, force-push — are pinned behind explicit `ask` rules. That claim
needed checking before designing anything around it, because if the rules simply
failed, the fix is to repair the rules and stop.

They did not simply fail. Three findings, in ascending order of how much they
changed the design:

**1. The reset was correctly allowed, and would be again.** The command was
`git -C <repo> reset --soft de133f2`. Its tool call returned
in **2.2 seconds** (18:40:15.232Z → 18:40:17.420Z), bracketed by comparably
fast neighbours — no human read a permission prompt in that window. And it
should not have had to. The operative gate for resets is the auto-mode
classifier, not the static rule, and its own denials in this transcript archive
are filed under `[Irreversible Local Destruction]`:

> Permission for this action was denied by the Claude Code auto mode
> classifier. Reason: [Irreversible Local Destruction] `git reset --hard
> origin/main` discards the local triage commit…

A `--soft` reset is honestly not that. It moves a branch pointer and keeps the
index and working tree. Session B had even tagged a backup first
(`git tag pre-reword-backup 43bac69`) — textbook care. Nothing about the command
was wrong.

**2. The force-push was not covered at all.** The `ask` list carried
`git push --force` and `git push -f`, in four shapes each (bare/`-C` ×
Bash/PowerShell). It carried **no** entry for `--force-with-lease`. So
`git -C ... push --force-with-lease` matched no `ask` rule and fell through to
the `allow` entry `Bash(git -C * push:*)`. This is a plain gap in the rule list,
and it is fixed alongside this ADR.

**3. The lease did not protect anything.** `--force-with-lease` compares the
remote-*tracking* ref, and a background fetch had refreshed that ref, so the
lease passed and the clobber proceeded. San had recorded this exact failure mode
earlier the same day.

### The finding that actually drove the design

Close finding 2 — add every force-push spelling to the `ask` list — and this
incident still happens, because finding 1 stands. The reset was the safe verb.
The dangerous fact was never in the command string:

> **the range you are discarding contains a commit you did not write, and it is
> already on the remote**

That fact lives in the repository. A prefix rule cannot see it. A semantic
classifier reading the command cannot see it either — it would have to be
clairvoyant about what `de133f2..HEAD` contained at 14:40:15, which is a
property of the world, not of the text. Any guard that reasons about *verbs*
will keep choosing between blocking every `reset` (which is unusable — resets
are how you legitimately fix your own history) and blocking none.

So the guard has to be **stateful**: ask git, at the moment of the call, what
this command would actually destroy.

## Options considered

**(a) A `pre-push` git hook on repos flagged direct-to-main.** Catches pushes
from any source, not just Claude sessions, and survives a session that ignores
the Claude hook layer. Rejected as the primary: it fires only at the push, which
is three minutes and two commits after the point where the session went wrong,
and it needs installing and maintaining across twelve clones on two machines
with no existing propagation path for `pre-push` (the `scripts/githooks/`
mechanism covers `pre-commit`/`post-commit`/`post-checkout`). Worth revisiting
as defence-in-depth; not worth blocking this on.

**(b) Server-side branch protection / a ruleset on the affected repo.
— DISQUALIFIED, and not for a design reason.** This was the strongest option on
paper: server-side survives any local bypass. It is unavailable:

```
$ gh api repos/<owner>/<private-repo>/rulesets
{"message":"Upgrade to GitHub Pro or make this repository public to enable this
feature.","status":"403"}
```

Branch protection and rulesets are paid features for **private** repositories,
and the repo this happened in — the one holding the most irreplaceable prose —
is private. The same call against public `claude-ops`
returns `[]` and would work fine. So server-side protection is available for
exactly the eight repos where a PR gate already exists, and unavailable for the
four private direct-to-main ones where it is needed. Note also that even where
it works it is a poor fit for the legitimate-rewrite case the brief calls out
(the de-identification squash): a ruleset blocking force-push has to be
toggled off and back on around such a rewrite, which is a footgun of its own —
protection that is routinely disabled is protection you cannot rely on being
enabled.

**(c) A house-conventions rule and nothing else.** Necessary — it is written,
see `conventions/parallel-sessions.md` — but demonstrably not sufficient on its
own. `hooks/git-staging-guard.py` exists because a behavioural rule about
staging failed twice in two days, the second time *after* the first was already
a known lesson in the same session. The finding recorded there applies verbatim
here: **the durable fix for a reflex is a mechanism, not an intention.**

**(d) A `PreToolUse` hook on the invariant. — CHOSEN.** Detailed below.

## Decision

`hooks/published-history-guard.py`, a global `PreToolUse` hook on
`Bash`/`PowerShell`, blocks two command shapes when — and only when — the
repository says they would drop a commit that is already on the remote:

1. a **history-rewriting push** (`--force`, `-f`, `--force-with-lease[=...]`,
   `--force-if-includes`, `--mirror`, or a `+refspec`);
2. a **backward `reset`** whose discarded range contains published commits.

Four things about that are deliberate.

**Both shapes, not just the push.** The push is where the loss becomes
irreversible, so it must be guarded. But the reset is where the session went
wrong, and catching it there is strictly better: in this incident the reset
check fires at 14:40:15, **49 seconds before** the destructive push and before
the session builds two more commits on a base the remote had already moved past.
The push check is the backstop; the reset check is the fix.

**`main` only.** Force-pushing a feature branch is one session's own lane, is
the normal way to tidy a PR before merge, and merge-deletes anyway. Guarding it
would fire constantly for no risk, and a guard that cries wolf gets routed
around — which is a worse outcome than the mistake it prevents. The exposure
this exists for is precisely the direct-to-main repo, where every session pushes
to one shared ref with nothing in between.

**Ground truth is `ls-remote`, never the tracking ref.** The tracking ref is the
thing that defeated `--force-with-lease`; a guard that consulted it would
inherit the same blind spot. This follows ADR-004's regression suite, which
asserts against the bare remote for the same reason.

**It fails open, with one stated exception.** Unparseable payload, no git
binary, not a repo, an unrecognised command — all exit 0, because a guard must
not break unrelated work. The exception: having positively identified a rewrite
of `main`, if it *cannot verify* what would be destroyed (no network, no auth,
an unresolvable ref) it blocks. Failing open there reopens the exact hole it was
written to close, and the override is one token away.

Override is `REWRITE-MAIN-OK`, per-command, matching `STAGE-ALL-OK` and
`MASK-OK`. The de-identification squash is the standing example of a rewrite
that should proceed — the guard's job is to make that a decision rather than a
default.

Separately, the rule-list gap from finding 2 is closed: `--force-with-lease`
and `--force-if-includes` join `--force`/`-f` in the `ask` list, in all four
shapes.

## Verification

26 new checks, `python -m unittest discover -s tests` green at 166 total. The
suite builds **real** repositories — a bare remote plus clones playing Session A
and Session B — because the assumption that broke in the incident (that a local
ref tells you what the remote has) is exactly the kind a mock would have
preserved.

Verified by mutation, not just by passing:

| Mutation | Checks that fail |
|---|---|
| Both checks neutered (`return None`) | 10 |
| `_remote_head` regressed to the tracking ref | 7 |

The second is the one worth keeping. It is a mechanical re-introduction of
`--force-with-lease`'s own bug into the guard, and the suite catches it — so a
future edit that "simplifies" the network call away cannot land quietly.

Two real defects surfaced during that work, both of which would have made the
guard fail open on the shape it exists to catch:

- **`shlex.split(..., posix=True)` eats backslashes**, so
  a Windows-style `git -C D:\work\repo push --force` tokenized with the path
  mangled to `D:workrepo`. The repo then failed to resolve and the
  command sailed through — on Windows, which is the platform this runs on. Now
  tokenized in non-posix mode with quotes stripped afterwards.
- **A clone that has not fetched since the remote moved does not hold the remote
  tip**, so every ancestry question about it answered "unknown", which the first
  draft read as "nothing published is at risk". That is the *normal* state for
  the session this guard is called in. Both paths now fetch once and fail closed
  if the object still cannot be read.

Neither was caught by reading the code. Both were caught by running it against a
reconstruction of the incident, which is the argument for building the fixture
that way.

## Consequences

- Force-pushing `main` and resetting `main` backwards now cost one deliberate
  override token whenever published commits are in the discarded range. That is
  the intended friction and it lands on a genuinely rare operation.
- The guard makes a **network call** (`ls-remote`) on those shapes only. Not on
  a plain push, not on a feature branch, not on any other git command.
- **Non-`main` refs are unguarded, by design.** A session can still force-push a
  shared feature branch out from under another session. Accepted: those are
  short-lived, single-owner, and PR-gated.
- **Private repos remain without a server-side backstop** until the plan changes
  or they go public. The local guard is the whole defence there, and a session
  that shells out through a path the hook does not see is not covered. This is a
  real residual risk, recorded rather than papered over.
- The canonical `conventions/parallel-sessions.md` gains the divergence-recovery
  rule. The **compressed** shared block mirrored into sibling repos'
  `CLAUDE.md` is deliberately left unchanged: editing it drifts every public
  consumer at once and reddens the drift check until each is swept, which is a
  fleet-wide change and a separate piece of work from this one.
