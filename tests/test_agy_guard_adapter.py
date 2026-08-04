#!/usr/bin/env python3
"""Tests for vendors/gemini/hooks/agy-guard-adapter.py.

The adapter is a translator, so these tests are about the TRANSLATION and the
FAILURE POSTURE, not about the redlines themselves — those are owned by
tests/test_credential_guard.py and friends, and duplicating a rule here would
be the same drift mistake the adapter exists to avoid (posture.md limit #6).
What is asserted here:

  1. a redline the canonical guard blocks comes back as a `deny` on this
     contract too, for the shell shape AND the file-field shape;
  2. the cases that must keep working — existence checks, ordinary files,
     prose mentioning a credential filename, the per-guard overrides — come
     back as a pass;
  3. a pass prints NOTHING. This is the load-bearing one. Antigravity reads a
     well-formed response with no `decision` as a DENY, so an adapter that
     helpfully emitted `{}` would block every tool call in the session; and
     `{"decision": "allow"}` would auto-approve past the permission reviewer.
     Both were measured on 2026-08-04;
  4. an unrunnable check denies rather than passing.

No real secret values appear here. The guards key on paths and command shapes,
so the fixtures reference sensitive *paths* and fake variable *names*.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ADAPTER = REPO / "vendors" / "gemini" / "hooks" / "agy-guard-adapter.py"


def run_adapter(payload, script=ADAPTER, env=None):
    """Drive the adapter exactly as Antigravity does: JSON on stdin, JSON (or
    nothing) on stdout. Returns (returncode, stdout)."""
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.returncode, proc.stdout


def tool_call(name, args, **extra):
    """An Antigravity PreToolUse payload, with the common fields it always
    carries (camelCase — protojson) so the fixtures match what was observed."""
    payload = {
        "conversationId": "00000000-0000-0000-0000-000000000000",
        "modelName": "gemini-3.6-flash-high",
        "stepIdx": 3,
        "toolCall": {"name": name, "args": args},
        "workspacePaths": [],
    }
    payload.update(extra)
    return payload


class AdapterTestCase(unittest.TestCase):
    def assertDenied(self, payload, msg=""):
        code, out = run_adapter(payload)
        self.assertEqual(code, 0, "the adapter must always exit 0; the verdict "
                                  "is in stdout, and a non-zero exit is read as "
                                  "a hook failure and fails OPEN")
        self.assertTrue(out.strip(), f"expected a deny, got no output: {msg or payload}")
        body = json.loads(out)
        self.assertEqual(body.get("decision"), "deny", msg or payload)
        self.assertTrue(body.get("reason", "").strip(),
                        "a deny with an empty reason teaches the agent nothing")
        return body

    def assertPassed(self, payload, msg=""):
        code, out = run_adapter(payload)
        self.assertEqual(code, 0, msg or payload)
        # NOT `{}`; NOT `{"decision": "allow"}`. See the module docstring.
        self.assertEqual(out, "", f"a pass must print nothing: {msg or payload}")

    def cmd(self, command, **args):
        return tool_call("run_command", {"CommandLine": command, **args})


class TestShellRedlines(AdapterTestCase):
    """run_command carries a command line, so it maps onto the guards' Bash shape."""

    def test_credential_read_is_denied(self):
        self.assertDenied(self.cmd("cat ~/.env"))
        self.assertDenied(self.cmd("type C:/tmp/decoy/.env"))
        self.assertDenied(self.cmd("python3 -c \"print(open('~/.claude.json').read())\""))

    def test_env_var_exposure_is_denied(self):
        # The 2026-07-02 founding incident's shape, reaching this lane.
        self.assertDenied(self.cmd("printenv ANTHROPIC_API_KEY"))
        self.assertDenied(self.cmd("echo $GITHUB_TOKEN"))
        self.assertDenied(self.cmd("env"))

    def test_private_key_read_is_denied(self):
        self.assertDenied(self.cmd("cat ~/.ssh/id_ed25519"))

    def test_whole_tree_staging_is_denied(self):
        # git-staging-guard reaches this lane through the same mapping.
        self.assertDenied(self.cmd("git add -A"))
        self.assertDenied(self.cmd("git -C /repo commit -am 'wip'"))

    def test_deny_reason_carries_the_guard_message(self):
        body = self.assertDenied(self.cmd("cat ~/.env"))
        self.assertIn("CREDENTIAL GUARD", body["reason"])
        body = self.assertDenied(self.cmd("git add -A"))
        self.assertIn("GIT STAGING GUARD", body["reason"])


