#!/usr/bin/env python3
"""Test suite for security/secret-redaction-guard.py.

Driven as the harness drives it: a PreToolUse JSON payload on stdin. The
redact-and-allow path must return exit 0 with an allow verdict carrying
`updatedInput`; the codex target must deny with the exit-2 backstop. Every
secret in these tests is assembled at runtime so no real-looking token sits
in the source text.

Stdlib only (no pytest) so CI is a bare `python -m unittest`.
"""
import importlib.util
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

GUARD = (
    Path(__file__).resolve().parent.parent / "security" / "secret-redaction-guard.py"
)

_spec = importlib.util.spec_from_file_location("secret_redaction_guard", GUARD)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

AWS_KEY = "AKIA" + "IOSFODNN7EXAMPLE"
GH_PAT = "ghp_" + "aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789"
ANT_KEY = "sk-ant-" + "api03-" + "x" * 24


def run(tool_input, tool_name="Bash", args=(), env_extra=None):
    payload = json.dumps({"tool_name": tool_name, "tool_input": tool_input})
    env = os.environ.copy()
    env.pop("AGENT_OPS_GUARD_SHADOW", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(GUARD), *args], input=payload,
        capture_output=True, text=True, env=env,
    )


class TestRedactAndAllow(unittest.TestCase):
    def test_secret_in_command_is_redacted_and_allowed(self) -> None:
        proc = run({"command": f"curl -H 'x-api-key: {ANT_KEY}' https://x"})
        self.assertEqual(proc.returncode, 0)
        out = json.loads(proc.stdout)
        hso = out["hookSpecificOutput"]
        self.assertEqual(hso["permissionDecision"], "allow")
        self.assertIn("Redacted 1 credential(s)", hso["permissionDecisionReason"])
        self.assertIn("anthropic_api_key", hso["permissionDecisionReason"])
        self.assertNotIn(ANT_KEY, json.dumps(out))
        self.assertIn("[REDACTED:anthropic_api_key]", hso["updatedInput"]["command"])
        # Non-secret context survives the rewrite.
        self.assertIn("curl -H", hso["updatedInput"]["command"])
        self.assertIn("https://x", hso["updatedInput"]["command"])

    def test_nested_tool_input_is_walked(self) -> None:
        proc = run({
            "file_path": "notes.md",
            "content": {"env": [f"export AWS_KEY={AWS_KEY}",
                                f"token={GH_PAT}"]},
        }, tool_name="Write")
        out = json.loads(proc.stdout)
        hso = out["hookSpecificOutput"]
        self.assertIn("Redacted 2 credential(s)", hso["permissionDecisionReason"])
        blob = json.dumps(hso["updatedInput"])
        self.assertNotIn(AWS_KEY, blob)
        self.assertNotIn(GH_PAT, blob)
        self.assertIn("[REDACTED:aws_access_key]", blob)
        self.assertIn("[REDACTED:github_pat]", blob)
        self.assertEqual(hso["updatedInput"]["file_path"], "notes.md")

    def test_reason_names_count_and_types(self) -> None:
        proc = run({"command": f"echo {AWS_KEY} {AWS_KEY}"})
        hso = json.loads(proc.stdout)["hookSpecificOutput"]
        self.assertIn("Redacted 2 credential(s)", hso["permissionDecisionReason"])
        self.assertIn("aws_access_key", hso["permissionDecisionReason"])


class TestCleanPassthrough(unittest.TestCase):
    def test_clean_command_allows_silently(self) -> None:
        proc = run({"command": "git status"})
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "")

    def test_lookalike_prose_is_not_redacted(self) -> None:
        for text in (
            "let access_key_id = 'placeholder'",
            "https://example.com/api/v1/resource",
            "AKIA_PREFIX_IS_NOT_A_KEY_HERE",
            "docs mention sk-ant keys in general terms",
        ):
            proc = run({"command": text})
            self.assertEqual(proc.stdout.strip(), "", text)

    def test_markers_are_idempotent(self) -> None:
        marked = "curl -u user:[REDACTED:connection_string]@host " \
                 "[REDACTED:aws_access_key]"
        proc = run({"command": marked})
        self.assertEqual(proc.stdout.strip(), "", "marker text was re-redacted")


class TestPatternsUnit(unittest.TestCase):
    def test_connection_string_password_only(self) -> None:
        text = "postgres://admin:supersecret@db.example.com:5432/prod"
        redacted, found = mod.redact_text(text)
        self.assertEqual(found, ["connection_string"])
        self.assertIn("admin:[REDACTED:connection_string]@db.example.com", redacted)

    def test_private_key_block(self) -> None:
        # Assembled at runtime so no key-block literal sits in this source.
        marker = "PRIVATE KEY-----"
        key = (f"-----BEGIN OPENSSH {marker}\nabc\ndef\n"
               f"-----END OPENSSH {marker}")
        redacted, found = mod.redact_text(f"before\n{key}\nafter")
        self.assertEqual(found, ["private_key_block"])
        self.assertIn("before", redacted)
        self.assertIn("after", redacted)
        self.assertNotIn("OPENSSH", redacted)

    def test_jwt(self) -> None:
        jwt = "eyJ" + "a" * 12 + ".eyJ" + "b" * 12 + "." + "c" * 12
        _, found = mod.redact_text(f"Authorization: Bearer {jwt}")
        self.assertEqual(found, ["jwt"])


class TestCodexTarget(unittest.TestCase):
    def test_finding_denies_with_exit_2(self) -> None:
        proc = run({"command": f"echo {AWS_KEY}"}, args=("--target", "codex"))
        self.assertEqual(proc.returncode, 2)
        out = json.loads(proc.stdout)
        self.assertEqual(
            out["hookSpecificOutput"]["permissionDecision"], "deny"
        )
        self.assertIn("Redacted 1 credential(s)", proc.stderr)

    def test_clean_input_allows(self) -> None:
        proc = run({"command": "git status"}, args=("--target", "codex"))
        self.assertEqual(proc.returncode, 0)


class TestShadowMode(unittest.TestCase):
    def test_shadow_logs_types_never_values(self) -> None:
        proc = run({"command": f"echo {AWS_KEY}"},
                   env_extra={"AGENT_OPS_GUARD_SHADOW": "1"})
        self.assertEqual(proc.returncode, 0)
        self.assertIn("would redact", proc.stderr)
        self.assertIn("aws_access_key", proc.stderr)
        self.assertNotIn(AWS_KEY, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "")


class TestFailOpen(unittest.TestCase):
    def test_unparseable_payload_allows(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(GUARD)], input="not json",
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
