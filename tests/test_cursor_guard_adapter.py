#!/usr/bin/env python3
"""Tests for vendors/cursor/hooks/cursor-guard-adapter.py.

The adapter is a translator for Cursor PreToolUse hook events, translating
Cursor tool calls (Shell, ReadFile, WriteFile, EditFile, etc.) into canonical
Claude Code PreToolUse payloads, executing redline guards sequentially, and
enforcing a fail-closed posture.

What is asserted here:
  1. Cursor tool calls (Shell, ReadFile, WriteFile, EditFile) reaching redlines
     are denied with exit code 2 and a JSON deny body.
  2. Safe tool calls pass cleanly.
  3. Windows UTF-8 BOM on stdin is parsed cleanly and redlines still deny.
  4. Cursor payloads carrying `cursor_version` return explicit {"permission": "allow"}.
  5. Fail-closed posture: missing repo root, missing guard script, or guard crashes
     result in explicit denial.
  6. Reference configuration in vendors/cursor/hooks/hooks.json is valid and deployable.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ADAPTER = REPO / "vendors" / "cursor" / "hooks" / "cursor-guard-adapter.py"
CREDENTIAL_GUARD = REPO / "security" / "credential-guard.py"
HOOKS_CONFIG = REPO / "vendors" / "cursor" / "hooks" / "hooks.json"


def run_adapter(payload, script=ADAPTER, env=None, bom=False):
    """Drive the adapter as Cursor / cursor-agent does.
    Returns (returncode, stdout, stderr).
    """
    if isinstance(payload, bytes):
        raw = payload
    elif isinstance(payload, str):
        raw = payload.encode("utf-8")
    else:
        raw = json.dumps(payload).encode("utf-8")
    if bom:
        raw = b"\xef\xbb\xbf" + raw

    proc = subprocess.run(
        [sys.executable, str(script)],
        input=raw,
        capture_output=True,
        env=env,
    )
    return proc.returncode, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace")


def cursor_payload(name, tool_input, **extra):
    """Standard Cursor PreToolUse event payload (supporting snake_case & camelCase)."""
    payload = {
        "hook_event_name": "preToolUse",
        "session_id": "00000000-0000-0000-0000-000000000000",
        "cwd": "C:/repo",
        "workspace_root": "C:/repo",
        "tool_name": name,
        "tool_input": tool_input,
        "cursor_version": "2026.07.23-e383d2b",
    }
    payload.update(extra)
    return payload


class AdapterTestCase(unittest.TestCase):
    def assertDenied(self, payload, msg="", bom=False, script=ADAPTER, env=None):
        code, out, err = run_adapter(payload, script=script, env=env, bom=bom)
        self.assertEqual(code, 2, f"expected exit code 2 (deny): {msg or payload}\nstdout: {out}\nstderr: {err}")
        self.assertTrue(out.strip() or err.strip(), f"expected deny message: {msg or payload}")
        if out.strip():
            body = json.loads(out)
            self.assertEqual(body.get("decision"), "deny", msg or payload)
            self.assertTrue(body.get("reason", "").strip(), "deny reason should not be empty")
            return body
        return {}

    def assertPassed(self, payload, msg="", bom=False, script=ADAPTER, env=None):
        code, out, err = run_adapter(payload, script=script, env=env, bom=bom)
        self.assertEqual(code, 0, f"expected exit code 0 (allow): {msg or payload}\nstderr: {err}")
        return out


class TestShellRedlines(AdapterTestCase):
    """Shell tool calls map to canonical Bash commands and check redlines."""

    def test_credential_read_denied(self):
        self.assertDenied(cursor_payload("Shell", {"command": "cat ~/.env"}))
        self.assertDenied(cursor_payload("Shell", {"command": "type C:/tmp/decoy/.env"}))

    def test_env_var_exposure_denied(self):
        self.assertDenied(cursor_payload("Shell", {"command": "printenv ANTHROPIC_API_KEY"}))
        self.assertDenied(cursor_payload("Shell", {"command": "echo $GITHUB_TOKEN"}))

    def test_private_key_read_denied(self):
        self.assertDenied(cursor_payload("Shell", {"command": "cat ~/.ssh/id_rsa"}))

    def test_staging_redline_denied(self):
        self.assertDenied(cursor_payload("Shell", {"command": "git commit -am 'quick fix'"}))

    def test_benign_shell_command_passed(self):
        out = self.assertPassed(cursor_payload("Shell", {"command": "ls"}))
        self.assertEqual(json.loads(out), {"permission": "allow"})

    def test_dotenv_example_passed(self):
        self.assertPassed(cursor_payload("Shell", {"command": "cat .env.example"}))

    def test_override_mask_ok_passed(self):
        self.assertPassed(cursor_payload("Shell", {"command": "cat ~/.env # MASK-OK"}))


class TestFileFieldTools(AdapterTestCase):
    """ReadFile, WriteFile, EditFile, and other file-path tools."""

    def test_read_file_on_credential_denied(self):
        self.assertDenied(cursor_payload("ReadFile", {"path": "~/.aws/credentials"}))
        self.assertDenied(cursor_payload("ReadFile", {"file_path": "/home/x/.env"}))

    def test_read_file_on_ordinary_file_passed(self):
        out = self.assertPassed(cursor_payload("ReadFile", {"path": "C:/repo/README.md"}))
        self.assertEqual(json.loads(out), {"permission": "allow"})

    def test_write_file_on_credential_denied(self):
        self.assertDenied(cursor_payload("WriteFile", {"file_path": "~/.ssh/id_rsa", "content": "x"}))
        self.assertDenied(cursor_payload("WriteFile", {"path": "C:/ws/.env", "contents": "SECRET=1"}))

    def test_edit_file_on_credential_denied(self):
        self.assertDenied(cursor_payload("EditFile", {"target_file": "~/.env", "edits": []}))

    def test_public_key_read_passed(self):
        self.assertPassed(cursor_payload("ReadFile", {"path": "~/.ssh/id_ed25519.pub"}))

    def test_camel_case_tool_payload_supported(self):
        payload = {
            "hookEventName": "preToolUse",
            "toolName": "ReadFile",
            "toolInput": {"path": "~/.env"},
            "cursor_version": "2026.07.23",
        }
        self.assertDenied(payload)


class TestBomAndPayloadHandling(AdapterTestCase):
    """Windows UTF-8 BOM and payload edge cases."""

    def test_utf8_bom_stdin_handled(self):
        self.assertDenied(cursor_payload("Shell", {"command": "cat ~/.env"}), bom=True)
        out = self.assertPassed(cursor_payload("Shell", {"command": "ls"}), bom=True)
        self.assertEqual(json.loads(out), {"permission": "allow"})

    def test_cursor_version_returns_explicit_allow(self):
        out = self.assertPassed(cursor_payload("Shell", {"command": "ls"}))
        self.assertEqual(json.loads(out), {"permission": "allow"})

    def test_payload_without_cursor_version_returns_empty_stdout(self):
        payload = {"tool_name": "Shell", "tool_input": {"command": "ls"}}
        out = self.assertPassed(payload)
        self.assertEqual(out, "")

    def test_unparseable_stdin_passes(self):
        code, out, _ = run_adapter("not json{")
        self.assertEqual(code, 0)
        self.assertEqual(out, "")


class TestFailsClosed(AdapterTestCase):
    """Verify fail-closed behavior on missing repo root or missing guard file."""

    def _adapter_outside_repo(self, tmp):
        target = Path(tmp) / "nowhere" / "cursor-guard-adapter.py"
        target.parent.mkdir(parents=True)
        shutil.copy(ADAPTER, target)
        return target

    def test_missing_checkout_denies(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = self._adapter_outside_repo(tmp)
            env = {k: v for k, v in os.environ.items() if k != "AGENT_OPS_ROOT"}
            code, out, err = run_adapter(cursor_payload("Shell", {"command": "echo hi"}), script=script, env=env)
            self.assertEqual(code, 2)
            self.assertIn("could not be found", out + err)

    def test_missing_guard_file_denies(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = self._adapter_outside_repo(tmp)
            fake_root = Path(tmp) / "root"
            (fake_root / "security").mkdir(parents=True)
            shutil.copy(CREDENTIAL_GUARD, fake_root / "security" / "credential-guard.py")
            env = dict(os.environ, AGENT_OPS_ROOT=str(fake_root))
            code, out, err = run_adapter(cursor_payload("Shell", {"command": "echo hi"}), script=script, env=env)
            self.assertEqual(code, 2)
            self.assertIn("git-staging-guard", out + err)

    def test_agent_ops_root_override_honored(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = self._adapter_outside_repo(tmp)
            env = dict(os.environ, AGENT_OPS_ROOT=str(REPO))
            self.assertDenied(cursor_payload("Shell", {"command": "cat ~/.env"}), script=script, env=env)
            self.assertPassed(cursor_payload("Shell", {"command": "ls"}), script=script, env=env)


class TestReferenceConfig(unittest.TestCase):
    """Verify reference hooks.json file."""

    def test_config_structure_and_timeout(self):
        self.assertTrue(HOOKS_CONFIG.is_file(), "vendors/cursor/hooks/hooks.json must exist")
        data = json.loads(HOOKS_CONFIG.read_text(encoding="utf-8"))
        groups = data.get("hooks", {}).get("PreToolUse", [])
        self.assertEqual(len(groups), 1)
        handler = groups[0]["hooks"][0]
        self.assertEqual(handler["type"], "command")
        self.assertIn("cursor-guard-adapter.py", handler["command"])
        self.assertGreaterEqual(handler["timeout"], 135)


if __name__ == "__main__":
    unittest.main()
