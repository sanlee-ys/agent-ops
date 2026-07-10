#!/usr/bin/env python3
"""Test suite for scripts/check-generated-drift.py.

Each case builds a real throwaway git repo with a deterministic generator
(``gen.py`` copying ``source.txt`` → ``out.txt``) and drives the gate exactly
as CI does: as a subprocess, judged on exit code. The exit-code contract is
the interface — 0 clean, 1 drift, 2 operator/config error — so every case
asserts a specific code, not just "nonzero". The allow case (clean repo →
exit 0) is asserted alongside the block cases for the same reason the
credential-guard suite does it: a gate that cries wolf gets removed from CI.

Stdlib only, same as the sibling suites — bare ``python -m unittest`` in CI.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check-generated-drift.py"

OK = 0
DRIFT = 1
ERROR = 2

GENERATOR = """\
from pathlib import Path
Path("out.txt").write_text("built: " + Path("source.txt").read_text())
"""

CONFIG = """\
[check.site]
build = ["python gen.py"]
watch = ["out.txt"]
"""


def git(repo, *args):
    """Run git isolated from the host's user/system config (no signing hooks,
    no templates) so the tests behave the same on any machine and in CI."""
    env = dict(
        os.environ,
        HOME=str(repo),
        GIT_CONFIG_NOSYSTEM="1",
        GIT_AUTHOR_NAME="t",
        GIT_AUTHOR_EMAIL="t@t",
        GIT_COMMITTER_NAME="t",
        GIT_COMMITTER_EMAIL="t@t",
    )
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args],
        capture_output=True, text=True, env=env, check=True,
    )


def run_gate(repo, *extra):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *extra],
        cwd=repo, capture_output=True, text=True,
    )


class GeneratedDriftTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        (self.repo / "gen.py").write_text(GENERATOR)
        (self.repo / "source.txt").write_text("v1\n")
        (self.repo / ".generated-drift.toml").write_text(CONFIG)
        git(self.repo, "init", "-q")
        # Commit source + a FRESH build of the output, i.e. the honest state
        # the gate is meant to certify.
        subprocess.run([sys.executable, "gen.py"], cwd=self.repo, check=True)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "baseline")

    def test_clean_repo_passes(self):
        proc = run_gate(self.repo)
        self.assertEqual(proc.returncode, OK, proc.stderr + proc.stdout)
        self.assertIn("ok", proc.stdout)

    def test_source_edit_without_rebuild_is_drift(self):
        # The founding failure mode: edit the source, forget the rebuild.
        # source.txt is dirty but NOT watched, so pre-flight must not trip.
        (self.repo / "source.txt").write_text("v2\n")
        proc = run_gate(self.repo)
        self.assertEqual(proc.returncode, DRIFT, proc.stderr + proc.stdout)
        self.assertIn("DRIFT", proc.stdout)
        self.assertIn("out.txt", proc.stdout)

    def test_new_untracked_output_is_drift(self):
        # A generator that grows a new output file the author never committed:
        # plain `git diff` misses untracked files; the gate must not.
        (self.repo / "gen.py").write_text(
            GENERATOR + 'Path("out2.txt").write_text("new artifact")\n'
        )
        (self.repo / ".generated-drift.toml").write_text(
            CONFIG.replace('watch = ["out.txt"]', 'watch = ["out.txt", "out2.txt"]')
        )
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "generator grows an output")
        proc = run_gate(self.repo)
        self.assertEqual(proc.returncode, DRIFT, proc.stderr + proc.stdout)
        self.assertIn("out2.txt", proc.stdout)

    def test_dirty_watched_path_is_operator_error_not_drift(self):
        # A hand-edited output before the gate runs makes drift unattributable;
        # that must be the distinct ERROR code, and no build may run.
        (self.repo / "out.txt").write_text("hand edit\n")
        proc = run_gate(self.repo)
        self.assertEqual(proc.returncode, ERROR, proc.stderr + proc.stdout)
        self.assertIn("before any build", proc.stderr)

    def test_failing_build_is_error_not_drift(self):
        (self.repo / ".generated-drift.toml").write_text(
            CONFIG.replace("python gen.py", "python no_such_script.py")
        )
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "broken build cmd")
        proc = run_gate(self.repo)
        self.assertEqual(proc.returncode, ERROR, proc.stderr + proc.stdout)
        self.assertIn("build command failed", proc.stderr)

    def test_missing_config_is_error(self):
        (self.repo / ".generated-drift.toml").unlink()
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "drop config")
        proc = run_gate(self.repo)
        self.assertEqual(proc.returncode, ERROR, proc.stderr + proc.stdout)
        self.assertIn("no config", proc.stderr)

    def test_config_without_checks_is_error(self):
        (self.repo / ".generated-drift.toml").write_text("# empty\n")
        proc = run_gate(self.repo)
        self.assertEqual(proc.returncode, ERROR, proc.stderr + proc.stdout)
        self.assertIn("no [check.*] tables", proc.stderr)

    def test_multiple_checks_report_each_and_any_drift_fails(self):
        # Second generator/output pair; only the second drifts. Both results
        # must be visible, and the run must still exit DRIFT.
        (self.repo / "gen2.py").write_text(
            'from pathlib import Path\n'
            'Path("out_b.txt").write_text("built: " + '
            'Path("source_b.txt").read_text())\n'
        )
        (self.repo / "source_b.txt").write_text("b1\n")
        subprocess.run([sys.executable, "gen2.py"], cwd=self.repo, check=True)
        (self.repo / ".generated-drift.toml").write_text(
            CONFIG
            + '\n[check.b]\nbuild = ["python gen2.py"]\nwatch = ["out_b.txt"]\n'
        )
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "second check")
        (self.repo / "source_b.txt").write_text("b2\n")
        proc = run_gate(self.repo)
        self.assertEqual(proc.returncode, DRIFT, proc.stderr + proc.stdout)
        self.assertIn("[site] ok", proc.stdout)
        self.assertIn("[b] DRIFT", proc.stdout)


if __name__ == "__main__":
    unittest.main()
