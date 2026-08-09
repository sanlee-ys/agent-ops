#!/usr/bin/env python3
"""Test suite for scripts/settings-toggle.py.

The program's entire justification is a claim about what it *cannot* do, so the
tests are organised around that claim rather than around its features:

  - the owned keys round-trip, so the convenience half actually works;
  - an unusual-but-valid document survives byte-for-byte in every part the
    program does not own - unicode, nesting, key order, CRLF, a BOM;
  - reaching for a forbidden key fails loudly, at both layers, rather than
    no-opping quietly. A silent no-op is the dangerous outcome here: it reads
    as "the boundary held" while telling you nothing about whether it did.

The forbidden-key cases drive the internals directly as well as the CLI. The
CLI's `choices` restriction is the layer a future edit is most likely to
loosen, so the layer underneath it is tested where a caller would hit it.

Stdlib only (no pytest), matching the other guard suites, so CI stays a bare
`python -m unittest`.
"""
import importlib.util
import json
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
    "env": {"SOME_FLAG": "1"},
    "autoMode": {"environment": ["données: café, naïve, 日本語, emoji 🚀"]},
    "aKeyThatSortsFirst": {"nested": {"deeply": [1, 2, {"three": None}]}},
}

FORBIDDEN = ("permissions", "env", "hooks", "autoMode", "statusLine")


def write(path: Path, document, *, bom: bool = False, crlf: bool = False) -> None:
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
    )


def read(path: Path) -> dict:
    return json.loads(path.read_bytes().decode("utf-8-sig"))


class TempSettings(unittest.TestCase):
    """Each test gets its own settings file in a throwaway directory."""

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.path = Path(self._dir.name) / "settings.json"


class TestOwnedKeysRoundTrip(TempSettings):
    """The convenience half: both owned keys toggle on and back off."""

    def test_skill_override_set_then_unset(self) -> None:
        write(self.path, {"theme": "dark"})

        result = run(self.path, "set", "skillOverrides", "some-skill", "off")
        self.assertEqual(result.returncode, OK, result.stderr)
        self.assertEqual(read(self.path)["skillOverrides"], {"some-skill": "off"})

        result = run(self.path, "unset", "skillOverrides", "some-skill")
        self.assertEqual(result.returncode, OK, result.stderr)
        # Emptied out entirely rather than left as a `{}` husk.
        self.assertNotIn("skillOverrides", read(self.path))
        self.assertEqual(read(self.path), {"theme": "dark"})

    def test_every_documented_skill_override_value(self) -> None:
        write(self.path, {})
        for value in toggle.SKILL_OVERRIDE_VALUES:
            result = run(self.path, "set", "skillOverrides", "s", value)
            self.assertEqual(result.returncode, OK, result.stderr)
            self.assertEqual(read(self.path)["skillOverrides"]["s"], value)

    def test_skill_override_rejects_an_unrecognised_value(self) -> None:
        write(self.path, {"theme": "dark"})
        result = run(self.path, "set", "skillOverrides", "some-skill", "enabled")
        self.assertEqual(result.returncode, REFUSED)
        self.assertIn("not a recognised skill override", result.stderr)
        self.assertEqual(read(self.path), {"theme": "dark"})

    def test_disabled_server_set_then_unset(self) -> None:
        write(self.path, {"theme": "dark"})

        result = run(self.path, "set", "disabledMcpServers", "some-server")
        self.assertEqual(result.returncode, OK, result.stderr)
        self.assertEqual(read(self.path)["disabledMcpServers"], ["some-server"])

        result = run(self.path, "unset", "disabledMcpServers", "some-server")
        self.assertEqual(result.returncode, OK, result.stderr)
        self.assertNotIn("disabledMcpServers", read(self.path))

    def test_disabling_twice_does_not_duplicate(self) -> None:
        write(self.path, {"disabledMcpServers": ["a", "b", "a"]})
        result = run(self.path, "set", "disabledMcpServers", "a")
        self.assertEqual(result.returncode, OK, result.stderr)
        self.assertEqual(read(self.path)["disabledMcpServers"], ["b", "a"])

    def test_disabled_servers_takes_no_value(self) -> None:
        write(self.path, {})
        result = run(self.path, "set", "disabledMcpServers", "some-server", "off")
        self.assertEqual(result.returncode, REFUSED)
        self.assertIn("takes no value", result.stderr)

    def test_missing_file_is_created(self) -> None:
        self.assertFalse(self.path.exists())
        result = run(self.path, "set", "skillOverrides", "s", "off")
        self.assertEqual(result.returncode, OK, result.stderr)
        self.assertEqual(read(self.path), {"skillOverrides": {"s": "off"}})

    def test_show_reports_only_the_owned_keys(self) -> None:
        write(self.path, {**AWKWARD, "skillOverrides": {"s": "name-only"}})
        result = run(self.path, "show")
        self.assertEqual(result.returncode, OK, result.stderr)
        body = result.stdout.split("\n", 1)[1]
        self.assertEqual(json.loads(body), {"skillOverrides": {"s": "name-only"}})
        for key in FORBIDDEN:
            self.assertNotIn(key, body)


