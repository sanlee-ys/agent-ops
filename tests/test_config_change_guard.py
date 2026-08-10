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

Groups:

  - **Blocked.** A watched scope whose resulting file has lost a guard, or has
    `disableAllHooks` set.
  - **Allowed.** The far more important half. This guard sits on the one file a
    false positive cannot be repaired from — a wrong block bricks the config,
    and the repair would itself be a config change the guard blocks again. So
    the unwatched scopes, the intact chain, and every malformed input are pinned
    as allowed on purpose.
  - **Fail-open.** Every error path must exit 0 and say why on stderr, because
    silence is indistinguishable from "the hook never fired".
  - **v1.1 escalations.** The shapes v1.0's substring check reported as an
    intact chain while the config had no protection left: `bypassPermissions`,
    an unrestricted-shell allow rule, a traffic-redirecting `env` key, and the
    three ways to keep a guard's *name* while stopping it from firing (moved to
    a non-blocking event, given an empty matcher, repointed at
    `<guard>-disabled.py`). Each is paired with the near-miss benign shape it
    must NOT flag, because that pairing is what keeps the guard usable.

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
        """Interpreter and directory are free; the `<guard>.py` filename is not.

        v1.1 tightened this from "the guard's name appears somewhere in the
        serialized hooks blob" to "a command under the expected event references
        the exact `<guard>.py` filename". How the script is *invoked* is still
        nobody's business — `uv run`, `python3`, a bare `py`, an absolute path, a
        `~`-relative one — so all four spellings below must stay allowed.
        """
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


def realistic_wiring(**extra):
    """The live wiring's *shape*: several PreToolUse entries, varied matchers.

    `settings_with()` gives every guard its own `*`-matched entry, which is a
    fine baseline but not what a real settings.json looks like. The false-block
    regression that matters is against the real shape — guards grouped under
    narrow matchers (`Workflow`, `Bash|PowerShell`) alongside a `*` one, plus a
    matcher-less `ConfigChange` entry. Kept structural, with no machine-specific
    paths, so it stays valid in a public repo.
    """
    h = '$HOME/.claude/hooks'
    body = {
        "hooks": {
            "PreToolUse": [
                {"matcher": "Workflow", "hooks": [
                    {"type": "command", "command": 'python3 "%s/fanout-guard.py"' % h}]},
                {"matcher": "Bash|PowerShell", "hooks": [
                    {"type": "command", "command": 'python3 "%s/git-staging-guard.py"' % h},
                    {"type": "command",
                     "command": 'python3 "%s/published-history-guard.py"' % h}]},
                {"matcher": "*", "hooks": [
                    {"type": "command", "command": 'python3 "%s/credential-guard.py"' % h}]},
            ],
            "ConfigChange": [
                {"hooks": [{"type": "command",
                            "command": 'python3 "%s/config-change-guard.py"' % h}]}],
        },
        "permissions": {
            "defaultMode": "auto",
            "allow": ["Bash(git status:*)", "Bash(gh pr:*)", "Read", "Grep", "Glob"],
        },
    }
    body.update(extra)
    return body


class TestRealWiringIsAllowed(GuardTestCase):
    """The regression that costs the most if it breaks: a false block.

    A wrong block here bricks the config, and the repair is itself a config
    change this guard blocks again. So the real wiring shape is pinned as
    allowed, separately from the synthetic baseline.
    """

    def test_realistic_wiring_allowed(self):
        path = self.write_settings(realistic_wiring())
        out, err = self.check(path)
        self.assertFalse(blocked(out), "false block on the real wiring shape: %s" % err)

    def test_bare_tool_names_that_are_not_shells_are_fine(self):
        """`Read`/`Grep`/`Glob`/`Agent` as bare allow entries are normal."""
        s = realistic_wiring()
        s["permissions"]["allow"].extend(["Agent", "Workflow", "WebFetch"])
        out, _ = self.check(self.write_settings(s))
        self.assertFalse(blocked(out))


class TestPermissionLayer(GuardTestCase):
    """v1.1 check 1 and 2 — v1.0 never read `permissions` at all.

    Each of these leaves all four guard names present and correctly wired, so
    v1.0 passed them while the config had no protection left.
    """

    def test_bypass_permissions_blocked(self):
        s = realistic_wiring()
        s["permissions"]["defaultMode"] = "bypassPermissions"
        out, err = self.check(self.write_settings(s))
        self.assertTrue(blocked(out))
        self.assertIn("bypassPermissions", out)
        self.assertIn("bypassPermissions", err)

    def test_ordinary_modes_allowed(self):
        """plan/acceptEdits/default/auto are user preferences, not tampering."""
        for mode in ("default", "auto", "plan", "acceptEdits"):
            with self.subTest(mode=mode):
                s = realistic_wiring()
                s["permissions"]["defaultMode"] = mode
                out, _ = self.check(self.write_settings(s))
                self.assertFalse(blocked(out))

    def test_unrestricted_shell_rules_blocked(self):
        for rule in ("Bash", "Bash(*)", "Bash(:*)", "Bash(*:*)", "Bash()",
                     "PowerShell(*)", "Shell(:*)", "  Bash( * )  "):
            with self.subTest(rule=rule):
                s = realistic_wiring()
                s["permissions"]["allow"].append(rule)
                out, _ = self.check(self.write_settings(s))
                self.assertTrue(blocked(out), "%r should be refused" % rule)

    def test_prefixed_shell_rules_not_flagged(self):
        """The usability half: narrowing these is /doctor's job, not a tripwire.

        A guard that fires on ordinary allowlist maintenance gets routed around
        within a week, so every one of these must stay silent.
        """
        for rule in ("Bash(git status)", "Bash(gh pr view *)", "Bash(uv run:*)",
                     "Bash(npm test)", "PowerShell(Get-ChildItem:*)",
                     "mcp__kb-agent__search_kb", "Bash(rm -rf:*)"):
            with self.subTest(rule=rule):
                s = realistic_wiring()
                s["permissions"]["allow"].append(rule)
                out, err = self.check(self.write_settings(s))
                self.assertFalse(blocked(out), "false block on %r: %s" % (rule, err))

    def test_permissions_absent_or_malformed_is_not_a_block(self):
        """Fail-open discipline: a missing/odd `permissions` key is not tamper."""
        for value in (None, [], "auto", 3):
            with self.subTest(value=value):
                s = realistic_wiring()
                if value is None:
                    s.pop("permissions")
                else:
                    s["permissions"] = value
                out, _ = self.check(self.write_settings(s))
                self.assertFalse(blocked(out))


