#!/usr/bin/env python3
"""Test suite for hooks/config-change-guard.py.

The guard is a POST-CHANGE STATE check: the `ConfigChange` payload carries only
`config_source` and `config_path`, so the guard reads the file at that path and
asks whether the guard chain is intact *now*. These tests therefore drive it the
way the harness does — a JSON payload on stdin — against real settings files
written to a temp dir.

What is proved here is the guard's *logic*, and only that. Whether the harness
fires `ConfigChange` at all, and whether the block verdict actually vetoes the
change, are separate facts that a unit test cannot reach; both are unmeasured and
recorded as such in `hooks/README.md`. A green suite here means "the guard would
refuse the right things if it ran", not "the guard is enforcing anything".

Three groups:

  - **Blocked.** A watched scope whose resulting file has lost a guard, or has
    `disableAllHooks` set.
  - **Allowed.** The far more important half. This guard sits on the one file a
    false positive cannot be repaired from — a wrong block bricks the config,
    and the repair would itself be a config change the guard blocks again. So
    the unwatched scopes, the intact chain, and every malformed input are pinned
    as allowed on purpose.
  - **Fail-open.** Every error path must exit 0 and say why on stderr, because
    silence is indistinguishable from "the hook never fired".

Stdlib only (no pytest) so CI is a bare `python -m unittest`. Verdict shape: the
guard always exits 0 and signals a block with `{"decision": "block"}` on stdout
(the documented JSON form), not with an exit code — so these assert on stdout,
unlike the PreToolUse guards' suites which assert on exit 0/2.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

GUARD = Path(__file__).resolve().parent.parent / "hooks" / "config-change-guard.py"

ALL_GUARDS = (
    "credential-guard",
    "published-history-guard",
    "git-staging-guard",
    "fanout-guard",
)


def settings_with(*guards, **extra):
    """A settings object wiring each named guard, spelled as the live file does."""
    body = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": 'python3 "$HOME/.claude/hooks/%s.py"' % g,
                        }
                    ],
                }
                for g in guards
            ]
        }
    }
    body.update(extra)
    return body


def run(payload, raw=None):
    """Drive the guard as the harness does; return (stdout, stderr)."""
    proc = subprocess.run(
        [sys.executable, str(GUARD)],
        input=raw if raw is not None else json.dumps(payload),
        capture_output=True,
        text=True,
    )
    # The guard's contract is exit 0 always — a non-zero exit would surface as a
    # hook *error* rather than a verdict, which is a different thing entirely.
    assert proc.returncode == 0, "guard exited %d: %s" % (proc.returncode, proc.stderr)
    return proc.stdout, proc.stderr


def blocked(stdout):
    if not stdout.strip():
        return False
    return json.loads(stdout).get("decision") == "block"


class GuardTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write_settings(self, obj, name="settings.json", encoding="utf-8"):
        path = self.tmp / name
        path.write_text(json.dumps(obj, indent=2), encoding=encoding)
        return str(path)

    def check(self, path, source="user_settings"):
        return run({"config_source": source, "config_path": path})


class TestBlockedShapes(GuardTestCase):
    """A watched scope left without part of the chain."""

    def test_one_guard_removed(self):
        path = self.write_settings(settings_with(*ALL_GUARDS[1:]))
        out, err = self.check(path)
        self.assertTrue(blocked(out))
        self.assertIn("credential-guard", out)
        # Mirrored to stderr so it surfaces even where the JSON path is ignored.
        self.assertIn("credential-guard", err)

    def test_every_guard_removed(self):
        path = self.write_settings({"hooks": {}})
        out, _ = self.check(path)
        self.assertTrue(blocked(out))
        for g in ALL_GUARDS:
            self.assertIn(g, out)

    def test_hooks_key_absent_entirely(self):
        path = self.write_settings({"theme": "dark"})
        out, _ = self.check(path)
        self.assertTrue(blocked(out))

    def test_disable_all_hooks(self):
        path = self.write_settings(settings_with(*ALL_GUARDS, disableAllHooks=True))
        out, _ = self.check(path)
        self.assertTrue(blocked(out))
        self.assertIn("disableAllHooks", out)

    def test_policy_settings_is_watched(self):
        """Watched, and the block is emitted — see the caveat below."""
        path = self.write_settings({"hooks": {}})
        out, _ = self.check(path, source="policy_settings")
        self.assertTrue(blocked(out))

    def test_policy_settings_block_is_diagnostic_only(self):
        """Pins the documented limit rather than asserting enforcement.

        Claude Code's hooks reference says a `ConfigChange` block does not apply
        to `policy_settings`. The guard still emits the verdict — and the stderr
        mirror is what makes that useful — but nothing here proves the harness
        acts on it, and this test exists so that claim is never read out of the
        test above. See `hooks/README.md`.
        """
        path = self.write_settings({"hooks": {}})
        _, err = self.check(path, source="policy_settings")
        self.assertTrue(err.strip(), "a policy_settings verdict must reach stderr")


class TestAllowedShapes(GuardTestCase):
    """The half that keeps the guard from bricking a config."""

    def test_intact_chain(self):
        path = self.write_settings(settings_with(*ALL_GUARDS))
        out, _ = self.check(path)
        self.assertFalse(blocked(out))

    def test_spelling_is_not_load_bearing(self):
        """Matched as substrings, so an absolute path or `uv run` still counts."""
        body = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "*",
                        "hooks": [
                            {"type": "command", "command": "uv run C:/x/credential-guard.py"},
                            {"type": "command", "command": "python /y/published-history-guard.py"},
                            {"type": "command", "command": "python3 ~/git-staging-guard.py"},
                            {"type": "command", "command": "py fanout-guard.py"},
                        ],
                    }
                ]
            }
        }
        path = self.write_settings(body)
        out, _ = self.check(path)
        self.assertFalse(blocked(out))

    def test_project_and_local_scopes_are_not_watched(self):
        """They cannot carry the global chain; blocking them would be noise."""
        path = self.write_settings({"hooks": {}})
        for source in ("project_settings", "local_settings", "skills"):
            with self.subTest(source=source):
                out, _ = self.check(path, source=source)
                self.assertFalse(blocked(out))

    def test_unknown_source_is_not_watched(self):
        path = self.write_settings({"hooks": {}})
        out, _ = self.check(path, source="some_future_scope")
        self.assertFalse(blocked(out))

    def test_disable_all_hooks_false_is_fine(self):
        path = self.write_settings(settings_with(*ALL_GUARDS, disableAllHooks=False))
        out, _ = self.check(path)
        self.assertFalse(blocked(out))

    def test_bom_prefixed_settings_file(self):
        """A BOM'd settings file must not be read as a missing chain.

        credential-guard v2.7 failed open on every call over exactly this, and a
        fail-open there is silent. Here the same bug would be a false BLOCK on a
        file whose chain is intact — the unrepairable direction.
        """
        path = self.write_settings(settings_with(*ALL_GUARDS), encoding="utf-8-sig")
        out, _ = self.check(path)
        self.assertFalse(blocked(out))


class TestFailsOpen(GuardTestCase):
    """Every error path allows, and says why. Silence would be a lie."""

    def _assert_fail_open(self, out, err):
        self.assertFalse(blocked(out))
        self.assertIn("failing open", err)

    def test_unparseable_payload(self):
        out, err = run(None, raw="not json at all")
        self._assert_fail_open(out, err)

    def test_payload_is_not_an_object(self):
        out, err = run(["user_settings"])
        self._assert_fail_open(out, err)

    def test_missing_config_path(self):
        out, err = run({"config_source": "user_settings"})
        self._assert_fail_open(out, err)

    def test_config_path_does_not_exist(self):
        out, err = run(
            {"config_source": "user_settings", "config_path": str(self.tmp / "nope.json")}
        )
        self._assert_fail_open(out, err)

    def test_settings_file_is_unparseable(self):
        """An edit caught mid-write. Allowing is the only safe move."""
        path = self.tmp / "settings.json"
        path.write_text('{"hooks": {', encoding="utf-8")
        out, err = self.check(str(path))
        self._assert_fail_open(out, err)

    def test_settings_file_is_not_an_object(self):
        path = self.tmp / "settings.json"
        path.write_text("[]", encoding="utf-8")
        out, err = self.check(str(path))
        self._assert_fail_open(out, err)

    def test_empty_stdin(self):
        out, err = run(None, raw="")
        self._assert_fail_open(out, err)


if __name__ == "__main__":
    unittest.main()
