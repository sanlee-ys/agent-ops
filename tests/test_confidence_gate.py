#!/usr/bin/env python3
"""Test suite for scripts/confidence_gate.py.

Organised around the verdicts the gate can return, not around its internals —
each test picks prior runs and a candidate that force one verdict, checked
against the formula in the module docstring (confidence = |best_improvement|
/ MAD of prior runs, adapted from davebcn87/pi-autoresearch, MIT License).

Stdlib only (no pytest) so CI stays a bare `python -m unittest discover`; also
runs unchanged under `uv run pytest tests/test_confidence_gate.py`, since
pytest collects `unittest.TestCase` classes directly.
"""
import contextlib
import importlib.util
import io
import json
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "confidence_gate",
    Path(__file__).resolve().parent.parent / "scripts" / "confidence_gate.py",
)
cg = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cg)


class TestEvaluateKeep(unittest.TestCase):
    def test_keep_lower_is_better(self) -> None:
        # prior median 10, MAD 1; candidate 6 -> best_improvement 4, confidence 4.0
        result = cg.evaluate([9, 10, 11], 6, "lower-is-better")
        self.assertEqual(result["runs"], 3)
        self.assertEqual(result["mad"], 1)
        self.assertEqual(result["best_improvement"], 4)
        self.assertEqual(result["confidence"], 4.0)
        self.assertEqual(result["verdict"], "keep")
        self.assertNotIn("reason", result)

    def test_keep_higher_is_better(self) -> None:
        # prior median 10, MAD 1; candidate 14 -> best_improvement 4, confidence 4.0
        result = cg.evaluate([9, 10, 11], 14, "higher-is-better")
        self.assertEqual(result["best_improvement"], 4)
        self.assertEqual(result["confidence"], 4.0)
        self.assertEqual(result["verdict"], "keep")


class TestEvaluateNoise(unittest.TestCase):
    def test_noise_lower_is_better(self) -> None:
        # prior median 10, MAD 1; candidate 9.5 -> best_improvement 0.5, confidence 0.5
        result = cg.evaluate([9, 10, 11], 9.5, "lower-is-better")
        self.assertEqual(result["best_improvement"], 0.5)
        self.assertEqual(result["confidence"], 0.5)
        self.assertEqual(result["verdict"], "noise")
        self.assertNotIn("reason", result)

    def test_noise_higher_is_better(self) -> None:
        result = cg.evaluate([9, 10, 11], 10.5, "higher-is-better")
        self.assertEqual(result["confidence"], 0.5)
        self.assertEqual(result["verdict"], "noise")


class TestEvaluateInconclusive(unittest.TestCase):
    def test_mid_range_confidence(self) -> None:
        # prior median 10, MAD 1; candidate 8.5 -> best_improvement 1.5, confidence 1.5
        result = cg.evaluate([9, 10, 11], 8.5, "lower-is-better")
        self.assertEqual(result["confidence"], 1.5)
        self.assertEqual(result["verdict"], "inconclusive")

    def test_confident_but_wrong_direction(self) -> None:
        # Candidate moves the metric the WORSE way, but with high confidence.
        # Not "keep" (wrong direction) and not "noise" (the move is real) —
        # the gate reports "inconclusive" with a reason rather than inventing
        # a fifth verdict.
        result = cg.evaluate([9, 10, 11], 14, "lower-is-better")
        self.assertEqual(result["best_improvement"], -4)
        self.assertEqual(result["confidence"], 4.0)
        self.assertEqual(result["verdict"], "inconclusive")
        self.assertIn("reason", result)


class TestEvaluateInsufficientRuns(unittest.TestCase):
    def test_below_the_three_run_floor(self) -> None:
        for prior_runs in ([], [10], [9, 11]):
            with self.subTest(prior_runs=prior_runs):
                result = cg.evaluate(prior_runs, 5, "lower-is-better")
                self.assertEqual(result["verdict"], "insufficient_runs")
                self.assertIsNone(result["confidence"])
                self.assertIsNone(result["mad"])
                self.assertIsNone(result["best_improvement"])
                self.assertIn("reason", result)
                self.assertEqual(result["runs"], len(prior_runs))


