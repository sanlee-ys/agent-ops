# Branch hygiene — the merge setting covers one side (hard rule)

`delete_branch_on_merge` deletes `origin/<branch>` when a pull request merges.
It does not touch the local branch, and the command that would clean that up
refuses to. Local branches therefore accumulate in a clone that looks tidy from
GitHub.

This is a claude-ops-local convention — no consumer repo mirrors it, so there is
no shared block to propagate.

## The mechanism

Two independent facts combine into a silent leak:

1. **`delete_branch_on_merge` is server-side.** It is a per-repo GitHub setting,
   off by default, enabled across these repos on 2026-07-04. What it deletes is
   the remote ref. Nothing about it reaches a clone.
2. **These repos squash-merge.** A squash merge writes a *new* commit onto
   `main`; the branch's own commits never become ancestors of it. So
   `git branch -d` — which deletes only branches whose commits `main` already
   contains — correctly refuses every merged branch as "not fully merged."

The safe command doesn't apply, and the forcing one is the kind of thing a
session declines to run on a hunch. The branch stays.

What makes it *silent* rather than merely untidy is which side got cleaned.
`git branch -r` and the GitHub branch list are both correct, because the remote
was tidied on schedule. The litter appears only in `git branch --list` inside a
clone, which nothing routinely reads. The half of the system that gets inspected
is the half that was fixed.

## The evidence

Found 2026-07-26 while closing out an unrelated session: `claude-ops` held **18**
local branches (17 squash-merged, one with no commits at all) and `netops-lab`
held 4. Every one of the 21 had a merged pull request. Several were from that
same day, created under the one-concern-one-branch rule in
[`operating-model.md`](../operating-model.md) — which is the point rather than an
aside: that rule makes branches deliberately cheap and frequent, so this fills
faster than it feels like it should.

An hour before finding them, the same session had reported "one unpushed local
branch" as its only outstanding litter. It had looked at the remote.

## The sweep

Per repo, in this order:

```
git -C <repo> fetch --prune
git -C <repo> worktree prune
git -C <repo> branch --list --merged main
git -C <repo> branch --list --no-merged main
gh pr list -R <owner>/<repo> --state merged --limit 100 --json number,headRefName,title
git -C <repo> branch -D <verified branches...>
```

`fetch --prune` first, so the remote-tracking refs reflect what the server
actually still has rather than what this clone last saw.

## The rules that make `-D` safe here

`-D` discards commits with no warning and no recovery path short of the reflog.
These are not optional:

- **Match every branch to a merged pull request by `headRefName` before
  deleting.** That match is the only thing standing between a routine sweep and
  destroying unpushed work. Never infer it from a branch name that looks
  finished — the name is the thing a half-done branch and a merged one have in
  common.
- **A branch with no matching merged PR is not litter.** It is unfinished, or it
  belongs to a parallel session that has not pushed yet. Leave it, and say so in
  the report rather than quietly skipping it. See
  [`parallel-sessions.md`](parallel-sessions.md) and
  [`ADR-006`](../decisions/ADR-006-claim-the-concern-before-working-it.md) — an
  unpushed branch is precisely the state that convention exists to make visible.
- **Use `-d`, not `-D`, for anything `--merged main` lists.** That path is
  genuinely safe and stays the default where it applies; reaching for `-D`
  everywhere trades a real guarantee for uniform-looking commands.
- **`worktree prune` first.** A branch checked out in a stale worktree will not
  delete, and the error reads like a permissions problem rather than a
  registration one.
- **One command with many branch arguments, not a shell loop.** Loops are
  unanalyzable by the permission layer and prompt on every iteration.

## The check

Do the sweep at session close in any repo where a PR was merged, and report the
count. Do not treat a clean GitHub branch list as evidence — it is the surface
this failure mode leaves intact.

The reusable shape, beyond git: **a cleanup control that runs on one side of a
sync boundary can leave the other side dirty while removing the symptom you
would have noticed.** Before trusting any automated tidy-up, name which side it
runs on and check the other one by hand at least once.
