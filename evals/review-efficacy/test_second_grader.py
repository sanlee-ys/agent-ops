#!/usr/bin/env python3
"""Tests for `second_grader.py`.

The grading itself is a network call and cannot run here. Everything around
it can, and the parts that decide a number are the parts worth testing: the
reply parser, the kappa, the redaction that keeps a local path out of a public
repository, and the prompt builder.

The last test is the one that matters most. It rebuilds all 20 stored prompts
from the stored evidence and compares the sha256 against the files on disk. A
reader who doubts the second grade can check that the prompts in the run
directory are the ones the grading rules produce, with no re-run and no
network.
"""

import json
import pathlib
import re
import unittest

import second_grader as sg

HERE = pathlib.Path(__file__).resolve().parent
RUN = HERE / "runs" / "2026-09-04"
SECOND = RUN / "second-grader"


class TestParseVerdict(unittest.TestCase):
    def test_plain_object(self) -> None:
        verdict, reason = sg.parse_verdict(
            '{"catch": true, "false_findings": 0, "note": "n"}'
        )
        self.assertIsNone(reason)
        self.assertEqual(verdict["catch"], True)
        self.assertEqual(verdict["false_findings"], 0)
        self.assertEqual(verdict["note"], "n")

    def test_code_fence_is_tolerated(self) -> None:
        verdict, reason = sg.parse_verdict(
            '```json\n{"catch": false, "false_findings": 2, "note": "n"}\n```'
        )
        self.assertIsNone(reason)
        self.assertEqual(verdict["catch"], False)
        self.assertEqual(verdict["false_findings"], 2)

    def test_prose_around_the_object_is_tolerated(self) -> None:
        verdict, reason = sg.parse_verdict(
            'Here is my verdict:\n{"catch": true, "false_findings": 1}\nDone.'
        )
        self.assertIsNone(reason)
        self.assertEqual(verdict["false_findings"], 1)
        self.assertEqual(verdict["note"], "")

    def test_no_object(self) -> None:
        verdict, reason = sg.parse_verdict("I cannot grade this.")
        self.assertIsNone(verdict)
        self.assertIn("no JSON object", reason)

    def test_missing_catch_is_not_a_verdict(self) -> None:
        verdict, reason = sg.parse_verdict('{"false_findings": 0}')
        self.assertIsNone(verdict)
        self.assertIn("`catch`", reason)

    def test_string_catch_is_rejected(self) -> None:
        # "true" is not true. A grader that answers with a string has not
        # answered the binary question, and guessing its intent would invent
        # agreement.
        verdict, reason = sg.parse_verdict('{"catch": "true", "false_findings": 0}')
        self.assertIsNone(verdict)
        self.assertIn("not a boolean", reason)

    def test_boolean_false_findings_is_rejected(self) -> None:
        # bool is a subclass of int in Python, so an unguarded isinstance
        # check would read `true` as the count 1.
        verdict, reason = sg.parse_verdict('{"catch": true, "false_findings": true}')
        self.assertIsNone(verdict)
        self.assertIn("not an integer", reason)

    def test_broken_json_is_named(self) -> None:
        verdict, reason = sg.parse_verdict('{"catch": true, "false_findings":}')
        self.assertIsNone(verdict)
        self.assertIn("did not parse", reason)


class TestKappa(unittest.TestCase):
    def test_perfect_agreement_with_both_labels_present(self) -> None:
        kappa, po, pe = sg.cohens_kappa([(True, True), (False, False)])
        self.assertEqual(po, 1.0)
        self.assertAlmostEqual(kappa, 1.0)

    def test_one_label_everywhere_is_undefined_not_zero(self) -> None:
        # Both graders said catch on every unit. Expected agreement is 1.0,
        # so the denominator is zero. Reporting 0.0 would read as chance
        # agreement, which is the opposite of what happened.
        kappa, po, pe = sg.cohens_kappa([(True, True)] * 5)
        self.assertEqual(po, 1.0)
        self.assertAlmostEqual(pe, 1.0)
        self.assertIsNone(kappa)

    def test_chance_level_agreement_is_zero(self) -> None:
        kappa, po, _ = sg.cohens_kappa(
            [(True, True), (True, False), (False, False), (False, True)]
        )
        self.assertEqual(po, 0.5)
        self.assertAlmostEqual(kappa, 0.0)

    def test_empty_input(self) -> None:
        self.assertEqual(sg.cohens_kappa([]), (None, None, None))


