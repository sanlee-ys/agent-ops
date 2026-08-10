#!/usr/bin/env python3
"""Test suite for scripts/settings-toggle.py.

The program's entire justification is a claim about what it *cannot* do, so the
tests are organised around that claim rather than around its features:

  - the two owned settings round-trip, so the convenience half actually works;
  - an unusual-but-valid document survives byte-for-byte in every part the
    program does not own - unicode, nesting, key order, CRLF, a BOM, and a
    compact single-line `~/.claude.json`;
  - reaching for a forbidden key fails loudly, at both layers, rather than
    no-opping quietly. A silent no-op is the dangerous outcome here: it reads
    as "the boundary held" while telling you nothing about whether it did;
  - nothing the program prints ever contains a value from the file other than
    the one key it is changing. Both target files are full of credentials, and
    stdout is read by the agent that invoked the program.

The forbidden-key cases drive the internals directly as well as the CLI. The
CLI has no way to name a key at all, so the layer underneath it is tested where
a future non-CLI caller would land.

Stdlib only (no pytest), matching the other guard suites, so CI stays a bare
`python -m unittest`.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOGGLE = Path(__file__).resolve().parent.parent / "scripts" / "settings-toggle.py"

# Hyphenated filename, so it is loaded by path rather than imported by name.
_spec = importlib.util.spec_from_file_location("settings_toggle", TOGGLE)
toggle = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(toggle)

OK, REFUSED, USAGE = 0, 1, 2

# A marker that must never reach stdout or stderr. Deliberately not shaped like
# a real credential, so the repo's redline guard has nothing to complain about
# while the test still proves the leak path is closed.
SECRET = "NEVER-PRINT-THIS-VALUE"

# A settings file with the shapes that break naive rewriters: non-ASCII text,
# nested objects and arrays, a deliberately non-alphabetical key order, and the
# exact keys this program must never touch.
AWKWARD = {
    "theme": "dark",
    "statusLine": {"type": "command", "command": 'bash "$HOME/.claude/sl.sh"'},
    "hooks": {
        "PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "g.py"}]}
        ]
    },
    "permissions": {
        "defaultMode": "auto",
        "disableBypassPermissionsMode": "disable",
        "allow": ["Bash(git status:*)", "Read"],
        "deny": ["Read(**/.env)"],
    },
    "env": {"SOME_FLAG": "1", "SOME_TOKEN": SECRET},
    "apiKeyHelper": "/bin/echo " + SECRET,
    "awsAuthRefresh": "aws sso login",
    "otelHeadersHelper": "/bin/echo " + SECRET,
    "disableAllHooks": False,
    "autoMode": {"environment": ["données: café, naïve, 日本語, emoji 🚀"]},
    "aKeyThatSortsFirst": {"nested": {"deeply": [1, 2, {"three": None}]}},
}

# Every top-level key of a settings.json that the program must not write, and
# whose values must never be printed.
FORBIDDEN = (
    "permissions",
    "env",
    "hooks",
    "disableAllHooks",
    "apiKeyHelper",
    "awsAuthRefresh",
    "otelHeadersHelper",
    "autoMode",
    "statusLine",
)

# The project keys used in the ~/.claude.json fixture. Deliberately
# platform-neutral strings; they are dict keys, never opened.
PROJECT = os.path.join(os.sep + "work", "repo-one")
OTHER_PROJECT = os.path.join(os.sep + "work", "repo-two")


def claude_json(disabled=None) -> dict:
    """A ~/.claude.json shaped like the real one: secrets top-level and nested."""
    entry = {
        "allowedTools": ["Read"],
        "history": [{"display": "a prompt mentioning " + SECRET}],
        "mcpServers": {
            "private": {"url": "https://x", "headers": {"Authorization": SECRET}}
        },
    }
    if disabled is not None:
        entry["disabledMcpServers"] = disabled
    return {
        "numStartups": 42,
        "oauthAccount": {"emailAddress": "someone@example.com", "token": SECRET},
        "mcpServers": {
            "global": {"url": "https://y", "headers": {"X-Api-Key": SECRET}}
        },
        "projects": {
            PROJECT: entry,
            OTHER_PROJECT: {"history": [], "disabledMcpServers": ["untouched"]},
        },
    }


def write(path: Path, document, *, bom=False, crlf=False, compact=False) -> None:
    if compact:
        text = json.dumps(document, separators=(",", ":"), ensure_ascii=False)
    else:
        text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    if crlf:
        text = text.replace("\n", "\r\n")
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))


def run(path: Path, *argv: str) -> subprocess.CompletedProcess:
    """Drive the CLI exactly as an operator would."""
    return subprocess.run(
        [sys.executable, str(TOGGLE), "--settings", str(path), *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def read(path: Path) -> dict:
    return json.loads(path.read_bytes().decode("utf-8-sig"))


def backups(path: Path) -> list[Path]:
    return sorted(p for p in path.parent.iterdir() if ".bak-" in p.name)


class TempSettings(unittest.TestCase):
    """Each test gets its own settings file in a throwaway directory."""

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.dir = Path(self._dir.name)
        self.path = self.dir / "settings.json"
        self.claude = self.dir / ".claude.json"


# ---------------------------------------------------------------------------
# The convenience half actually works
# ---------------------------------------------------------------------------


class TestSkillOverrides(TempSettings):
    def test_skill_off_then_on(self) -> None:
        write(self.path, {"theme": "dark"})

        result = run(self.path, "--skill", "some-skill", "--off")
        self.assertEqual(result.returncode, OK, result.stderr)
        self.assertEqual(read(self.path)["skillOverrides"], {"some-skill": "off"})

        result = run(self.path, "--skill", "some-skill", "--on")
        self.assertEqual(result.returncode, OK, result.stderr)
        # Emptied out entirely rather than left as a `{}` husk.
        self.assertNotIn("skillOverrides", read(self.path))
        self.assertEqual(read(self.path), {"theme": "dark"})

    def test_the_only_value_it_can_write_is_off(self) -> None:
        """There is no free-form value argument, so `off` is the vocabulary."""
        write(self.path, {})
        run(self.path, "--skill", "s", "--off")
        self.assertEqual(read(self.path)["skillOverrides"]["s"], toggle.SKILL_OFF)
        self.assertEqual(toggle.SKILL_OFF, "off")

    def test_off_is_idempotent(self) -> None:
        write(self.path, {**AWKWARD, "skillOverrides": {"s": "off"}}, crlf=True)
        before = self.path.read_bytes()
        result = run(self.path, "--skill", "s", "--off")
        self.assertEqual(result.returncode, OK, result.stderr)
        self.assertIn("No change", result.stdout)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(backups(self.path), [])

    def test_on_for_an_absent_skill_is_idempotent(self) -> None:
        write(self.path, {"theme": "dark"})
        before = self.path.read_bytes()
        result = run(self.path, "--skill", "never-set", "--on")
        self.assertEqual(result.returncode, OK, result.stderr)
        self.assertIn("No change", result.stdout)
        self.assertEqual(self.path.read_bytes(), before)

    def test_a_second_skill_joins_the_first(self) -> None:
        write(self.path, {})
        run(self.path, "--skill", "one", "--off")
        run(self.path, "--skill", "two", "--off")
        self.assertEqual(
            read(self.path)["skillOverrides"], {"one": "off", "two": "off"}
        )

    def test_missing_file_is_created(self) -> None:
        self.assertFalse(self.path.exists())
        result = run(self.path, "--skill", "s", "--off")
        self.assertEqual(result.returncode, OK, result.stderr)
        self.assertEqual(read(self.path), {"skillOverrides": {"s": "off"}})

    def test_settings_local_json_is_also_a_valid_target(self) -> None:
        local = self.dir / "settings.local.json"
        write(local, {})
        self.assertEqual(
            run(local, "--skill", "s", "--off").returncode, OK
        )

    def test_a_dotted_name_cannot_escape_its_owned_key(self) -> None:
        """A crafted name stays a name; it is not a path into the document."""
        write(self.path, AWKWARD)
        result = run(self.path, "--skill", "permissions.allow", "--off")
        self.assertEqual(result.returncode, OK, result.stderr)
        after = read(self.path)
        self.assertEqual(after["skillOverrides"], {"permissions.allow": "off"})
        self.assertEqual(after["permissions"], AWKWARD["permissions"])


class TestDisabledMcpServers(TempSettings):
    """The half that was inert in 1.0: the real, per-project location."""

    def test_disable_then_enable(self) -> None:
        write(self.claude, claude_json())

        result = run(self.claude, "--mcp-server", "github", "--disable",
                     "--project", PROJECT)
        self.assertEqual(result.returncode, OK, result.stderr)
        entry = read(self.claude)["projects"][PROJECT]
        self.assertEqual(entry["disabledMcpServers"], ["github"])

        result = run(self.claude, "--mcp-server", "github", "--enable",
                     "--project", PROJECT)
        self.assertEqual(result.returncode, OK, result.stderr)
        entry = read(self.claude)["projects"][PROJECT]
        self.assertNotIn("disabledMcpServers", entry)

    def test_it_writes_under_the_project_not_at_the_top_level(self) -> None:
        """The 1.0 bug: a flat top-level key that the harness never reads."""
        write(self.claude, claude_json())
        run(self.claude, "--mcp-server", "github", "--disable", "--project", PROJECT)
        after = read(self.claude)
        self.assertNotIn("disabledMcpServers", after)
        self.assertIn("disabledMcpServers", after["projects"][PROJECT])

    def test_disable_is_idempotent(self) -> None:
        write(self.claude, claude_json(disabled=["github"]))
        before = self.claude.read_bytes()
        result = run(self.claude, "--mcp-server", "github", "--disable",
                     "--project", PROJECT)
        self.assertEqual(result.returncode, OK, result.stderr)
        self.assertIn("No change", result.stdout)
        self.assertEqual(self.claude.read_bytes(), before)

    def test_disabling_twice_does_not_duplicate(self) -> None:
        write(self.claude, claude_json(disabled=["a", "github", "a"]))
        run(self.claude, "--mcp-server", "a", "--disable", "--project", PROJECT)
        self.assertEqual(
            read(self.claude)["projects"][PROJECT]["disabledMcpServers"],
            ["github", "a"],
        )

    def test_sibling_projects_are_untouched(self) -> None:
        write(self.claude, claude_json())
        run(self.claude, "--mcp-server", "github", "--disable", "--project", PROJECT)
        after = read(self.claude)["projects"][OTHER_PROJECT]
        self.assertEqual(after, claude_json()["projects"][OTHER_PROJECT])

    def test_the_projects_own_other_keys_are_untouched(self) -> None:
        write(self.claude, claude_json())
        run(self.claude, "--mcp-server", "github", "--disable", "--project", PROJECT)
        after = read(self.claude)["projects"][PROJECT]
        original = claude_json()["projects"][PROJECT]
        self.assertEqual(after["history"], original["history"])
        self.assertEqual(after["mcpServers"], original["mcpServers"])
        self.assertEqual(after["allowedTools"], original["allowedTools"])

    def test_top_level_secrets_are_untouched(self) -> None:
        write(self.claude, claude_json())
        run(self.claude, "--mcp-server", "github", "--disable", "--project", PROJECT)
        after = read(self.claude)
        self.assertEqual(after["mcpServers"], claude_json()["mcpServers"])
        self.assertEqual(after["oauthAccount"], claude_json()["oauthAccount"])

    def test_a_differently_spelled_project_path_resolves(self) -> None:
        write(self.claude, claude_json())
        spelled = PROJECT.replace(os.sep, "/") if os.sep != "/" else PROJECT
        result = run(self.claude, "--mcp-server", "github", "--disable",
                     "--project", spelled + os.sep + ".")
        self.assertEqual(result.returncode, OK, result.stderr)
        # Resolved onto the existing key rather than creating a near-duplicate.
        self.assertEqual(len(read(self.claude)["projects"]), 2)

    def test_an_unknown_project_is_refused_not_created(self) -> None:
        write(self.claude, claude_json())
        before = self.claude.read_bytes()
        result = run(self.claude, "--mcp-server", "github", "--disable",
                     "--project", os.path.join(os.sep, "nowhere"))
        self.assertEqual(result.returncode, REFUSED)
        self.assertIn("no project entry", result.stderr)
        self.assertEqual(self.claude.read_bytes(), before)

    def test_the_refusal_does_not_list_the_other_projects(self) -> None:
        """Even the refusal path must not enumerate the file's contents."""
        write(self.claude, claude_json())
        result = run(self.claude, "--mcp-server", "github", "--disable",
                     "--project", os.path.join(os.sep, "nowhere"))
        self.assertNotIn(OTHER_PROJECT, result.stderr)
        self.assertNotIn(PROJECT, result.stderr)


