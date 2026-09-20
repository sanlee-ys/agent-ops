#!/usr/bin/env python3
"""Test suite for scripts/handoff_check.py.

Three things this suite is really about, beyond the detectors themselves:

  1. **The false-positive side of every detector.** A drift check that
     over-reports trains the reader to ignore it, and an ignored red check is
     worse than no check. Each class below carries the near miss it must NOT
     flag. `TestJobConsistency` is the sharpest case: a finished job that hands
     one remaining step to the owner is correct, and the check must stay quiet.
  2. **Absent is not zero.** `TestAbsentIsNotZero` asserts from the failing
     side that an unread forge never reads as an empty one, that an UNMEASURED
     row never counts as a MATCH, and that a missing HANDOFF.md refuses instead
     of passing.
  3. **The tool never writes.** `TestNeverWrites` reads the HANDOFF bytes
     before and after a full run and compares them.

Every command is recorded output through a fake `run`, so the suite needs no
network, no forge, and no repo.

Stdlib only (no pytest) so CI stays a bare `python -m unittest discover`.
"""
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "handoff_check",
    Path(__file__).resolve().parent.parent / "scripts" / "handoff_check.py",
)
hc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hc)


# --- Recorded command output -------------------------------------------------

GH_PR_LIST = json.dumps([
    {"number": 208}, {"number": 209},
])

LS_REMOTE_TAGS = """
288c3c18c19b0e47e261c8b3104b3016ae3feba3\trefs/tags/v1.0.0
a04d27765703f6cc9c44c7d5212ed36a9d00ce61\trefs/tags/v3.1.0
629f3c6621e1c360d452f9cbed10252d61e15874\trefs/tags/v3.1.0^{}
263ae661ccec95f9216fef038a4f0432d435e829\trefs/tags/v3.2.1
10f634859213fac4844cd5e5682449cab2046ad6\trefs/tags/v3.2.1^{}
""".strip()

LS_REMOTE_MAIN = "aa8e6d54e0000000000000000000000000000001\trefs/heads/main"

HANDOFF = """# HANDOFF - 2026-08-02

## State

- Work continues on branch `tool/handoff-check`.
- `v3.1.0` is shipped. Sixteen PRs merged since the tag (#137-#154, less
  #139 - closed, superseded by #142 - and #147, still open).
- In flight: two Dependabot PRs, both open - #208 and #209 (a bump from
  4.37.3, which is not a release of this repo).

## Next jobs, in order

1. ~~**The scaled region eval.**~~ **DONE - shipped 2026-08-02.** What is
   left is owner-only: the tag and the release.
2. **An option, not a commitment.** Do not start it as cleanup.
3. ~~**The higher-power re-run.**~~ **DONE - run 2026-08-03.**

## Owner-only actions pending

- **Tagging and releasing the eval.** The release commit is on `main`.
- **Running the higher-power re-run (job 3).** The harness is run-ready.
"""


def fake_run(overrides=None, fail=()):
    """A stand-in for `hc.run` that replays recorded output.

    `fail` names commands that must raise, so a test can assert what the tool
    does when a system of record does not answer.
    """
    table = {
        "gh pr list": GH_PR_LIST,
        "git branch": "tool/handoff-check\n",
        "git rev-parse": "aa8e6d54e0000000000000000000000000000001\n",
        "git ls-remote --tags": LS_REMOTE_TAGS,
        "git ls-remote origin": LS_REMOTE_MAIN,
    }
    table.update(overrides or {})

    def _run(args, cwd):
        key = " ".join(args[:3])
        for prefix in sorted(table, key=len, reverse=True):
            if key.startswith(prefix):
                if prefix in fail:
                    raise hc.CommandError("recorded failure")
                return table[prefix]
        raise AssertionError("no recorded output for %r" % (args,))

    return _run


