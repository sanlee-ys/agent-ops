#!/usr/bin/env python3
"""Tests for vendors/pi/hooks/pi-guard-adapter.py.

The adapter is a translator. These tests assert TRANSLATION and FAILURE
POSTURE. They do not restate the redline rules. Those rules belong to
tests/test_credential_guard.py and the sibling guard tests. A copied rule
here would be the same drift that the adapter exists to avoid
(posture.md limit 6).

What these tests assert:

  1. THE DEFECT. Fed Pi's own documented stdin envelope, the canonical
     guard allows a credential read. That is why this adapter exists.
  2. A redline the canonical guard blocks comes back as a deny on Pi's
     contract, for the shell shape and the file-field shape.
  3. The cases that must keep working come back as a pass. A pass never
     emits {"decision": "allow"}. An explicit allow is an approval.
  4. An unrunnable check denies rather than passing.
  5. Non-shell Pi tools are namespaced as pi:<name>, so they do not
     inherit Claude tool semantics.

No real secret values appear here. The guards key on paths and command
shapes, so the fixtures use sensitive paths and fake variable names.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ADAPTER = REPO / "vendors" / "pi" / "hooks" / "pi-guard-adapter.py"
CREDENTIAL_GUARD = REPO / "security" / "credential-guard.py"


def _load_adapter_module():
    spec = importlib.util.spec_from_file_location("pi_guard_adapter", ADAPTER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


ADAPTER_MOD = _load_adapter_module()


def run_adapter(payload, script=ADAPTER, env=None):
    """Drive the adapter as the TypeScript extension does.

    JSON on stdin. A deny is exit 2 plus a reason on stdout.
    Returns (returncode, stdout).
    """
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.returncode, proc.stdout


def tool_call(name, tool_input, **extra):
    """A Pi tool_call payload in the documented shape."""
    payload = {
        "toolName": name,
        "toolCallId": "tc_0",
        "input": tool_input,
        "cwd": "C:/repo",
    }
    payload.update(extra)
    return payload


def ts_envelope(name, tool_input, **extra):
    """The dual-key object the TypeScript extension writes."""
    payload = {
        "toolName": name,
        "tool_name": name,
        "toolCallId": "tc_0",
        "input": tool_input,
        "toolInput": tool_input,
        "tool_input": tool_input,
        "cwd": "C:/repo",
    }
    payload.update(extra)
    return payload


class TestTheDefectThisAdapterExistsFor(unittest.TestCase):
    """Pi sends toolName/input. The guards read tool_name/tool_input.

    Against the raw Pi envelope both keys come back empty, no branch
    matches, and the guard exits 0. That is a silent no-op.

    If this test ever fails, the premise changed. A guard learned Pi's
    dialect. Re-derive the wiring. Do not patch around it.
    """

    def _guard(self, payload):
        proc = subprocess.run(
            [sys.executable, str(CREDENTIAL_GUARD)],
            input=json.dumps(payload), capture_output=True, text=True,
        )
        return proc.returncode

    def test_pi_envelope_is_a_silent_no_op_for_the_raw_guard(self):
        native = tool_call("bash", {"command": "cat ~/.env"})
        self.assertEqual(self._guard(native), 0,
                         "premise changed: the raw guard now judges Pi's "
                         "envelope; re-derive the wiring rather than patching")

    def test_the_same_command_blocks_in_claude_dialect(self):
        snake = {"tool_name": "Bash", "tool_input": {"command": "cat ~/.env"}}
        self.assertEqual(self._guard(snake), 2,
                         "control case: identical command, snake_case payload")


class TestTranslate(unittest.TestCase):
    """Assert the mapping. Do not assert the redline rules."""

    def test_shell_tools_are_only_bash_and_shell(self):
        self.assertEqual(ADAPTER_MOD._SHELL_TOOLS, {"bash", "shell"})

    def test_bash_maps_to_claude_bash(self):
        claude, is_shell = ADAPTER_MOD._translate(
            tool_call("bash", {"command": "git status"}))
        self.assertTrue(is_shell)
        self.assertEqual(claude["tool_name"], "Bash")
        self.assertEqual(claude["tool_input"]["command"], "git status")
        self.assertEqual(claude["cwd"], "C:/repo")

    def test_shell_maps_to_claude_bash(self):
        claude, is_shell = ADAPTER_MOD._translate(
            tool_call("shell", {"command": "npm test"}))
        self.assertTrue(is_shell)
        self.assertEqual(claude["tool_name"], "Bash")
        self.assertEqual(claude["tool_input"]["command"], "npm test")

    def test_shell_name_is_case_insensitive(self):
        claude, is_shell = ADAPTER_MOD._translate(
            tool_call("SHELL", {"command": "echo hi"}))
        self.assertTrue(is_shell)
        self.assertEqual(claude["tool_name"], "Bash")

    def test_read_write_edit_are_namespaced(self):
        for name in ("read", "write", "edit"):
            claude, is_shell = ADAPTER_MOD._translate(
                tool_call(name, {"path": "README.md"}))
            self.assertFalse(is_shell, name)
            self.assertEqual(claude["tool_name"], "pi:" + name)
            self.assertEqual(claude["tool_input"]["path"], "README.md")

    def test_grep_find_ls_are_namespaced(self):
        for name in ("grep", "find", "ls"):
            claude, is_shell = ADAPTER_MOD._translate(
                tool_call(name, {"path": "src"}))
            self.assertFalse(is_shell, name)
            self.assertEqual(claude["tool_name"], "pi:" + name)

    def test_missing_tool_name_is_nothing_to_judge(self):
        self.assertIsNone(ADAPTER_MOD._translate({"cwd": "C:/repo"}))

    def test_bash_without_command_is_nothing_to_judge(self):
        self.assertIsNone(ADAPTER_MOD._translate(tool_call("bash", {})))

    def test_ts_envelope_is_understood(self):
        claude, is_shell = ADAPTER_MOD._translate(
            ts_envelope("bash", {"command": "git status"}))
        self.assertTrue(is_shell)
        self.assertEqual(claude["tool_input"]["command"], "git status")

    def test_snake_case_aliases_are_understood(self):
        claude, is_shell = ADAPTER_MOD._translate({
            "tool_name": "read",
            "tool_input": {"path": "README.md"},
            "cwd": "D:/ws",
        })
        self.assertFalse(is_shell)
        self.assertEqual(claude["tool_name"], "pi:read")
        self.assertEqual(claude["cwd"], "D:/ws")


class AdapterTestCase(unittest.TestCase):
    def assertDenied(self, payload, msg=""):
        code, out = run_adapter(payload)
        self.assertEqual(code, 2, f"expected an explicit deny exit: {msg or payload}")
        self.assertTrue(out.strip(), f"expected a deny body, got none: {msg or payload}")
        self.assertFalse(
            out.lstrip().startswith("{"),
            f"deny reason is text, not a JSON verdict: {out!r}",
        )
        self.assertNotIn('{"decision": "allow"}', out)
        return out

    def assertPassed(self, payload, msg=""):
        code, out = run_adapter(payload)
        self.assertEqual(code, 0, msg or payload)
        self.assertEqual(out, "", f"a pass must print nothing: {msg or payload}")
        self.assertNotIn('{"decision": "allow"}', out)

    def cmd(self, command, **extra):
        return tool_call("bash", {"command": command}, **extra)


class TestShellRedlines(AdapterTestCase):
    """bash carries a command line, so it maps onto the guards' Bash shape."""

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
        out = self.assertDenied(self.cmd("cat ~/.env"))
        self.assertIn("CREDENTIAL GUARD", out)
        out = self.assertDenied(self.cmd("git add -A"))
        self.assertIn("GIT STAGING GUARD", out)

    def test_alternate_shell_tool_name_is_covered(self):
        self.assertDenied(tool_call("shell", {"command": "cat ~/.env"}))

    def test_ts_envelope_is_judged(self):
        self.assertDenied(ts_envelope("bash", {"command": "cat ~/.env"}))

    def test_sdk_snake_case_envelope_is_also_understood(self):
        self.assertDenied({
            "tool_name": "bash",
            "tool_input": {"command": "cat ~/.env"},
        })