class TestEvaluateMadZero(unittest.TestCase):
    def test_identical_prior_runs_never_divides_by_zero(self) -> None:
        result = cg.evaluate([10, 10, 10], 5, "lower-is-better")
        self.assertEqual(result["mad"], 0)
        self.assertIsNone(result["confidence"])
        self.assertEqual(result["verdict"], "inconclusive")
        self.assertIn("reason", result)
        self.assertEqual(result["best_improvement"], 5)


class TestEvaluateValidation(unittest.TestCase):
    def test_invalid_direction_raises(self) -> None:
        with self.assertRaises(ValueError):
            cg.evaluate([1, 2, 3], 1, "sideways")


class TestMedianAbsoluteDeviation(unittest.TestCase):
    def test_known_values(self) -> None:
        self.assertEqual(cg.median_absolute_deviation([1, 2, 3, 4, 5]), 1)
        self.assertEqual(cg.median_absolute_deviation([10, 10, 10]), 0)


class TestCli(unittest.TestCase):
    def _run(self, payload, direction, argv_extra=None):
        stdin = io.StringIO(json.dumps(payload))
        stdout = io.StringIO()
        argv = ["--direction", direction] + (argv_extra or [])
        with contextlib.redirect_stdout(stdout):
            real_stdin = cg.sys.stdin
            cg.sys.stdin = stdin
            try:
                exit_code = cg.main(argv)
            finally:
                cg.sys.stdin = real_stdin
        return exit_code, json.loads(stdout.getvalue())

    def test_exit_zero_on_keep(self) -> None:
        exit_code, result = self._run(
            {"prior_runs": [9, 10, 11], "candidate": 6}, "lower-is-better"
        )
        self.assertEqual(exit_code, cg.KEEP)
        self.assertEqual(result["verdict"], "keep")

    def test_exit_one_on_noise(self) -> None:
        exit_code, result = self._run(
            {"prior_runs": [9, 10, 11], "candidate": 9.5}, "lower-is-better"
        )
        self.assertEqual(exit_code, cg.NOT_KEEP)
        self.assertEqual(result["verdict"], "noise")

    def test_exit_one_on_insufficient_runs(self) -> None:
        exit_code, result = self._run(
            {"prior_runs": [10], "candidate": 5}, "lower-is-better"
        )
        self.assertEqual(exit_code, cg.NOT_KEEP)
        self.assertEqual(result["verdict"], "insufficient_runs")

    def test_reads_from_file(self) -> None:
        import tempfile

        payload = {"prior_runs": [9, 10, 11], "candidate": 6}
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "run.json"
            input_path.write_text(json.dumps(payload), encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = cg.main(
                    ["--input", str(input_path), "--direction", "lower-is-better"]
                )
            result = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, cg.KEEP)
        self.assertEqual(result["verdict"], "keep")


class TestCliUsageErrors(unittest.TestCase):
    def _exit_code_on_stdin(self, text, direction="lower-is-better"):
        stdin = io.StringIO(text)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            real_stdin = cg.sys.stdin
            cg.sys.stdin = stdin
            try:
                return cg.main(["--direction", direction])
            finally:
                cg.sys.stdin = real_stdin

    def test_bad_json_is_a_usage_error(self) -> None:
        self.assertEqual(self._exit_code_on_stdin("not json"), cg.USAGE_ERROR)

    def test_missing_prior_runs_is_a_usage_error(self) -> None:
        self.assertEqual(
            self._exit_code_on_stdin(json.dumps({"candidate": 5})), cg.USAGE_ERROR
        )

    def test_non_numeric_candidate_is_a_usage_error(self) -> None:
        payload = {"prior_runs": [9, 10, 11], "candidate": "fast"}
        self.assertEqual(self._exit_code_on_stdin(json.dumps(payload)), cg.USAGE_ERROR)

    def test_unrecognized_direction_exits_via_argparse(self) -> None:
        # argparse itself enforces `choices=DIRECTIONS` and calls sys.exit(2)
        # before main()'s own body runs.
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                cg.main(["--direction", "sideways"])
        self.assertEqual(raised.exception.code, cg.USAGE_ERROR)


if __name__ == "__main__":
    unittest.main()
