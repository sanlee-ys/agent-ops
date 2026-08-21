#!/usr/bin/env python3
"""Tests for vendors/grok/hooks/grok-guard-adapter.py.

The adapter is a translator, so these tests are about the TRANSLATION and the
FAILURE POSTURE, not about the redlines themselves — those are owned by
tests/test_credential_guard.py and friends, and duplicating a rule here would
be the same drift mistake the adapter exists to avoid (posture.md limit #6).
What is asserted here:

  1. THE DEFECT. Fed Grok's own documented stdin envelope, the canonical guard
     allows a credential read. That is the whole reason this adapter exists and
     it is asserted first, because a wiring built on an unstated premise is a
     wiring nobody can re-derive later;
  2. a redline the canonical guard blocks comes back as a `deny` on Grok's
     contract, for the shell shape AND the file-field shape;
  3. the cases that must keep working — existence checks, ordinary files, prose
     mentioning a credential filename, the per-guard overrides — come back as a
     pass, and a pass never emits `{"decision": "allow"}`. An explicit allow is
     an approval; a guard must not widen permissions by not objecting;
  4. an unrunnable check denies rather than passing, because Grok's hook runner
     is documented fail-open on every failure class;
  5. the reference hook configs are deployable — in particular that the Windows
     one names an absolute interpreter, since bare `python3` on a provisioned
     Windows box is a WindowsApps App Execution Alias that allocates a console.

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
ADAPTER = REPO / "vendors" / "grok" / "hooks" / "grok-guard-adapter.py"
CREDENTIAL_GUARD = REPO / "security" / "credential-guard.py"


def run_adapter(payload, script=ADAPTER, env=None):
    """Drive the adapter exactly as Grok does: JSON on stdin, JSON on stdout,
    exit code alongside. Returns (returncode, stdout)."""
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.returncode, proc.stdout


def tool_call(name, tool_input, **extra):
    """A Grok PreToolUse payload, with the common fields every event carries.

    camelCase throughout — that is the wire format, and it is the entire
    reason this adapter exists (grok user-guide 10-hooks.md, "camelCase input").
    """
    payload = {
        "hookEventName": "pre_tool_use",
        "sessionId": "00000000-0000-0000-0000-000000000000",
        "cwd": "C:/repo",
        "workspaceRoot": "C:/repo",
        "permissionMode": "default",
        "toolName": name,
        "toolInput": tool_input,
        "toolUseId": "tu_0",
        "toolInputTruncated": False,
        "timestamp": "2026-08-08T12:00:00Z",
    }
    payload.update(extra)
    return payload


class TestTheDefectThisAdapterExistsFor(unittest.TestCase):
    """Grok ships `[compat.claude] hooks = true`, so it loads the fleet guards
    straight from ~/.claude/settings.json and `grok inspect` lists all three.
    They have never fired. The guards read `tool_name`/`tool_input`; Grok sends
    `toolName`/`toolInput`; nothing matches and the guard exits 0 = allow.

    If this test ever fails, the premise changed — a guard learned Grok's
    dialect natively — and the wiring wants re-deriving, not patching.
    """

    def _guard(self, payload):
        proc = subprocess.run(
            [sys.executable, str(CREDENTIAL_GUARD)],
            input=json.dumps(payload), capture_output=True, text=True,
        )
        return proc.returncode

    def test_grok_envelope_is_a_silent_no_op_for_the_raw_guard(self):
        camel = tool_call("run_terminal_command", {"command": "cat ~/.env"})
        self.assertEqual(self._guard(camel), 0,
                         "premise changed: the raw guard now judges Grok's "
                         "envelope; re-derive the wiring rather than patching")

    def test_the_same_command_blocks_in_claude_dialect(self):
        snake = {"tool_name": "Bash", "tool_input": {"command": "cat ~/.env"}}
        self.assertEqual(self._guard(snake), 2,
                         "control case: identical command, snake_case payload")


class AdapterTestCase(unittest.TestCase):
    def assertDenied(self, payload, msg=""):
        code, out = run_adapter(payload)
        # Both channels agree on purpose: the stdout `reason` is what Grok
        # surfaces to the model, and exit 2 is an explicit deny in its own
        # right, so the block survives losing either one.
        self.assertEqual(code, 2, f"expected an explicit deny exit: {msg or payload}")
        self.assertTrue(out.strip(), f"expected a deny body, got none: {msg or payload}")
        body = json.loads(out)
        self.assertEqual(body.get("decision"), "deny", msg or payload)
        self.assertTrue(body.get("reason", "").strip(),
                        "a deny with an empty reason teaches the agent nothing")
        return body

    def assertPassed(self, payload, msg=""):
        code, out = run_adapter(payload)
        self.assertEqual(code, 0, msg or payload)
        # NOT `{"decision": "allow"}`. Grok accepts it, and it is an approval
        # rather than a neutral pass; whether it short-circuits the permission
        # mode is unmeasured, and a guard must not widen permissions as a side
        # effect of not objecting.
        self.assertEqual(out, "", f"a pass must print nothing: {msg or payload}")

    def cmd(self, command, **extra):
        return tool_call("run_terminal_command", {"command": command}, **extra)


class TestShellRedlines(AdapterTestCase):
    """run_terminal_command carries a command line, so it maps onto the guards'
    Bash shape."""

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

    def test_alternate_shell_tool_names_are_covered(self):
        """`run_terminal_command` is the name in the hook payload example;
        `run_terminal_cmd` appears in the headless flag examples and `Shell`
        can arrive through Cursor-compat routing. A shell call that this file
        failed to recognise would fall to the field scan, which does not read
        commands — so it would sail through."""
        self.assertDenied(tool_call("run_terminal_cmd", {"command": "cat ~/.env"}))
        self.assertDenied(tool_call("Shell", {"command": "cat ~/.env"}))

    def test_sdk_snake_case_envelope_is_also_understood(self):
        """Hooks registered through the grok-agent-sdk arrive snake_cased.
        Accepting both spellings beats guessing which side registered us."""
        self.assertDenied({"hook_event_name": "pre_tool_use",
                           "tool_name": "run_terminal_command",
                           "tool_input": {"command": "cat ~/.env"}})


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
        self.assertPassed(self.cmd("RISK-OK git reset --hard HEAD~1"))

    def test_file_deletion_is_not_a_read(self):
        self.assertPassed(self.cmd("rm ~/.env.bak"))

    def test_bypass_permission_mode_changes_nothing(self):
        """`--yolo` / `--always-approve` sets permissionMode=bypassPermissions.
        The adapter never reads that field: the hook is upstream of the
        permission system, which is the entire reason ADR-012 makes hooks the
        control rather than permission modes."""
        self.assertDenied(self.cmd("cat ~/.env", permissionMode="bypassPermissions"))
        self.assertPassed(self.cmd("npm test", permissionMode="bypassPermissions"))


class TestAdr015Verdicts(AdapterTestCase):
    """ADR-015's two guards speak Claude's extra verdicts. Grok's PreToolUse
    contract is allow / deny / rewrite. The adapter translates; it does not
    reimplement the scores or the patterns."""

    def assertRewritten(self, payload, marker, msg=""):
        code, out = run_adapter(payload)
        self.assertEqual(code, 0, msg or payload)
        self.assertTrue(out.strip(), "a rewrite must emit updatedInput")
        body = json.loads(out)
        self.assertIsNone(body.get("decision"),
                          "a rewrite omits decision; an explicit allow is "
                          "an approval")
        updated = body["hookSpecificOutput"]["updatedInput"]
        blob = json.dumps(updated)
        self.assertIn(marker, blob, msg or payload)
        return body, updated

    def test_hard_reset_confirm_becomes_deny(self):
        """git reset --hard scores confirm (ask). Grok has no ask channel, so
        the adapter denies and the reason still names RISK-OK."""
        body = self.assertDenied(self.cmd("git reset --hard HEAD~1"))
        self.assertIn("DESTRUCTIVE-COMMAND GUARD", body["reason"])
        self.assertIn("RISK-OK", body["reason"])
        self.assertIn("git.reset_hard", body["reason"])

    def test_soft_reset_still_passes(self):
        self.assertPassed(self.cmd("git reset --soft HEAD~1"))

    def test_literal_aws_key_is_rewritten_not_denied(self):
        # Assemble at runtime so a live redaction hook cannot rewrite this
        # file's source the way it rewrote a bench script on 2026-08-21.
        sample = "AKIA" + "IOSFODNN7EXAMPLE"
        body, updated = self.assertRewritten(
            self.cmd("echo " + sample),
            "[REDACTED:aws_access_key]",
        )
        self.assertNotIn(sample, json.dumps(updated))
        self.assertEqual(body["hookSpecificOutput"]["hookEventName"],
                         "PreToolUse")

    def test_redaction_on_a_non_shell_write(self):
        """secret-redaction walks every tool_input, not only shell commands."""
        sample = "AKIA" + "IOSFODNN7EXAMPLE"
        _, updated = self.assertRewritten(
            tool_call("search_replace", {
                "path": "C:/repo/README.md",
                "new_string": "token=" + sample,
            }),
            "[REDACTED:aws_access_key]",
        )
        self.assertEqual(updated["path"], "C:/repo/README.md")


class TestFileFieldTools(AdapterTestCase):
    """Every non-shell tool is handed over as-is and judged by the guard's
    path-field scan — the tool-shape-agnostic default-deny. A reader Grok adds
    tomorrow is covered without an edit here."""

    def test_read_file_on_a_credential_store_is_denied(self):
        self.assertDenied(tool_call("read_file", {"path": "~/.aws/credentials"}))
        self.assertDenied(tool_call("read_file", {"target_file": "/home/x/.env"}))

    def test_read_file_on_an_ordinary_file_passes(self):
        self.assertPassed(tool_call("read_file", {"path": "C:/repo/README.md"}))

    def test_unknown_reader_tool_is_covered(self):
        # Not in any list the adapter holds; caught structurally by the field scan.
        self.assertDenied(tool_call("some_future_reader", {"target_file": "~/.npmrc"}))

    def test_write_to_a_credential_store_is_denied(self):
        # Overwriting a key store is as bad an outcome as printing it.
        self.assertDenied(tool_call("search_replace",
                                    {"path": "~/.ssh/id_rsa", "new_string": "x"}))

    def test_public_key_is_not_a_secret(self):
        self.assertPassed(tool_call("read_file", {"path": "~/.ssh/id_ed25519.pub"}))

    def test_listing_and_search_pass(self):
        self.assertPassed(tool_call("list_dir", {"path": "C:/repo"}))
        self.assertPassed(tool_call("web_search", {"query": "what is a .env file"}))

    def test_grok_tool_names_cannot_borrow_claude_tool_semantics(self):
        """`Grep` in the guard means Claude Code's Grep, whose output_mode
        nuance lets an existence check through. Grok's `grep` is a different
        tool with different args, so inheriting that nuance by accident would
        be a silent hole. The adapter namespaces every non-shell tool."""
        self.assertDenied(tool_call("grep", {"path": "~/.env", "output_mode": "content"}))
        self.assertDenied(tool_call("Grep", {"path": "~/.env", "output_mode": "content"}))
        self.assertDenied(tool_call("Glob", {"path": "~/.env"}))


class TestPayloadHandling(AdapterTestCase):
    """Nothing to judge is a pass; it is not a failed check."""

    def test_no_tool_name_passes(self):
        self.assertPassed({"hookEventName": "session_start", "sessionId": "x"})

    def test_empty_tool_input_passes(self):
        self.assertPassed(tool_call("list_permissions", {}))

    def test_unparseable_stdin_passes(self):
        proc = subprocess.run([sys.executable, str(ADAPTER)], input="not json{",
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "")

    def test_bom_prefixed_stdin_is_still_judged(self):
        """A Windows wrapper piping through PowerShell prepends a UTF-8 BOM. A
        strict decode there turned the Cursor lane into a silent no-op once
        already (vendors/cursor/README.md); do not repeat it here."""
        raw = "\ufeff" + json.dumps(self.cmd("cat ~/.env"))
        proc = subprocess.run([sys.executable, str(ADAPTER)],
                              input=raw.encode("utf-8"), capture_output=True)
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(json.loads(proc.stdout)["decision"], "deny")

    def test_workspace_root_supplies_cwd_when_absent(self):
        payload = tool_call("run_terminal_command", {"command": "git status"})
        payload.pop("cwd")
        self.assertPassed(payload)


class TestFailsClosed(AdapterTestCase):
    """Grok's hook runner is fail-open on every failure class it documents —
    timeouts, crashes, malformed output — so a broken guard is indistinguishable
    from no guard. The adapter inverts that for the failures it can see."""

    def _adapter_outside_repo(self, tmp):
        """A copy of the adapter with no agent-ops checkout above it, so the
        walk-up resolution genuinely fails."""
        target = Path(tmp) / "nowhere" / "grok-guard-adapter.py"
        target.parent.mkdir(parents=True)
        shutil.copy(ADAPTER, target)
        return target

    def test_missing_checkout_denies(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = self._adapter_outside_repo(tmp)
            env = {k: v for k, v in os.environ.items() if k != "AGENT_OPS_ROOT"}
            code, out = run_adapter(self.cmd("echo hi"), script=script, env=env)
            self.assertEqual(code, 2)
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
            shutil.copy(CREDENTIAL_GUARD, fake_root / "security" / "credential-guard.py")
            env = dict(os.environ, AGENT_OPS_ROOT=str(fake_root))
            code, out = run_adapter(self.cmd("echo hi"), script=script, env=env)
            self.assertEqual(code, 2)
            body = json.loads(out)
            self.assertEqual(body["decision"], "deny")
            self.assertIn("secret-redaction-guard", body["reason"])

    def test_agent_ops_root_env_override_is_honoured(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = self._adapter_outside_repo(tmp)
            env = dict(os.environ, AGENT_OPS_ROOT=str(REPO))
            code, out = run_adapter(self.cmd("cat ~/.env"), script=script, env=env)
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out)["decision"], "deny")
            code, out = run_adapter(self.cmd("npm test"), script=script, env=env)
            self.assertEqual(out, "", "the override must allow as well as deny")


class TestReferenceConfigs(unittest.TestCase):
    """The versioned hook files are deployable artifacts, not decoration."""

    POSIX = REPO / "vendors" / "grok" / "hooks.json"
    WINDOWS = REPO / "vendors" / "grok" / "hooks.windows.json"

    def _entry(self, path):
        config = json.loads(path.read_text(encoding="utf-8"))
        groups = config["hooks"]["PreToolUse"]
        self.assertEqual(len(groups), 1)
        return groups[0]

    def test_both_wire_the_adapter_on_every_tool(self):
        for path in (self.POSIX, self.WINDOWS):
            with self.subTest(config=path.name):
                entry = self._entry(path)
                # An omitted matcher matches everything. A literal "*" is not a
                # wildcard here — the matcher is a REGEX, and `*` has nothing to
                # repeat, so it is at best a compile error and at worst a hook
                # that quietly never fires.
                self.assertNotIn("matcher", entry,
                                 "omit the matcher; do not write '*'")
                handler = entry["hooks"][0]
                self.assertEqual(handler["type"], "command")
                self.assertIn("grok-guard-adapter.py", handler["command"])

    def test_timeout_clears_the_adapter_worst_case(self):
        """Grok's default hook timeout is 5 SECONDS and a timed-out hook fails
        OPEN, so an unset timeout is not a slow guard — it is no guard. The
        adapter's budget is five guards at 45s."""
        for path in (self.POSIX, self.WINDOWS):
            with self.subTest(config=path.name):
                self.assertGreaterEqual(self._entry(path)["hooks"][0]["timeout"], 225)

    def test_windows_config_names_an_absolute_interpreter(self):
        """Bare `python3` on a provisioned Windows box resolves to the
        WindowsApps App Execution Alias — a zero-byte reparse point that
        allocates a visible conhost and re-execs. That is the 2026-08-06
        orphaned-hook-window incident; do not re-ship it."""
        command = self._entry(self.WINDOWS)["hooks"][0]["command"]
        interpreter = command.split(" ", 1)[0]
        self.assertTrue(interpreter.startswith("${"),
                        "the interpreter must be an absolute, expanded path")
        self.assertNotIn("WindowsApps", interpreter)
        self.assertTrue(interpreter.endswith("python3.exe"), interpreter)

    def test_windows_config_avoids_home(self):
        """`$HOME` is set under Git Bash and absent under PowerShell, where it
        expands to nothing and the hook fails to launch — which, since Grok
        fails open, silently removes the guard. `${USERPROFILE}` is always set.
        Measured 2026-08-08 via `grok inspect --json` under both parents."""
        self.assertNotIn("$HOME", self.WINDOWS.read_text(encoding="utf-8"))

    def test_no_quotes_in_the_command(self):
        """Keep the command unquoted so it cannot depend on whether the runner
        hands it to a shell — the same failure the Antigravity adapter records,
        where a quoted path simply failed to launch."""
        for path in (self.POSIX, self.WINDOWS):
            with self.subTest(config=path.name):
                self.assertNotIn('"', self._entry(path)["hooks"][0]["command"])

    def test_no_local_user_path(self):
        """This repo is public; the reference configs must be genericized."""
        for path in (self.POSIX, self.WINDOWS):
            with self.subTest(config=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("C:/Users", text)
                self.assertNotIn("C:\\\\Users", text)


if __name__ == "__main__":
    unittest.main()