class TestShellAllowed(AdapterTestCase):
    """False-positive discipline must survive the translation."""

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
        # The adapter knows nothing about these tokens. They ride through
        # in the command string. That is the point.
        self.assertPassed(self.cmd("cat ~/.env  # MASK-OK"))
        self.assertPassed(self.cmd("STAGE-ALL-OK git add -A"))

    def test_file_deletion_is_not_a_read(self):
        self.assertPassed(self.cmd("rm ~/.env.bak"))


class TestFileFieldTools(AdapterTestCase):
    """Every non-shell tool is handed over as-is.

    The guard's path-field scan judges it. A reader Pi adds tomorrow is
    covered without an edit here.
    """

    def test_read_on_a_credential_store_is_denied(self):
        self.assertDenied(tool_call("read", {"path": "~/.aws/credentials"}))
        self.assertDenied(tool_call("read", {"target_file": "/home/x/.env"}))

    def test_read_on_an_ordinary_file_passes(self):
        self.assertPassed(tool_call("read", {"path": "C:/repo/README.md"}))

    def test_unknown_reader_tool_is_covered(self):
        self.assertDenied(tool_call("some_future_reader", {"target_file": "~/.npmrc"}))

    def test_write_to_a_credential_store_is_denied(self):
        self.assertDenied(tool_call("write",
                                    {"path": "~/.ssh/id_rsa", "content": "x"}))

    def test_edit_on_a_credential_store_is_denied(self):
        self.assertDenied(tool_call("edit", {"path": "~/.env"}))

    def test_public_key_is_not_a_secret(self):
        self.assertPassed(tool_call("read", {"path": "~/.ssh/id_ed25519.pub"}))

    def test_listing_and_search_pass(self):
        self.assertPassed(tool_call("ls", {"path": "C:/repo"}))
        self.assertPassed(tool_call("find", {"path": "C:/repo"}))
        self.assertPassed(tool_call("web_search", {"query": "what is a .env file"}))

    def test_pi_tool_names_cannot_borrow_claude_tool_semantics(self):
        """Grep in the guard means Claude Code Grep.

        output_mode=files_with_matches lets an existence check through.
        Pi grep is a different tool. Glob always allows in the guard.
        The adapter namespaces every non-shell tool so those nuances
        cannot leak in.
        """
        self.assertDenied(tool_call("grep", {
            "path": "~/.env", "output_mode": "files_with_matches"}))
        self.assertDenied(tool_call("Grep", {
            "path": "~/.env", "output_mode": "files_with_matches"}))
        self.assertDenied(tool_call("Glob", {"path": "~/.env"}))


