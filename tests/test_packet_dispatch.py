#!/usr/bin/env python3
"""Test suite for vendors/packet/compile.py -- git facts and the dispatch path.

Everything here that touches git builds a real throwaway repository with a
real **bare remote**, because the two claims worth pinning cannot be faked:

1. `branch_pushed` is answered by `git ls-remote` and not by the tracking
   ref. `test_a_stale_tracking_ref_lies` proves the distinction by making the
   cache lie -- it deletes the branch on the remote without fetching, so
   `git branch -r` still lists it and `ls-remote` does not.
2. `boundary_violations` is derived from git and never from the model. The
   fake vendor here writes files the packet did not license and reports
   nothing about having done so; the violation is found anyway.

**No live dispatch and no API spend.** The vendor CLI is replaced by
`AGENT_OPS_PACKET_FAKE_RUNNER`, which still builds the real argv and still
runs the whole bracketing-and-typing path -- so the code under test is the
shipped code, not a test-only branch of it.

Stdlib only, same as the sibling suites.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "vendors" / "packet"
sys.path.insert(0, str(PKG))

import compile as C  # noqa: E402
import packet as P  # noqa: E402

COMPILE = PKG / "compile.py"

# Stands in for `codex` / `agy`. Receives the real argv, optionally writes the
# files named by FAKE_WRITE (so a boundary violation can be produced by
# something other than the test itself), and emits line-delimited JSON the way
# both vendors' structured modes do.
FAKE_VENDOR = """\
import json, os, sys
for rel in [p for p in os.environ.get("FAKE_WRITE", "").split(";") if p]:
    target = os.path.join(os.environ["FAKE_REPO"], rel)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    open(target, "w").write("touched by the seat\\n")
if os.environ.get("FAKE_SILENT"):
    sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
print(json.dumps({"type": "item.completed", "argv_len": len(sys.argv)}))
if os.environ.get("FAKE_GARBAGE"):
    print("this line is not json")
print(json.dumps({"type": "turn.completed"}))
sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
"""

REVISION = "b" * 40


def git(repo, *args, check=True):
    env = dict(
        os.environ,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_AUTHOR_NAME="t",
        GIT_AUTHOR_EMAIL="t@t",
        GIT_COMMITTER_NAME="t",
        GIT_COMMITTER_EMAIL="t@t",
    )
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", "-c", "gpg.format=openpgp", *args],
        capture_output=True,
        text=True,
        env=env,
        check=check,
    )


class GitFixture(unittest.TestCase):
    """A work repo on branch `work`, pushed to a real bare remote."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.bare = root / "remote.git"
        self.repo = root / "work"
        self.bare.mkdir()
        self.repo.mkdir()
        subprocess.run(["git", "init", "--bare", "-b", "main", str(self.bare)],
                       capture_output=True, check=True)
        git(self.repo, "init", "-b", "main")
        (self.repo / "kept.txt").write_text("one\n", encoding="utf-8")
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "a.md").write_text("a\n", encoding="utf-8")
        git(self.repo, "add", "kept.txt", "docs/a.md")
        git(self.repo, "commit", "-m", "seed")
        git(self.repo, "remote", "add", "origin", str(self.bare))
        git(self.repo, "checkout", "-b", "work")
        git(self.repo, "push", "-u", "origin", "work")
        self.head = C.resolve_revision(self.repo, "HEAD")
        self.addCleanup(self.tmp.cleanup)

    def packet(self, **over):
        pkt = {
            "packet_version": P.PACKET_VERSION,
            "packet_id": P.new_ulid(),
            "issued_at": "2026-08-09T12:00:00Z",
            "issuer_seat": "claude",
            "target_seat": "codex",
            "target_model_family": "openai",
            "role": "review",
            "route_reason": "independence",
            "off_lane_justification": None,
            "repo": "sanlee-ys/agent-ops",
            "branch": "work",
            "branch_pushed": True,
            "base_revision": self.head,
            "concern": "hold the edge",
            "files_in_scope": ["docs/**"],
            "files_out_of_scope": [],
            "write_authority": "none",
            "write_paths": [],
            "verification_already_run": [],
            "vendor_options": {},
            "overrides": [],
            "authored_by": "claude",
            "packet_digest": "",
        }
        pkt.update(over)
        return P.sealed(pkt)