class TestShellAllowed(AdapterTestCase):
    """The false-positive discipline the guards were built with has to survive
    the translation, or the guard gets routed around here exactly as it would
    in Claude Code."""

    def test_existence_checks_pass(self):
        self.assertPassed(self.cmd("Test-Path ~/.env"))
        self.assertPassed(self.cmd("ls -la ~/.ssh"))
        self.assertPassed(self.cmd("stat ~/.env"))
        self.assertPassed(self.cmd("grep -l TOKEN ~/.env"))

    def test_ordinary_commands_pass(self):
        self.assertPassed(self.cmd("npm test"))
        self.assertPassed(self.cmd("git status"))
        self.assertPassed(self.cmd("cat README.md"))

    def test_prose_mentioning_a_credential_file_passes(self):
        self.assertPassed(self.cmd('git commit -m "chore: add .env to .gitignore"'))
        self.assertPassed(self.cmd("echo 'remember to gitignore .env'"))

    def test_dotenv_template_passes(self):
        self.assertPassed(self.cmd("cat .env.example"))

    def test_overrides_reach_the_guards_untouched(self):
        # The adapter knows nothing about these tokens; they ride through in the
        # command string, which is the point.
        self.assertPassed(self.cmd("cat ~/.env  # MASK-OK"))
        self.assertPassed(self.cmd("STAGE-ALL-OK git add -A"))

    def test_file_deletion_is_not_a_read(self):
        self.assertPassed(self.cmd("rm ~/.env.bak"))


class TestFileFieldTools(AdapterTestCase):
    """Every non-shell tool is handed over as-is and judged by the guard's
    path-field scan — the tool-shape-agnostic default-deny. A reader Antigravity
    adds tomorrow is covered without an edit here."""

    def test_view_file_on_a_credential_store_is_denied(self):
        self.assertDenied(tool_call("view_file", {"AbsolutePath": "~/.aws/credentials"}))
        self.assertDenied(tool_call("view_file", {"AbsolutePath": "/home/x/.env"}))

    def test_view_file_on_an_ordinary_file_passes(self):
        self.assertPassed(tool_call("view_file", {"AbsolutePath": "C:/repo/README.md"}))

    def test_unknown_reader_tool_is_covered(self):
        # Not in any list the adapter holds; caught structurally by the field scan.
        self.assertDenied(tool_call("some_future_reader", {"TargetFile": "~/.npmrc"}))

    def test_write_to_a_credential_store_is_denied(self):
        # Overwriting a key store is as bad an outcome as printing it.
        self.assertDenied(tool_call("write_to_file",
                                    {"TargetFile": "~/.ssh/id_rsa", "Content": "x"}))

    def test_public_key_is_not_a_secret(self):
        self.assertPassed(tool_call("view_file", {"AbsolutePath": "~/.ssh/id_ed25519.pub"}))

    def test_listing_and_search_pass(self):
        self.assertPassed(tool_call("list_dir", {"DirectoryPath": "C:/repo"}))
        self.assertPassed(tool_call("search_web", {"query": "what is a .env file"}))

    def test_agy_tool_names_cannot_borrow_claude_tool_semantics(self):
        """`Grep` in the guard means Claude Code's Grep, whose output_mode
        nuance lets an existence check through. An Antigravity tool that happens
        to share a name has different args, so inheriting that nuance would be a
        silent hole. The adapter namespaces every non-shell tool to prevent it."""
        self.assertDenied(tool_call("Grep", {"path": "~/.env", "output_mode": "content"}))
        self.assertDenied(tool_call("Glob", {"path": "~/.env"}))


class TestPayloadHandling(AdapterTestCase):
    """Nothing to judge is a pass; it is not a failed check."""

    def test_no_tool_call_passes(self):
        self.assertPassed({"conversationId": "x", "stepIdx": 1})

    def test_empty_args_pass(self):
        self.assertPassed(tool_call("list_permissions", {}))

    def test_unparseable_stdin_passes(self):
        proc = subprocess.run([sys.executable, str(ADAPTER)], input="not json{",
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "")

    def test_alternate_command_key_is_found(self):
        self.assertDenied(tool_call("shell_exec", {"command": "cat ~/.env"}))

    def test_cwd_falls_back_to_workspace_paths(self):
        payload = tool_call("run_command", {"CommandLine": "git status"},
                            workspacePaths=[str(REPO)])
        self.assertPassed(payload)


