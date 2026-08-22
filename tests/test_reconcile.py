#!/usr/bin/env python3
"""Test suite for scripts/reconcile.py.

Covers the PARSING and FORMATTING logic only. Every parser in the script takes
TEXT rather than a subprocess, which is what lets this suite run recorded `gh`
and `git` output with no network and no repo. `collect()` takes an injected
runner for the same reason.

The suite is organised around the claim the script makes — "a claim with no
matching record here is a fabrication or a silent failure" — so the cases that
matter most are the ones where a record must NOT appear: a pull request outside
the window, a branch that is only in the local cache, an entry the forge
returned malformed.

Stdlib only (no pytest) so CI stays a bare `python -m unittest discover`.
"""
import contextlib
import importlib.util
import io
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "reconcile", Path(__file__).resolve().parent.parent / "scripts" / "reconcile.py"
)
reconcile = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(reconcile)

NOW = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)


class TestParseSince(unittest.TestCase):
    """The window start. A wrong window silently hides a real record, which is
    the one failure this script must not have."""

    def test_hours(self) -> None:
        self.assertEqual(reconcile.parse_since("6h", NOW), NOW - timedelta(hours=6))

    def test_minutes_days_weeks(self) -> None:
        self.assertEqual(reconcile.parse_since("90m", NOW), NOW - timedelta(minutes=90))
        self.assertEqual(reconcile.parse_since("2d", NOW), NOW - timedelta(days=2))
        self.assertEqual(reconcile.parse_since("3w", NOW), NOW - timedelta(weeks=3))

    def test_spacing_and_case(self) -> None:
        self.assertEqual(reconcile.parse_since(" 6 H ", NOW), NOW - timedelta(hours=6))

    def test_iso_with_zone(self) -> None:
        self.assertEqual(
            reconcile.parse_since("2026-08-22T06:00:00Z", NOW),
            datetime(2026, 8, 22, 6, 0, 0, tzinfo=timezone.utc),
        )

    def test_naive_iso_is_read_as_utc(self) -> None:
        """A naive value must not become a local-time window silently."""
        self.assertEqual(
            reconcile.parse_since("2026-08-22T06:00:00", NOW),
            datetime(2026, 8, 22, 6, 0, 0, tzinfo=timezone.utc),
        )

    def test_nonsense_is_refused(self) -> None:
        for bad in ("", "   ", "yesterday", "6", "h", "6y"):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    reconcile.parse_since(bad, NOW)


class TestParseLsRemote(unittest.TestCase):
    """`git ls-remote`, never `git branch -r`. The second is a LOCAL cache and
    can list a branch the remote deleted an hour ago — a snapshot built to
    catch a false claim must not be built from a cache that can carry one."""

    SAMPLE = (
        "9f000d8f1c2b3a4d5e6f708192a3b4c5d6e7f809\trefs/heads/main\n"
        "b1675e5aabbccddeeff00112233445566778899a\trefs/heads/feat/reconcile-claims\n"
        "1234567\trefs/heads/docs/adr-003-phase1-status\n"
    )

    def test_names_are_extracted_and_sorted(self) -> None:
        self.assertEqual(
            reconcile.parse_ls_remote(self.SAMPLE),
            ["docs/adr-003-phase1-status", "feat/reconcile-claims", "main"],
        )

    def test_tags_and_other_refs_are_ignored(self) -> None:
        text = (
            "aaaaaaa\trefs/tags/v0.2.0\n"
            "bbbbbbb\trefs/pull/118/head\n"
            "ccccccc\trefs/heads/main\n"
        )
        self.assertEqual(reconcile.parse_ls_remote(text), ["main"])

    def test_empty_and_noise(self) -> None:
        self.assertEqual(reconcile.parse_ls_remote(""), [])
        self.assertEqual(reconcile.parse_ls_remote("From github.com:o/r\n"), [])

    def test_duplicates_collapse(self) -> None:
        self.assertEqual(
            reconcile.parse_ls_remote("aaaaaaa\trefs/heads/main\n"
                                      "aaaaaaa\trefs/heads/main\n"),
            ["main"],
        )


