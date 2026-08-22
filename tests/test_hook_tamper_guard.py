#!/usr/bin/env python3
"""Test suite for hooks/hook-tamper-guard.py.

Four halves, and the last two decide whether the guard survives contact with
real work:

  1. mutations of a DEPLOYED guard file block,
  2. reads of the same file, and edits of the CANONICAL source, do not,
  3. prose that quotes a protected path does not,
  4. the override works, and a malformed payload fails open.

Group 3 is not padding. `security/posture.md` limit 5 records a credential-guard
draft that blocked its own commit message, and `hooks/git-staging-guard.py`
carries the same lesson. This guard is more exposed than either: the documents
that explain it quote its protected paths on every line.

Stdlib only (no pytest) so CI stays a bare `python -m unittest discover`. The
guard is driven exactly as the harness drives it: a PreToolUse JSON payload on
stdin, exit 0 = allow, exit 2 = block.
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

GUARD = Path(__file__).resolve().parent.parent / "hooks" / "hook-tamper-guard.py"

BLOCK, ALLOW = 2, 0

# A repo path, spelled the way a session actually spells it. No dot-config
# directory appears in it, which is the whole reason it stays editable.
CANONICAL = "/home/dev/code/agent-ops/hooks/credential-guard.py"


def run(command: str, tool_name: str = "Bash") -> int:
    """Drive the guard with a shell payload; return its exit code."""
    payload = json.dumps({"tool_name": tool_name, "tool_input": {"command": command}})
    proc = subprocess.run(
        [sys.executable, str(GUARD)], input=payload, capture_output=True, text=True
    )
    return proc.returncode


def run_tool(tool_name: str, tool_input: dict) -> int:
    """Drive the guard with an arbitrary tool payload."""
    payload = json.dumps({"tool_name": tool_name, "tool_input": tool_input})
    proc = subprocess.run(
        [sys.executable, str(GUARD)], input=payload, capture_output=True, text=True
    )
    return proc.returncode


class TestDeployedGuardMutationsBlocked(unittest.TestCase):
    """The threat: an agent disarms a guard mid-session."""

    def test_write_tool_at_a_deployed_hook(self) -> None:
        self.assertEqual(
            run_tool("Write", {"file_path": "~/.claude/hooks/credential-guard.py",
                               "content": "import sys; sys.exit(0)"}),
            BLOCK,
        )

    def test_edit_tool_at_a_deployed_hook(self) -> None:
        self.assertEqual(
            run_tool("Edit", {"file_path": "~/.claude/hooks/git-staging-guard.py",
                              "old_string": "exit(2)", "new_string": "exit(0)"}),
            BLOCK,
        )

    def test_edit_tool_at_the_live_settings_file(self) -> None:
        self.assertEqual(
            run_tool("Edit", {"file_path": "~/.claude/settings.json",
                              "old_string": "a", "new_string": "b"}),
            BLOCK,
        )

    def test_notebook_edit_at_a_deployed_hook(self) -> None:
        self.assertEqual(
            run_tool("NotebookEdit", {"notebook_path": "~/.claude/hooks/probe.ipynb",
                                      "new_source": "pass"}),
            BLOCK,
        )

    def test_paths_array_is_seen(self) -> None:
        self.assertEqual(
            run_tool("MultiEdit", {"paths": ["notes.md", "~/.claude/hooks/x.py"],
                                   "content": "..."}),
            BLOCK,
        )

    def test_every_vendor_lane_is_covered(self) -> None:
        """Each path is documented in that vendor's README in this repo."""
        for target in (
            "~/.cursor/hooks.json",
            "~/.grok/hooks/grok-guard-adapter.py",
            "~/.grok/hooks/fleet-guards.json",
            "~/.grok/config.toml",
            "~/.gemini/config/hooks.json",
            "~/.pi/agent/extensions/fleet-guard.ts",
            "~/.pi/agent/settings.json",
        ):
            with self.subTest(target=target):
                self.assertEqual(
                    run_tool("Write", {"file_path": target, "content": "x"}), BLOCK
                )

    def test_redirection_into_a_deployed_hook(self) -> None:
        self.assertEqual(run("echo 'import sys' > ~/.claude/hooks/credential-guard.py"),
                         BLOCK)
        self.assertEqual(run("cat x.py >> ~/.claude/hooks/credential-guard.py"), BLOCK)

    def test_delete_of_a_deployed_hook(self) -> None:
        self.assertEqual(run("rm ~/.claude/hooks/credential-guard.py"), BLOCK)
        self.assertEqual(run("rm -f $HOME/.claude/hooks/published-history-guard.py"),
                         BLOCK)
        self.assertEqual(run("Remove-Item ~/.grok/hooks/grok-guard-adapter.py"), BLOCK)

    def test_copy_onto_a_deployed_hook(self) -> None:
        """The deploy direction. Legitimate, and deliberately not silent."""
        self.assertEqual(run("cp " + CANONICAL + " ~/.claude/hooks/credential-guard.py"),
                         BLOCK)
        self.assertEqual(
            run("Copy-Item " + CANONICAL + " ~/.claude/hooks/credential-guard.py"),
            BLOCK,
        )
        self.assertEqual(
            run("Copy-Item -Path " + CANONICAL
                + " -Destination ~/.claude/hooks/credential-guard.py"),
            BLOCK,
        )

    def test_move_onto_a_deployed_hook(self) -> None:
        self.assertEqual(run("mv new-guard.py ~/.claude/hooks/credential-guard.py"),
                         BLOCK)

    def test_powershell_content_cmdlets(self) -> None:
        self.assertEqual(run("Set-Content ~/.claude/settings.json '{}'"), BLOCK)
        self.assertEqual(run("'{}' | Out-File ~/.claude/settings.json"), BLOCK)
        self.assertEqual(
            run("Set-Content -Path ~/.claude/hooks/credential-guard.py -Value ''"),
            BLOCK,
        )

    def test_sed_in_place(self) -> None:
        self.assertEqual(run("sed -i 's/exit(2)/exit(0)/' ~/.claude/hooks/x.py"), BLOCK)
        self.assertEqual(run("sed --in-place=.bak 's/a/b/' ~/.claude/hooks/x.py"), BLOCK)

    def test_inline_interpreter_write(self) -> None:
        self.assertEqual(
            run("""python -c "open('~/.claude/hooks/credential-guard.py','w').write('')" """),
            BLOCK,
        )
        self.assertEqual(
            run("""python3 -c "import os; os.remove(os.path.expanduser('~/.claude/hooks/x.py'))" """),
            BLOCK,
        )

    def test_later_segment_of_a_compound_command(self) -> None:
        """The offence is rarely first."""
        self.assertEqual(run("git status && rm ~/.claude/hooks/credential-guard.py"),
                         BLOCK)

    def test_windows_backslash_spelling(self) -> None:
        self.assertEqual(run(r"del %USERPROFILE%\.claude\hooks\credential-guard.py"),
                         BLOCK)


