# The agent-facing contract is executed, not read (hard rule)

`CLAUDE.md`, `AGENTS.md`, a `## Releasing` section — these are not documentation
with an agent as an incidental reader. They are the program the agent runs.
Written that way, they get two properties ordinary docs don't need: the model's
**disagreement is surfaced before its edits**, and every procedure states its
**idempotency boundary** — which step must not be repeated, and what to do
instead when it half-fails.

This is a agent-ops-local convention — no consumer repo mirrors it, so there is
no shared block to propagate.

Distilled from a read of [pi](https://github.com/earendil-works/pi) (MIT), an
agent harness whose `AGENTS.md` is unusually disciplined about being a contract
rather than a description.

## Rule 1: say agree or disagree, then say what changed

pi's `AGENTS.md`, under *Conversational Style*:

> When responding to user feedback or an analysis, explicitly say whether you
> agree or disagree before saying what you changed.

The failure this closes is specific and common. A user pushes back; the model
edits; the reply is a changelog. The user reads compliance and infers agreement,
because a list of changes is what agreement looks like from the outside. If the
model actually thought the feedback was wrong and complied anyway, that
disagreement is now unrecoverable — it existed only in the turn that got
replaced by a diff.

Ordering matters more than it looks. Stated *after* the changes, the position
reads as justification for work already done, and the model is now arguing
against its own output. Stated *first*, it is a claim the user can act on before
reading anything else — including "I disagree and did it anyway", which is a
legitimate and useful thing to say out loud.

This pairs directly with San's own standing rules: findings default to
*deferred*, and a real design fork gets surfaced as an explicit question rather
than silently resolved. Agree/disagree is the same discipline at turn
granularity — the smallest unit where a silent capitulation can happen.

pi's neighboring rule is worth taking with it: *answer the question first,
before making edits or running implementation commands.* Both defend the same
thing, which is that the reasoning must not be inferable only from the diff.

## Rule 2: procedures are runbooks, with the idempotency line drawn

pi's release section (`AGENTS.md`, *Releasing*) is written as steps an agent
executes, not as an overview a human skims. The transferable parts:

- **A precondition that is a question to the human, not an assumption.** Step 1
  is "ask the user whether they ran the `/cl` prompt on the latest commit" — not
  "changelogs should be current". A precondition the agent cannot verify becomes
  a question, and the runbook stops there until it is answered.
- **A smoke test with the acceptance criterion spelled out.** Not "verify it
  works" but: run both the Node and Bun builds from outside the repo so they
  can't resolve workspace files, start interactive mode, submit a prompt, wait
  for the model reply — and *then* it counts as passed. Plus the disposition:
  failures are release blockers unless the user explicitly accepts the risk.
- **The exact command, including the env vars, including why they're scoped to
  that one command.** `npm_config_min_release_age=0` is documented as
  release-command-only, with the reason (the normal npm age gate would otherwise
  block the release lockfile refresh).
- **The idempotency boundary, stated as a prohibition at the exact step.**
  "Do not rerun the release script after a tag was pushed." And on the failure
  path: the CI publish helper *is* idempotent and skips versions already on npm,
  so rerun the tag workflow — but do not rerun `release:patch` for the same
  version.

That last pair is the whole point. A retry is the single most natural thing an
agent does when a step fails, and a multi-step release is exactly where a retry
is destructive: the tag is pushed, the version is burned, the changelog section
is already rotated. So the runbook does not merely describe the happy path — it
names, per step, which half is safe to repeat and which is not. **Any procedure
an agent will execute needs that line drawn explicitly, because "just run it
again" is the default and it is wrong here.**

The check: for every runbook in this fleet, is there a step where a rerun does
damage? If yes, is the prohibition written *at that step*, in the imperative,
rather than left as something the reader is expected to infer from context?

## Rule 3 (external confirmation): the multi-session git rules converge

pi's `AGENTS.md` opens its *Git* section with the same premise this repo's
[`parallel-sessions.md`](parallel-sessions.md) starts from — multiple sessions
in one working directory, each editing different files, unable to see each
other — and derives the same rules from it:

- Only commit files you changed in this session.
- Stage explicit paths; never `git add -A` / `git add .`. Run `git status`
  first and verify.
- A hard forbidden-verbs list: `git reset --hard`, `git checkout .`,
  `git clean -fd`, `git stash`, `git add -A`, `git add .`,
  `git commit --no-verify`.
- On a rebase conflict in a file you did not modify: abort and ask the user.
- Never force push.

That is, line for line, what this repo enforces mechanically in
[`../hooks/git-staging-guard.py`](../hooks/git-staging-guard.py) (whole-tree
staging blocked) and
[`../hooks/published-history-guard.py`](../hooks/published-history-guard.py)
(force-push and backward `reset` on `main` blocked when the discarded range
holds a published commit), with the reasoning in
[`../decisions/ADR-007-guard-the-invariant-not-the-verb.md`](../decisions/ADR-007-guard-the-invariant-not-the-verb.md).

Recorded here as **independent convergence, not as a source.** These rules were
written here after a local incident — two sessions racing on `main`, one
erasing the other's pushed commit — and pi arrived at them from its own
concurrency model, in a widely-used project (~81k stars at the time of this
read, 2026-08-01) with many contributors. Two independent derivations of the same short list is the closest
thing to evidence available for a practice that can't be A/B tested on one
machine: it is not one person's idiosyncrasy.

One real difference is worth keeping visible. pi states the rules as prose in
`AGENTS.md` and trusts the agent to follow them. This repo states them *and*
backs the two costliest with `PreToolUse` hooks, because that is this repo's
whole thesis — a behavioral rule that matters gets a mechanical backstop or it
eventually fails. The convergence validates the rules; it does not validate
leaving them behavioral.

See also [`allowlists-fail-both-ways.md`](allowlists-fail-both-ways.md),
[`truncation-defers.md`](truncation-defers.md) and
[`truncated-producers-taint.md`](truncated-producers-taint.md), from the same
read.
