#!/usr/bin/env python3
"""Test suite for hooks/published-history-guard.py.

The guard is stateful — it answers "would this destroy a published commit?" by
asking a real repository — so these tests build real repositories. A mocked git
would only prove the guard's own assumptions back to itself, and the assumption
that broke in the incident (that a tracking ref tells you what the remote has)
is precisely the kind a mock would have preserved.

Three groups:

  - **The incident, reconstructed.** Two clones of one bare remote playing the
    parts of Session A and Session B, reproducing 2026-07-26 commit for commit.
    These are the cases that must fail against an unfixed guard.
  - **Blocked shapes.** The other ways to drop a published commit from `main`.
  - **Allowed shapes.** The far more important half. A guard that fires on
    feature-branch rebases, on prose quoting it, or on a plain push gets routed
    around, and a routed-around guard protects nothing.

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
