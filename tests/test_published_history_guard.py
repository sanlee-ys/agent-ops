#!/usr/bin/env python3
"""Test suite for hooks/published-history-guard.py.

The guard is stateful — it answers "would this destroy a published commit?" by
asking a real repository — so these tests build real repositories. A mocked git
would only prove the guard's own assumptions back to itself, and the assumption
that broke in the incident (that a tracking ref tells you what the remote has)
is precisely the kind a mock would have preserved.

Four groups:

  - **The incident, reconstructed.** Two clones of one bare remote playing the
    parts of Session A and Session B, reproducing 2026-07-26 commit for commit.
    These are the cases that must fail against an unfixed guard.
  - **Blocked shapes.** The other ways to drop a published commit from `main`.
  - **Allowed shapes.** The far more important half. A guard that fires on
    feature-branch rebases, on prose quoting it, or on a plain push gets routed
    around, and a routed-around guard protects nothing.
  - **The other entry points** (`TestOtherWaysToRewriteMain`). v1.0 dispatched
    on `push` and `reset` only, so `commit --amend`, `rebase`, `branch -f`,
    `checkout -B`, `update-ref`, `filter-branch` and a remote-branch delete all
    reached `main` uninspected. Every verb there is paired: the rewrite that
    drops a published commit, and the same verb used safely. The pairing is the
    point — a one-sided suite proves a guard blocks, not that it is usable.

Stdlib only (no pytest) so CI is a bare `python -m unittest`. The guard is
driven exactly as the harness drives it: a PreToolUse JSON payload on stdin,
exit 0 = allow, exit 2 = block.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

GUARD = Path(__file__).resolve().parent.parent / "hooks" / "published-history-guard.py"

BLOCK, ALLOW = 2, 0


def run(command: str, tool_name: str = "Bash", cwd: str | None = None) -> int:
    """Drive the guard the way the harness does; return its exit code."""
    payload = {"tool_name": tool_name, "tool_input": {"command": command}}
    if cwd:
        payload["cwd"] = cwd
    proc = subprocess.run(
        [sys.executable, str(GUARD)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    return proc.returncode


def git(repo: Path, *args: str) -> str:
    """Run git in ``repo``, raising on failure so a broken fixture is loud."""
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr}")
    return proc.stdout.strip()


def commit(repo: Path, filename: str, text: str, message: str) -> str:
    (repo / filename).write_text(text, encoding="utf-8")
    git(repo, "add", filename)
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD")


class GitFixture(unittest.TestCase):
    """A bare remote plus however many clones a test needs."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="phguard-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.remote = self.tmp / "remote.git"
        subprocess.run(
            ["git", "init", "--bare", "-b", "main", str(self.remote)],
            capture_output=True,
            check=True,
        )

    def clone(self, name: str) -> Path:
        path = self.tmp / name
        subprocess.run(
            ["git", "clone", str(self.remote), str(path)],
            capture_output=True,
            check=True,
        )
        git(path, "config", "user.email", "test@example.invalid")
        git(path, "config", "user.name", "Test Session")
        return path

    def seeded_clone(self, name: str) -> Path:
        """A clone with one commit already pushed to `main`."""
        repo = self.clone(name)
        commit(repo, "ideas.md", "base\n", "base commit")
        git(repo, "push", "-u", "origin", "main")
        return repo