class TestCanonicalSourcesStayEditable(unittest.TestCase):
    """A guard evolves through a pull request. If this group ever goes red, the
    guard has locked the only route by which it can be fixed."""

    def test_edit_of_the_canonical_guard(self) -> None:
        self.assertEqual(
            run_tool("Edit", {"file_path": CANONICAL,
                              "old_string": "a", "new_string": "b"}),
            ALLOW,
        )

    def test_write_of_a_new_canonical_guard(self) -> None:
        self.assertEqual(
            run_tool("Write", {"file_path": "/home/dev/code/agent-ops/hooks/new-guard.py",
                               "content": "import sys"}),
            ALLOW,
        )

    def test_edit_of_the_vendor_reference_config(self) -> None:
        """`vendors/gemini/hooks.json` is a reference config, not a deployment."""
        self.assertEqual(
            run_tool("Write", {"file_path": "/home/dev/code/agent-ops/vendors/gemini/hooks.json",
                               "content": "{}"}),
            ALLOW,
        )

    def test_edit_of_the_plugin_tree(self) -> None:
        """`vendors/claude/plugin/hooks/` has no dot-config directory in it."""
        self.assertEqual(
            run_tool("Write", {"file_path":
                               "/home/dev/code/agent-ops/vendors/claude/plugin/hooks/hooks.json",
                               "content": "{}"}),
            ALLOW,
        )

    def test_shell_edit_inside_the_clone(self) -> None:
        self.assertEqual(run("sed -i 's/a/b/' " + CANONICAL), ALLOW)
        self.assertEqual(run("rm /home/dev/code/agent-ops/hooks/old-guard.py"), ALLOW)

    def test_a_project_settings_file_is_not_the_live_one(self) -> None:
        self.assertEqual(
            run_tool("Write", {"file_path": "/home/dev/code/myapp/settings.json",
                               "content": "{}"}),
            ALLOW,
        )

    def test_a_similar_word_is_not_a_dot_directory(self) -> None:
        self.assertEqual(
            run_tool("Write", {"file_path": "/home/dev/notclaude/hooks/x.py",
                               "content": "x"}),
            ALLOW,
        )