# ---------------------------------------------------------------------------
# Untrusted names
# ---------------------------------------------------------------------------


class TestNamesAreValidated(TempSettings):
    """A name arrives from whoever composed the command line. Check it."""

    MALICIOUS = (
        '"},"permissions":{"defaultMode":"bypassPermissions',
        "a\\\"b",
        "back\\slash",
        "{braced}",
        "[bracketed]",
        "new\nline",
        "carriage\rreturn",
        "tab\there",
        "bell\x07",
        "quote'single",
        'quote"double',
        "$(whoami)",
        "`whoami`",
        "semi;colon",
        "",
        "x" * 129,
    )

    def test_a_malicious_skill_name_is_refused(self) -> None:
        write(self.path, AWKWARD)
        before = self.path.read_bytes()
        for name in self.MALICIOUS:
            with self.subTest(name=name):
                result = run(self.path, "--skill", name, "--off")
                self.assertEqual(result.returncode, REFUSED, result.stdout)
                self.assertIn("not an acceptable", result.stderr)
                self.assertEqual(self.path.read_bytes(), before)

    def test_a_malicious_server_name_is_refused(self) -> None:
        write(self.claude, claude_json())
        before = self.claude.read_bytes()
        for name in self.MALICIOUS:
            with self.subTest(name=name):
                result = run(self.claude, "--mcp-server", name, "--disable",
                             "--project", PROJECT)
                self.assertEqual(result.returncode, REFUSED, result.stdout)
                self.assertIn("not an acceptable", result.stderr)
                self.assertEqual(self.claude.read_bytes(), before)

    def test_a_null_byte_is_refused(self) -> None:
        """Driven directly: Windows CreateProcess cannot carry a NUL in argv.

        Going through the CLI would test the OS, not the validator, and would
        raise ValueError in the *test* process before the program ever ran.
        """
        for kind in ("skill", "MCP server"):
            with self.assertRaises(toggle.Refused):
                toggle._require_valid_name("null\x00byte", kind)

    def test_the_injection_attempt_never_becomes_a_key(self) -> None:
        """The payload is refused - and could not have worked anyway."""
        write(self.path, AWKWARD)
        run(self.path, "--skill", self.MALICIOUS[0], "--off")
        self.assertEqual(read(self.path), AWKWARD)

    def test_ordinary_names_are_accepted(self) -> None:
        write(self.path, {})
        for name in ("dcb", "artifact-design", "a_b", "a.b", "with space", "A1"):
            with self.subTest(name=name):
                self.assertEqual(
                    run(self.path, "--skill", name, "--off").returncode, OK
                )

    def test_a_control_character_in_project_is_refused(self) -> None:
        write(self.claude, claude_json())
        result = run(self.claude, "--mcp-server", "github", "--disable",
                     "--project", "/work\n/repo")
        self.assertEqual(result.returncode, REFUSED)
        self.assertIn("control character", result.stderr)