class TestPayloadHandling(AdapterTestCase):
    """Nothing to judge is a pass. It is not a failed check."""

    def test_no_tool_name_passes(self):
        self.assertPassed({"sessionId": "x"})

    def test_empty_tool_input_passes(self):
        self.assertPassed(tool_call("list_permissions", {}))

    def test_unparseable_stdin_passes(self):
        proc = subprocess.run([sys.executable, str(ADAPTER)], input="not json{",
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "")

    def test_bom_prefixed_stdin_is_still_judged(self):
        """A Windows wrapper piping through PowerShell prepends a UTF-8 BOM."""
        raw = "\ufeff" + json.dumps(self.cmd("cat ~/.env"))
        proc = subprocess.run([sys.executable, str(ADAPTER)],
                              input=raw.encode("utf-8"), capture_output=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn(b"CREDENTIAL GUARD", proc.stdout)

    def test_cwd_on_the_payload_is_accepted(self):
        payload = tool_call("bash", {"command": "git status"})
        payload["cwd"] = str(REPO)
        self.assertPassed(payload)


class TestFailsClosed(AdapterTestCase):
    """A broken check is not a pass."""

    def _adapter_outside_repo(self, tmp):
        """Copy the adapter to a tree with no agent-ops checkout above it."""
        target = Path(tmp) / "nowhere" / "pi-guard-adapter.py"
        target.parent.mkdir(parents=True)
        shutil.copy(ADAPTER, target)
        return target

    def test_missing_checkout_denies(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = self._adapter_outside_repo(tmp)
            env = {k: v for k, v in os.environ.items() if k != "AGENT_OPS_ROOT"}
            code, out = run_adapter(self.cmd("echo hi"), script=script, env=env)
            self.assertEqual(code, 2)
            self.assertIn("could not be found", out)
            self.assertIn("PI GUARD ADAPTER", out)

    def test_missing_guard_file_denies(self):
        """A checkout that resolves but has lost a guard script must deny."""
        with tempfile.TemporaryDirectory() as tmp:
            script = self._adapter_outside_repo(tmp)
            fake_root = Path(tmp) / "root"
            (fake_root / "security").mkdir(parents=True)
            # Only the marker exists. hooks/git-staging-guard.py is absent.
            shutil.copy(CREDENTIAL_GUARD, fake_root / "security" / "credential-guard.py")
            env = dict(os.environ, AGENT_OPS_ROOT=str(fake_root))
            code, out = run_adapter(self.cmd("echo hi"), script=script, env=env)
            self.assertEqual(code, 2)
            self.assertIn("git-staging-guard", out)

    def test_guard_crash_denies(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = self._adapter_outside_repo(tmp)
            fake_root = Path(tmp) / "root"
            (fake_root / "security").mkdir(parents=True)
            (fake_root / "security" / "credential-guard.py").write_text(
                "import sys\nsys.exit(1)\n", encoding="utf-8")
            env = dict(os.environ, AGENT_OPS_ROOT=str(fake_root))
            code, out = run_adapter(
                tool_call("read", {"path": "README.md"}),
                script=script, env=env)
            self.assertEqual(code, 2)
            self.assertIn("could not return a verdict", out)

    def test_agent_ops_root_env_override_is_honoured(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = self._adapter_outside_repo(tmp)
            env = dict(os.environ, AGENT_OPS_ROOT=str(REPO))
            code, out = run_adapter(self.cmd("cat ~/.env"), script=script, env=env)
            self.assertEqual(code, 2)
            self.assertIn("CREDENTIAL GUARD", out)
            code, out = run_adapter(self.cmd("npm test"), script=script, env=env)
            self.assertEqual(out, "", "the override must allow as well as deny")


if __name__ == "__main__":
    unittest.main()