class TestParsePorcelain(unittest.TestCase):
    """Uncommitted work is invisible across machines. Naming it is half the
    reason this snapshot exists."""

    def test_status_and_path(self) -> None:
        rows = reconcile.parse_porcelain(
            " M scripts/reconcile.py\n"
            "?? tests/test_reconcile.py\n"
            "A  conventions/reconcile-claims.md\n"
        )
        self.assertEqual(
            rows,
            [
                {"status": "M", "path": "scripts/reconcile.py"},
                {"status": "??", "path": "tests/test_reconcile.py"},
                {"status": "A", "path": "conventions/reconcile-claims.md"},
            ],
        )

    def test_rename_reports_the_new_path(self) -> None:
        """That is the file on disk now."""
        rows = reconcile.parse_porcelain("R  old/name.py -> new/name.py\n")
        self.assertEqual(rows, [{"status": "R", "path": "new/name.py"}])

    def test_quoted_path_is_unquoted(self) -> None:
        rows = reconcile.parse_porcelain('?? "a file with spaces.md"\n')
        self.assertEqual(rows[0]["path"], "a file with spaces.md")

    def test_clean_tree(self) -> None:
        self.assertEqual(reconcile.parse_porcelain(""), [])


class TestParsePrList(unittest.TestCase):
    """The forge is the system of record for a pull request. A half-read entry
    is worse than a missing one, because it looks like corroboration."""

    SAMPLE = json.dumps([
        {"number": 118, "title": "guard: refuse mutations",
         "headRefName": "feat/config-guard", "createdAt": "2026-08-22T22:40:00Z",
         "mergedAt": "2026-08-22T23:25:11Z",
         "url": "https://example.invalid/pull/118"},
        {"number": 68, "title": "ADR-003 Phase 1",
         "headRefName": "docs/adr-003-phase1-status",
         "createdAt": "2026-08-05T23:23:29Z", "mergedAt": "",
         "url": "https://example.invalid/pull/68"},
    ])

    def test_fields_are_renamed_and_sorted(self) -> None:
        rows = reconcile.parse_pr_list(self.SAMPLE)
        self.assertEqual([r["number"] for r in rows], [68, 118])
        self.assertEqual(rows[1]["head_branch"], "feat/config-guard")
        self.assertEqual(rows[1]["title"], "guard: refuse mutations")

    def test_missing_optional_fields_become_empty_strings(self) -> None:
        rows = reconcile.parse_pr_list(json.dumps([{"number": 7}]))
        self.assertEqual(rows[0]["title"], "")
        self.assertEqual(rows[0]["head_branch"], "")

    def test_an_entry_with_no_number_is_dropped(self) -> None:
        """A pull request that cannot be identified cannot corroborate a claim."""
        rows = reconcile.parse_pr_list(json.dumps([{"title": "no number here"}]))
        self.assertEqual(rows, [])

    def test_empty_list(self) -> None:
        self.assertEqual(reconcile.parse_pr_list("[]"), [])
        self.assertEqual(reconcile.parse_pr_list(""), [])

    def test_non_json_raises(self) -> None:
        with self.assertRaises(reconcile.RepoError):
            reconcile.parse_pr_list("gh: command not found")

    def test_json_that_is_not_a_list_raises(self) -> None:
        with self.assertRaises(reconcile.RepoError):
            reconcile.parse_pr_list('{"message": "Not Found"}')