class TestRemoteTruth(GitFixture):
    def test_ls_remote_finds_a_pushed_branch(self):
        self.assertEqual(C.branch_on_remote(self.repo, "work"), self.head)

    def test_ls_remote_does_not_find_an_unpushed_branch(self):
        git(self.repo, "checkout", "-b", "local-only")
        self.assertIsNone(C.branch_on_remote(self.repo, "local-only"))

    def test_a_stale_tracking_ref_lies(self):
        """The whole reason `branch_pushed` is a live query.

        Delete the branch on the remote without fetching. `git branch -r` --
        a read of the local cache -- still reports it. `ls-remote` does not.
        A packet trusting the cache would ship a review pinned to a branch
        nobody can fetch.
        """
        git(self.bare, "update-ref", "-d", "refs/heads/work")
        cached = git(self.repo, "branch", "-r").stdout
        self.assertIn("origin/work", cached)
        self.assertIsNone(C.branch_on_remote(self.repo, "work"))

    def test_an_unpushed_branch_refuses_at_check_time(self):
        pkt = self.packet(branch="never-pushed", branch_pushed=False)
        found = {r.code for r in C.all_refusals(pkt, self.repo)}
        self.assertIn("E-BRANCH-NOT-PUSHED", found)

    def test_an_unresolvable_revision_refuses(self):
        pkt = self.packet(base_revision=REVISION)
        found = {r.code for r in C.all_refusals(pkt, self.repo)}
        self.assertIn("E-REVISION-UNRESOLVABLE", found)

    def test_a_clean_packet_survives_the_environmental_checks(self):
        self.assertEqual(C.all_refusals(self.packet(), self.repo), [])


class TestGlobs(unittest.TestCase):
    def test_double_star_crosses_a_slash(self):
        self.assertTrue(C.matches_any("a/b/c.py", ["a/**"]))

    def test_single_star_does_not(self):
        self.assertFalse(C.matches_any("a/b/c.py", ["a/*.py"]))
        self.assertTrue(C.matches_any("a/c.py", ["a/*.py"]))

    def test_a_bare_directory_covers_its_contents(self):
        self.assertTrue(C.matches_any("docs/a.md", ["docs"]))
        self.assertTrue(C.matches_any("docs/a.md", ["docs/"]))

    def test_a_prefix_is_not_a_match(self):
        self.assertFalse(C.matches_any("docsy/a.md", ["docs/**"]))

    def test_windows_separators_normalize(self):
        self.assertTrue(C.matches_any("a\\b\\c.py", ["a/**"]))


class TestBoundaryViolations(GitFixture):
    def test_write_authority_none_makes_every_change_a_violation(self):
        """`files_in_scope` is a READING boundary, not a write licence."""
        pkt = self.packet(write_authority="none", files_in_scope=["docs/**"])
        self.assertEqual(C.boundary_violations(pkt, ["docs/a.md"]), ["docs/a.md"])

    def test_write_paths_licenses_exactly_what_it_names(self):
        pkt = self.packet(
            role="implement",
            acceptance=["true"],
            authored_by=None,
            write_authority="paths",
            write_paths=["docs/**"],
            off_lane_justification="agent-ops repo exception",
        )
        pkt.pop("authored_by")
        pkt = P.sealed(pkt)
        self.assertEqual(
            C.boundary_violations(pkt, ["docs/a.md", "kept.txt"]), ["kept.txt"]
        )

    def test_workspace_authority_can_produce_no_violations(self):
        pkt = self.packet(
            role="implement",
            acceptance=["true"],
            write_authority="workspace",
            off_lane_justification="agent-ops repo exception",
        )
        pkt.pop("authored_by")
        pkt = P.sealed(pkt)
        self.assertEqual(C.boundary_violations(pkt, ["anything.txt"]), [])

    def test_files_changed_sees_an_untracked_file(self):
        before = C.worktree_state(self.repo)
        (self.repo / "surprise.txt").write_text("x\n", encoding="utf-8")
        after = C.worktree_state(self.repo)
        self.assertIn("surprise.txt", C.files_changed(self.repo, before, after))

    def test_files_changed_sees_a_modification(self):
        before = C.worktree_state(self.repo)
        (self.repo / "kept.txt").write_text("two\n", encoding="utf-8")
        after = C.worktree_state(self.repo)
        self.assertIn("kept.txt", C.files_changed(self.repo, before, after))

    def test_files_changed_sees_a_commit(self):
        before = C.worktree_state(self.repo)
        (self.repo / "kept.txt").write_text("three\n", encoding="utf-8")
        git(self.repo, "add", "kept.txt")
        git(self.repo, "commit", "-m", "moved")
        after = C.worktree_state(self.repo)
        self.assertIn("kept.txt", C.files_changed(self.repo, before, after))

    def test_a_quiet_dispatch_produces_nothing(self):
        before = C.worktree_state(self.repo)
        after = C.worktree_state(self.repo)
        self.assertEqual(C.files_changed(self.repo, before, after), [])


