#!/usr/bin/env python3
"""Test suite for scripts/dead_rules_audit.py.

Two things this suite is really about, beyond the detectors themselves:

  1. **The false-positive side of every detector.** A dead-rules audit that
     over-counts is worse than none, because the number is the whole product.
     Each detector class below carries the near misses it must NOT flag.
  2. **What never leaves the transcript.** A transcript holds the whole
     session. TestNothingLeaks asserts that assistant prose, user prose and
     file contents never reach a count or an example, and that the em-dash
     detector emits no examples at all.

Fixtures are synthetic transcripts written into a temporary directory, so the
suite never reads the real session store.

Stdlib only (no pytest) so CI stays a bare `python -m unittest discover`.
"""
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "dead_rules_audit",
    Path(__file__).resolve().parent.parent / "scripts" / "dead_rules_audit.py",
)
audit_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(audit_mod)

NOW = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)


def shell_record(command, when=NOW, tool="Bash"):
    return {
        "type": "assistant",
        "timestamp": when.isoformat().replace("+00:00", "Z"),
        "message": {"content": [
            {"type": "tool_use", "name": tool, "input": {"command": command}}
        ]},
    }


def text_record(text, when=NOW):
    return {
        "type": "assistant",
        "timestamp": when.isoformat().replace("+00:00", "Z"),
        "message": {"content": [{"type": "text", "text": text}]},
    }


def write_transcript(root, name, records):
    project = Path(root) / "C--synthetic-project"
    project.mkdir(parents=True, exist_ok=True)
    path = project / (name + ".jsonl")
    path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )
    return path


class TestCompoundInspection(unittest.TestCase):
    """Three or more read-only segments in one command."""

    def test_three_read_only_segments(self) -> None:
        self.assertTrue(audit_mod.is_compound_inspection(
            "git status && git log --oneline -3 && gh pr list"))

    def test_semicolons_count_too(self) -> None:
        self.assertTrue(audit_mod.is_compound_inspection(
            "git status; git branch --list; git remote -v"))

    def test_git_dash_c_form_is_still_a_read(self) -> None:
        """`git -C <path> status` puts the subcommand third."""
        self.assertTrue(audit_mod.is_compound_inspection(
            "git -C /r status && git -C /r log && git -C /r branch --list"))

    def test_two_segments_are_not_counted(self) -> None:
        """Cheap and common. Counting it would drown the signal."""
        self.assertFalse(audit_mod.is_compound_inspection(
            "git status && git log --oneline -3"))

    def test_a_chain_with_a_mutation_is_not_inspection(self) -> None:
        """`add && commit && push` has a real ordering dependency."""
        self.assertFalse(audit_mod.is_compound_inspection(
            "git add x.py && git commit -m 'x' && git push"))

    def test_a_single_command_is_not_a_chain(self) -> None:
        self.assertFalse(audit_mod.is_compound_inspection("git status"))

    def test_an_unknown_verb_breaks_the_chain(self) -> None:
        self.assertFalse(audit_mod.is_compound_inspection(
            "git status && terraform apply && gh pr list"))


class TestCdThenGit(unittest.TestCase):
    def test_the_shape(self) -> None:
        self.assertTrue(audit_mod.is_cd_then_git("cd /repo && git status"))
        self.assertTrue(audit_mod.is_cd_then_git('cd "/a path/repo" ; git log'))

    def test_git_dash_c_is_the_correct_form(self) -> None:
        self.assertFalse(audit_mod.is_cd_then_git("git -C /repo status"))

    def test_cd_alone_is_fine(self) -> None:
        self.assertFalse(audit_mod.is_cd_then_git("cd /repo"))

    def test_cd_then_something_else(self) -> None:
        self.assertFalse(audit_mod.is_cd_then_git("cd /repo && npm test"))

    def test_a_word_ending_in_cd_is_not_cd(self) -> None:
        self.assertFalse(audit_mod.is_cd_then_git("abcd /repo && git status"))