class TestFailsClosed(AdapterTestCase):
    """Antigravity fails OPEN when a hook errors, so a broken guard is
    indistinguishable from no guard. The adapter inverts that for the failures
    it can see."""

    def _adapter_outside_repo(self, tmp):
        """A copy of the adapter with no agent-ops checkout above it, so the
        walk-up resolution genuinely fails."""
        target = Path(tmp) / "nowhere" / "agy-guard-adapter.py"
        target.parent.mkdir(parents=True)
        shutil.copy(ADAPTER, target)
        return target

    def test_missing_checkout_denies(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = self._adapter_outside_repo(tmp)
            env = {k: v for k, v in os.environ.items() if k != "AGENT_OPS_ROOT"}
            code, out = run_adapter(self.cmd("echo hi"), script=script, env=env)
            self.assertEqual(code, 0)
            body = json.loads(out)
            self.assertEqual(body["decision"], "deny")
            self.assertIn("could not be found", body["reason"])

    def test_missing_guard_file_denies(self):
        """A checkout that resolves but has lost a guard script must not pass
        the call through — the redline that guard owns went unchecked."""
        with tempfile.TemporaryDirectory() as tmp:
            script = self._adapter_outside_repo(tmp)
            fake_root = Path(tmp) / "root"
            (fake_root / "security").mkdir(parents=True)
            # Only the marker exists; hooks/git-staging-guard.py is absent.
            shutil.copy(REPO / "security" / "credential-guard.py",
                        fake_root / "security" / "credential-guard.py")
            env = dict(os.environ, AGENT_OPS_ROOT=str(fake_root))
            code, out = run_adapter(self.cmd("echo hi"), script=script, env=env)
            self.assertEqual(code, 0)
            body = json.loads(out)
            self.assertEqual(body["decision"], "deny")
            self.assertIn("git-staging-guard", body["reason"])

    def test_agent_ops_root_env_override_is_honoured(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = self._adapter_outside_repo(tmp)
            env = dict(os.environ, AGENT_OPS_ROOT=str(REPO))
            code, out = run_adapter(self.cmd("cat ~/.env"), script=script, env=env)
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)["decision"], "deny")
            code, out = run_adapter(self.cmd("npm test"), script=script, env=env)
            self.assertEqual(out, "", "the override must allow as well as deny")


class TestReferenceConfig(unittest.TestCase):
    """The versioned hooks.json is a deployable artifact, not decoration."""

    CONFIG = REPO / "vendors" / "gemini" / "hooks.json"

    def test_is_valid_json_and_wires_the_adapter(self):
        config = json.loads(self.CONFIG.read_text(encoding="utf-8"))
        entry = config["fleet-guards"]["PreToolUse"][0]
        self.assertEqual(entry["matcher"], "*", "the guard must see every tool")
        handler = entry["hooks"][0]
        self.assertEqual(handler["type"], "command")
        self.assertIn("agy-guard-adapter.py", handler["command"])

    def test_command_path_is_unquoted(self):
        """Quotes are passed through literally rather than consumed by a shell,
        so a quoted path fails to launch — and a hook that fails to launch is a
        hook that silently is not there."""
        command = json.loads(self.CONFIG.read_text(encoding="utf-8"))[
            "fleet-guards"]["PreToolUse"][0]["hooks"][0]["command"]
        self.assertNotIn('"', command)

    def test_no_local_user_path(self):
        """This repo is public; the reference config must be genericized."""
        text = self.CONFIG.read_text(encoding="utf-8")
        self.assertNotIn("C:/Users", text)
        self.assertNotIn("C:\\\\Users", text)

    def test_no_stray_top_level_keys(self):
        """Every top-level key is a hook NAME, so there is no comment mechanism
        — and a stray one is not ignored. A `_comment` array made the CLI report
        `cannot unmarshal array into ... JSONHookSpec` and load ZERO hooks from
        the file, while the session carried on unguarded with nothing but a log
        line to say so (measured 2026-08-04). One decorative key silently
        removes every guard in the file, so assert the shape."""
        config = json.loads(self.CONFIG.read_text(encoding="utf-8"))
        allowed = {"enabled", "PreToolUse", "PostToolUse", "PreInvocation",
                   "PostInvocation", "Stop"}
        for name, spec in config.items():
            self.assertIsInstance(spec, dict, f"{name} is not a hook spec")
            self.assertTrue(set(spec) <= allowed,
                            f"{name} carries unknown keys: {set(spec) - allowed}")

    def test_timeout_clears_the_adapter_worst_case(self):
        """A hook timeout is an error, and an errored hook fails OPEN. The
        adapter's own fail-closed deny only wins if it gets to run first."""
        handler = json.loads(self.CONFIG.read_text(encoding="utf-8"))[
            "fleet-guards"]["PreToolUse"][0]["hooks"][0]
        self.assertGreaterEqual(handler["timeout"], 135)


if __name__ == "__main__":
    unittest.main()