@contextlib.contextmanager
def repo_with(handoff=HANDOFF, changelog=None, run=None, fail=()):
    """A temporary repo holding a HANDOFF, with commands replayed."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        if handoff is not None:
            (root / "HANDOFF.md").write_text(handoff, encoding="utf-8")
        if changelog is not None:
            (root / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
        original = hc.run
        hc.run = run or fake_run(fail=fail)
        try:
            yield root
        finally:
            hc.run = original


def row(result, check):
    for entry in result["checks"]:
        if entry["check"] == check:
            return entry
    raise AssertionError("no row for %s" % check)


# --- Section parsing ---------------------------------------------------------


class TestSectionSplit(unittest.TestCase):
    def test_state_stops_at_the_next_heading(self) -> None:
        sections = hc.split_sections(HANDOFF)
        self.assertIn("state", sections)
        self.assertIn("v3.1.0", sections["state"])
        self.assertNotIn("Owner-only", sections["state"])

    def test_a_sub_heading_stays_inside_its_parent(self) -> None:
        """A State section carries sub-headings, and they are part of it."""
        sections = hc.split_sections(
            "## State\n\n### Landed since\n\n- a claim\n\n## Next jobs\n\n1. x")
        self.assertIn("a claim", sections["state"])
        self.assertIn("Landed since", sections["state"])

    def test_find_section_matches_a_prefix(self) -> None:
        """Headings carry a varying tail, so an exact match would miss."""
        sections = hc.split_sections(HANDOFF)
        self.assertIsNotNone(hc.find_section(sections, "next jobs"))
        self.assertIsNotNone(hc.find_section(sections, "owner-only"))
        self.assertIsNone(hc.find_section(sections, "escalate"))


# --- Open pull requests ------------------------------------------------------


class TestClaimedOpenPrs(unittest.TestCase):
    def test_the_word_attaches_to_the_nearest_number(self) -> None:
        self.assertEqual(
            hc.claimed_open_prs("#147, still open"), {147})

    def test_a_merged_list_is_not_open(self) -> None:
        """The hard case. One sentence lists eleven numbers and one is open."""
        self.assertEqual(
            hc.claimed_open_prs(
                "Sixteen PRs merged since the tag (#137-#154, less #139 - "
                "closed, superseded by #142 - and #147, still open)."),
            {147},
        )

    def test_opened_is_not_open(self) -> None:
        self.assertEqual(hc.claimed_open_prs("#51 was opened yesterday"), set())
        self.assertEqual(hc.claimed_open_prs("#52 reopened after review"), set())

    def test_a_distant_word_does_not_attach(self) -> None:
        far = "#900 " + "x" * 200 + " open"
        self.assertEqual(hc.claimed_open_prs(far), set())

    def test_the_window_stops_at_the_sentence(self) -> None:
        """A number at the end of one sentence must not reach the next one."""
        self.assertEqual(
            hc.claimed_open_prs("and #147, merged. Two others are open."),
            set())

    def test_the_window_stops_at_the_next_bullet(self) -> None:
        self.assertEqual(
            hc.claimed_open_prs("- landed in #147\n- one PR is open"), set())

    def test_a_decimal_does_not_end_the_window(self) -> None:
        """A period inside `4.37.3` is followed by a digit, so it stops nothing."""
        self.assertEqual(
            hc.claimed_open_prs("#147 bumps 4.37.3 and stays open"), {147})

    def test_no_claim_is_an_empty_set(self) -> None:
        self.assertEqual(hc.claimed_open_prs("#1 merged, #2 closed"), set())

    def test_the_word_before_the_list_is_missed(self) -> None:
        """The known under-report, pinned so nobody reads it as coverage.

        English attaches the word ahead of the list here. No window catches
        that, which is why `check_open_prs` never compares this set for
        equality against the forge.
        """
        self.assertEqual(
            hc.claimed_open_prs("both open: #208 and #209"), set())

    def test_mentioned_prs_reads_no_english(self) -> None:
        """The robust half. A number is on the page or it is not."""
        self.assertEqual(
            hc.mentioned_prs("both open: #208 and #209, after #137 merged"),
            {208, 209, 137})


class TestClaimedBranch(unittest.TestCase):
    def test_the_shape(self) -> None:
        self.assertEqual(hc.claimed_branch("work is on branch `feat/x`"),
                         "feat/x")

    def test_no_backticks_is_no_claim(self) -> None:
        """A HANDOFF writes an identifier in backticks. Prose is not a claim."""
        self.assertIsNone(hc.claimed_branch("each its own branch then a PR"))

    def test_an_unrelated_backtick_is_not_a_branch(self) -> None:
        self.assertIsNone(hc.claimed_branch("read `src/api.py` first"))


# --- Versions ----------------------------------------------------------------


class TestVersions(unittest.TestCase):
    def test_prose_requires_the_leading_v(self) -> None:
        """The dependency-bump trap, and the reason the `v` is required.

        `4.37.3` is a Dependabot number. It is usually the highest number on
        the page, and without this rule it reads as the newest release of the
        repo. The tag check then reports a false MATCH and the drift stays.
        """
        state = "`v3.2.0` shipped. Bump codeql-action 4 to 4.37.3."
        self.assertEqual(hc.highest_version(state), (3, 2, 0))

    def test_the_highest_named_release_wins(self) -> None:
        self.assertEqual(
            hc.highest_version("v3.0.0 then v3.1.0 then v3.2.0"), (3, 2, 0))

    def test_no_version_is_none(self) -> None:
        self.assertIsNone(hc.highest_version("no release is named here"))

    def test_a_tag_name_parses_without_the_v(self) -> None:
        """A tag name and a CHANGELOG label are known to be versions."""
        self.assertEqual(hc.parse_version("3.2.1"), (3, 2, 1))
        self.assertEqual(hc.parse_version("v3.2.1"), (3, 2, 1))
        self.assertIsNone(hc.parse_version("latest"))


class TestChangelogTop(unittest.TestCase):
    def test_unreleased_is_skipped(self) -> None:
        """`[Unreleased]` names no version, so it can disagree with nothing."""
        text = "# Changelog\n\n## [Unreleased]\n\nwork\n\n## [3.2.1] - 2026-08-03\n"
        self.assertEqual(hc.parse_changelog_top(text), "3.2.1")

    def test_no_released_heading_is_none(self) -> None:
        self.assertIsNone(hc.parse_changelog_top("# Changelog\n\n## [Unreleased]\n"))

    def test_the_first_released_heading_wins(self) -> None:
        text = "## [3.2.1]\n\n## [3.2.0]\n"
        self.assertEqual(hc.parse_changelog_top(text), "3.2.1")


# --- Record parsers ----------------------------------------------------------


class TestRecordParsers(unittest.TestCase):
    def test_gh_pr_list(self) -> None:
        self.assertEqual(hc.parse_gh_pr_list(GH_PR_LIST), {208, 209})
        self.assertEqual(hc.parse_gh_pr_list("[]"), set())

    def test_bad_payload_raises_rather_than_reading_empty(self) -> None:
        """An empty set is a real answer. A broken payload must not become one."""
        with self.assertRaises(ValueError):
            hc.parse_gh_pr_list('{"number": 1}')
        with self.assertRaises(json.JSONDecodeError):
            hc.parse_gh_pr_list("not json")

    def test_an_annotated_tag_counts_once(self) -> None:
        """`refs/tags/v3.1.0` and `...^{}` are one tag, not two."""
        self.assertEqual(hc.parse_ls_remote_tags(LS_REMOTE_TAGS),
                         ["v1.0.0", "v3.1.0", "v3.2.1"])

    def test_tags_sort_by_version_not_by_string(self) -> None:
        text = ("a" * 40 + "\trefs/tags/v3.10.0\n" + "b" * 40 + "\trefs/tags/v3.9.0")
        self.assertEqual(hc.parse_ls_remote_tags(text)[-1], "v3.10.0")

    def test_a_tag_with_no_version_is_dropped(self) -> None:
        """The comparison cannot order `latest`, so it never enters it."""
        text = "c" * 40 + "\trefs/tags/latest"
        self.assertEqual(hc.parse_ls_remote_tags(text), [])

    def test_ls_remote_head(self) -> None:
        self.assertEqual(
            hc.parse_ls_remote_head(LS_REMOTE_MAIN, "refs/heads/main"),
            "aa8e6d54e0000000000000000000000000000001")
        self.assertIsNone(
            hc.parse_ls_remote_head(LS_REMOTE_MAIN, "refs/heads/other"))


# --- The job cross-check -----------------------------------------------------


class TestJobConsistency(unittest.TestCase):
    """The failure that motivated the tool, and the near miss beside it."""

    def setUp(self) -> None:
        sections = hc.split_sections(HANDOFF)
        self.jobs = hc.find_section(sections, "next jobs")
        self.owner = hc.find_section(sections, "owner-only")

    def test_a_done_job_restated_as_pending_is_found(self) -> None:
        stale = hc.restated_jobs(self.jobs, self.owner)
        self.assertEqual([entry["job"] for entry in stale], [3])
        self.assertIn("higher", stale[0]["shared"])

    def test_a_handed_over_step_is_not_a_drift(self) -> None:
        """Job 1 is DONE and hands the tag to the owner. That is correct.

        The owner-only entry describes a DIFFERENT action, in different words.
        A check keyed on the job NUMBER would flag this, which is why the
        signal is the job's own words instead.
        """
        stale = hc.restated_jobs(self.jobs, self.owner)
        self.assertNotIn(1, [entry["job"] for entry in stale])

    def test_an_unfinished_job_is_never_flagged(self) -> None:
        """Job 2 carries no DONE mark, so the owner list may say anything."""
        stale = hc.restated_jobs(self.jobs, self.owner)
        self.assertNotIn(2, [entry["job"] for entry in stale])

    def test_done_marks(self) -> None:
        jobs = hc.done_jobs("1. ~~**Struck out.**~~ shipped\n2. **DONE now.**\n"
                            "3. **Still open.** work continues")
        self.assertEqual(sorted(jobs), [1, 2])

    def test_a_later_line_does_not_close_a_job(self) -> None:
        """A job body often reports another job's outcome. That is not its own."""
        jobs = hc.done_jobs("1. **Open work.**\n   Job 2 is DONE, see below.")
        self.assertEqual(jobs, {})

    def test_a_version_never_matches_two_jobs_together(self) -> None:
        """Every job in one release cycle names the same version."""
        self.assertEqual(hc.significant_words(hc.action_name("`v3.2.0` ship")),
                         {"ship"})

    def test_one_shared_word_is_below_the_floor(self) -> None:
        """The stated limit. One word is a coincidence, two is a restatement."""
        jobs = "1. ~~**The region eval.**~~ **DONE.**"
        owner = "- **Tagging the region.** Owner runs it."
        self.assertEqual(hc.restated_jobs(jobs, owner), [])