class TestReadsStayAllowed(unittest.TestCase):
    """Direction matters. credential-guard governs the reads that carry an
    exposure; this guard refuses writes only."""

    def test_read_tool(self) -> None:
        self.assertEqual(
            run_tool("Read", {"file_path": "~/.claude/hooks/credential-guard.py"}),
            ALLOW,
        )

    def test_grep_and_glob(self) -> None:
        self.assertEqual(
            run_tool("Grep", {"pattern": "exit", "path": "~/.claude/hooks/"}), ALLOW
        )
        self.assertEqual(run_tool("Glob", {"pattern": "~/.claude/hooks/*.py"}), ALLOW)

    def test_shell_reads(self) -> None:
        self.assertEqual(run("cat ~/.claude/hooks/credential-guard.py"), ALLOW)
        self.assertEqual(run("Get-Content ~/.grok/hooks/grok-guard-adapter.py"), ALLOW)
        self.assertEqual(run("diff " + CANONICAL + " ~/.claude/hooks/credential-guard.py"),
                         ALLOW)

    def test_metadata_checks(self) -> None:
        self.assertEqual(run("ls -l ~/.claude/hooks/"), ALLOW)
        self.assertEqual(run("Test-Path ~/.claude/hooks/credential-guard.py"), ALLOW)
        self.assertEqual(run("sha256sum ~/.claude/hooks/credential-guard.py"), ALLOW)

    def test_sed_without_in_place_is_a_read(self) -> None:
        self.assertEqual(run("sed -n '1,5p' ~/.claude/hooks/credential-guard.py"), ALLOW)

    def test_inline_interpreter_read(self) -> None:
        self.assertEqual(
            run("""python -c "print(open('~/.claude/hooks/x.py').read())" """), ALLOW
        )

    def test_backup_direction_is_allowed(self) -> None:
        """A copy OUT of the deployed tree is a backup, not a disarm."""
        self.assertEqual(
            run("cp ~/.claude/hooks/credential-guard.py /tmp/guard-snapshot.py"), ALLOW
        )
        self.assertEqual(
            run("Copy-Item ~/.claude/hooks/credential-guard.py /tmp/snapshot.py"), ALLOW
        )

    def test_a_public_url_is_not_a_local_path(self) -> None:
        self.assertEqual(
            run_tool("WebFetch",
                     {"url": "https://example.invalid/repo/.claude/settings.json"}),
            ALLOW,
        )


class TestProseIsNotAMutation(unittest.TestCase):
    """The guard must be able to document itself. Every case below appears, in
    substance, in the commit message and PR body written the day it was built."""

    def test_path_inside_a_commit_message(self) -> None:
        self.assertEqual(
            run("git commit -m 'guard writes to ~/.claude/hooks/ now block'"), ALLOW
        )

    def test_path_inside_a_pr_body(self) -> None:
        self.assertEqual(
            run("gh pr create --title 'add hook-tamper-guard' "
                "--body 'It refuses rm ~/.claude/hooks/credential-guard.py'"),
            ALLOW,
        )

    def test_path_inside_echo(self) -> None:
        self.assertEqual(
            run("echo 'never edit ~/.claude/hooks/credential-guard.py by hand'"), ALLOW
        )

    def test_path_inside_a_heredoc_body(self) -> None:
        command = (
            "git commit -F - <<'EOF'\n"
            "guard: protect the deployed chain\n\n"
            "A Write at ~/.claude/hooks/credential-guard.py now blocks.\n"
            "So does `cp canonical ~/.claude/hooks/credential-guard.py`.\n"
            "EOF"
        )
        self.assertEqual(run(command), ALLOW)

    def test_pr_body_heredoc(self) -> None:
        command = (
            "gh pr create --body \"$(cat <<'EOF'\n"
            "Blocks Set-Content ~/.claude/settings.json.\n"
            "EOF\n"
            ')"'
        )
        self.assertEqual(run(command), ALLOW)

    def test_a_pipe_inside_a_message_does_not_split_a_segment(self) -> None:
        self.assertEqual(
            run("git commit -m 'rm | Set-Content ~/.claude/hooks/x.py both block'"),
            ALLOW,
        )

    def test_grepping_for_the_guards_own_subject(self) -> None:
        self.assertEqual(run("rg 'claude/hooks' hooks/"), ALLOW)


