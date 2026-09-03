# Land

A PR exists and the ask is to get it merged. Green is not the same as safe. Check
each exception in merge-authorization before the merge, and merge when none holds.

0. **Direction.** Name the PR by full URL and restate what it changes in one
   sentence. "Done" means merged, branch deleted, and `main` verified.
1. **Read the live state, not the memory of it.** `gh pr view` for status and
   checks, `gh pr checks` for each gate, `git ls-remote` for what the remote holds.
   A tracking ref is a local cache (force-with-lease-not-safe-here).
2. **Every gate ran and is green.** A skipped or missing gate is not a pass. If CI
   is red or a gate did not run, stop and report; that is exception 1.
3. **A `git revert` would undo it.** Published or outward-facing content, a data
   migration, a deletion, anything near secrets or the private-repo boundary fails
   this test. If it fails, stop and report; that is exception 2.
4. **No guessed design decision is inside it.** If the PR encodes a fork you
   picked, surface that fork as a question about this PR, and stop; that is
   exception 3.
5. **Merge, and delete the branch.** Squash unless the repo's CLAUDE.md says
   otherwise.
6. **Bar: `main` on the remote carries the merge commit, and the next CI run on
   `main` is green.** Read `gh run list --branch main --limit 1` after it finishes.
   A green check on a workflow that did no work is not proof
   (agentic-ci-succeeds-quietly); when the workflow produces an artifact, check
   the artifact.
7. **Prune the local branch** after the merge (branch-hygiene).

**Reply:** merged or stopped, the PR link, which exception held if stopped, and
the `main` CI result.
