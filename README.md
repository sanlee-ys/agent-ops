# claude-ops

Field notes on running an agentic coding CLI as a real teammate on a real
machine, with real credentials sitting nearby — written by one engineer,
for one machine, published because the failure modes don't stay put.

## Why this exists

Agentic CLIs like Claude Code don't just edit files anymore. They run shell
commands, read arbitrary config, call MCP servers with live tokens in their
environment, and fan out into multi-agent workflows that can spend real money
in minutes. That combination — broad tool access plus standing credentials —
is a live security surface, and it's under-documented. Most of what's written
about it is either marketing ("agents are safe by design") or after-the-fact
incident response at a company that isn't going to publish its postmortems.

This repo is neither. It's the operating layer that grew out of actually
running Claude Code day to day on one machine: a security posture, the
`PreToolUse` guards that enforce part of it mechanically, five incident
postmortems written in blameless format with the failures left in — plus
two write-ups deliberately demoted to debug notes when the log was held to
an honest severity bar — five reusable skills, and the working agreements
(how work gets scoped, how parallel sessions stay out of each other's way)
that the posture and the incidents both assume.

Three of those are credential exposures — one covering two separate leaks
of the same GitHub PAT — for four exposure events in one week, three of
them the *same* credential leaking through a *different* tool or command
shape each time, because the guard that closed the previous gap was scoped
to the surface someone had thought to enumerate, not to the surface that
actually existed. That pattern — a mechanical control that's
only as complete as its author's imagination — is the throughline of this
repo, and it's also the reason the guard's own source is published here
rather than kept private. Security through "attacker doesn't know the rules"
doesn't hold on a machine where the attacker already has local execution;
the guard's value is defense-in-depth, not secrecy, so publishing it costs
nothing and might get the next gap found by a reader instead of a leak.

## Map

- **`operating-model.md`** — the working agreements this all runs on: DCB
  (Direction / Contracts / Bar) as the scoping discipline, the session
  pre-flight, the parallel-session protocol, and reasoning effort as a
  routing axis (recorded with its own lack of evidence stated). Compressed
  2026-08-01 to the parts that are load-bearing as prose — every practice
  that mattered enough either earned a mechanical backstop in `hooks/` and
  `conventions/`, or it was ceremony; the long form is in git history.
- **`security/`**
  - `posture.md` — the layered security model: permission allowlist design,
    escape hatches, and the standing rule that credential-touching commands
    (token rotation, key generation) are run by the human directly, never
    through a tool call.
  - `credential-guard.py` — the published `PreToolUse` hook. Blocks bulk
    environment dumps and reads of known-sensitive files (shell config,
    SSH keys, cloud CLI credential stores, `.env` files) across Bash,
    PowerShell, Read, and content-mode Grep. What it covers is also, by
    omission, a map of what it doesn't — that's discussed openly in
    `security/README.md` and in the incidents.
  - `README.md` — how the hook is wired in, what it does and doesn't cover,
    and the override convention for legitimate reads it blocks.
- **`hooks/git-staging-guard.py`** — a `PreToolUse` hook that blocks
  whole-tree staging (`git add -A|-u|.`, `git commit -a`), so a session cannot
  sweep a *parallel* session's uncommitted work into an unrelated commit. The
  interesting constraint is that it must not block prose: the commit messages
  and postmortems describing the incidents quote those flags verbatim, so it
  strips heredoc bodies and tokenizes rather than grepping for a flag. Tested
  both ways in `tests/`.
- **`hooks/published-history-guard.py`** — a `PreToolUse` hook that blocks a
  force-push or a backward `reset` on `main` when the discarded range holds a
  commit the remote already has, so one session cannot erase another's pushed
  work in a direct-to-main repo. Unlike the guards above it is *stateful*: the
  fact that condemns the command ("that range contains someone else's published
  commit") is in the repository, not in the command string, so it asks git —
  and asks `ls-remote`, never the tracking ref, since a stale-then-refreshed
  tracking ref is what defeated `--force-with-lease` in the incident behind it.
  Reasoning in [`decisions/ADR-007`](decisions/ADR-007-guard-the-invariant-not-the-verb.md).
- **`incidents/`** — five blameless postmortems, held to a deliberate bar:
  real exposure, real spend, or a live control failing. They share a spine —
  summary, impact, root cause, the fixes actually applied, lessons learned —
  but the format follows the failure rather than a template. Four of the
  five are one story told honestly: the same credential surface leaking
  through a different tool or command shape each time, each guard scoped to
  the surface its author had imagined rather than the one that existed. The
  fifth is a multi-agent fan-out with no cost cap spending a usage window in
  minutes.
  - `2026-07-02-plaintext-api-key-exposure.md`
  - `2026-07-02-uncapped-premium-fanout.md`
  - `2026-07-03-github-pat-plaintext-recurrence.md`
  - `2026-07-03-credential-guard-interpreter-bypass.md`
  - `2026-07-04-github-pat-read-grep-leak.md`
- **`debug-notes/`** — two write-ups that were originally filed as incidents
  and demoted on 2026-08-01 when the log was held to the bar above: the
  console-flash hunt (three root causes, one wrong diagnosis) and the killed
  `SessionEnd` hook that silently wedged memory sync. Worth keeping, not
  incidents — a log where every annoying bug is an "incident" is a log where
  severity means nothing. The demotion is the posture.
- **`skills/`** — five custom skills (`dcb`, `descope-sweep`, `park`,
  `proglog`, `handoff`) published as patterns, with a `README.md` explaining
  what each does and when it fires.
- **`decisions/`** — the repo's own contract, honestly versioned:
  - `ADR-001-public-claude-ops-repo.md` — the scope contract: what gets
    published here and what never does.
  - `ADR-002-public-first-canonicality.md` — the same-day reversal of
    ADR-001's sync model: this repo is the system of record, written
    public-first, because "redact carefully" is a behavioral rule and this
    repo's whole thesis is that behavioral rules get mechanical backstops.
  - `ADR-003-delegation-maturity.md` — the plan to close the last point of a
    self-rated 9/10, in three phases that each trade prose for a mechanical
    control or a measured number, plus a backlog deliberately gated shut
    until they land. Kept honest by its own measurements: the 40%
    rule-surface reduction the draft floated was falsified by the audit it
    called for — the real figure was ~16%, because the duplication it
    assumed was mostly not there.
  - `ADR-004-ref-explicit-git-in-shared-clones.md` — automation that commits
    to `HEAD` but pushes a named ref assumes the two are the same object.
    In a clone shared by parallel sessions that assumption is someone else's
    variable, and when it breaks the wrong way a squash-merge deletes the
    commit. Target the ref explicitly, or refuse to act.
  - `ADR-005-herdr-persistence-not-agent-awareness.md` — a trialled agent
    multiplexer, adopted. Kept mostly as a record of how it was nearly
    rejected for things it doesn't do: the "it reports success for input it
    never submitted" finding came from one log line correlated with one
    composer, and both halves were wrong — the call worked, and the text was
    dim placeholder nobody had typed. Corrected twice on the day of writing.
    A defect claimed from a single correlated observation is a hypothesis;
    reproduce it before writing decisions on top of it.
  - `ADR-006-claim-the-concern-before-working-it.md` — two sessions wrote the
    same decision the same afternoon, on different machines, and the
    in-flight scan that should have caught it returned nothing truthfully:
    one session's work was an untracked file, the other's an unpushed
    branch. The fix isn't a channel between sessions — both believed they
    owned the concern, and peers who agree on that collide however well they
    can talk. Push the branch before doing the work, so the claim exists
    where the other machines can see it.
- **`scripts/redline-guard.py`** — that backstop: a pre-commit hook that
  scans staged content for the publication-boundary violations (credential
  shapes, private repo names, private memory links, local paths). Its banned
  terms ship as SHA-256 hashes so the guard can't itself violate the
  redlines it enforces.

## Start here

1. **`security/posture.md`** — the model this repo assumes: layered
   controls, not a single silver-bullet hook.
2. **`incidents/2026-07-04-github-pat-read-grep-leak.md`** — the sharpest
   illustration of the throughline above. A hook built to stop shell
   commands from leaking a token got bypassed by Claude's own `Read` and
   `Grep` tools reading the same file with no shell involved — and even
   "grep instead of cat" wasn't safe, because content-mode grep still prints
   the matched line, and the matched line for a `"KEY": "value"` config
   entry *is* the secret.
3. **`security/credential-guard.py`** — the fix, in the form it actually
   runs in.

## Scale, honestly

This is one engineer's machine, not a team or a platform. There's no fleet,
no shared incident channel, no on-call rotation — every "postmortem" here is
a solo session catching its own mistake in the same turn it happened. It's
published anyway because the failure modes (tool-shape gaps in a mechanical
guard, uncapped multi-agent fan-out cost, a debugging session in production
credentials by accident) don't depend on team size. They just need an agent
with shell access and a person who trusts it a little too soon.