# --- Absent is not zero ------------------------------------------------------


class TestAbsentIsNotZero(unittest.TestCase):
    """The rule the whole report rests on, asserted from the failing side."""

    def test_an_unread_forge_is_not_an_empty_one(self) -> None:
        with repo_with(fail=("gh pr list",)) as root:
            result = hc.check_repo(root)
        entry = row(result, "open-prs")
        self.assertEqual(entry["status"], hc.UNMEASURED)
        self.assertIn("not an empty one", entry["reason"])
        self.assertNotEqual(entry["status"], hc.MATCH)

    def test_an_unread_remote_is_not_an_untagged_one(self) -> None:
        with repo_with(fail=("git ls-remote --tags",)) as root:
            result = hc.check_repo(root)
        entry = row(result, "latest-tag")
        self.assertEqual(entry["status"], hc.UNMEASURED)
        self.assertIn("not an untagged one", entry["reason"])

    def test_a_claim_the_handoff_never_makes_is_unmeasured(self) -> None:
        handoff = HANDOFF.replace("on branch `tool/handoff-check`", "underway")
        with repo_with(handoff=handoff) as root:
            result = hc.check_repo(root)
        entry = row(result, "branch")
        self.assertEqual(entry["status"], hc.UNMEASURED)
        self.assertIn("names no branch", entry["reason"])

    def test_a_missing_changelog_is_unmeasured_not_a_match(self) -> None:
        with repo_with() as root:
            result = hc.check_repo(root)
        entry = row(result, "changelog-top")
        self.assertEqual(entry["status"], hc.UNMEASURED)
        self.assertIn("no CHANGELOG.md", entry["reason"])

    def test_no_state_section_measures_nothing(self) -> None:
        with repo_with(handoff="# HANDOFF\n\n## Notes\n\nnothing here\n") as root:
            result = hc.check_repo(root)
        handoff_rows = [entry for entry in result["checks"]
                        if entry["source"] == "handoff"]
        self.assertEqual(len(handoff_rows), 5)
        for entry in handoff_rows:
            self.assertEqual(entry["status"], hc.UNMEASURED)
        self.assertEqual(result["drift"], 0)

    def test_a_check_that_could_answer_still_runs(self) -> None:
        """The job cross-check never reads State, so a missing State is no
        excuse for it. A check that COULD have answered must not report that
        it could not."""
        handoff = HANDOFF.split("## Next jobs")[1]
        with repo_with(handoff="## Next jobs" + handoff) as root:
            result = hc.check_repo(root)
        entry = row(result, "job-consistency")
        self.assertEqual(entry["status"], hc.DRIFT)
        self.assertIn("job 3", entry["derived"])
        self.assertEqual(row(result, "open-prs")["status"], hc.UNMEASURED)

    def test_unmeasured_rows_are_counted_apart_from_matches(self) -> None:
        with repo_with(fail=("gh pr list",)) as root:
            result = hc.check_repo(root)
        matches = len(result["checks"]) - result["drift"] - result["unmeasured"]
        self.assertGreaterEqual(result["unmeasured"], 1)
        self.assertEqual(
            matches,
            sum(1 for entry in result["checks"] if entry["status"] == hc.MATCH))

    def test_a_missing_handoff_refuses(self) -> None:
        """Exit 2, never 0. A deleted file must not read as a correct one."""
        with repo_with(handoff=None) as root:
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = hc.main([str(root)])
        self.assertEqual(code, 2)
        self.assertIn("not a pass", err.getvalue())


