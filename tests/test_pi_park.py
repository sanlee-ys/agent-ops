#!/usr/bin/env python3
"""Tests for vendors/pi/scripts/check-park.py.

Each case uses a throwaway settings file and a throwaway guard pair.
The tests do not read the live ~/.pi tree. The tests do not use secrets.

The CLI exit code is the interface: 0 when every applicable check passed,
1 when any check failed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "vendors"
    / "pi"
    / "scripts"
    / "check-park.py"
)

OK = 0
FAIL = 1

GUARD_BYTES = b"// fixture fleet-guard\n"


def write_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document) + "\n", encoding="utf-8")


class PiParkTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.root = self.tmp / "repo"
        (self.root / "security").mkdir(parents=True)
        (self.root / "security" / "credential-guard.py").write_text(
            "# marker\n", encoding="utf-8"
        )
        self.canonical = (
            self.root / "vendors" / "pi" / "extensions" / "fleet-guard.ts"
        )
        self.canonical.parent.mkdir(parents=True)
        self.canonical.write_bytes(GUARD_BYTES)
        self.deployed = self.tmp / "deployed" / "fleet-guard.ts"
        self.deployed.parent.mkdir(parents=True)
        self.deployed.write_bytes(GUARD_BYTES)
        self.settings = self.tmp / "settings.json"
        write_json(
            self.settings,
            {"defaultProvider": "kimi-coding", "defaultModel": "kimi-k3"},
        )

    def run_check(self, *extra: str, settings=None, deployed=None, env_extra=None):
        env = os.environ.copy()
        env["AGENT_OPS_ROOT"] = str(self.root)
        env.pop("PI_SETTINGS", None)
        if env_extra:
            env.update(env_extra)
        cmd = [sys.executable, str(SCRIPT)]
        settings_path = self.settings if settings is None else settings
        if settings_path is not None:
            cmd.extend(["--settings", str(settings_path)])
        deployed_path = self.deployed if deployed is None else deployed
        if deployed_path is not None:
            cmd.extend(["--deployed", str(deployed_path)])
        cmd.extend(extra)
        return subprocess.run(cmd, capture_output=True, text=True, env=env)

    def test_parked_kimi_settings_pass(self):
        proc = self.run_check()
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        self.assertIn("SETTINGS PARK: PASS", proc.stdout)
        self.assertIn("kimi-coding", proc.stdout)
        self.assertIn("kimi-k3", proc.stdout)

    def test_xai_settings_fail(self):
        write_json(
            self.settings,
            {"defaultProvider": "xai", "defaultModel": "kimi-k3"},
        )
        proc = self.run_check()
        self.assertEqual(proc.returncode, FAIL, proc.stdout + proc.stderr)
        self.assertIn("SETTINGS PARK: FAIL", proc.stdout)
        self.assertIn("xai", proc.stdout)
        self.assertIn("forbidden backend", proc.stdout)

    def test_grok_model_fail(self):
        write_json(
            self.settings,
            {"defaultProvider": "kimi-coding", "defaultModel": "grok-4.5"},
        )
        proc = self.run_check()
        self.assertEqual(proc.returncode, FAIL, proc.stdout + proc.stderr)
        self.assertIn("SETTINGS PARK: FAIL", proc.stdout)
        self.assertIn("grok", proc.stdout)
        self.assertIn("forbidden token", proc.stdout)

    def test_anthropic_provider_fail(self):
        write_json(
            self.settings,
            {"defaultProvider": "anthropic", "defaultModel": "kimi-k3"},
        )
        proc = self.run_check()
        self.assertEqual(proc.returncode, FAIL, proc.stdout + proc.stderr)
        self.assertIn("SETTINGS PARK: FAIL", proc.stdout)
        self.assertIn("anthropic", proc.stdout)
        self.assertIn("forbidden backend", proc.stdout)

    def test_matching_guard_hashes_pass(self):
        write_json(self.settings, {})
        proc = self.run_check()
        self.assertEqual(proc.returncode, OK, proc.stdout + proc.stderr)
        self.assertIn("GUARD COPY DRIFT: PASS", proc.stdout)
        self.assertIn("SHA-256 matches", proc.stdout)
        self.assertIn("SETTINGS PARK: PASS", proc.stdout)

    def test_drifted_guard_bytes_fail(self):
        self.deployed.write_bytes(GUARD_BYTES + b"// drifted\n")
        proc = self.run_check()
        self.assertEqual(proc.returncode, FAIL, proc.stdout + proc.stderr)
        self.assertIn("GUARD COPY DRIFT: FAIL", proc.stdout)
        self.assertIn("differ", proc.stdout)

    def test_missing_canonical_fail(self):
        self.canonical.unlink()
        proc = self.run_check()
        self.assertEqual(proc.returncode, FAIL, proc.stdout + proc.stderr)
        self.assertIn("GUARD COPY DRIFT: FAIL", proc.stdout)
        self.assertIn("canonical file is missing", proc.stdout)

    def test_missing_deployed_fail(self):
        missing = self.tmp / "no-such-deployed.ts"
        proc = self.run_check(deployed=missing)
        self.assertEqual(proc.returncode, FAIL, proc.stdout + proc.stderr)
        self.assertIn("GUARD COPY DRIFT: FAIL", proc.stdout)
        self.assertIn("deployed copy is missing", proc.stdout)


if __name__ == "__main__":
    unittest.main()
