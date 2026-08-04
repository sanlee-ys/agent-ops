#!/usr/bin/env python3
"""Cursor (cursor-agent) compatibility tests for the three canonical guards.

cursor-agent auto-imports Claude Code hooks from ~/.claude/settings.json and
drives them differently from Claude Code in three measured ways (Windows,
cursor-agent 2026.07.23-e383d2b; see vendors/cursor/README.md "Guard wiring"):

  1. its PowerShell payload wrapper pipes stdin with a leading UTF-8 BOM —
     a text-stream json.load raised on it and every guard FAILED OPEN;
  2. its shell tool is named "Shell", not Bash/PowerShell, so name-gated
     command checks never ran;
  3. it treats an empty-stdout hook run as failed, and imports hooks with
     failClosed hardcoded false — so a silent allow was recorded as a failed
     hook and silently allowed. An explicit {"permission": "allow"} makes the
     allow a measured success.

These tests pin the TRANSLATION, not the redlines — the rules themselves are
owned by test_credential_guard.py and friends. What is asserted: a BOM-wrapped
payload still parses (deny still denies), "Shell" commands are checked, a
Cursor allow prints the explicit verdict, and a Claude Code allow still prints
NOTHING (Claude Code's stdout contract is unchanged).

No real secret values appear here; fixtures reference sensitive paths only.
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CREDENTIAL = REPO / "security" / "credential-guard.py"
STAGING = REPO / "hooks" / "git-staging-guard.py"
HISTORY = REPO / "hooks" / "published-history-guard.py"

CURSOR_EXTRAS = {
    "cursor_version": "2026.07.23-e383d2b",
    "hook_event_name": "preToolUse",
    "session_id": "00000000-0000-0000-0000-000000000000",
}

BLOCK, ALLOW = 2, 0


def run_guard(guard: Path, payload: dict, bom: bool = False):
    """Drive a guard as a harness does: JSON on stdin, exit code back.
    `bom=True` reproduces cursor-agent's Windows PowerShell wrapper, which
    prepends a UTF-8 BOM to the piped payload. Returns (returncode, stdout)."""
    raw = json.dumps(payload).encode("utf-8")
    if bom:
        raw = b"\xef\xbb\xbf" + raw
    proc = subprocess.run(
        [sys.executable, str(guard)], input=raw, capture_output=True
    )
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


def cursor_payload(tool_name: str, tool_input: dict) -> dict:
    return {"tool_name": tool_name, "tool_input": tool_input, **CURSOR_EXTRAS}


class TestBomToleratedDenyStillDenies(unittest.TestCase):
    """The BOM made every guard fail open. With it stripped, the deny that
    should have fired on 2026-08-04 (a Read of a .env fixture sailed through)
    fires."""

    def test_credential_guard_read_env_with_bom(self) -> None:
        code, _ = run_guard(
            CREDENTIAL,
            cursor_payload("Read", {"file_path": "C:\\ws\\.env"}),
            bom=True,
        )
        self.assertEqual(code, BLOCK)

    def test_staging_guard_shell_add_all_with_bom(self) -> None:
        code, _ = run_guard(
            STAGING, cursor_payload("Shell", {"command": "git add -A"}), bom=True
        )
        self.assertEqual(code, BLOCK)

    def test_claude_payload_without_bom_unchanged(self) -> None:
        code, _ = run_guard(
            CREDENTIAL, {"tool_name": "Read", "tool_input": {"file_path": "~/.env"}}
        )
        self.assertEqual(code, BLOCK)


class TestShellToolNameChecked(unittest.TestCase):
    """Cursor's single shell tool must get the same command checks as
    Bash/PowerShell."""

    def test_credential_guard_shell_reads_env(self) -> None:
        code, _ = run_guard(
            CREDENTIAL, cursor_payload("Shell", {"command": "cat ~/.env"})
        )
        self.assertEqual(code, BLOCK)

    def test_staging_guard_shell_whole_tree(self) -> None:
        code, _ = run_guard(
            STAGING, cursor_payload("Shell", {"command": "git commit -am 'x'"})
        )
        self.assertEqual(code, BLOCK)

    def test_shell_benign_command_allowed(self) -> None:
        code, _ = run_guard(STAGING, cursor_payload("Shell", {"command": "ls"}))
        self.assertEqual(code, ALLOW)

    def test_history_guard_shell_name_accepted(self) -> None:
        """A benign Shell command passes through the history guard's name gate
        (its push/reset verdicts need a live remote, owned by its own tests)."""
        code, _ = run_guard(
            HISTORY, cursor_payload("Shell", {"command": "git status"})
        )
        self.assertEqual(code, ALLOW)


class TestAllowVerdictDialect(unittest.TestCase):
    """A Cursor allow prints the explicit verdict; a Claude Code allow prints
    nothing. Both halves are load-bearing: Cursor records empty stdout as a
    failed hook (and imported hooks fail open), while Claude Code's contract
    is bare exit 0."""

    def test_cursor_allow_prints_verdict(self) -> None:
        for guard, payload in (
            (CREDENTIAL, cursor_payload("Read", {"file_path": "C:\\ws\\notes.txt"})),
            (CREDENTIAL, cursor_payload("Shell", {"command": "ls"})),
            (STAGING, cursor_payload("Shell", {"command": "git add src/x.py"})),
            (HISTORY, cursor_payload("Shell", {"command": "git status"})),
        ):
            code, out = run_guard(guard, payload, bom=True)
            self.assertEqual(code, ALLOW)
            self.assertEqual(json.loads(out), {"permission": "allow"})

    def test_claude_allow_prints_nothing(self) -> None:
        for guard, payload in (
            (CREDENTIAL, {"tool_name": "Read", "tool_input": {"file_path": "x.txt"}}),
            (STAGING, {"tool_name": "Bash", "tool_input": {"command": "git add x"}}),
            (HISTORY, {"tool_name": "Bash", "tool_input": {"command": "git status"}}),
        ):
            code, out = run_guard(guard, payload)
            self.assertEqual(code, ALLOW)
            self.assertEqual(out, "")

    def test_cursor_deny_is_exit_2_with_stderr(self) -> None:
        """Deny needs no dialect: cursor maps exit 2 + stderr to a block, and
        the message must survive so the agent sees why."""
        raw = b"\xef\xbb\xbf" + json.dumps(
            cursor_payload("Read", {"file_path": "C:\\ws\\.env"})
        ).encode("utf-8")
        proc = subprocess.run(
            [sys.executable, str(CREDENTIAL)], input=raw, capture_output=True
        )
        self.assertEqual(proc.returncode, BLOCK)
        self.assertIn(b"CREDENTIAL GUARD", proc.stderr)


class TestUnparseableStillFailsOpenSilently(unittest.TestCase):
    """The fail-open posture on garbage input is unchanged — and stays silent
    (no verdict can be voiced for a payload whose dialect is unknown)."""

    def test_garbage_payload(self) -> None:
        for guard in (CREDENTIAL, STAGING, HISTORY):
            proc = subprocess.run(
                [sys.executable, str(guard)], input=b"not json", capture_output=True
            )
            self.assertEqual(proc.returncode, ALLOW)
            self.assertEqual(proc.stdout, b"")


if __name__ == "__main__":
    unittest.main()