# --- The checks end to end ---------------------------------------------------


class TestCheckRepo(unittest.TestCase):
    def test_open_prs_drift_names_the_stale_claim(self) -> None:
        with repo_with() as root:
            result = hc.check_repo(root)
        entry = row(result, "open-prs")
        self.assertEqual(entry["status"], hc.DRIFT)
        self.assertEqual(entry["claimed"], "open per State: 147")
        self.assertEqual(entry["derived"], "open per gh: 208, 209")
        self.assertIn("calls 147 open. The forge does not", entry["reason"])

    def test_an_open_pr_the_state_never_names_is_a_drift(self) -> None:
        """The staleness class. The forge moved after the file was written."""
        handoff = HANDOFF.replace("#208 and #209", "#137 and #142")
        with repo_with(handoff=handoff) as root:
            result = hc.check_repo(root)
        entry = row(result, "open-prs")
        self.assertEqual(entry["status"], hc.DRIFT)
        self.assertIn("lists 208, 209 open", entry["reason"])

    def test_open_prs_match(self) -> None:
        """#147 goes, and both live numbers stay named. Nothing disagrees."""
        handoff = HANDOFF.replace("and #147, still open", "and #147, merged")
        with repo_with(handoff=handoff) as root:
            result = hc.check_repo(root)
        self.assertEqual(row(result, "open-prs")["status"], hc.MATCH)

    def test_neither_side_naming_a_pr_is_unmeasured(self) -> None:
        """Silence on both sides agrees with nothing. It is not a MATCH."""
        run = fake_run({"gh pr list": "[]"})
        with repo_with(handoff="## State\n\n- no pull request is named.\n",
                       run=run) as root:
            result = hc.check_repo(root)
        entry = row(result, "open-prs")
        self.assertEqual(entry["status"], hc.UNMEASURED)
        self.assertIn("neither", entry["reason"])

    def test_branch_match(self) -> None:
        with repo_with() as root:
            result = hc.check_repo(root)
        self.assertEqual(row(result, "branch")["status"], hc.MATCH)

    def test_main_matches_the_remote(self) -> None:
        with repo_with() as root:
            result = hc.check_repo(root)
        self.assertEqual(row(result, "main-vs-origin")["status"], hc.MATCH)

    def test_a_clone_behind_the_remote_drifts(self) -> None:
        run = fake_run({"git rev-parse": "0" * 40 + "\n"})
        with repo_with(run=run) as root:
            result = hc.check_repo(root)
        entry = row(result, "main-vs-origin")
        self.assertEqual(entry["status"], hc.DRIFT)
        self.assertEqual(entry["source"], "clone")
        self.assertIn("does not carry", entry["reason"])

    def test_latest_tag_drift_is_one_directional(self) -> None:
        """The remote is ahead of the prose, which is the staleness class."""
        with repo_with() as root:
            result = hc.check_repo(root)
        entry = row(result, "latest-tag")
        self.assertEqual(entry["status"], hc.DRIFT)
        self.assertEqual(entry["claimed"], "v3.1.0")
        self.assertEqual(entry["derived"], "v3.2.1")

    def test_a_handoff_that_names_a_newer_version_is_not_a_drift(self) -> None:
        """A HANDOFF written after the tag is correct, not stale."""
        handoff = HANDOFF.replace("`v3.1.0` is shipped", "`v3.9.0` is shipped")
        with repo_with(handoff=handoff) as root:
            result = hc.check_repo(root)
        self.assertEqual(row(result, "latest-tag")["status"], hc.MATCH)

    def test_changelog_top_drift(self) -> None:
        with repo_with(changelog="## [Unreleased]\n\n## [3.2.1] - 2026\n") as root:
            result = hc.check_repo(root)
        entry = row(result, "changelog-top")
        self.assertEqual(entry["status"], hc.DRIFT)
        self.assertEqual(entry["derived"], "3.2.1")

    def test_changelog_top_match(self) -> None:
        with repo_with(changelog="## [3.1.0] - 2026\n") as root:
            result = hc.check_repo(root)
        self.assertEqual(row(result, "changelog-top")["status"], hc.MATCH)

    def test_job_consistency_drift_names_the_job(self) -> None:
        with repo_with() as root:
            result = hc.check_repo(root)
        entry = row(result, "job-consistency")
        self.assertEqual(entry["status"], hc.DRIFT)
        self.assertIn("job 3", entry["derived"])

    def test_every_check_appears_once_in_order(self) -> None:
        with repo_with() as root:
            result = hc.check_repo(root)
        self.assertEqual(
            tuple(entry["check"] for entry in result["checks"]), hc.CHECKS)