class TestTheIncident(GitFixture):
    """2026-07-26 in `career`, reconstructed against real repositories.

    Session B resets past a commit Session A has already pushed, then
    force-pushes over it. Both halves must be caught; either one alone would
    have saved the commit.
    """

    def setUp(self) -> None:
        super().setUp()
        self.a = self.seeded_clone("session_a")
        self.base = git(self.a, "rev-parse", "HEAD")

        # Session B branches from the same base and pushes its own commit.
        self.b = self.clone("session_b")
        commit(self.b, "ideas.md", "base\nB's glossary retarget\n", "B: retarget")
        git(self.b, "push", "origin", "main")

        # Session A pulls B's commit, adds its own, and pushes. This is the
        # commit that was destroyed.
        git(self.a, "pull", "--rebase")
        commit(self.a, "notes.md", "A's Kun Chen correction\n", "A: correct entry")
        git(self.a, "push", "origin", "main")

    def test_soft_reset_past_session_a_commit_is_blocked(self) -> None:
        """The literal command Session B ran, 49 seconds before the damage."""
        self.assertEqual(
            run(f"git -C {self.b} reset --soft {self.base}"),
            BLOCK,
        )

    def test_force_with_lease_over_session_a_commit_is_blocked(self) -> None:
        """The push that actually destroyed the work.

        Its lease *passed* in the incident, because a background fetch had
        refreshed the tracking ref. So the fixture refreshes it too — if the
        guard consulted the tracking ref like `--force-with-lease` does, this
        test would let it through, which is the whole point.
        """
        git(self.b, "fetch", "origin")
        git(self.b, "reset", "--hard", self.base)
        commit(self.b, "ideas.md", "base\nB's rework\n", "B: rework")
        self.assertEqual(
            run(f"git -C {self.b} push --force-with-lease"),
            BLOCK,
        )

    def test_reset_to_own_unpushed_work_still_allowed(self) -> None:
        """B's reset would have been fine had A not pushed underneath it.

        Same command, same repo, one difference: nothing published sits in the
        discarded range. The guard must tell those two apart, or it is just a
        ban on `reset`.
        """
        b2 = self.seeded_clone("session_b_alone")
        base = git(b2, "rev-parse", "HEAD")
        commit(b2, "ideas.md", "base\nlocal only\n", "unpushed work")
        self.assertEqual(run(f"git -C {b2} reset --soft {base}"), ALLOW)


class TestBlockedShapes(GitFixture):
    """The other ways to drop a published commit from `main`."""

    def setUp(self) -> None:
        super().setUp()
        self.repo = self.seeded_clone("repo")
        self.base = git(self.repo, "rev-parse", "HEAD")
        other = self.clone("other")
        commit(other, "theirs.md", "their work\n", "another session's commit")
        git(other, "push", "origin", "main")
        # Diverge locally without seeing their commit.
        commit(self.repo, "mine.md", "my work\n", "my commit")

    def test_force(self) -> None:
        self.assertEqual(run(f"git -C {self.repo} push --force"), BLOCK)

    def test_force_short_flag(self) -> None:
        self.assertEqual(run(f"git -C {self.repo} push -f origin main"), BLOCK)

    def test_plus_refspec(self) -> None:
        self.assertEqual(run(f"git -C {self.repo} push origin +main"), BLOCK)

    def test_force_with_lease_explicit_branch(self) -> None:
        self.assertEqual(
            run(f"git -C {self.repo} push --force-with-lease origin main"), BLOCK
        )

    def test_hard_reset_past_published_commit(self) -> None:
        """The discarded range must actually *contain* the published commit.

        Pull their commit in first, then reset back past it. Without the pull
        their work is not in this branch's history at all, so a reset cannot
        drop it — see `test_reset_while_remote_is_ahead_drops_nothing_published`
        for that neighbouring case, which is correctly allowed.
        """
        git(self.repo, "pull", "--rebase")
        self.assertEqual(run(f"git -C {self.repo} reset --hard {self.base}"), BLOCK)

    def test_reset_while_remote_is_ahead_drops_nothing_published(self) -> None:
        """Diverged, but the discarded range is entirely your own unpushed work.

        The reset is survivable (reflog) and destroys nothing anyone else has.
        The force-push that would follow is the dangerous half, and
        `test_force` above covers it. Blocking here too would be the kind of
        over-firing that gets a guard disabled.
        """
        self.assertEqual(run(f"git -C {self.repo} reset --hard {self.base}"), ALLOW)

    def test_caught_in_second_half_of_compound_command(self) -> None:
        self.assertEqual(
            run(f"git -C {self.repo} status && git -C {self.repo} push --force"),
            BLOCK,
        )

    def test_cwd_is_used_when_no_dash_C(self) -> None:
        """A bare `git push --force` is judged against the session's cwd."""
        self.assertEqual(run("git push --force", cwd=str(self.repo)), BLOCK)

    def test_unreachable_remote_fails_closed(self) -> None:
        """The one place the guard fails closed rather than open."""
        git(self.repo, "remote", "set-url", "origin", str(self.tmp / "does-not-exist"))
        self.assertEqual(run(f"git -C {self.repo} push --force"), BLOCK)