class TestEverythingElseSurvives(TempSettings):
    """An unusual-but-valid document comes back unchanged but for the one key."""

    def test_awkward_document_is_preserved(self) -> None:
        write(self.path, AWKWARD)
        result = run(self.path, "set", "skillOverrides", "some-skill", "off")
        self.assertEqual(result.returncode, OK, result.stderr)

        after = read(self.path)
        self.assertEqual(after.pop("skillOverrides"), {"some-skill": "off"})
        self.assertEqual(after, AWKWARD)

    def test_key_order_is_preserved(self) -> None:
        write(self.path, AWKWARD)
        run(self.path, "set", "skillOverrides", "some-skill", "off")
        after = json.loads(self.path.read_bytes().decode("utf-8-sig"))
        # Original order intact, new key appended - not re-sorted.
        self.assertEqual(list(after)[: len(AWKWARD)], list(AWKWARD))
        self.assertEqual(list(after)[-1], "skillOverrides")

    def test_unicode_is_not_escaped(self) -> None:
        write(self.path, AWKWARD)
        run(self.path, "set", "skillOverrides", "some-skill", "off")
        text = self.path.read_bytes().decode("utf-8")
        self.assertIn("日本語", text)
        self.assertIn("🚀", text)
        self.assertNotIn("\\u", text)

    def test_crlf_endings_survive(self) -> None:
        write(self.path, AWKWARD, crlf=True)
        run(self.path, "set", "skillOverrides", "some-skill", "off")
        raw = self.path.read_bytes()
        self.assertIn(b"\r\n", raw)
        # Every newline is a CRLF - no bare LF survived the rewrite.
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        self.assertEqual(read(self.path)["permissions"], AWKWARD["permissions"])

    def test_lf_endings_are_not_converted_to_crlf(self) -> None:
        write(self.path, AWKWARD)
        run(self.path, "set", "skillOverrides", "some-skill", "off")
        self.assertNotIn(b"\r\n", self.path.read_bytes())

    def test_bom_survives(self) -> None:
        """PowerShell 5.1 writes UTF-8 with a BOM by default."""
        write(self.path, AWKWARD, bom=True)
        result = run(self.path, "set", "skillOverrides", "some-skill", "off")
        self.assertEqual(result.returncode, OK, result.stderr)
        self.assertTrue(self.path.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertEqual(read(self.path)["hooks"], AWKWARD["hooks"])

    def test_bypass_permissions_setting_is_untouched(self) -> None:
        """The specific value this whole program exists to keep out of reach."""
        write(self.path, AWKWARD)
        run(self.path, "set", "disabledMcpServers", "some-server")
        permissions = read(self.path)["permissions"]
        self.assertEqual(permissions["disableBypassPermissionsMode"], "disable")
        self.assertEqual(permissions["allow"], AWKWARD["permissions"]["allow"])

    def test_a_no_op_edit_leaves_the_file_byte_identical(self) -> None:
        write(self.path, {**AWKWARD, "skillOverrides": {"s": "off"}}, crlf=True)
        before = self.path.read_bytes()
        result = run(self.path, "set", "skillOverrides", "s", "off")
        self.assertEqual(result.returncode, OK, result.stderr)
        self.assertIn("No change", result.stdout)
        self.assertEqual(self.path.read_bytes(), before)

    def test_dry_run_writes_nothing(self) -> None:
        write(self.path, AWKWARD)
        before = self.path.read_bytes()
        result = run(self.path, "--dry-run", "set", "skillOverrides", "s", "off")
        self.assertEqual(result.returncode, OK, result.stderr)
        self.assertIn("skillOverrides", result.stdout)
        self.assertEqual(self.path.read_bytes(), before)

    def test_no_temp_file_is_left_behind(self) -> None:
        write(self.path, AWKWARD)
        run(self.path, "set", "skillOverrides", "s", "off")
        self.assertEqual(
            [p.name for p in self.path.parent.iterdir()], ["settings.json"]
        )


class TestForbiddenKeysFailLoudly(TempSettings):
    """Reaching for an unowned key must refuse, not quietly do nothing."""

    def test_cli_refuses_each_forbidden_key_by_name(self) -> None:
        write(self.path, AWKWARD)
        for key in FORBIDDEN:
            with self.subTest(key=key):
                result = run(self.path, "set", key, "anything", "value")
                # argparse `choices` - a usage error, not a silent success.
                self.assertEqual(result.returncode, USAGE)
                self.assertIn("invalid choice", result.stderr)
                # The refusal names the boundary rather than just complaining.
                self.assertIn("skillOverrides", result.stderr)
                self.assertEqual(read(self.path), AWKWARD)

    def test_replace_owned_refuses_a_forbidden_key(self) -> None:
        """The layer under the CLI, where a future non-CLI caller would land."""
        for key in FORBIDDEN:
            with self.subTest(key=key):
                with self.assertRaises(toggle.Refused) as caught:
                    toggle._replace_owned(dict(AWKWARD), key, {"anything": True})
                self.assertIn("not a key this program owns", str(caught.exception))

    def test_apply_refuses_a_forbidden_key(self) -> None:
        with self.assertRaises(toggle.Refused):
            toggle._apply(dict(AWKWARD), "permissions", "allow", "x", remove=False)

    def test_replace_owned_does_not_mutate_its_input(self) -> None:
        original = json.loads(json.dumps(AWKWARD))
        toggle._replace_owned(original, "skillOverrides", {"s": "off"})
        self.assertEqual(original, AWKWARD)
        self.assertNotIn("skillOverrides", original)

    def test_diff_assertion_catches_an_unowned_change(self) -> None:
        """The backstop, exercised directly - it must refuse, loudly."""
        after = dict(AWKWARD)
        after["permissions"] = {"defaultMode": "bypassPermissions"}
        with self.assertRaises(toggle.Refused) as caught:
            toggle._assert_only_owned_changed(AWKWARD, after)
        self.assertIn("permissions", str(caught.exception))

    def test_diff_assertion_catches_a_deleted_unowned_key(self) -> None:
        after = {k: v for k, v in AWKWARD.items() if k != "hooks"}
        with self.assertRaises(toggle.Refused) as caught:
            toggle._assert_only_owned_changed(AWKWARD, after)
        self.assertIn("hooks", str(caught.exception))

    def test_diff_assertion_allows_an_owned_change(self) -> None:
        after = {**AWKWARD, "skillOverrides": {"s": "off"}}
        toggle._assert_only_owned_changed(AWKWARD, after)  # must not raise

    def test_owned_set_is_exactly_the_two_documented_keys(self) -> None:
        """A widened boundary must break a test, not slip through review."""
        self.assertEqual(
            sorted(toggle.OWNED_KEYS), ["disabledMcpServers", "skillOverrides"]
        )

    def test_a_dotted_name_cannot_escape_its_owned_key(self) -> None:
        """A crafted name stays a name; it is not a path into the document."""
        write(self.path, AWKWARD)
        result = run(
            self.path, "set", "skillOverrides", "permissions.allow", "off"
        )
        self.assertEqual(result.returncode, OK, result.stderr)
        after = read(self.path)
        self.assertEqual(after["skillOverrides"], {"permissions.allow": "off"})
        self.assertEqual(after["permissions"], AWKWARD["permissions"])


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
            [sys.executable, str(TOGGLE), "show"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, USAGE, result.stdout)
        self.assertIn("--settings", result.stderr)

    def test_omitting_settings_never_writes_anything(self) -> None:
        """A refusal that still touched a file would defeat the point."""
        result = subprocess.run(
            [sys.executable, str(TOGGLE), "set", "skillOverrides", "s", "off"],
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


class TestMalformedInputRefuses(TempSettings):
    """Refuse and write nothing, rather than rewrite something misunderstood."""

    def test_invalid_json_refuses(self) -> None:
        self.path.write_text('{"theme": "dark",}', encoding="utf-8")
        before = self.path.read_bytes()
        result = run(self.path, "set", "skillOverrides", "s", "off")
        self.assertEqual(result.returncode, REFUSED)
        self.assertIn("not valid JSON", result.stderr)
        self.assertEqual(self.path.read_bytes(), before)

    def test_duplicate_key_refuses_rather_than_dropping_one(self) -> None:
        self.path.write_text(
            '{"hooks": {"a": 1}, "theme": "dark", "hooks": {"b": 2}}',
            encoding="utf-8",
        )
        before = self.path.read_bytes()
        result = run(self.path, "set", "skillOverrides", "s", "off")
        self.assertEqual(result.returncode, REFUSED)
        self.assertIn("duplicate key", result.stderr)
        self.assertEqual(self.path.read_bytes(), before)

    def test_non_object_document_refuses(self) -> None:
        self.path.write_text("[1, 2, 3]", encoding="utf-8")
        result = run(self.path, "set", "skillOverrides", "s", "off")
        self.assertEqual(result.returncode, REFUSED)
        self.assertIn("not a JSON object", result.stderr)

    def test_wrongly_typed_owned_key_refuses(self) -> None:
        write(self.path, {"skillOverrides": ["not", "an", "object"]})
        result = run(self.path, "set", "skillOverrides", "s", "off")
        self.assertEqual(result.returncode, REFUSED)
        self.assertIn("not an object", result.stderr)

    def test_empty_file_is_treated_as_an_empty_document(self) -> None:
        self.path.write_text("", encoding="utf-8")
        result = run(self.path, "set", "skillOverrides", "s", "off")
        self.assertEqual(result.returncode, OK, result.stderr)
        self.assertEqual(read(self.path), {"skillOverrides": {"s": "off"}})


if __name__ == "__main__":
    unittest.main()