class TestExitCodes(unittest.TestCase):
    """The exit code is the interface: 0 no drift, 1 drift, 2 usage error."""

    def test_drift_exits_one(self) -> None:
        with repo_with() as root:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = hc.main([str(root)])
        self.assertEqual(code, 1)
        self.assertIn("DRIFT", out.getvalue())

    def test_a_clean_handoff_exits_zero(self) -> None:
        handoff = (
            "## State\n\n- on branch `tool/handoff-check`, `v3.2.1` is the tag,"
            " #208 and #209 stay open.\n")
        with repo_with(handoff=handoff) as root:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = hc.main([str(root)])
        self.assertEqual(code, 0)
        self.assertNotIn("DRIFT ", out.getvalue())

    def test_unmeasured_alone_does_not_fail(self) -> None:
        """An UNMEASURED row is reported loudly. It is not a failure."""
        handoff = "## State\n\n- nothing mechanical is claimed here.\n"
        with repo_with(handoff=handoff, fail=("gh pr list",)) as root:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = hc.main([str(root)])
        self.assertEqual(code, 0)
        self.assertIn("not a pass", out.getvalue())

    def test_a_missing_repo_is_a_usage_error(self) -> None:
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as raised:
                hc.main(["/no/such/repo/anywhere"])
        self.assertEqual(raised.exception.code, 2)

    def test_json_carries_the_same_rows(self) -> None:
        with repo_with() as root:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = hc.main([str(root), "--json"])
        payload = json.loads(out.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(len(payload["checks"]), len(hc.CHECKS))
        self.assertEqual(payload["drift"],
                         sum(1 for entry in payload["checks"]
                             if entry["status"] == hc.DRIFT))


class TestNeverWrites(unittest.TestCase):
    """The tool checks. It does not repair."""

    def test_the_handoff_is_byte_identical_after_a_run(self) -> None:
        with repo_with() as root:
            path = root / "HANDOFF.md"
            before = path.read_bytes()
            hc.check_repo(root)
            self.assertEqual(path.read_bytes(), before)

    def test_no_file_is_created(self) -> None:
        with repo_with() as root:
            before = sorted(item.name for item in root.iterdir())
            hc.check_repo(root)
            self.assertEqual(sorted(item.name for item in root.iterdir()),
                             before)


if __name__ == "__main__":
    unittest.main()