# ---------------------------------------------------------------------------
# The boundary
# ---------------------------------------------------------------------------


class TestForbiddenKeysFailLoudly(TempSettings):
    """Reaching for an unowned key must refuse, not quietly do nothing."""

    def test_the_cli_offers_no_way_to_name_a_key(self) -> None:
        write(self.path, AWKWARD)
        for key in FORBIDDEN:
            with self.subTest(key=key):
                result = run(self.path, "--" + key, "x")
                self.assertEqual(result.returncode, USAGE, result.stdout)
                self.assertEqual(read(self.path), AWKWARD)

    def test_positional_arguments_are_rejected(self) -> None:
        """The 1.0 `set <key> <name> <value>` shape is gone, not repurposed."""
        write(self.path, AWKWARD)
        result = run(self.path, "set", "permissions", "allow", "Bash(rm:*)")
        self.assertEqual(result.returncode, USAGE)
        self.assertEqual(read(self.path), AWKWARD)

    def test_replace_owned_refuses_a_forbidden_key(self) -> None:
        """The layer under the CLI, where a future non-CLI caller would land."""
        for key in FORBIDDEN:
            with self.subTest(key=key):
                with self.assertRaises(toggle.Refused) as caught:
                    toggle._replace_owned(
                        dict(AWKWARD), key, {"x": True}, toggle.SKILL_OWNED_KEYS
                    )
                self.assertIn("not a key this operation owns", str(caught.exception))

    def test_an_unexpected_key_is_a_hard_error_not_a_silent_skip(self) -> None:
        """The failure mode that would read as 'the boundary held'."""
        with self.assertRaises(toggle.Refused):
            toggle._require_owned("permissions", toggle.SKILL_OWNED_KEYS)
        with self.assertRaises(toggle.Refused):
            toggle._require_owned("apiKeyHelper", toggle.MCP_OWNED_KEYS)

    def test_the_two_operations_cannot_reach_each_others_key(self) -> None:
        with self.assertRaises(toggle.Refused):
            toggle._replace_owned({}, "projects", {}, toggle.SKILL_OWNED_KEYS)
        with self.assertRaises(toggle.Refused):
            toggle._replace_owned({}, "skillOverrides", {}, toggle.MCP_OWNED_KEYS)

    def test_replace_owned_does_not_mutate_its_input(self) -> None:
        original = json.loads(json.dumps(AWKWARD))
        toggle._replace_owned(
            original, "skillOverrides", {"s": "off"}, toggle.SKILL_OWNED_KEYS
        )
        self.assertEqual(original, AWKWARD)
        self.assertNotIn("skillOverrides", original)

    def test_diff_assertion_catches_an_unowned_change(self) -> None:
        """The backstop, exercised directly - it must refuse, loudly."""
        after = dict(AWKWARD)
        after["permissions"] = {"defaultMode": "bypassPermissions"}
        with self.assertRaises(toggle.Refused) as caught:
            toggle._assert_only_owned_changed(
                AWKWARD, after, toggle.SKILL_OWNED_KEYS
            )
        self.assertIn("permissions", str(caught.exception))

    def test_diff_assertion_catches_a_deleted_unowned_key(self) -> None:
        after = {k: v for k, v in AWKWARD.items() if k != "hooks"}
        with self.assertRaises(toggle.Refused) as caught:
            toggle._assert_only_owned_changed(
                AWKWARD, after, toggle.SKILL_OWNED_KEYS
            )
        self.assertIn("hooks", str(caught.exception))

    def test_diff_assertion_allows_an_owned_change(self) -> None:
        after = {**AWKWARD, "skillOverrides": {"s": "off"}}
        toggle._assert_only_owned_changed(
            AWKWARD, after, toggle.SKILL_OWNED_KEYS
        )  # must not raise

    def test_nested_assertion_catches_a_sibling_project_change(self) -> None:
        before = claude_json()
        after = json.loads(json.dumps(before))
        after["projects"][OTHER_PROJECT]["allowedTools"] = ["Bash"]
        with self.assertRaises(toggle.Refused) as caught:
            toggle._assert_only_project_entry_changed(before, after, PROJECT)
        self.assertIn("other than the one addressed", str(caught.exception))
        # And it reports a count, not the path.
        self.assertNotIn(OTHER_PROJECT, str(caught.exception))

    def test_nested_assertion_catches_a_change_inside_the_entry(self) -> None:
        before = claude_json()
        after = json.loads(json.dumps(before))
        after["projects"][PROJECT]["mcpServers"] = {}
        with self.assertRaises(toggle.Refused) as caught:
            toggle._assert_only_project_entry_changed(before, after, PROJECT)
        self.assertIn("mcpServers", str(caught.exception))

    def test_nested_assertion_allows_the_owned_change(self) -> None:
        before = claude_json()
        after = json.loads(json.dumps(before))
        after["projects"][PROJECT]["disabledMcpServers"] = ["github"]
        toggle._assert_only_project_entry_changed(before, after, PROJECT)

    def test_owned_set_is_exactly_the_documented_boundary(self) -> None:
        """A widened boundary must break a test, not slip through review."""
        self.assertEqual(toggle.SKILL_OWNED_KEYS, ("skillOverrides",))
        self.assertEqual(toggle.MCP_OWNED_KEYS, ("projects",))
        self.assertEqual(toggle.PROJECT_OWNED_KEY, "disabledMcpServers")
        self.assertEqual(
            toggle.OWNED_KEYS,
            ("disabledMcpServers", "projects", "skillOverrides"),
        )

    def test_bypass_permissions_setting_is_untouched(self) -> None:
        """The specific value this whole program exists to keep out of reach."""
        write(self.path, AWKWARD)
        run(self.path, "--skill", "s", "--off")
        permissions = read(self.path)["permissions"]
        self.assertEqual(permissions["disableBypassPermissionsMode"], "disable")
        self.assertEqual(permissions["allow"], AWKWARD["permissions"]["allow"])