class TestArgv(GitFixture):
    def test_codex_first_turn(self):
        pkt = self.packet(vendor_options={"sandbox": "read-only", "cd": "/w"})
        argv = C.build_argv(pkt, "PROMPT")
        self.assertEqual(argv[:2], ["codex", "exec"])
        self.assertIn("--skip-git-repo-check", argv)
        self.assertEqual(argv[argv.index("--sandbox") + 1], "read-only")
        self.assertEqual(argv[argv.index("--cd") + 1], "/w")
        self.assertEqual(argv[-1], "PROMPT")

    def test_codex_resume_carries_neither_sandbox_nor_cd(self):
        pkt = self.packet(vendor_options={"resume_session_id": "sid"})
        argv = C.build_argv(pkt, "PROMPT")
        self.assertIn("resume", argv)
        self.assertNotIn("--sandbox", argv)
        self.assertNotIn("--cd", argv)

    def test_agy_puts_every_flag_before_dash_p_and_the_prompt_last(self):
        """`-p` is a value-taking flag; anything after it is swallowed.

        Measured on agy 1.1.11 and encoded in telltale's seat: `agy -p
        --output-format stream-json "<prompt>"` returns a paragraph about CLI
        output formats and exits 0. It fails silently in both directions, so
        the ordering is asserted rather than trusted.
        """
        pkt = self.packet(
            target_seat="agy",
            target_model_family="google",
            role="review",
            authored_by="claude",
            vendor_options={"output_format": "json"},
        )
        argv = C.build_argv(pkt, "PROMPT")
        self.assertEqual(argv[-2:], ["-p", "PROMPT"])
        self.assertLess(argv.index("--output-format"), argv.index("-p"))

    def test_there_is_no_phase_one_path_for_cursor(self):
        pkt = self.packet(
            target_seat="cursor",
            target_model_family="composer",
            authored_by="claude",
            route_reason="surface-fit",
            off_lane_justification="IDE-native review",
            vendor_options={"workspace_root": "/w", "launch_parent": "powershell"},
        )
        with self.assertRaises(ValueError):
            C.build_argv(pkt, "PROMPT")


class TestDispatchAgainstAFake(GitFixture):
    def setUp(self):
        super().setUp()
        self.fake = Path(self.tmp.name) / "fake_vendor.py"
        self.fake.write_text(FAKE_VENDOR, encoding="utf-8")
        self.store = Path(self.tmp.name) / "store"

    def runner(self, **env):
        base = dict(os.environ, FAKE_REPO=str(self.repo))
        base.update({k: str(v) for k, v in env.items()})

        def run(argv, timeout):
            return C._subprocess_runner(
                [sys.executable, str(self.fake), *argv], timeout
            )

        self._env_patch(base)
        return run

    def _env_patch(self, env):
        old = dict(os.environ)
        os.environ.clear()
        os.environ.update(env)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(old)))

    def test_a_seat_that_writes_outside_its_licence_is_caught_by_git(self):
        pkt = self.packet(
            role="implement",
            acceptance=["true"],
            write_authority="paths",
            write_paths=["docs/**"],
            off_lane_justification="agent-ops repo exception",
        )
        pkt.pop("authored_by")
        pkt = P.sealed(pkt)
        run = self.runner(FAKE_WRITE="docs/new.md;src/sneaky.py")
        ret = C.dispatch(pkt, self.repo, runner=run)
        self.assertEqual(ret["outcome"], "answered")
        self.assertIn("docs/new.md", ret["files_changed"])
        self.assertIn("src/sneaky.py", ret["files_changed"])
        # Only the unlicensed one is a violation. The seat reported nothing
        # about either; git did all the reporting.
        self.assertEqual(ret["boundary_violations"], ["src/sneaky.py"])

    def test_a_read_only_packet_that_writes_anything_is_a_violation(self):
        pkt = self.packet()
        run = self.runner(FAKE_WRITE="docs/new.md")
        ret = C.dispatch(pkt, self.repo, runner=run)
        self.assertEqual(ret["boundary_violations"], ["docs/new.md"])

    def test_a_well_behaved_read_only_dispatch_is_clean(self):
        pkt = self.packet()
        ret = C.dispatch(pkt, self.repo, runner=self.runner())
        self.assertEqual(ret["boundary_violations"], [])
        self.assertEqual(ret["files_changed"], [])
        self.assertEqual(ret["packet_digest"], pkt["packet_digest"])

    def test_no_output_is_not_answered_with_an_empty_body(self):
        """Zero and absent are different states, and stay different."""
        pkt = self.packet()
        ret = C.dispatch(pkt, self.repo, runner=self.runner(FAKE_SILENT="1"))
        self.assertEqual(ret["outcome"], "no-output")

    def test_a_nonzero_exit_is_failed(self):
        pkt = self.packet()
        ret = C.dispatch(pkt, self.repo, runner=self.runner(FAKE_EXIT="3"))
        self.assertEqual(ret["outcome"], "failed")
        self.assertEqual(ret["exit_code"], 3)

    def test_an_unparseable_stream_line_degrades_and_does_not_fail(self):
        pkt = self.packet()
        ret = C.dispatch(pkt, self.repo, runner=self.runner(FAKE_GARBAGE="1"))
        self.assertEqual(ret["outcome"], "answered")
        self.assertEqual(ret["stream_parse_errors"], 1)

    def test_usage_is_absent_rather_than_zero(self):
        pkt = self.packet()
        ret = C.dispatch(pkt, self.repo, runner=self.runner())
        self.assertIsNone(ret["usage"])


