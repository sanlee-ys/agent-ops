#!/usr/bin/env python3
"""Test suite for hooks/destructive-command-guard.py.

Two layers. The subprocess layer drives the guard exactly as the harness does:
a PreToolUse JSON payload on stdin, exit 0 = allow, exit 2 = block, JSON
verdicts on stdout for warn/confirm. The import layer loads the module and
pins the scoring matrix itself: the 25-cell snapshot and the monotonicity
invariants, ported as test obligations from the secguard reference design.

Stdlib only (no pytest) so CI is a bare `python -m unittest`.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

GUARD = Path(__file__).resolve().parent.parent / "hooks" / "destructive-command-guard.py"

_spec = importlib.util.spec_from_file_location("destructive_command_guard", GUARD)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def run(command: str, tool_name: str = "Bash", env_extra: dict | None = None):
    payload = json.dumps({"tool_name": tool_name, "tool_input": {"command": command}})
    env = os.environ.copy()
    env.pop("AGENT_OPS_GUARD_SHADOW", None)
    env["AGENT_OPS_GUARD_SCORING"] = os.devnull  # isolate from any real config
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(GUARD)], input=payload, capture_output=True,
        text=True, env=env,
    )


def verdict(proc) -> str:
    """allow / warn / confirm / block, reconstructed from the process result."""
    if proc.returncode == 2:
        return "block"
    if not proc.stdout.strip():
        return "allow"
    out = json.loads(proc.stdout)
    decision = out.get("hookSpecificOutput", {}).get("permissionDecision")
    if decision == "ask":
        return "confirm"
    if decision is None:
        # A warn is a systemMessage note with no permission decision.
        return "warn" if "GUARD" in out.get("systemMessage", "") else "allow"
    return decision


class TestScoringMatrix(unittest.TestCase):
    """The matrix itself, pinned cell by cell."""

    def test_all_25_cells_snapshot(self) -> None:
        expected = [
            ["confirm", "warn", "warn", "allow", "allow"],
            ["confirm", "confirm", "warn", "warn", "allow"],
            ["block", "confirm", "confirm", "warn", "warn"],
            ["block", "block", "confirm", "confirm", "warn"],
            ["block", "block", "block", "confirm", "confirm"],
        ]
        for blast in range(5):
            for rev in range(5):
                self.assertEqual(
                    mod.bucket(blast, rev), expected[blast][rev],
                    f"mismatch at (blast={blast}, reversibility={rev})",
                )

    def test_monotone_in_blast(self) -> None:
        order = list(mod.ACTIONS)
        for rev in range(5):
            for b in range(4):
                self.assertLessEqual(
                    order.index(mod.bucket(b, rev)),
                    order.index(mod.bucket(b + 1, rev)),
                )

    def test_antimonotone_in_reversibility(self) -> None:
        order = list(mod.ACTIONS)
        for blast in range(5):
            for r in range(4):
                self.assertGreaterEqual(
                    order.index(mod.bucket(blast, r)),
                    order.index(mod.bucket(blast, r + 1)),
                )

    def test_every_rule_scores_in_range(self) -> None:
        for rule_id, (blast, rev) in mod.RULES.items():
            self.assertTrue(0 <= blast <= 4 and 0 <= rev <= 4, rule_id)


class TestHeadlineSplit(unittest.TestCase):
    """The reason this guard exists: same verb, different score."""

    def test_reset_soft_allows(self) -> None:
        self.assertEqual(verdict(run("git reset --soft HEAD~1")), "allow")

    def test_reset_mixed_allows(self) -> None:
        self.assertEqual(verdict(run("git reset HEAD~1")), "allow")

    def test_reset_hard_confirms(self) -> None:
        self.assertEqual(verdict(run("git reset --hard origin/main")), "confirm")

    def test_reset_merge_warns(self) -> None:
        self.assertEqual(verdict(run("git reset --merge")), "warn")

    def test_reset_pathspec_unstage_allows(self) -> None:
        self.assertEqual(verdict(run("git reset -- src/app.py")), "allow")


class TestGitRules(unittest.TestCase):
    def test_clean_force_confirms(self) -> None:
        self.assertEqual(verdict(run("git clean -fd")), "confirm")

    def test_clean_dry_run_allows(self) -> None:
        self.assertEqual(verdict(run("git clean -nd")), "allow")

    def test_checkout_pathspec_confirms(self) -> None:
        self.assertEqual(verdict(run("git checkout -- src/app.py")), "confirm")

    def test_checkout_branch_allows(self) -> None:
        self.assertEqual(verdict(run("git checkout feature/x")), "allow")
        self.assertEqual(verdict(run("git checkout -b feature/x")), "allow")

    def test_restore_worktree_confirms(self) -> None:
        self.assertEqual(verdict(run("git restore src/app.py")), "confirm")

    def test_restore_staged_allows(self) -> None:
        self.assertEqual(verdict(run("git restore --staged src/app.py")), "allow")

    def test_branch_force_delete_warns(self) -> None:
        self.assertEqual(verdict(run("git branch -D old-branch")), "warn")

    def test_branch_list_allows(self) -> None:
        self.assertEqual(verdict(run("git branch --list")), "allow")

    def test_stash_drop_confirms(self) -> None:
        self.assertEqual(verdict(run("git stash drop")), "confirm")
        self.assertEqual(verdict(run("git stash clear")), "confirm")

    def test_stash_push_allows(self) -> None:
        self.assertEqual(verdict(run("git stash push -m wip")), "allow")

    def test_no_verify_warns(self) -> None:
        self.assertEqual(verdict(run("git commit --no-verify -m x")), "warn")

    def test_commit_short_n_warns(self) -> None:
        # -n is the short form of --no-verify for commit only.
        self.assertEqual(verdict(run("git commit -n -m x")), "warn")

    def test_push_short_n_allows(self) -> None:
        # For push, -n is --dry-run, not --no-verify.
        self.assertEqual(verdict(run("git push -n")), "allow")

    def test_dash_c_form_still_matched(self) -> None:
        self.assertEqual(
            verdict(run("git -C C:\\repo reset --hard HEAD~2")), "confirm"
        )

    def test_later_segment_of_compound(self) -> None:
        self.assertEqual(
            verdict(run("git status && git reset --hard HEAD~1")), "confirm"
        )


class TestRmRules(unittest.TestCase):
    def test_rm_rf_home_blocks(self) -> None:
        self.assertEqual(verdict(run("rm -rf ~")), "block")

    def test_rm_rf_root_blocks(self) -> None:
        self.assertEqual(verdict(run("rm -rf /")), "block")

    def test_rm_rf_drive_root_blocks(self) -> None:
        self.assertEqual(verdict(run("rm -rf C:\\")), "block")

    def test_rm_rf_dot_git_blocks(self) -> None:
        self.assertEqual(verdict(run("rm -rf myrepo/.git")), "block")

    def test_rm_rf_relative_warns(self) -> None:
        self.assertEqual(verdict(run("rm -rf node_modules")), "warn")

    def test_rm_Rf_uppercase_relative_warns(self) -> None:
        # BSD/macOS spelling: -R in a combined short flag is recursive too.
        self.assertEqual(verdict(run("rm -Rf build")), "warn")

    def test_rm_Rf_home_blocks(self) -> None:
        self.assertEqual(verdict(run("rm -Rf ~/")), "block")

    def test_rm_fR_root_blocks(self) -> None:
        self.assertEqual(verdict(run("rm -fR /")), "block")

    def test_rm_single_file_allows(self) -> None:
        self.assertEqual(verdict(run("rm build/output.log")), "allow")

    def test_remove_item_recurse_warns(self) -> None:
        self.assertEqual(
            verdict(run("Remove-Item -Recurse -Force build", "PowerShell")), "warn"
        )

    def test_find_delete_confirms(self) -> None:
        self.assertEqual(verdict(run("find . -name '*.tmp' -delete")), "confirm")

    def test_shred_confirms(self) -> None:
        self.assertEqual(verdict(run("shred -u notes.txt")), "confirm")


class TestBackstopAndOverride(unittest.TestCase):
    def test_block_writes_reason_to_stderr_and_exits_2(self) -> None:
        proc = run("rm -rf ~")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("DESTRUCTIVE-COMMAND GUARD", proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(
            out["hookSpecificOutput"]["permissionDecision"], "deny"
        )

    def test_warn_emits_no_permission_decision(self) -> None:
        # A warn must not auto-approve the command: no permissionDecision,
        # only a systemMessage note and a stderr line, exit 0.
        proc = run("git branch -D old-branch")
        self.assertEqual(proc.returncode, 0)
        out = json.loads(proc.stdout)
        self.assertNotIn("hookSpecificOutput", out)
        self.assertIn("GUARD", out.get("systemMessage", ""))
        self.assertIn("warn", proc.stderr)

    def test_override_token_allows(self) -> None:
        self.assertEqual(verdict(run("RISK-OK rm -rf ~")), "allow")

    def test_prose_in_heredoc_ignored(self) -> None:
        cmd = "git commit -F- <<'EOF'\nexplains why rm -rf ~ was blocked\nEOF"
        self.assertEqual(verdict(run(cmd)), "allow")

    def test_non_shell_tool_allows(self) -> None:
        self.assertEqual(verdict(run("rm -rf ~", tool_name="Read")), "allow")


class TestShadowMode(unittest.TestCase):
    def test_shadow_logs_and_allows(self) -> None:
        proc = run("rm -rf ~", env_extra={"AGENT_OPS_GUARD_SHADOW": "1"})
        self.assertEqual(proc.returncode, 0)
        self.assertIn("would block", proc.stderr)

    def test_shadow_falsy_values_enforce(self) -> None:
        for value in ("0", "off", "false", ""):
            proc = run("rm -rf ~", env_extra={"AGENT_OPS_GUARD_SHADOW": value})
            self.assertEqual(proc.returncode, 2, f"shadow={value!r}")


class TestAsymmetricFailOpen(unittest.TestCase):
    def test_classify_unparseable_with_trigger_escalates(self) -> None:
        # An unbalanced single quote fails both tokenization attempts.
        self.assertEqual(mod.classify("rm -rf 'broken"), "unparseable.trigger")

    def test_classify_unparseable_without_trigger_allows(self) -> None:
        self.assertIsNone(mod.classify("echo 'broken"))

    def test_salvageable_quote_still_classifies_normally(self) -> None:
        # The tokenizer's second attempt closes an unbalanced double quote,
        # so the real rule fires instead of the escalation.
        self.assertEqual(mod.classify('rm -rf "broken'), "rm.recursive")


class TestConfigOverrides(unittest.TestCase):
    def _with_config(self, cfg: dict, command: str):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            json.dump(cfg, fh)
            path = fh.name
        try:
            return run(command, env_extra={"AGENT_OPS_GUARD_SCORING": path})
        finally:
            os.unlink(path)

    def test_per_rule_action_override(self) -> None:
        proc = self._with_config(
            {"actions": {"git.reset_hard": "allow"}}, "git reset --hard HEAD~1"
        )
        self.assertEqual(verdict(proc), "allow")

    def test_per_cell_override(self) -> None:
        proc = self._with_config(
            {"cells": {"1,0": "block"}}, "git reset --hard HEAD~1"
        )
        self.assertEqual(verdict(proc), "block")

    def test_per_rule_score_override(self) -> None:
        proc = self._with_config(
            {"rules": {"git.reset_hard": {"blast": 0, "reversibility": 4}}},
            "git reset --hard HEAD~1",
        )
        self.assertEqual(verdict(proc), "allow")

    def test_bad_config_is_ignored_not_fatal(self) -> None:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            fh.write("{not json")
            path = fh.name
        try:
            proc = run("git reset --hard HEAD~1",
                       env_extra={"AGENT_OPS_GUARD_SCORING": path})
        finally:
            os.unlink(path)
        self.assertEqual(verdict(proc), "confirm")
        self.assertIn("config ignored", proc.stderr)


if __name__ == "__main__":
    unittest.main()
