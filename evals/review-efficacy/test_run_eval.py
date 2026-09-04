#!/usr/bin/env python3
"""Tests for the review-efficacy harness.

The harness decides what a reviewer sees and how a run is scored, so a silent
defect here turns into a wrong measurement rather than a red build. These tests
cover the four places that can produce a wrong measurement: seed validation,
the line numbering, the paired statistic, and the exclusion of a case that did
not run or was not graded.

Run them:

    uv run python -m unittest discover -s evals/review-efficacy -p "test_*.py" -v

They are NOT in this repository's CI job. `.github/workflows/ci.yml` discovers
`tests/` only, and this lane does not edit that file.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_eval  # noqa: E402


DIFF = "\n".join([
    "diff --git a/m.py b/m.py",
    "index 111..222 100644",
    "--- a/m.py",
    "+++ b/m.py",
    "@@ -1,3 +1,4 @@",
    " import os",
    "-limit = 2",
    "+limit = 3",
    "+other = 3",
    " print(limit)",
    "",
])


class TestApplyMutation(unittest.TestCase):
    def test_seeds_an_added_line(self):
        out = run_eval.apply_mutation(DIFF, "limit = 3", "limit = 4")
        self.assertIn("+limit = 4", out)
        self.assertNotIn("+limit = 3", out)

    def test_refuses_an_ambiguous_anchor(self):
        with self.assertRaises(run_eval.CaseError) as ctx:
            run_eval.apply_mutation(DIFF, "= 3", "= 4")
        self.assertIn("matches 2 times", str(ctx.exception))

    def test_refuses_an_absent_anchor(self):
        with self.assertRaises(run_eval.CaseError):
            run_eval.apply_mutation(DIFF, "no such text", "x")

    def test_refuses_a_context_line(self):
        with self.assertRaises(run_eval.CaseError) as ctx:
            run_eval.apply_mutation(DIFF, "print(limit)", "print(0)")
        self.assertIn("not inside a single added line", str(ctx.exception))

    def test_refuses_a_removed_line(self):
        with self.assertRaises(run_eval.CaseError):
            run_eval.apply_mutation(DIFF, "limit = 2", "limit = 9")

    def test_refuses_a_line_count_change(self):
        with self.assertRaises(run_eval.CaseError) as ctx:
            run_eval.apply_mutation(DIFF, "limit = 3", "limit = 4\nextra = 1")
        self.assertIn("line count", str(ctx.exception))

    def test_refuses_the_file_header(self):
        """A `+++` header is not an added line, however much it looks like one."""
        with self.assertRaises(run_eval.CaseError):
            run_eval.apply_mutation(DIFF, "+++ b/m.py", "+++ b/other.py")


class TestNumberDiff(unittest.TestCase):
    def test_numbers_added_and_context_lines_only(self):
        out = run_eval.number_diff(DIFF).splitlines()
        self.assertEqual(out[5], "     1  import os")
        self.assertEqual(out[6], "       -limit = 2")
        self.assertEqual(out[7], "     2 +limit = 3")
        self.assertEqual(out[8], "     3 +other = 3")
        self.assertEqual(out[9], "     4  print(limit)")

    def test_a_no_newline_marker_takes_no_number_and_does_not_advance(self):
        """`\\ No newline at end of file` annotates the line above it. Numbering
        it shifts every later added line by one, and a finding then cites the
        wrong line."""
        diff = "\n".join([
            "--- a/m.py",
            "+++ b/m.py",
            "@@ -1,2 +1,2 @@",
            " keep",
            "-old",
            "\\ No newline at end of file",
            "+new",
        ])
        out = run_eval.number_diff(diff).splitlines()
        self.assertEqual(out[5], "\\ No newline at end of file")
        self.assertEqual(out[6], "     2 +new")

    def test_leaves_headers_unnumbered(self):
        out = run_eval.number_diff(DIFF).splitlines()
        self.assertEqual(out[2], "--- a/m.py")
        self.assertEqual(out[3], "+++ b/m.py")
        self.assertTrue(out[4].startswith("@@"))


class TestBuildPrompt(unittest.TestCase):
    def test_carries_the_rules_and_the_diff(self):
        prompt = run_eval.build_prompt("RULES-TEXT", "a title", "the-diff")
        self.assertIn("RULES-TEXT", prompt)
        self.assertIn("a title", prompt)
        self.assertIn("the-diff", prompt)

    def test_an_over_cap_diff_raises_rather_than_truncates(self):
        """Truncation can cut the seeded defect out of the prompt. A reviewer
        graded on a prompt that never held the defect is a false result."""
        with self.assertRaises(run_eval.CaseError) as ctx:
            run_eval.build_prompt("R", "t", "x" * (run_eval.DIFF_CHAR_CAP + 1))
        self.assertIn("over the", str(ctx.exception))


class TestMcNemar(unittest.TestCase):
    def test_no_discordant_pair_is_undefined_not_one(self):
        self.assertIsNone(run_eval.mcnemar_exact_two_sided(0, 0))

    def test_six_nil_reaches_significance(self):
        self.assertAlmostEqual(run_eval.mcnemar_exact_two_sided(6, 0), 0.03125, places=6)

    def test_five_nil_does_not(self):
        self.assertAlmostEqual(run_eval.mcnemar_exact_two_sided(5, 0), 0.0625, places=6)

    def test_an_even_split_is_one(self):
        self.assertAlmostEqual(run_eval.mcnemar_exact_two_sided(3, 3), 1.0, places=6)

    def test_the_statistic_is_symmetric(self):
        self.assertEqual(
            run_eval.mcnemar_exact_two_sided(5, 1),
            run_eval.mcnemar_exact_two_sided(1, 5),
        )

    def test_the_power_floor_is_six(self):
        self.assertEqual(run_eval.min_discordant_for_significance(), 6)


def _write_run(tmp: Path, cases: dict, grades: dict, conditions=None) -> Path:
    run_dir = tmp / "run"
    run_dir.mkdir()
    manifest = {"cases": cases, "conditions": conditions or {
        "claude": {"model": "claude-sonnet-5"}, "codex": {"model": "gpt-x"}}}
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "grades.json").write_text(json.dumps(grades), encoding="utf-8")
    return run_dir


def _case(ok_claude=True, ok_codex=True):
    return {
        "pr": 1,
        "defect_class": "x",
        "writer_provenance": "Claude Fable 5 <noreply@anthropic.com>",
        "conditions": {
            "claude": {"ok": ok_claude},
            "codex": {"ok": ok_codex},
        },
    }


def _grade(claude_catch, codex_catch):
    return {
        "claude": {"catch": claude_catch, "false_findings": 0},
        "codex": {"catch": codex_catch, "false_findings": 0},
    }


class TestReport(unittest.TestCase):
    def _report(self, cases, grades, conditions=None):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = _write_run(Path(tmp), cases, {"cases": grades}, conditions)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = run_eval.report(run_dir)
            return code, buf.getvalue()

    def test_a_failed_condition_is_unrun_and_leaves_the_paired_statistic(self):
        cases = {"a": _case(), "b": _case(ok_codex=False)}
        grades = {"a": _grade(True, False), "b": _grade(True, True)}
        _, out = self._report(cases, grades)
        self.assertIn("UNRUN", out)
        self.assertIn("complete pairs only: 1 of 2", out)

    def test_a_half_run_case_still_counts_for_the_condition_that_ran(self):
        """The other condition's failure must not delete a graded result."""
        cases = {"a": _case(), "b": _case(ok_codex=False)}
        grades = {"a": _grade(True, False), "b": _grade(True, True)}
        _, out = self._report(cases, grades)
        self.assertIn("claude  catch rate: 2/2 graded cases", out)
        self.assertIn("codex   catch rate: 0/1 graded cases", out)

    def test_an_ungraded_case_leaves_the_paired_statistic(self):
        cases = {"a": _case(), "b": _case()}
        grades = {"a": _grade(True, False), "b": _grade(None, None)}
        _, out = self._report(cases, grades)
        self.assertIn("UNGRADED", out)
        self.assertIn("complete pairs only: 1 of 2", out)

    def test_it_counts_the_discordant_pairs_in_the_right_direction(self):
        cases = {c: _case() for c in "abcd"}
        grades = {
            "a": _grade(True, False),      # Claude-only
            "b": _grade(False, True),      # Codex-only
            "c": _grade(False, True),      # Codex-only
            "d": _grade(True, True),       # concordant
        }
        _, out = self._report(cases, grades)
        self.assertIn("Codex-only 2, Claude-only 1", out)
        self.assertIn("claude  catch rate: 2/4", out)
        self.assertIn("codex   catch rate: 3/4", out)

    def test_an_unresolved_model_id_is_warned_about(self):
        cases = {"a": _case()}
        grades = {"a": _grade(True, True)}
        _, out = self._report(cases, grades, conditions={
            "claude": {"model": None},
            "codex": {"model": "unresolved: could not read the Codex config"},
        })
        self.assertIn("WARNING", out)
        self.assertIn("cannot name the model", out)

    def test_resolved_model_ids_produce_no_warning(self):
        cases = {"a": _case()}
        grades = {"a": _grade(True, True)}
        _, out = self._report(cases, grades)
        self.assertIn("claude-sonnet-5", out)
        self.assertNotIn("WARNING", out)

    def test_it_reports_writer_provenance(self):
        cases = {"a": _case()}
        grades = {"a": _grade(True, True)}
        _, out = self._report(cases, grades)
        self.assertIn("Writer provenance: 1 of 1", out)

    def test_a_case_with_no_claude_trailer_is_warned_about(self):
        """The headline claim is about a Claude-authored diff. A case with no
        trailer narrows the population, and the report says so."""
        case = _case()
        case["writer_provenance"] = "none: the head commit has no Co-Authored-By trailer"
        _, out = self._report({"a": case}, {"a": _grade(True, True)})
        self.assertIn("WARNING", out)
        self.assertIn("not Claude-authored diffs", out)

    def test_it_says_when_the_run_cannot_reach_significance(self):
        cases = {c: _case() for c in "ab"}
        grades = {"a": _grade(True, False), "b": _grade(True, False)}
        _, out = self._report(cases, grades)
        self.assertIn("CANNOT reach significance", out)

    def test_a_missing_grades_file_is_a_usage_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            (run_dir / "manifest.json").write_text('{"cases": {}}', encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = run_eval.report(run_dir)
            self.assertEqual(code, run_eval.USAGE_ERROR)


class TestClaudeReviewText(unittest.TestCase):
    def test_it_reads_the_result_and_the_model(self):
        payload = json.dumps({"result": "the review", "modelUsage": {"claude-sonnet-5": {}}})
        text, model = run_eval._claude_review_text(payload)
        self.assertEqual(text, "the review")
        self.assertEqual(model, "claude-sonnet-5")

    def test_it_falls_back_to_the_raw_output(self):
        text, model = run_eval._claude_review_text("not json")
        self.assertEqual(text, "not json")
        self.assertIsNone(model)


class TestResolveExecutable(unittest.TestCase):
    def test_an_unknown_command_passes_through(self):
        argv = ["definitely-not-a-real-command-xyz", "--flag"]
        self.assertEqual(run_eval.resolve_executable(argv), argv)

    def test_a_known_command_gets_an_absolute_path(self):
        out = run_eval.resolve_executable([sys.executable, "-V"])
        self.assertTrue(Path(out[0]).is_absolute())
        self.assertEqual(out[1:], ["-V"])

    @unittest.skipUnless(sys.platform == "win32", "Windows shim behaviour")
    def test_a_windows_shim_goes_through_the_interpreter(self):
        """A .CMD shim cannot be started by CreateProcess. The first pilot run
        lost all ten Codex conditions to exactly this."""
        with tempfile.TemporaryDirectory() as tmp:
            shim = Path(tmp) / "faketool.cmd"
            shim.write_text("@echo off\n", encoding="utf-8")
            real_which = run_eval.shutil.which
            run_eval.shutil.which = lambda name: str(shim) if name == "faketool" else real_which(name)
            try:
                out = run_eval.resolve_executable(["faketool", "exec"])
            finally:
                run_eval.shutil.which = real_which
        self.assertEqual(out[1], "/c")
        self.assertEqual(out[2], str(shim))
        self.assertEqual(out[3], "exec")


class TestCodexModel(unittest.TestCase):
    def test_it_never_raises(self):
        """A missing or odd config is reported, never crashed on."""
        self.assertIsInstance(run_eval.resolve_codex_model(), str)


if __name__ == "__main__":
    unittest.main()