class TestAllowedShapes(GitFixture):
    """The half that decides whether the guard survives contact with real work."""

    def setUp(self) -> None:
        super().setUp()
        self.repo = self.seeded_clone("repo")
        self.base = git(self.repo, "rev-parse", "HEAD")

    def test_plain_push(self) -> None:
        commit(self.repo, "mine.md", "work\n", "my commit")
        self.assertEqual(run(f"git -C {self.repo} push"), ALLOW)

    def test_force_push_on_feature_branch(self) -> None:
        """Rebasing your own PR branch is normal and must stay frictionless."""
        git(self.repo, "checkout", "-b", "feature-x")
        commit(self.repo, "mine.md", "work\n", "my commit")
        git(self.repo, "push", "-u", "origin", "feature-x")
        commit(self.repo, "mine.md", "reworked\n", "amended work")
        self.assertEqual(
            run(f"git -C {self.repo} push --force-with-lease"), ALLOW
        )

    def test_force_push_that_is_actually_a_fast_forward(self) -> None:
        """`--force` on a branch that has not diverged destroys nothing."""
        commit(self.repo, "mine.md", "work\n", "my commit")
        self.assertEqual(run(f"git -C {self.repo} push --force"), ALLOW)

    def test_reset_dropping_only_unpushed_commits(self) -> None:
        commit(self.repo, "mine.md", "work\n", "unpushed")
        self.assertEqual(run(f"git -C {self.repo} reset --soft {self.base}"), ALLOW)

    def test_bare_reset_unstages(self) -> None:
        self.assertEqual(run(f"git -C {self.repo} reset"), ALLOW)

    def test_reset_with_pathspec_unstages(self) -> None:
        self.assertEqual(run(f"git -C {self.repo} reset -- ideas.md"), ALLOW)

    def test_override_token(self) -> None:
        """The deliberate rewrite — the de-identification squash shape."""
        other = self.clone("other")
        commit(other, "theirs.md", "their work\n", "published commit")
        git(other, "push", "origin", "main")
        commit(self.repo, "mine.md", "mine\n", "my commit")
        self.assertEqual(
            run(f"REWRITE-MAIN-OK git -C {self.repo} push --force"), ALLOW
        )

    def test_prose_quoting_the_command_in_a_heredoc(self) -> None:
        """The guard must be able to document itself.

        credential-guard's v1 blocked its own commit message; this suite exists
        partly so that lesson does not have to be relearned per hook.
        """
        command = (
            f"git -C {self.repo} commit -F - <<'EOF'\n"
            "Add published-history guard\n\n"
            "Blocks `git push --force` and `git reset --hard <base>` when the\n"
            "discarded range holds a published commit.\n"
            "EOF"
        )
        self.assertEqual(run(command), ALLOW)

    def test_quoted_command_in_an_echo(self) -> None:
        self.assertEqual(
            run("echo 'run git push --force to rewrite'"), ALLOW
        )

    def test_unrelated_git_commands(self) -> None:
        for cmd in ("git status", "git log --oneline", "git fetch origin"):
            with self.subTest(cmd=cmd):
                self.assertEqual(run(f"git -C {self.repo} {cmd.split(' ',1)[1]}"), ALLOW)

    def test_non_git_command(self) -> None:
        self.assertEqual(run("rsync --force a b"), ALLOW)

    def test_non_shell_tool_is_ignored(self) -> None:
        self.assertEqual(
            run(f"git -C {self.repo} push --force", tool_name="Read"), ALLOW
        )

    def test_not_a_repository_is_ignored(self) -> None:
        self.assertEqual(
            run(f"git -C {self.tmp / 'nope'} push --force"), ALLOW
        )

    def test_malformed_payload_fails_open(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(GUARD)],
            input="not json",
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, ALLOW)