class TestAmbientEnvInjection(GuardTestCase):
    """v1.1 check 3 — an `env` block per se is normal; these keys are not."""

    def test_traffic_redirect_and_ambient_credentials_blocked(self):
        for key in ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
                    "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
            with self.subTest(key=key):
                s = realistic_wiring(env={key: "x"})
                out, _ = self.check(self.write_settings(s))
                self.assertTrue(blocked(out))
                self.assertIn(key, out)

    def test_key_match_is_case_insensitive(self):
        s = realistic_wiring(env={"anthropic_base_url": "http://elsewhere"})
        out, _ = self.check(self.write_settings(s))
        self.assertTrue(blocked(out))

    def test_benign_env_allowed(self):
        s = realistic_wiring(env={"EDITOR": "vim", "TZ": "UTC",
                                  "CLAUDE_CODE_ENABLE_TELEMETRY": "0"})
        out, err = self.check(self.write_settings(s))
        self.assertFalse(blocked(out), "false block on a benign env block: %s" % err)


class TestStructuralGuardCheck(GuardTestCase):
    """v1.1 check 4 — the three ways to keep a guard's NAME but stop it firing.

    Every case here passed v1.0's substring test, which asked only whether the
    string `credential-guard` appeared anywhere in the serialized hooks blob.
    """

    def test_guard_moved_to_a_non_blocking_event(self):
        """PostToolUse runs *after* the tool call, so it cannot refuse anything."""
        s = realistic_wiring()
        moved = s["hooks"]["PreToolUse"].pop()          # the credential-guard entry
        s["hooks"]["PostToolUse"] = [moved]
        out, _ = self.check(self.write_settings(s))
        self.assertTrue(blocked(out))
        self.assertIn("credential-guard", out)

    def test_guard_neutered_with_an_empty_matcher(self):
        s = realistic_wiring()
        s["hooks"]["PreToolUse"][-1]["matcher"] = ""
        out, _ = self.check(self.write_settings(s))
        self.assertTrue(blocked(out))
        self.assertIn("credential-guard", out)

    def test_guard_repointed_at_a_disabled_copy(self):
        """`credential-guard-disabled.py` *contains* `credential-guard`.

        This is the case that most cleanly separates v1.1 from v1.0: the
        substring check matches the decoy filename, the filename check does not.
        """
        s = realistic_wiring()
        s["hooks"]["PreToolUse"][-1]["hooks"][0]["command"] = (
            'python3 "$HOME/.claude/hooks/credential-guard-disabled.py"')
        out, _ = self.check(self.write_settings(s))
        self.assertTrue(blocked(out))
        self.assertIn("credential-guard", out)

    def test_absent_matcher_means_all_tools_and_is_allowed(self):
        """No `matcher` key at all is Claude Code's "every tool" — not neutering.

        Only an explicitly empty matcher is the neutering shape. Getting this
        backwards would false-block the matcher-less entries the live file uses.
        """
        s = realistic_wiring()
        s["hooks"]["PreToolUse"][-1].pop("matcher")
        out, err = self.check(self.write_settings(s))
        self.assertFalse(blocked(out), "false block on a matcher-less entry: %s" % err)

    def test_guards_may_share_one_entry(self):
        """Grouping all four under a single matcher is valid wiring."""
        h = '$HOME/.claude/hooks'
        s = {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [
            {"type": "command", "command": 'python3 "%s/%s.py"' % (h, g)}
            for g in ALL_GUARDS]}]}}
        out, _ = self.check(self.write_settings(s))
        self.assertFalse(blocked(out))

    def test_malformed_hook_entries_do_not_crash_the_guard(self):
        """Junk in the hooks tree must fail toward a verdict, never a traceback.

        A traceback is a non-zero exit, which the harness reports as a hook
        *error* rather than a verdict — a different thing entirely, and the one
        outcome `run()` refuses to accept.
        """
        s = realistic_wiring()
        s["hooks"]["PreToolUse"].extend([None, "junk", {"hooks": None},
                                         {"hooks": ["junk"]}, {"matcher": 7}])
        out, _ = self.check(self.write_settings(s))
        self.assertFalse(blocked(out))

    def test_hooks_is_not_a_dict(self):
        out, _ = self.check(self.write_settings({"hooks": []}))
        self.assertTrue(blocked(out))


if __name__ == "__main__":
    unittest.main()