class TestVenvInterpreter(unittest.TestCase):
    def test_both_layouts(self) -> None:
        self.assertTrue(audit_mod.is_venv_interpreter(".venv/Scripts/python.exe x.py"))
        self.assertTrue(audit_mod.is_venv_interpreter(".venv/bin/python x.py"))
        self.assertTrue(audit_mod.is_venv_interpreter(
            r"C:\repo\.venv\Scripts\python x.py"))

    def test_the_launcher_form_is_correct(self) -> None:
        self.assertFalse(audit_mod.is_venv_interpreter("uv run python x.py"))

    def test_a_bare_interpreter_is_not_a_venv_path(self) -> None:
        self.assertFalse(audit_mod.is_venv_interpreter("python x.py"))

    def test_a_venv_path_that_is_not_an_interpreter(self) -> None:
        self.assertFalse(audit_mod.is_venv_interpreter("ls .venv/Scripts/"))


class TestEmDash(unittest.TestCase):
    def test_counts_every_occurrence(self) -> None:
        self.assertEqual(audit_mod.count_em_dashes("a — b — c"), 2)

    def test_an_en_dash_counts_too(self) -> None:
        self.assertEqual(audit_mod.count_em_dashes("a – b"), 1)

    def test_a_hyphen_is_not_a_dash(self) -> None:
        self.assertEqual(audit_mod.count_em_dashes("well-known --flag"), 0)

    def test_empty(self) -> None:
        self.assertEqual(audit_mod.count_em_dashes(""), 0)
        self.assertEqual(audit_mod.count_em_dashes(None), 0)


