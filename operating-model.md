# Operating model: running Claude Code as an engineering teammate

This is the working agreement for directing Claude Code across a set of
personal repos. It is not a product manual — it is the set of practices that
grew out of running an agentic CLI, with real credentials and real git
remotes, across multiple machines and multiple sessions at once. Each
practice below exists because of a specific failure mode it closes off; see
`incidents/` for the postmortems that motivated several of them.

## 1. DCB: Direction, Contracts, Bar

The standing frame for directing any AI coding tool, this one included, is
three parts: **Direction**, **Contracts**, **Bar**. Short version: I set the
direction, the contracts, and the bar; the model does most of the typing; I
verify the output against the real repos before anything ships.

**Direction — mine, not delegable.** Who's doing this work and what is it
actually for. What's in scope, what "done" means for this piece of work,
which hat I'm wearing while I do it. This is the context a model needs to
establish a baseline; without it, the model is guessing at the goal, not
just the implementation.

**Contracts — the rules the tool is bound to, stated up front.** "Don't make
things up" is too weak to survive a model that's confidently wrong. The
useful version names the exact thing it isn't allowed to invent — a
credential format, a file path, a fact about a repo it hasn't read — as a
specific, checkable rule, not a vague hope. Contracts also cover fixed output
shapes for recurring tasks, so the result can be scanned instead of re-read
in full every time.

**Bar — trust, but verify.** What has to be true before output counts as
shipped. Checked against the real source — the actual repo state, the actual
file on disk, the actual command output — never against how confident the
model's prose sounds. A task only moves to "done" once it's been verified,
not when a response implies it's handled.

Why this matters regardless of model quality: a stronger model raises the
ceiling on hard reasoning, but it does not raise the floor on confident
wrongness by itself. DCB is the harness that makes any model safe to point
at real work — it's the same three checks whether the model is fast and
cheap or slow and expensive. The stricter the cost of being wrong, the
stricter the contract: something with legal or compliance weight gets a
"never assert, always flag as unverified" contract; a low-stakes first draft
can be produced freely and edited after.

## 2. Session pre-flight

Run this before touching any repo, every session, not just the first one of
the day:

1. **Sync.** Check out the main branch and pull. The local clone may be
   stale — a different machine may have moved the remote since you last
   looked at it, and this repo's history includes exactly that: an
   uncommitted local fix silently lost because a session on a different
   machine had already moved main first.
2. **Check.** Confirm `main` is green before building on it
   (`gh run list --branch main --limit 1`, or `gh run list --status failure`
   across the repos in play). Report a red `main` to the user at the top of
   the session, unprompted — this is the agent's job, not something the user
   should be discovering from CI notification mail. Added 2026-07-19, after a
   decision-log lint failure sat on `architecture`'s `main` and surfaced only
   because the user happened to read the GitHub emails in his inbox. A
   scheduled sweep is the wrong instrument for this: scheduled tasks run on
   the home machine and default to the weekend, so a weekday breakage would
   sit for days. Pre-flight fires on every machine, every session, same day.
3. **Scan.** Look for open pull requests and remote branches touching the
   same area before starting. The same fix half-built in two places at once
   is wasted work discovered late, not work saved.
4. **Claim.** One concern maps to one branch maps to one pull request. If
   the deliverable doesn't fit in a sentence, it's two pieces of work, not
   one — split it before starting rather than discovering the seam midway
   through a diff.
5. **Cut** along files nothing else touches. Files that aggregate or
   summarize other files (a README, an index, a generated doc) are the
   collision hotspots — serialize those rather than parallelizing across
   them.

## 3. Two cadences, and matching the cadence to the work

There are two different modes of working with the tool, and picking the
wrong one for the situation is itself the failure mode worth naming.

**Design, ambiguous, or learning work** — a new direction, a real tradeoff,
anything consequential or hard to reverse — runs in small steps with a stop
after each one. The model summarizes what it did, states the key decision it
made and why, says what's next, and waits. This is deliberately slower: it's
the only mode where the human actually gets to see a decision before it's
built on top of, weigh in, or redirect before three more steps compound the
wrong call.