class TestCLI(GitFixture):
    """The shipped entry point, driven as CI and an operator would."""

    def setUp(self):
        super().setUp()
        self.fake = Path(self.tmp.name) / "fake_vendor.py"
        self.fake.write_text(FAKE_VENDOR, encoding="utf-8")
        self.store = Path(self.tmp.name) / "store"

    def run_cli(self, *args, **env):
        environ = dict(os.environ, AGENT_OPS_PACKET_STORE=str(self.store))
        environ.update({k: str(v) for k, v in env.items()})
        return subprocess.run(
            [sys.executable, str(COMPILE), *args],
            capture_output=True, text=True, env=environ,
        )

    def write_packet(self, pkt, name="packet.json"):
        path = Path(self.tmp.name) / name
        path.write_text(json.dumps(pkt, indent=2), encoding="utf-8")
        return path

    def test_check_exits_zero_on_a_clean_packet(self):
        path = self.write_packet(self.packet())
        proc = self.run_cli("check", str(path), "--repo-dir", str(self.repo))
        self.assertEqual(proc.returncode, C.OK, proc.stderr)

    def test_check_exits_one_on_a_refusal(self):
        pkt = self.packet(authored_by="codex")
        proc = self.run_cli("check", str(self.write_packet(pkt)), "--repo-dir", str(self.repo))
        self.assertEqual(proc.returncode, C.REFUSED)
        self.assertIn("E-SELF-REVIEW", proc.stderr)

    def test_a_tampered_packet_fails_its_own_digest(self):
        pkt = self.packet()
        pkt["concern"] = "quietly something else"
        proc = self.run_cli("check", str(self.write_packet(pkt)), "--repo-dir", str(self.repo))
        self.assertEqual(proc.returncode, C.REFUSED)
        self.assertIn("E-DIGEST", proc.stderr)

    def test_dry_run_prints_the_argv_and_spawns_nothing(self):
        path = self.write_packet(self.packet())
        proc = self.run_cli(
            "dispatch", str(path), "--repo-dir", str(self.repo), "--dry-run"
        )
        self.assertEqual(proc.returncode, C.OK, proc.stderr)
        argv = json.loads(proc.stdout)["argv"]
        self.assertEqual(argv[:2], ["codex", "exec"])

    def test_dispatch_to_a_non_phase_one_seat_is_refused(self):
        pkt = self.packet(
            target_seat="grok",
            target_model_family="xai",
            role="research",
            question="anything",
            route_reason="capacity",
            off_lane_justification="guard verification only",
        )
        pkt.pop("authored_by")
        pkt = P.sealed(pkt)
        proc = self.run_cli(
            "dispatch", str(self.write_packet(pkt)), "--repo-dir", str(self.repo)
        )
        self.assertEqual(proc.returncode, C.REFUSED)
        self.assertIn("E-NO-DISPATCH-PATH", proc.stderr)

    def test_end_to_end_against_the_fake_records_a_violation(self):
        path = self.write_packet(self.packet())
        proc = self.run_cli(
            "dispatch", str(path), "--repo-dir", str(self.repo),
            AGENT_OPS_PACKET_FAKE_RUNNER=str(self.fake),
            FAKE_REPO=str(self.repo),
            FAKE_WRITE="src/sneaky.py",
        )
        self.assertEqual(proc.returncode, C.OK, proc.stderr)
        ret = json.loads(proc.stdout)
        self.assertEqual(ret["boundary_violations"], ["src/sneaky.py"])
        stored = self.store / ret["packet_id"] / "return.json"
        self.assertTrue(stored.exists())

    def test_report_is_an_instrument_and_not_a_gate(self):
        path = self.write_packet(self.packet())
        self.run_cli(
            "dispatch", str(path), "--repo-dir", str(self.repo),
            AGENT_OPS_PACKET_FAKE_RUNNER=str(self.fake),
            FAKE_REPO=str(self.repo),
            FAKE_WRITE="src/sneaky.py",
        )
        proc = self.run_cli("report")
        self.assertEqual(proc.returncode, C.OK, proc.stderr)
        self.assertIn("boundary-violation rate: 1/1", proc.stdout)
        self.assertIn("Reported, not gated", proc.stdout)

    def test_schema_check_passes_against_the_committed_artifact(self):
        proc = self.run_cli("schema", "--check")
        self.assertEqual(proc.returncode, C.OK, proc.stderr)


if __name__ == "__main__":
    unittest.main()