class TestWindow(unittest.TestCase):
    """A record outside the window is not evidence about this window."""

    def test_only_records_inside_the_window_count(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            write_transcript(root, "s", [
                shell_record("cd /r && git status", NOW),
                shell_record("cd /r && git status", NOW - timedelta(days=30)),
            ])
            result = audit_mod.audit(Path(root), days=7, now=NOW)
        rules = result["rules"]["cd-then-git"]
        self.assertEqual(sum(b["count"] for b in rules.values()), 1)

    def test_counts_are_bucketed_per_day(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            write_transcript(root, "s", [
                shell_record("cd /r && git status", NOW),
                shell_record("cd /r && git log", NOW - timedelta(days=2)),
            ])
            result = audit_mod.audit(Path(root), days=7, now=NOW)
        self.assertEqual(sorted(result["rules"]["cd-then-git"]),
                         ["2026-08-20", "2026-08-22"])

    def test_a_record_with_no_timestamp_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            write_transcript(root, "s", [
                {"type": "assistant", "message": {"content": [
                    {"type": "tool_use", "name": "Bash",
                     "input": {"command": "cd /r && git status"}}]}},
            ])
            result = audit_mod.audit(Path(root), days=7, now=NOW)
        self.assertEqual(result["records_in_window"], 0)


class TestMalformedInput(unittest.TestCase):
    """A transcript is written by another program. It must never wedge this one."""

    def test_an_unparseable_line_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            project = Path(root) / "C--synthetic-project"
            project.mkdir(parents=True)
            (project / "s.jsonl").write_text(
                "not json\n" + json.dumps(shell_record("cd /r && git status"))
                + "\n{\n", encoding="utf-8",
            )
            result = audit_mod.audit(Path(root), days=7, now=NOW)
        self.assertEqual(result["records_in_window"], 1)

    def test_records_of_other_types_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            write_transcript(root, "s", [
                {"type": "system", "timestamp": NOW.isoformat()},
                {"type": "attachment", "timestamp": NOW.isoformat()},
            ])
            result = audit_mod.audit(Path(root), days=7, now=NOW)
        for rule in audit_mod.DETECTORS:
            self.assertEqual(result["rules"][rule], {})

    def test_a_content_block_of_the_wrong_shape(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            write_transcript(root, "s", [{
                "type": "assistant", "timestamp": NOW.isoformat(),
                "message": {"content": ["a bare string", None, 7]},
            }])
            result = audit_mod.audit(Path(root), days=7, now=NOW)
        self.assertEqual(result["rules"]["cd-then-git"], {})

    def test_an_empty_transcript_root(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            result = audit_mod.audit(Path(root), days=7, now=NOW)
        self.assertEqual(result["transcripts_in_window"], 0)


class TestNothingLeaks(unittest.TestCase):
    """A transcript holds the whole session. An audit of it must not become a
    second copy of it."""

    def test_the_em_dash_detector_emits_no_examples(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            write_transcript(root, "s", [
                text_record("A sentence — with a secret plan in it.")
            ])
            result = audit_mod.audit(Path(root), days=7, now=NOW)
        buckets = result["rules"]["em-dash"]
        self.assertEqual(sum(b["count"] for b in buckets.values()), 1)
        for bucket in buckets.values():
            self.assertEqual(bucket["examples"], [])
        report = audit_mod.format_report(result)
        self.assertNotIn("secret plan", report)

    def test_assistant_prose_never_reaches_an_example(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            write_transcript(root, "s", [
                text_record("I will now cd /r && git status for you."),
                shell_record("cd /r && git status"),
            ])
            result = audit_mod.audit(Path(root), days=7, now=NOW)
        report = audit_mod.format_report(result)
        self.assertNotIn("for you", report)
        self.assertIn("cd /r && git status", report)

    def test_user_records_are_never_scanned(self) -> None:
        """The operator's own text must not reach a count or an example."""
        with tempfile.TemporaryDirectory() as root:
            write_transcript(root, "s", [{
                "type": "user", "timestamp": NOW.isoformat(),
                "message": {"content": [
                    {"type": "text", "text": "run cd /r && git status — please"}
                ]},
            }])
            result = audit_mod.audit(Path(root), days=7, now=NOW)
        self.assertEqual(result["rules"]["cd-then-git"], {})
        self.assertEqual(result["rules"]["em-dash"], {})

    def test_a_tool_input_that_is_not_a_command_is_ignored(self) -> None:
        """A Write payload's `content` is file text, and file text never
        reaches a count."""
        with tempfile.TemporaryDirectory() as root:
            write_transcript(root, "s", [{
                "type": "assistant", "timestamp": NOW.isoformat(),
                "message": {"content": [{
                    "type": "tool_use", "name": "Write",
                    "input": {"file_path": "x.md",
                              "content": "cd /r && git status — an example"},
                }]},
            }])
            result = audit_mod.audit(Path(root), days=7, now=NOW)
        self.assertEqual(result["rules"]["cd-then-git"], {})
        self.assertEqual(result["rules"]["em-dash"], {})

    def test_examples_are_capped_and_truncated(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            write_transcript(root, "s", [
                shell_record("cd /r%d && git status %s" % (i, "x" * 300))
                for i in range(6)
            ])
            result = audit_mod.audit(Path(root), days=7, now=NOW)
        bucket = result["rules"]["cd-then-git"]["2026-08-22"]
        self.assertEqual(bucket["count"], 6)
        self.assertEqual(len(bucket["examples"]), audit_mod.MAX_EXAMPLES)
        for example in bucket["examples"]:
            self.assertLessEqual(len(example), audit_mod.EXAMPLE_WIDTH)


class TestReport(unittest.TestCase):
    def test_absence_is_stated_not_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            result = audit_mod.audit(Path(root), days=7, now=NOW)
        report = audit_mod.format_report(result)
        for rule in audit_mod.DETECTORS:
            self.assertIn(rule, report)
        self.assertIn("no hits in window", report)

    def test_the_limit_is_always_printed(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            result = audit_mod.audit(Path(root), days=7, now=NOW)
        report = audit_mod.format_report(result)
        self.assertIn("DETECTABLE subset only", report)
        self.assertIn("conventions/dead-rules-audit.md", report)


class TestCli(unittest.TestCase):
    """argparse writes usage text to stderr; it is captured so a pass is quiet."""

    def _exit_code(self, argv):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                audit_mod.main(argv)
        return raised.exception.code

    def test_a_missing_root_exits_two(self) -> None:
        self.assertEqual(self._exit_code(["--root", "/no/such/dir"]), 2)

    def test_a_zero_day_window_exits_two(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(self._exit_code(["--root", root, "--days", "0"]), 2)

    def test_json_output_parses(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            write_transcript(root, "s", [shell_record("cd /r && git status")])
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = audit_mod.main(["--root", root, "--json"])
        self.assertEqual(code, 0)
        parsed = json.loads(buffer.getvalue())
        self.assertIn("rules", parsed)
        self.assertIn("window_days", parsed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