class TestOtherWaysToRewriteMain(GitFixture):
    """Every entry point the two-verb dispatch never saw.

    v1.0 inspected `git push` and `git reset` and nothing else, so six other
    spellings of "move `main` backwards over somebody's published commit"
    reached the ref uninspected — and `commit --amend` on a pushed commit is a
    reflex, not an attack.

    Each verb is tested twice, and the *allow* half is the load-bearing one. A
    guard that blocks `git commit --amend` on an unpushed commit, or a rebase of
    a purely local branch, is a guard somebody disables wholesale — at which
    point the block cases protect nothing.

    The fixture: `main` at `base` -> `second`, both pushed. So HEAD is
    published, which is the normal state of a direct-to-main repo and the state
    every one of these verbs is dangerous in.
    """

    def setUp(self) -> None:
        super().setUp()
        self.repo = self.seeded_clone("repo")
        self.base = git(self.repo, "rev-parse", "HEAD")
        self.second = commit(self.repo, "second.md", "second\n", "second commit")
        git(self.repo, "push", "origin", "main")

    def unpushed(self) -> str:
        """Add a commit that the remote does not have."""
        return commit(self.repo, "local.md", "local\n", "unpushed work")

    def on_feature(self, name: str = "feature-x") -> None:
        git(self.repo, "checkout", "-b", name)

    # --- git commit --amend ------------------------------------------------

    def test_amend_of_a_pushed_commit_is_blocked(self) -> None:
        """The routine slip. HEAD is on the remote; amending replaces it."""
        self.assertEqual(
            run(f'git -C {self.repo} commit --amend -m "reworded"'), BLOCK
        )

    def test_amend_of_an_unpushed_commit_is_allowed(self) -> None:
        """The same command one commit later, and it must not fire.

        This is the near-miss that decides whether the amend check is usable:
        amending your own not-yet-pushed tip is the overwhelmingly common case.
        """
        self.unpushed()
        self.assertEqual(
            run(f'git -C {self.repo} commit --amend -m "reworded"'), ALLOW
        )

    def test_amend_on_a_feature_branch_is_allowed(self) -> None:
        self.on_feature()
        commit(self.repo, "mine.md", "work\n", "feature work")
        self.assertEqual(run(f"git -C {self.repo} commit --amend --no-edit"), ALLOW)

    def test_plain_commit_is_allowed(self) -> None:
        self.assertEqual(run(f'git -C {self.repo} commit -m "ordinary"'), ALLOW)

    def test_amend_in_a_repo_with_no_remote_is_allowed(self) -> None:
        """Nothing configured means nothing published — not "cannot verify".

        Without this the guard would fail closed in every `git init` scratch
        repo, which is how a guard gets switched off rather than fixed.
        """
        solo = self.tmp / "solo"
        solo.mkdir()
        subprocess.run(
            ["git", "init", "-b", "main", str(solo)], capture_output=True, check=True
        )
        git(solo, "config", "user.email", "test@example.invalid")
        git(solo, "config", "user.name", "Test Session")
        commit(solo, "a.md", "a\n", "first")
        self.assertEqual(run(f"git -C {solo} commit --amend --no-edit"), ALLOW)

    # --- git rebase --------------------------------------------------------

    def test_interactive_rebase_over_published_commits_is_blocked(self) -> None:
        """`git rebase -i <base>` gives every replayed commit a new sha.

        This is the incident's own shape: Session B was rewording its work when
        it went past somebody else's commit.
        """
        self.assertEqual(run(f"git -C {self.repo} rebase -i {self.base}"), BLOCK)

    def test_rebase_of_a_purely_local_branch_is_allowed(self) -> None:
        """The single most common rebase there is; it must stay frictionless."""
        self.on_feature()
        commit(self.repo, "mine.md", "one\n", "feature one")
        commit(self.repo, "mine.md", "two\n", "feature two")
        self.assertEqual(run(f"git -C {self.repo} rebase -i HEAD~2"), ALLOW)

    def test_rebase_onto_the_remote_tip_is_allowed(self) -> None:
        """Replaying unpushed work onto the remote — the guard's own remedy."""
        self.unpushed()
        self.assertEqual(run(f"git -C {self.repo} rebase origin/main"), ALLOW)

    def test_rebase_of_main_from_another_branch_is_blocked(self) -> None:
        """`git rebase <upstream> <branch>` names its victim explicitly."""
        self.on_feature()
        self.assertEqual(run(f"git -C {self.repo} rebase {self.base} main"), BLOCK)

    def test_rebase_continue_is_allowed(self) -> None:
        """Blocking mid-rebase strands the repo with no unblocked way out."""
        for control in ("--continue", "--abort", "--skip"):
            with self.subTest(control=control):
                self.assertEqual(run(f"git -C {self.repo} rebase {control}"), ALLOW)

    def test_pull_rebase_is_never_guarded(self) -> None:
        """It replays onto the remote tip, so nothing published is in range."""
        self.unpushed()
        self.assertEqual(run(f"git -C {self.repo} pull --rebase"), ALLOW)

    # --- git branch -f / -M ------------------------------------------------

    def test_branch_force_move_of_main_is_blocked(self) -> None:
        self.on_feature()
        self.assertEqual(
            run(f"git -C {self.repo} branch -f main {self.base}"), BLOCK
        )

    def test_branch_force_move_of_a_feature_branch_is_allowed(self) -> None:
        """`main`-only is deliberate; other refs pass with no network call."""
        git(self.repo, "branch", "feature-x")
        self.assertEqual(
            run(f"git -C {self.repo} branch -f feature-x {self.base}"), ALLOW
        )

    def test_branch_force_move_of_main_forward_is_allowed(self) -> None:
        """Re-pointing `main` at something that still contains the remote tip."""
        self.on_feature()
        self.assertEqual(
            run(f"git -C {self.repo} branch -f main origin/main"), ALLOW
        )

    def test_branch_rename_clobbering_main_is_blocked(self) -> None:
        """`git branch -M <src> main` takes its destination last."""
        git(self.repo, "branch", "scratch", self.base)
        self.on_feature()
        self.assertEqual(run(f"git -C {self.repo} branch -M scratch main"), BLOCK)

    def test_branch_listing_is_allowed(self) -> None:
        for args in ("--list", "-a", "--show-current", "-v"):
            with self.subTest(args=args):
                self.assertEqual(run(f"git -C {self.repo} branch {args}"), ALLOW)

    # --- git checkout -B / git switch -C -----------------------------------

    def test_checkout_force_create_over_main_is_blocked(self) -> None:
        self.assertEqual(
            run(f"git -C {self.repo} checkout -B main {self.base}"), BLOCK
        )

    def test_switch_force_create_over_main_is_blocked(self) -> None:
        self.assertEqual(
            run(f"git -C {self.repo} switch -C main {self.base}"), BLOCK
        )

    def test_checkout_force_create_of_another_branch_is_allowed(self) -> None:
        self.assertEqual(
            run(f"git -C {self.repo} checkout -B scratch {self.base}"), ALLOW
        )

    def test_checkout_force_create_of_main_at_the_remote_tip_is_allowed(self) -> None:
        """The CI idiom `git checkout -B main origin/main` drops nothing."""
        self.assertEqual(
            run(f"git -C {self.repo} checkout -B main origin/main"), ALLOW
        )

    def test_ordinary_checkout_is_allowed(self) -> None:
        for args in ("main", "-b feature-x", "-- second.md", "--force main"):
            with self.subTest(args=args):
                self.assertEqual(run(f"git -C {self.repo} checkout {args}"), ALLOW)

    # --- git update-ref ----------------------------------------------------

    def test_update_ref_moving_main_backwards_is_blocked(self) -> None:
        self.assertEqual(
            run(f"git -C {self.repo} update-ref refs/heads/main {self.base}"), BLOCK
        )

    def test_update_ref_on_another_ref_is_allowed(self) -> None:
        self.assertEqual(
            run(f"git -C {self.repo} update-ref refs/heads/scratch {self.base}"),
            ALLOW,
        )

    def test_update_ref_that_moves_nothing_is_allowed(self) -> None:
        self.assertEqual(
            run(f"git -C {self.repo} update-ref refs/heads/main {self.second}"),
            ALLOW,
        )

    # --- git filter-branch / git filter-repo --------------------------------

    def test_filter_branch_on_main_is_blocked(self) -> None:
        """No rev-list argument means HEAD, and HEAD is `main` here."""
        self.assertEqual(
            run(f"git -C {self.repo} filter-branch -f --msg-filter cat"), BLOCK
        )

    def test_filter_branch_over_all_refs_is_blocked(self) -> None:
        self.on_feature()
        self.assertEqual(
            run(f"git -C {self.repo} filter-branch -f --msg-filter cat -- --all"),
            BLOCK,
        )

    def test_filter_branch_on_another_branch_is_allowed(self) -> None:
        self.on_feature()
        self.assertEqual(
            run(f"git -C {self.repo} filter-branch -f --msg-filter cat"), ALLOW
        )

    def test_filter_branch_naming_another_ref_is_allowed(self) -> None:
        git(self.repo, "branch", "feature-x")
        self.assertEqual(
            run(
                f"git -C {self.repo} filter-branch -f --msg-filter cat -- feature-x"
            ),
            ALLOW,
        )

    def test_filter_repo_is_blocked(self) -> None:
        """It rewrites every ref by default, so what is checked out is moot."""
        self.on_feature()
        self.assertEqual(
            run(f"git -C {self.repo} filter-repo --path second.md --invert-paths"),
            BLOCK,
        )

    def test_filter_repo_with_nothing_published_is_allowed(self) -> None:
        solo = self.tmp / "solo-filter"
        solo.mkdir()
        subprocess.run(
            ["git", "init", "-b", "main", str(solo)], capture_output=True, check=True
        )
        git(solo, "config", "user.email", "test@example.invalid")
        git(solo, "config", "user.name", "Test Session")
        commit(solo, "a.md", "a\n", "first")
        self.assertEqual(run(f"git -C {solo} filter-repo --path a.md"), ALLOW)

    # --- deleting the published branch outright -----------------------------

    def test_push_delete_of_main_is_blocked(self) -> None:
        self.assertEqual(
            run(f"git -C {self.repo} push --delete origin main"), BLOCK
        )

    def test_push_colon_refspec_delete_of_main_is_blocked(self) -> None:
        """`git push origin :main` is the same deletion, spelled older."""
        self.assertEqual(run(f"git -C {self.repo} push origin :main"), BLOCK)

    def test_push_delete_of_a_feature_branch_is_allowed(self) -> None:
        """Deleting a merged PR branch is routine and must cost nothing."""
        git(self.repo, "push", "origin", "main:feature-x")
        self.assertEqual(
            run(f"git -C {self.repo} push --delete origin feature-x"), ALLOW
        )

    def test_push_colon_refspec_delete_of_a_feature_branch_is_allowed(self) -> None:
        git(self.repo, "push", "origin", "main:feature-x")
        self.assertEqual(run(f"git -C {self.repo} push origin :feature-x"), ALLOW)

    # --- posture, across the new entry points -------------------------------

    def test_override_works_on_a_newly_covered_verb(self) -> None:
        self.assertEqual(
            run(f'REWRITE-MAIN-OK git -C {self.repo} commit --amend -m "x"'), ALLOW
        )

    def test_unreachable_remote_still_fails_closed_on_a_new_verb(self) -> None:
        """The `_CANNOT_VERIFY` posture must extend with the coverage."""
        git(self.repo, "remote", "set-url", "origin", str(self.tmp / "does-not-exist"))
        self.on_feature()
        self.assertEqual(
            run(f"git -C {self.repo} branch -f main {self.base}"), BLOCK
        )

    def test_prose_quoting_a_newly_covered_verb_is_allowed(self) -> None:
        """The guard still has to be able to document itself."""
        command = (
            f"git -C {self.repo} commit -F - <<'EOF'\n"
            "Extend published-history guard past push and reset\n\n"
            "Now also catches `git commit --amend`, `git rebase -i HEAD~3`,\n"
            "`git branch -f main <sha>` and `git push --delete origin main`.\n"
            "EOF"
        )
        self.assertEqual(run(command), ALLOW)

    def test_caught_in_the_second_half_of_a_compound_command(self) -> None:
        self.assertEqual(
            run(
                f"git -C {self.repo} status && git -C {self.repo} branch -f main {self.base}"
            ),
            BLOCK,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