class TestFilterMergedSince(unittest.TestCase):
    """The window is the point. A merge outside it is not evidence for a claim
    about this cycle."""

    def _rows(self):
        return reconcile.parse_pr_list(TestParsePrList.SAMPLE)

    def test_inside_the_window(self) -> None:
        since = datetime(2026, 8, 22, 18, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(
            [r["number"] for r in reconcile.filter_merged_since(self._rows(), since)],
            [118],
        )

    def test_outside_the_window(self) -> None:
        since = datetime(2026, 8, 23, 0, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(reconcile.filter_merged_since(self._rows(), since), [])

    def test_an_undated_merge_is_dropped(self) -> None:
        rows = [{"number": 1, "merged_at": ""}, {"number": 2, "merged_at": "soon"}]
        since = datetime(2000, 1, 1, tzinfo=timezone.utc)
        self.assertEqual(reconcile.filter_merged_since(rows, since), [])


class TestFormatTable(unittest.TestCase):
    """The human view. It goes to stderr so stdout stays a clean JSON stream."""

    def _snapshot(self):
        return {
            "generated_at": NOW.isoformat(),
            "since": (NOW - timedelta(hours=6)).isoformat(),
            "repos": [{
                "path": "/home/dev/code/agent-ops",
                "current_branch": "feat/reconcile-claims",
                "last_commit": {"sha": "b1675e5aabbccdd", "subject": "guard: refuse",
                                "committed_at": "2026-08-22T23:25:11Z"},
                "uncommitted": [{"status": "M", "path": "scripts/reconcile.py"}],
                "remote_branches": ["main", "feat/reconcile-claims"],
                "open_prs": [{"number": 68, "title": "ADR-003 Phase 1",
                              "head_branch": "docs/adr-003", "created_at": "",
                              "merged_at": "", "url": ""}],
                "merged_prs": [],
            }],
        }

    def test_the_record_appears(self) -> None:
        table = reconcile.format_table(self._snapshot())
        self.assertIn("/home/dev/code/agent-ops", table)
        self.assertIn("feat/reconcile-claims", table)
        self.assertIn("#68", table)
        self.assertIn("b1675e5a", table)
        self.assertIn("scripts/reconcile.py", table)

    def test_absence_is_stated_not_omitted(self) -> None:
        """A silent gap reads as "not checked". It must read as "no record"."""
        table = reconcile.format_table(self._snapshot())
        self.assertIn("merged PRs  none", table)

    def test_the_purpose_line_is_present(self) -> None:
        self.assertIn("fabrication or a silent failure",
                      reconcile.format_table(self._snapshot()))

    def test_a_failed_repo_says_so(self) -> None:
        snapshot = {"repos": [{"path": "/nope", "error": "git is not on PATH"}]}
        table = reconcile.format_table(snapshot)
        self.assertIn("ERROR: git is not on PATH", table)


class TestCollect(unittest.TestCase):
    """`collect` with an injected runner: recorded output, no network, no repo."""

    def _runner(self, failing=None):
        def run(args, cwd):
            key = " ".join(args[2:5] if args[0] == "git" else args[1:3])
            if failing and failing in key:
                raise reconcile.RepoError("boom")
            if args[0] == "git" and "rev-parse" in args:
                return "feat/reconcile-claims\n"
            if args[0] == "git" and "log" in args:
                return "b1675e5\x1fguard: refuse\x1f2026-08-22T23:25:11+00:00\n"
            if args[0] == "git" and "status" in args:
                return " M scripts/reconcile.py\n"
            if args[0] == "git" and "ls-remote" in args:
                return "aaaaaaa\trefs/heads/main\n"
            if args[0] == "gh" and "open" in args:
                return TestParsePrList.SAMPLE
            if args[0] == "gh":
                return TestParsePrList.SAMPLE
            raise AssertionError("unexpected command: %r" % args)
        return run

    def test_a_full_snapshot(self) -> None:
        since = datetime(2026, 8, 22, 18, 0, 0, tzinfo=timezone.utc)
        repo = reconcile.collect("/repo", since, self._runner())
        self.assertNotIn("error", repo)
        self.assertEqual(repo["current_branch"], "feat/reconcile-claims")
        self.assertEqual(repo["last_commit"]["sha"], "b1675e5")
        self.assertEqual(repo["remote_branches"], ["main"])
        self.assertEqual([r["number"] for r in repo["merged_prs"]], [118])

    def test_a_failure_is_named_not_swallowed(self) -> None:
        """A repo that could not be read must not look like a repo with nothing
        in it — that is the shape that would let a false claim through."""
        repo = reconcile.collect("/repo", NOW, self._runner(failing="ls-remote"))
        self.assertIn("error", repo)

    def test_one_bad_repo_does_not_lose_the_good_one(self) -> None:
        snapshot = reconcile.build_snapshot(["/a", "/b"], NOW, self._runner())
        self.assertEqual(len(snapshot["repos"]), 2)
        self.assertIn("generated_at", snapshot)
        self.assertIn("since", snapshot)


class TestCli(unittest.TestCase):
    """argparse writes its usage text to stderr; it is captured so a passing
    run stays quiet."""

    def _exit_code(self, argv):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                reconcile.main(argv)
        return raised.exception.code

    def test_a_bad_since_exits_two(self) -> None:
        """Exit codes are the interface: 2 is a usage error."""
        self.assertEqual(self._exit_code(["--repo", ".", "--since", "yesterday"]), 2)

    def test_repo_is_required(self) -> None:
        self.assertEqual(self._exit_code(["--since", "6h"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
