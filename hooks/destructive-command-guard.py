#!/usr/bin/env python3
# hook-version: 1.1 (2026-08-19)
"""Destructive-command guard (global PreToolUse hook) — blast × reversibility scoring.

WHY. The auto-mode classifier judges a command by its verb, so it gives
`git reset --soft` and `git reset --hard` the same treatment. The 2026-07-26
incident (ADR-007) showed the two ends of that error: a safe soft reset is not
distinguishable from a working-tree wipe by the verb alone. The
published-history guard closed the *published-history* half with a repository
invariant. This guard closes the *local-destruction* half, where no repository
invariant exists: the damage is to the working tree, the stash, or the file
system, and git cannot be asked "what would this destroy" after the fact.

DESIGN (ported from the public secguard project, Apache-2.0 + Commons Clause;
the design is ported, the code is not — see decisions/ADR-015). Each rule
declares a two-axis score:

  * blast (0-4): 0 = one local file, 1 = local repo state, 2 = local machine,
    3 = one remote resource, 4 = shared infrastructure.
  * reversibility (0-4): 0 = permanent, 2 = moderate effort, 4 = instant undo.

  risk = blast + (4 - reversibility)

  bucket: risk <= 1 allow, 2-3 warn, 4-5 confirm, >= 6 block.

The construction is monotone: more blast never lowers the severity, and more
reversibility never raises it. The headline effect: `git reset --soft` scores
(0, 4) and is allowed; `git reset --hard` scores (1, 0) and asks for
confirmation. The verb is the same; the score is not.

HOW THIS SITS NEXT TO ADR-007. ADR-007 says: guard the invariant, not the
verb. That rule holds where an invariant exists — the published-history guard
asks the repository, and this guard never duplicates it. Local destruction has
no invariant to ask: `git reset --hard` destroys uncommitted work that no ref
records. Where the world cannot be asked, a calibrated estimate of the damage
beats a verb list with one severity, and the score table IS that estimate,
made explicit and testable per rule id.

BUCKETS, AS THE HARNESS SEES THEM.
  * allow   — exit 0.
  * warn    — exit 0, a `systemMessage` note on stdout, a note on stderr.
    No permission decision: the normal permission flow still applies.
  * confirm — a `permissionDecision: ask` JSON verdict. NOTE: in
    `bypassPermissions` mode the harness ignores `ask`, so a confirm degrades
    to allow there. Recorded, not hidden.
  * block   — a deny JSON verdict, the reason on stderr, and `sys.exit(2)`.
    Exit code 2 is the backstop: the harness honours it even in
    `bypassPermissions` mode, where it ignores JSON verdicts.

SHADOW MODE. Set AGENT_OPS_GUARD_SHADOW to a truthy value (not empty / 0 /
off / false) and the guard logs `would <action>` to stderr and enforces
nothing. This is the safe-rollout path: run in shadow, read the log, then arm.

ASYMMETRIC FAIL-OPEN. An unparseable segment normally allows — a guard must
not break unrelated work. But when the unparseable text contains a destructive
trigger keyword (`rm -rf`, `--hard`, `clean -f`, `-delete`, ...), the guard
escalates to confirm instead of allowing. Failing open on exactly the text
that names a destructive operation is the one asymmetry worth paying for.

CONFIG. Optional JSON next to this file (`guard-scoring.json`), or at the path
in AGENT_OPS_GUARD_SCORING. Three override maps, in precedence order:
  {"actions": {"git.reset_hard": "warn"},         # per-rule final action
   "rules":   {"git.reset_hard": {"blast": 1, "reversibility": 2}},
   "cells":   {"1,0": "block"}}                    # per-(blast,rev) cell
A config that does not parse is ignored with a stderr note — a scoring config
must not be able to wedge the shell.

OVERRIDE. Prefix the command with RISK-OK when the destructive operation is
genuinely the intent. Per-command on purpose, like STAGE-ALL-OK and
REWRITE-MAIN-OK: the point is that the decision gets made, not defaulted.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys

OVERRIDE = "RISK-OK"

SHADOW_ENV = "AGENT_OPS_GUARD_SHADOW"
CONFIG_ENV = "AGENT_OPS_GUARD_SCORING"

ACTIONS = ("allow", "warn", "confirm", "block")

# --- Scoring -----------------------------------------------------------------


def risk(blast: int, reversibility: int) -> int:
    return blast + (4 - reversibility)


def bucket(blast: int, reversibility: int) -> str:
    r = risk(blast, reversibility)
    if r <= 1:
        return "allow"
    if r <= 3:
        return "warn"
    if r <= 5:
        return "confirm"
    return "block"


# Rule id -> (blast, reversibility). Calibrations follow secguard's table where
# a rule maps one-to-one; the rm split is recalibrated for this fleet (a recursive
# delete of a project-relative path is routine agent work, so it warns rather
# than blocks; the dangerous-path form keeps the block).
RULES: dict[str, tuple[int, int]] = {
    "git.reset_soft": (0, 4),        # moves a pointer; index and tree survive
    "git.reset_hard": (1, 0),        # uncommitted work: no reflog, no recovery
    "git.reset_merge": (1, 2),       # refuses to clobber local edits
    "git.clean_force": (1, 0),       # untracked files: no git recovery
    "git.checkout_pathspec": (1, 1), # overwrites local edits with HEAD
    "git.restore_pathspec": (1, 1),
    "git.branch_force_delete": (1, 2),  # reflog keeps the commits ~90 days
    "git.stash_loss": (1, 1),
    "git.no_verify": (1, 3),         # skips hooks; the commit itself survives
    "rm.dangerous_path": (3, 0),     # home, root, drive root, .git
    "rm.recursive": (0, 1),          # project-relative recursive delete
    "rm.find_delete": (1, 1),
    "rm.shred": (1, 0),              # single file, intentionally permanent
    "unparseable.trigger": (1, 1),   # asymmetric fail-open: confirm, not allow
}


def _load_config() -> dict:
    path = os.environ.get(CONFIG_ENV) or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "guard-scoring.json"
    )
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8-sig") as fh:
            cfg = json.load(fh)
        if not isinstance(cfg, dict):
            raise ValueError("config root is not an object")
        return cfg
    except Exception as exc:  # a bad config must not wedge the shell
        sys.stderr.write(f"[destructive-command-guard] config ignored: {exc}\n")
        return {}


def decide(rule_id: str, config: dict) -> tuple[str, int, int]:
    """(action, blast, reversibility) for a rule, with overrides applied."""
    blast, rev = RULES[rule_id]
    rule_override = config.get("rules", {}).get(rule_id)
    if isinstance(rule_override, dict):
        b, r = rule_override.get("blast"), rule_override.get("reversibility")
        if isinstance(b, int) and isinstance(r, int) and 0 <= b <= 4 and 0 <= r <= 4:
            blast, rev = b, r
    action = bucket(blast, rev)
    cell = config.get("cells", {}).get(f"{blast},{rev}")
    if cell in ACTIONS:
        action = cell
    forced = config.get("actions", {}).get(rule_id)
    if forced in ACTIONS:
        action = forced
    return action, blast, rev


# --- Command parsing ---------------------------------------------------------

_HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1.*?^\2\s*$", re.DOTALL | re.MULTILINE)
_SPLIT = re.compile(r"&&|\|\||[;\n|&]")

# Destructive trigger keywords for the asymmetric fail-open path. A segment
# that cannot be tokenized is allowed UNLESS one of these appears in its text.
TRIGGERS = re.compile(
    r"rm\s+-[a-z]*r|--hard\b|clean\s+-[a-z]*f|--force\b|-delete\b"
    r"|\bshred\b|\bmkfs\b|\bdd\s+if=|Remove-Item\b.*-Recurse",
    re.IGNORECASE,
)


def _strip_prose(command: str) -> str:
    return _HEREDOC.sub(" ", command)


def _dequote(token: str) -> str:
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        return token[1:-1]
    return token


def _tokens(segment: str) -> list[str] | None:
    """Tokenize one segment. None when tokenization fails outright.

    Non-posix mode keeps Windows backslash paths intact (the lesson
    published-history-guard.py records); quotes are stripped afterwards.
    """
    for candidate in (segment, segment + '"'):
        try:
            return [_dequote(t) for t in shlex.split(candidate, posix=False)]
        except ValueError:
            continue
    return None


def _git_rest(tokens: list[str]) -> list[str] | None:
    """Tokens after `git` and its global flags, or None if not a git call."""
    if not tokens:
        return None
    lead = tokens[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if lead not in {"git", "git.exe"}:
        return None
    rest = tokens[1:]
    while rest:
        if rest[0] in {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}:
            rest = rest[2:]
        elif rest[0].startswith("-"):
            rest = rest[1:]
        else:
            break
    return rest


# Paths whose recursive deletion is machine-scope damage, not project cleanup.
_DRIVE_ROOT = re.compile(r"^[A-Za-z]:[\\/]?$")
_DANGEROUS_EXACT = {"/", "~", "~/", "$HOME", "${HOME}", "%USERPROFILE%",
                    "*", "/*", ".", "..", "/home", "/Users"}


def _dangerous_target(target: str) -> bool:
    t = target.rstrip()
    if t in _DANGEROUS_EXACT or _DRIVE_ROOT.match(t):
        return True
    base = re.split(r"[/\\]", t.rstrip("/\\"))[-1]
    return base == ".git"


def _classify_rm(tokens: list[str]) -> str | None:
    lead = tokens[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
    if lead == "shred":
        return "rm.shred"
    if lead == "find":
        if any(t == "-delete" for t in tokens) or (
            "-exec" in tokens and any(t in {"rm", "rm.exe"} for t in tokens)
        ):
            return "rm.find_delete"
        return None
    if lead in {"rm", "rm.exe"}:
        flags = [t for t in tokens[1:] if t.startswith("-")]
        # The combined-short-flag scan is case-insensitive on the letter: rm
        # spells recursive as -r or -R (the BSD/macOS habit), so -Rf and -fR
        # must classify the same as -rf.
        recursive = any(
            t in {"--recursive", "-R"}
            or (t[:1] == "-" and t[:2] != "--" and set("rR") & set(t))
            for t in flags
        )
        if not recursive:
            return None
        targets = [t for t in tokens[1:] if not t.startswith("-")]
        if any(_dangerous_target(t) for t in targets):
            return "rm.dangerous_path"
        return "rm.recursive"
    if lead in {"remove-item", "ri"}:
        low = [t.lower() for t in tokens[1:]]
        if not any(t.startswith("-recurse") for t in low):
            return None
        targets = [t for t in tokens[1:] if not t.startswith("-")]
        if any(_dangerous_target(t) for t in targets):
            return "rm.dangerous_path"
        return "rm.recursive"
    return None


def _classify_git(rest: list[str]) -> str | None:
    if not rest:
        return None
    sub, args = rest[0], rest[1:]

    if sub in {"commit", "push", "merge"}:
        # `-n` means --no-verify only for commit. For push it is --dry-run
        # and for merge it is --no-stat, so those match the long form only.
        no_verify = {"--no-verify", "-n"} if sub == "commit" else {"--no-verify"}
        if any(a in no_verify for a in args):
            return "git.no_verify"

    if sub == "reset":
        if "--" in args:
            return None  # pathspec unstage
        if "--hard" in args:
            return "git.reset_hard"
        if "--merge" in args or "--keep" in args:
            return "git.reset_merge"
        return "git.reset_soft"

    if sub == "clean":
        if "-n" in args or "--dry-run" in args:
            return None
        if any(
            a in {"--force"} or (a[:1] == "-" and a[:2] != "--" and "f" in a)
            for a in args
        ):
            return "git.clean_force"
        return None

    if sub == "checkout":
        if "--" in args and args[args.index("--") + 1:]:
            return "git.checkout_pathspec"
        if args and args[-1] == "." and "--" not in args:
            return "git.checkout_pathspec"
        return None

    if sub == "restore":
        if "--staged" in args and "--worktree" not in args and "-W" not in args:
            return None  # unstages only; working tree untouched
        return "git.restore_pathspec" if args else None

    if sub == "branch":
        flags = {a for a in args if a.startswith("-")}
        if "-D" in flags or ({"-d", "--delete"} & flags and {"-f", "--force"} & flags):
            return "git.branch_force_delete"
        return None

    if sub == "stash" and args and args[0] in {"drop", "clear"}:
        return "git.stash_loss"

    return None


def classify(segment: str) -> str | None:
    """The matched rule id for one command segment, or None."""
    tokens = _tokens(segment.strip())
    if tokens is None:
        return "unparseable.trigger" if TRIGGERS.search(segment) else None
    if not tokens:
        return None
    rest = _git_rest(tokens)
    if rest is not None:
        return _classify_git(rest)
    return _classify_rm(tokens)


# --- Verdict emission --------------------------------------------------------


def _is_shadow() -> bool:
    raw = os.environ.get(SHADOW_ENV, "").strip().lower()
    return raw not in {"", "0", "off", "false"}


def _reason(rule_id: str, blast: int, rev: int, action: str, segment: str) -> str:
    return (
        f"DESTRUCTIVE-COMMAND GUARD [{rule_id}] -> {action} "
        f"(blast={blast}, reversibility={rev}, risk={risk(blast, rev)}).\n"
        f"Command: {segment.strip()[:200]}\n"
        "The score says what this command can destroy and how recoverable the "
        "loss is. If the operation is the deliberate intent, prefix the "
        f"command with {OVERRIDE}."
    )


def _emit(action: str, reason: str, event: str, payload: dict) -> None:
    if action == "warn":
        # No permissionDecision: a warn is a note, not a verdict. Emitting
        # `allow` here would auto-approve the command past the permission
        # system, which is one bucket more power than warn is scored for.
        sys.stderr.write(f"[destructive-command-guard] warn: {reason}\n")
        print(json.dumps({"systemMessage": reason}))
        sys.exit(0)
    if action == "confirm":
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": event,
                "permissionDecision": "ask",
                "permissionDecisionReason": reason,
            }
        }))
        sys.exit(0)
    # block: JSON deny for harnesses that read stdout, then the exit-2
    # backstop, which the harness honours even in bypassPermissions mode.
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": event,
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.stderr.write(reason + "\n")
    sys.exit(2)


def _allow(payload) -> None:
    if isinstance(payload, dict) and "cursor_version" in payload:
        print('{"permission": "allow"}')
    sys.exit(0)


def main() -> None:
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        sys.exit(0)

    if data.get("tool_name") not in {"Bash", "PowerShell", "Shell"}:
        _allow(data)

    command = data.get("tool_input", {}).get("command", "")
    if not isinstance(command, str) or not command.strip():
        _allow(data)

    if OVERRIDE in command:
        _allow(data)

    config = _load_config()
    event = data.get("hook_event_name") or "PreToolUse"
    shadow = _is_shadow()

    worst: tuple[int, str, str] | None = None  # (severity, reason, action)
    for segment in _SPLIT.split(_strip_prose(command)):
        rule_id = classify(segment)
        if rule_id is None:
            continue
        action, blast, rev = decide(rule_id, config)
        if action == "allow":
            continue
        severity = ACTIONS.index(action)
        reason = _reason(rule_id, blast, rev, action, segment)
        if worst is None or severity > worst[0]:
            worst = (severity, reason, action)

    if worst is None:
        _allow(data)

    _, reason, action = worst
    if shadow:
        sys.stderr.write(
            f"[destructive-command-guard][shadow] would {action} (logged only)\n"
            f"{reason}\n"
        )
        _allow(data)

    _emit(action, reason, event, data)


if __name__ == "__main__":
    main()