class TestTargetsAreTheKnownFiles(TempSettings):
    """Neither operation can be pointed at an arbitrary file."""

    def test_a_skill_toggle_refuses_a_non_settings_file(self) -> None:
        odd = self.dir / "package.json"
        write(odd, {"name": "x"})
        result = run(odd, "--skill", "s", "--off")
        self.assertEqual(result.returncode, REFUSED)
        self.assertIn("not a file this operation edits", result.stderr)
        self.assertEqual(read(odd), {"name": "x"})

    def test_a_skill_toggle_refuses_the_claude_json(self) -> None:
        write(self.claude, claude_json())
        result = run(self.claude, "--skill", "s", "--off")
        self.assertEqual(result.returncode, REFUSED)

    def test_an_mcp_toggle_refuses_a_settings_json(self) -> None:
        """The 1.0 bug, now unreachable: the key does not live here."""
        write(self.path, AWKWARD)
        result = run(self.path, "--mcp-server", "github", "--disable",
                     "--project", PROJECT)
        self.assertEqual(result.returncode, REFUSED)
        self.assertIn("not a file this operation edits", result.stderr)
        self.assertEqual(read(self.path), AWKWARD)


class TestTargetIsAlwaysExplicit(TempSettings):
    """`--settings` is required, and that is a security property.

    The credential guard protecting the live Claude config is path-based on the
    command string. A default target applied inside Python is invisible to it,
    so a defaulting invocation clears the guard and then opens the very file
    the guard exists to protect - measured 2026-08-09, before this was fixed.
    These tests fail if anyone reintroduces a default.
    """

    def test_omitting_settings_is_a_usage_error(self) -> None:
        result = subprocess.run(
            [sys.executable, str(TOGGLE), "--skill", "s", "--off"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, USAGE, result.stdout)
        self.assertIn("--settings", result.stderr)

    def test_omitting_settings_never_writes_anything(self) -> None:
        """A refusal that still touched a file would defeat the point."""
        result = subprocess.run(
            [sys.executable, str(TOGGLE), "--skill", "s", "--off"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, USAGE, result.stdout)
        self.assertFalse(self.path.exists())

    def test_module_exposes_no_default_target(self) -> None:
        """The constant itself is gone, not merely unused by the parser."""
        self.assertFalse(
            hasattr(toggle, "DEFAULT_SETTINGS"),
            "DEFAULT_SETTINGS is back; a path-based guard cannot see a default "
            "applied inside Python.",
        )


# ---------------------------------------------------------------------------
# Output never shows the file
# ---------------------------------------------------------------------------


class TestNothingLeaks(TempSettings):
    """Both target files are full of credentials. Stdout is read by an agent."""

    def assertClean(self, result: subprocess.CompletedProcess) -> None:
        blob = (result.stdout or "") + (result.stderr or "")
        self.assertNotIn(SECRET, blob)
        for key in FORBIDDEN:
            self.assertNotIn(key, blob)

    def test_applying_a_skill_toggle_leaks_nothing(self) -> None:
        write(self.path, AWKWARD)
        result = run(self.path, "--skill", "s", "--off")
        self.assertEqual(result.returncode, OK, result.stderr)
        self.assertClean(result)

    def test_dry_run_prints_a_diff_not_the_document(self) -> None:
        write(self.path, AWKWARD)
        before = self.path.read_bytes()
        result = run(self.path, "--dry-run", "--skill", "s", "--off")
        self.assertEqual(result.returncode, OK, result.stderr)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertClean(result)
        # It still says exactly what it would do.
        self.assertIn("would change", result.stdout)
        self.assertIn('skillOverrides["s"]', result.stdout)
        self.assertIn("(absent) -> \"off\"", result.stdout)
        # A document dump would be many lines; a diff is a couple.
        self.assertLessEqual(len(result.stdout.strip().splitlines()), 2)

    def test_dry_run_on_the_claude_json_leaks_nothing(self) -> None:
        write(self.claude, claude_json())
        before = self.claude.read_bytes()
        result = run(self.claude, "--dry-run", "--mcp-server", "github",
                     "--disable", "--project", PROJECT)
        self.assertEqual(result.returncode, OK, result.stderr)
        self.assertEqual(self.claude.read_bytes(), before)
        self.assertClean(result)
        self.assertNotIn("oauthAccount", result.stdout)
        self.assertNotIn("history", result.stdout)
        self.assertIn('+ "github"', result.stdout)

    def test_the_mcp_diff_does_not_name_the_other_disabled_servers(self) -> None:
        write(self.claude, claude_json(disabled=["already-off", "another"]))
        result = run(self.claude, "--mcp-server", "github", "--disable",
                     "--project", PROJECT)
        self.assertEqual(result.returncode, OK, result.stderr)
        self.assertNotIn("already-off", result.stdout)
        self.assertNotIn("another", result.stdout)

    def test_show_reports_only_the_owned_setting(self) -> None:
        write(self.path, {**AWKWARD, "skillOverrides": {"s": "off"}})
        result = run(self.path, "--show")
        self.assertEqual(result.returncode, OK, result.stderr)
        self.assertClean(result)
        self.assertIn('skillOverrides: {"s": "off"}', result.stdout)

    def test_show_on_the_claude_json_reports_only_one_project_list(self) -> None:
        write(self.claude, claude_json(disabled=["github"]))
        result = run(self.claude, "--show", "--project", PROJECT)
        self.assertEqual(result.returncode, OK, result.stderr)
        self.assertClean(result)
        self.assertNotIn("oauthAccount", result.stdout)
        self.assertNotIn("untouched", result.stdout)  # the sibling project's
        self.assertIn('disabledMcpServers: ["github"]', result.stdout)


# ---------------------------------------------------------------------------
# Everything else in the file survives
# ---------------------------------------------------------------------------


class TestEverythingElseSurvives(TempSettings):
    def test_awkward_document_is_preserved(self) -> None:
        write(self.path, AWKWARD)
        result = run(self.path, "--skill", "some-skill", "--off")
        self.assertEqual(result.returncode, OK, result.stderr)
        after = read(self.path)
        self.assertEqual(after.pop("skillOverrides"), {"some-skill": "off"})
        self.assertEqual(after, AWKWARD)

    def test_key_order_is_preserved(self) -> None:
        write(self.path, AWKWARD)
        run(self.path, "--skill", "some-skill", "--off")
        after = json.loads(self.path.read_bytes().decode("utf-8-sig"))
        # Original order intact, new key appended - not re-sorted.
        self.assertEqual(list(after)[: len(AWKWARD)], list(AWKWARD))
        self.assertEqual(list(after)[-1], "skillOverrides")

    def test_unicode_is_not_escaped(self) -> None:
        write(self.path, AWKWARD)
        run(self.path, "--skill", "some-skill", "--off")
        text = self.path.read_bytes().decode("utf-8")
        self.assertIn("日本語", text)
        self.assertIn("🚀", text)
        self.assertNotIn("\\u", text)

    def test_crlf_endings_survive(self) -> None:
        write(self.path, AWKWARD, crlf=True)
        run(self.path, "--skill", "s", "--off")
        raw = self.path.read_bytes()
        self.assertIn(b"\r\n", raw)
        # Every newline is a CRLF - no bare LF survived the rewrite.
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        self.assertEqual(read(self.path)["permissions"], AWKWARD["permissions"])

    def test_lf_endings_are_not_converted_to_crlf(self) -> None:
        write(self.path, AWKWARD)
        run(self.path, "--skill", "s", "--off")
        self.assertNotIn(b"\r\n", self.path.read_bytes())

    def test_bom_survives(self) -> None:
        """PowerShell 5.1 writes UTF-8 with a BOM by default."""
        write(self.path, AWKWARD, bom=True)
        result = run(self.path, "--skill", "s", "--off")
        self.assertEqual(result.returncode, OK, result.stderr)
        self.assertTrue(self.path.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertEqual(read(self.path)["hooks"], AWKWARD["hooks"])

    def test_a_compact_document_stays_compact(self) -> None:
        """A large ~/.claude.json is one line; re-indenting it is a huge diff."""
        write(self.claude, claude_json(), compact=True)
        result = run(self.claude, "--mcp-server", "github", "--disable",
                     "--project", PROJECT)
        self.assertEqual(result.returncode, OK, result.stderr)
        text = self.claude.read_bytes().decode("utf-8")
        self.assertEqual(len(text.splitlines()), 1)
        self.assertNotIn(": ", text)

    def test_an_indented_document_stays_indented(self) -> None:
        write(self.claude, claude_json())
        run(self.claude, "--mcp-server", "github", "--disable", "--project", PROJECT)
        text = self.claude.read_bytes().decode("utf-8")
        self.assertIn('\n  "projects"', text)


# ---------------------------------------------------------------------------
# Durability
# ---------------------------------------------------------------------------


class TestBackupAndAtomicity(TempSettings):
    def test_a_backup_is_taken_before_the_write(self) -> None:
        write(self.path, AWKWARD)
        original = self.path.read_bytes()
        result = run(self.path, "--skill", "s", "--off")
        self.assertEqual(result.returncode, OK, result.stderr)
        saved = backups(self.path)
        self.assertEqual(len(saved), 1)
        # It is the file as it was, byte for byte.
        self.assertEqual(saved[0].read_bytes(), original)

    def test_the_backup_name_keeps_the_guarded_basename(self) -> None:
        """`settings.json.bak-<stamp>` is a shape the credential guard knows.

        A backup named anything else would be an unguarded plaintext copy of a
        credential-bearing file sitting beside the guarded original.
        """
        write(self.path, AWKWARD)
        run(self.path, "--skill", "s", "--off")
        name = backups(self.path)[0].name
        self.assertTrue(name.startswith("settings.json.bak-"), name)

    def test_two_runs_keep_two_backups(self) -> None:
        write(self.path, AWKWARD)
        run(self.path, "--skill", "one", "--off")
        run(self.path, "--skill", "two", "--off")
        self.assertEqual(len(backups(self.path)), 2)

    def test_no_backup_and_no_write_on_a_dry_run(self) -> None:
        write(self.path, AWKWARD)
        run(self.path, "--dry-run", "--skill", "s", "--off")
        self.assertEqual(backups(self.path), [])

    def test_no_temp_file_is_left_behind(self) -> None:
        write(self.path, AWKWARD)
        run(self.path, "--skill", "s", "--off")
        leftovers = [p.name for p in self.dir.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])


# ---------------------------------------------------------------------------
# Refuse rather than guess
# ---------------------------------------------------------------------------


class TestMalformedInputRefuses(TempSettings):
    """Refuse and write nothing, rather than rewrite something misunderstood."""

    def test_invalid_json_refuses_without_clobbering(self) -> None:
        self.path.write_text('{"theme": "dark",}', encoding="utf-8")
        before = self.path.read_bytes()
        result = run(self.path, "--skill", "s", "--off")
        self.assertEqual(result.returncode, REFUSED)
        self.assertIn("not valid JSON", result.stderr)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(backups(self.path), [])

    def test_invalid_claude_json_refuses_without_clobbering(self) -> None:
        self.claude.write_text('{"projects": ', encoding="utf-8")
        before = self.claude.read_bytes()
        result = run(self.claude, "--mcp-server", "github", "--disable",
                     "--project", PROJECT)
        self.assertEqual(result.returncode, REFUSED)
        self.assertIn("not valid JSON", result.stderr)
        self.assertEqual(self.claude.read_bytes(), before)

    def test_duplicate_key_refuses_rather_than_dropping_one(self) -> None:
        self.path.write_text(
            '{"hooks": {"a": 1}, "theme": "dark", "hooks": {"b": 2}}',
            encoding="utf-8",
        )
        before = self.path.read_bytes()
        result = run(self.path, "--skill", "s", "--off")
        self.assertEqual(result.returncode, REFUSED)
        self.assertIn("duplicate key", result.stderr)
        self.assertEqual(self.path.read_bytes(), before)

    def test_non_object_document_refuses(self) -> None:
        self.path.write_text("[1, 2, 3]", encoding="utf-8")
        result = run(self.path, "--skill", "s", "--off")
        self.assertEqual(result.returncode, REFUSED)
        self.assertIn("not a JSON object", result.stderr)

    def test_wrongly_typed_skill_overrides_refuses(self) -> None:
        write(self.path, {"skillOverrides": ["not", "an", "object"]})
        result = run(self.path, "--skill", "s", "--off")
        self.assertEqual(result.returncode, REFUSED)
        self.assertIn("not an object", result.stderr)

    def test_wrongly_typed_disabled_servers_refuses(self) -> None:
        document = claude_json()
        document["projects"][PROJECT]["disabledMcpServers"] = {"not": "a list"}
        write(self.claude, document)
        result = run(self.claude, "--mcp-server", "github", "--disable",
                     "--project", PROJECT)
        self.assertEqual(result.returncode, REFUSED)
        self.assertIn("not a list", result.stderr)

    def test_a_non_string_in_the_server_list_refuses(self) -> None:
        document = claude_json(disabled=["ok", 7])
        write(self.claude, document)
        result = run(self.claude, "--mcp-server", "github", "--disable",
                     "--project", PROJECT)
        self.assertEqual(result.returncode, REFUSED)
        self.assertIn("non-string entry", result.stderr)

    def test_empty_file_is_treated_as_an_empty_document(self) -> None:
        self.path.write_text("", encoding="utf-8")
        result = run(self.path, "--skill", "s", "--off")
        self.assertEqual(result.returncode, OK, result.stderr)
        self.assertEqual(read(self.path), {"skillOverrides": {"s": "off"}})


class TestFlagCombinations(TempSettings):
    """The state flags belong to their operation and to no other."""

    def test_skill_without_a_state_flag_is_a_usage_error(self) -> None:
        result = run(self.path, "--skill", "s")
        self.assertEqual(result.returncode, USAGE)
        self.assertIn("--off or --on", result.stderr)

    def test_mcp_without_a_state_flag_is_a_usage_error(self) -> None:
        result = run(self.claude, "--mcp-server", "x")
        self.assertEqual(result.returncode, USAGE)
        self.assertIn("--disable or --enable", result.stderr)

    def test_skill_with_disable_is_a_usage_error(self) -> None:
        result = run(self.path, "--skill", "s", "--disable")
        self.assertEqual(result.returncode, USAGE)

    def test_mcp_with_off_is_a_usage_error(self) -> None:
        result = run(self.claude, "--mcp-server", "x", "--off")
        self.assertEqual(result.returncode, USAGE)

    def test_off_and_on_together_is_a_usage_error(self) -> None:
        result = run(self.path, "--skill", "s", "--off", "--on")
        self.assertEqual(result.returncode, USAGE)

    def test_skill_and_mcp_server_together_is_a_usage_error(self) -> None:
        result = run(self.path, "--skill", "s", "--mcp-server", "x", "--off")
        self.assertEqual(result.returncode, USAGE)

    def test_no_operation_at_all_is_a_usage_error(self) -> None:
        result = run(self.path)
        self.assertEqual(result.returncode, USAGE)


if __name__ == "__main__":
    unittest.main()