class TestRedaction(unittest.TestCase):
    # The fixture is assembled from parts on purpose. A literal local user
    # path in this file would itself trip `scripts/redline-guard.py`, which
    # refuses that pattern at commit time in this public repository.
    SEP = chr(92)
    FIXTURE = "C:" + SEP + "Users" + SEP + "someone" + SEP + "tmp"

    def test_workdir_line_is_replaced(self) -> None:
        out = sg.redact_home("model: x\nworkdir: %s\nok\n" % self.FIXTURE)
        self.assertIn("workdir: <empty-scratch-dir>", out)
        self.assertNotIn("Users", out)

    def test_redaction_is_idempotent(self) -> None:
        once = sg.redact_home("workdir: %s\n" % self.FIXTURE)
        self.assertEqual(sg.redact_home(once), once)

    def test_no_stored_stderr_carries_a_local_user_path(self) -> None:
        # The same pattern `scripts/redline-guard.py` refuses at commit time.
        for path in sorted(SECOND.rglob("*.stderr.txt")):
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(
                re.search(r"(?:[Cc]:[\\/]+|/c/)Users[\\/]+\w+", text),
                "%s carries a local user path" % path.name,
            )


class TestPromptContent(unittest.TestCase):
    def setUp(self) -> None:
        self.grades = json.loads((RUN / "grades.json").read_text(encoding="utf-8"))
        self.prompt = (SECOND / "c01" / "claude.prompt.txt").read_text(
            encoding="utf-8"
        )

    def test_every_grading_rule_appears_word_for_word(self) -> None:
        for rule in self.grades["grading_rules"]:
            self.assertIn(rule, self.prompt)

    def test_the_prompt_carries_the_diff_and_the_review(self) -> None:
        self.assertIn(sg.PROMPT_FENCE_DIFF, self.prompt)
        self.assertIn(sg.PROMPT_FENCE_REVIEW, self.prompt)

    def test_the_prompt_never_names_the_lane_that_wrote_the_review(self) -> None:
        # The file name says `claude`; the prompt must not. A grader told the
        # family of the writer is no longer blind.
        head = self.prompt.split(sg.PROMPT_FENCE_DIFF)[0]
        self.assertNotIn("claude", head.lower())
        self.assertNotIn("codex", head.lower())

    def test_the_prompt_never_carries_the_first_grade(self) -> None:
        # The second grader must not be able to read the verdict it is meant
        # to check independently.
        for condition in sg.CONDITIONS:
            note = self.grades["cases"]["c01"][condition]["note"]
            self.assertNotIn(note, self.prompt)
        self.assertNotIn(self.grades["grader"], self.prompt)


class TestStoredPromptsMatchTheRules(unittest.TestCase):
    def test_all_twenty_prompts_rebuild_byte_identical(self) -> None:
        grades = json.loads((RUN / "grades.json").read_text(encoding="utf-8"))
        manifest = json.loads((RUN / "manifest.json").read_text(encoding="utf-8"))
        seen = 0
        for case_id, condition, prompt in sg.units(RUN, grades, manifest):
            stored = SECOND / case_id / ("%s.prompt.txt" % condition)
            self.assertTrue(stored.exists(), "%s missing" % stored.name)
            self.assertEqual(
                sg.sha256_text(stored.read_text(encoding="utf-8")),
                sg.sha256_text(prompt),
                "%s/%s does not match the rebuilt prompt" % (case_id, condition),
            )
            seen += 1
        self.assertEqual(seen, 20)

    def test_every_unit_has_a_parsable_reply(self) -> None:
        for path in sorted(SECOND.rglob("*.stdout.txt")):
            verdict, reason = sg.parse_verdict(path.read_text(encoding="utf-8"))
            self.assertIsNotNone(verdict, "%s: %s" % (path.name, reason))


class TestFirstGraderFilesAreUntouched(unittest.TestCase):
    def test_grades_json_still_names_the_first_grader(self) -> None:
        grades = json.loads((RUN / "grades.json").read_text(encoding="utf-8"))
        self.assertIn("Claude Code lane", grades["grader"])
        self.assertEqual(grades["graded_at"], "2026-09-04")
        self.assertEqual(len(grades["cases"]), 10)


if __name__ == "__main__":
    unittest.main()