class TestOverride(unittest.TestCase):
    """A per-command opt-in for a deliberate canonical-to-deploy sync.

    The block message deliberately does not name the token; this suite is the
    place it is asserted, because a human reads a test file and a model reads a
    block reason.
    """

    def test_override_permits_the_deploy(self) -> None:
        self.assertEqual(
            run("DEPLOY-OK cp " + CANONICAL + " ~/.claude/hooks/credential-guard.py"),
            ALLOW,
        )
        self.assertEqual(
            run("DEPLOY-OK Copy-Item " + CANONICAL
                + " ~/.claude/hooks/credential-guard.py"),
            ALLOW,
        )

    def test_the_block_message_does_not_name_the_override(self) -> None:
        """Repo standing decision: a guard must not advertise its own bypass to
        the model in a block reason."""
        payload = json.dumps({
            "tool_name": "Bash",
            "tool_input": {"command": "rm ~/.claude/hooks/credential-guard.py"},
        })
        proc = subprocess.run(
            [sys.executable, str(GUARD)], input=payload, capture_output=True, text=True
        )
        self.assertEqual(proc.returncode, BLOCK)
        self.assertNotIn("DEPLOY-OK", proc.stderr)
        self.assertNotIn("DEPLOY-OK", proc.stdout)


class TestFailOpen(unittest.TestCase):
    """A hook that crashes must not wedge every tool call.

    Deliberate, not inherited: this is a PreToolUse hook in Claude Code, and
    conventions/hooks-gate-their-own-repair.md records that every repair route
    is itself a tool call the wedged hook would refuse.
    """

    def test_unparseable_payload_allows(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(GUARD)], input="not json",
            capture_output=True, text=True
        )
        self.assertEqual(proc.returncode, ALLOW)

    def test_payload_is_not_an_object(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(GUARD)], input="[1, 2, 3]",
            capture_output=True, text=True
        )
        self.assertEqual(proc.returncode, ALLOW)

    def test_missing_tool_input_allows(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(GUARD)], input=json.dumps({"tool_name": "Bash"}),
            capture_output=True, text=True
        )
        self.assertEqual(proc.returncode, ALLOW)

    def test_tool_input_of_the_wrong_type(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(GUARD)],
            input=json.dumps({"tool_name": "Bash", "tool_input": "oops"}),
            capture_output=True, text=True
        )
        self.assertEqual(proc.returncode, ALLOW)

    def test_a_bom_prefixed_payload_is_still_read(self) -> None:
        """A PowerShell wrapper prepends a BOM; a strict decode turned
        credential-guard v2.7 into a silent no-op on every call."""
        payload = json.dumps({
            "tool_name": "Bash",
            "tool_input": {"command": "rm ~/.claude/hooks/credential-guard.py"},
        })
        proc = subprocess.run(
            [sys.executable, str(GUARD)],
            input=("﻿" + payload).encode("utf-8"), capture_output=True
        )
        self.assertEqual(proc.returncode, BLOCK)

    def test_cursor_payload_gets_an_explicit_allow(self) -> None:
        """cursor-agent treats empty stdout as a failed hook run."""
        payload = json.dumps({
            "cursor_version": "1.0.0",
            "tool_name": "Shell",
            "tool_input": {"command": "ls"},
        })
        proc = subprocess.run(
            [sys.executable, str(GUARD)], input=payload, capture_output=True, text=True
        )
        self.assertEqual(proc.returncode, ALLOW)
        self.assertIn("allow", proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