**Execution of an already-decided, bounded task** — mechanical edits,
renames, a batch that's already been explicitly authorized — runs to
completion and reports at the end. No checkpoint between mechanical steps.
If the scope was authorized up front, stopping to ask permission for each
sub-step is friction without safety value; the risk was already retired at
the authorization step, not at each keystroke.

The reason to keep these separate rather than always defaulting to
checkpoints (safe but slow) or always running to completion (fast but
risky): checkpointing mechanical work wastes a human's attention on
decisions that were already made, and running ambiguous work to completion
without a checkpoint is exactly how a wrong assumption made at step one
silently becomes the foundation for steps two through ten. When it's unclear
which mode applies, that's a signal to ask once, not to guess and hope.

A closely related rule: when a design choice actually has more than one
reasonable answer, that choice gets surfaced as an explicit question rather
than silently picked. And if a task starts growing past what was actually
asked for, that gets flagged before the extra work is built, not after.

## 4. The parallel-session protocol

Running more than one agentic session at once — across sibling repos, and
across more than one machine that share the same git remotes — has one
structural property that shapes everything else: the sessions cannot see
each other's uncommitted work. The only thing they share is each repo's main
branch on the remote. Everything below follows from that one fact.

- **One concern per session, one branch, one pull request.** If a piece of
  work doesn't fit in a sentence, it's two sessions. Don't let a session
  wander into adjacent cleanup just because it's already in the file —
  that's the usual shape scope creep takes here, and it should be named and
  asked about before it expands, not absorbed silently.
- **Branch from a freshly-pulled main, merge fast, delete the branch on
  merge.** The longer a branch lives, the more main moves out from under it,
  and the more painful the eventual merge. "Delete on merge" is two jobs, not
  one: `delete_branch_on_merge` handles the remote ref, and nothing handles the
  local branch — under squash-merge `git branch -d` refuses it as unmerged, so
  it survives in a clone that looks clean from GitHub. The sweep, and the rules
  that make a forced delete safe, are in
  [`conventions/branch-hygiene.md`](conventions/branch-hygiene.md).
- **Parallelize by independent file, not by task.** Two sessions can safely
  work side by side if they touch disjoint files. They cannot safely both
  write to a generated or aggregated file — a build output, an index, a
  registry, a generated document — because those files can't be merged the
  way source diffs can. The fix is a division of labor, not a tooling
  workaround: independent content can be authored in parallel, but the
  wiring step — the actual registration or rebuild that touches the shared
  file — stays in one hand, done once, after the independent pieces have
  already landed.
- **Sync before touching anything, every device, every time.** A local clone
  being behind isn't an edge case in this setup, it's the default state
  between sessions. Pulling (or fetching and rebasing) before starting work
  means a stale clone gets caught at pull time. Never committing straight to
  main means a stale clone that slipped through anyway gets caught at push
  time instead of silently overwriting someone else's merged work.
  Uncommitted local work has no existence outside the machine it was typed
  on — the moment a session moves to a different machine, anything not
  pushed should be treated as gone, because from every other session's point
  of view, it is.

- **Stage explicit paths. Never `git add -A`, `git add -u`, `git add .`, or
  `git commit -a`.** Those stage *whatever is dirty*, not *what this session
  changed*, and in a working tree that another session is also writing to, the
  difference is somebody else's half-finished work landing in your commit.
  Name the files: `git -C <repo> add path/one path/two`, then read
  `git show --stat HEAD` before pushing.

  This is the one rule here with a **mechanical backstop**:
  [`hooks/git-staging-guard.py`](hooks/git-staging-guard.py) is a `PreToolUse`
  hook that blocks those four shapes, with a `STAGE-ALL-OK` per-command
  override for the cases where whole-tree staging is genuinely right. It exists
  because the behavioural version of this rule failed twice on 2026-07-18/19 —
  the second time *after* the first was already a known lesson in the same
  session, which is what a reflex looks like from the outside. A rule that
  depends on remembering, under time pressure, in the boring part of the work,
  is a rule with a known failure rate. The guard is that failure rate written
  down as code.

A given repo can layer its own version of these rules on top for local
specifics — its own collision-prone files, its own history of near-misses —
but the underlying shape (shared remote main as the only coordination point)
is the same everywhere.
