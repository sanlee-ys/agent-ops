#!/usr/bin/env python3
# adapter-version: 1.0 (2026-08-10) — Cursor Fail-Closed Guard Adapter under ADR-012.
"""Cursor PreToolUse adapter for the fleet guards.

WHAT THIS IS NOT. It is not a second implementation of the redlines. The rules
live in exactly one place each — `security/credential-guard.py`,
`hooks/git-staging-guard.py`, `hooks/published-history-guard.py` — and this
file never inspects a command, never matches a path, and holds no pattern of
its own. `security/posture.md` limit #6 records what the other choice costs: a
duplicated copy of guard logic drifted out of sync and shipped a gap that had
already been fixed in the original. So the adapter is a pure TRANSLATOR. It
rewrites Cursor's tool call into the Claude Code PreToolUse payload the canonical
guards already read, runs them unmodified as subprocesses, and rewrites their
verdict back into Cursor's response format. A redline change lands in the guards
and reaches this lane with no edit here.

WHY AN ADAPTER AT ALL. ADR-012 made capability parity the fleet default.
Cursor executes bounded IDE-native work, but requires full redline guard enforcement.
cursor-agent hook payloads may use snake_case or camelCase, send tool names like
`Shell`, `ReadFile`, `WriteFile`, `EditFile`, and Windows wrappers may prepend a
UTF-8 BOM to stdin.

THE TWO CONTRACTS.

  Claude Code  ->  {"tool_name": "Bash", "tool_input": {"command": ...}} on
                   stdin; exit 0 allows, exit 2 blocks with stderr as reason.
  Cursor       ->  {"tool_name": ..., "tool_input": {...}} or camelCase on stdin;
                   exit 2 with stderr and/or {"decision": "deny", "reason": ...}
                   on stdout blocks the tool call.

ALLOW PRINTS NOTHING (or {"permission": "allow"} for cursor_version payloads).
Exit 0 with empty stdout is the documented success path for standard hooks.
For cursor_version payloads, an explicit {"permission": "allow"} is printed because
cursor-agent treats empty stdout as a failed hook run.

FAIL CLOSED, DELIBERATELY.
The canonical guards fail OPEN on an unparseable payload — availability over strictness
for a threat model of honest mistakes. This adapter inverts that for its own failures:

  - guards not found on disk (repo moved, clone deleted) -> DENY, loudly.
  - a guard crashes, or times out                        -> DENY, naming it.
  - an internal error anywhere in this file              -> DENY.
  - stdin that is not a tool call we recognise           -> pass through. That
    is not a failure; it is a payload with nothing to judge.

NO CONSOLE WINDOWS. On Windows the guards are spawned with CREATE_NO_WINDOW so no
console windows pop up.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

# --- Locating the canonical guards -----------------------------------------
# Resolved, never copied. `AGENT_OPS_ROOT` wins so a machine that keeps the
# clone somewhere unusual needs no edit here; otherwise walk up from this
# file's real path (realpath, so a symlinked deployment resolves into the repo)
# looking for the marker that identifies an agent-ops checkout.
_MARKER = os.path.join("security", "credential-guard.py")


def _repo_root() -> str | None:
    env = os.environ.get("AGENT_OPS_ROOT")
    if env and os.path.isfile(os.path.join(env, _MARKER)):
        return env
    here = os.path.dirname(os.path.realpath(__file__))
    while True:
        if os.path.isfile(os.path.join(here, _MARKER)):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            return None
        here = parent


# Guards run in order; the first block wins. credential-guard is first because
# it is the redline with an incident history behind every clause.
_GUARDS = (
    ("credential-guard", os.path.join("security", "credential-guard.py"), False),
    ("git-staging-guard", os.path.join("hooks", "git-staging-guard.py"), True),
    ("published-history-guard",
     os.path.join("hooks", "published-history-guard.py"), True),
)

_TIMEOUT = 45

# Windows: keep the guard subprocesses from allocating a console window.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


# --- Cursor -> Claude Code payload ------------------------------------------
_SHELL_TOOLS = {
    "shell", "bash", "powershell", "run_terminal_command", "run_terminal_cmd",
    "cmd", "terminal", "exec_command",
}

_COMMAND_KEYS = ("command", "commandline", "cmd", "script")
_CWD_KEYS = ("cwd", "workingdirectory", "workingdir", "directory")


def _pick(args: dict, keys: tuple[str, ...]) -> str | None:
    """First value in `args` whose key matches one of `keys`, case-insensitively."""
    lowered = {str(k).lower(): v for k, v in args.items()}
    for key in keys:
        value = lowered.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _first(payload: dict, *keys):
    """First present value among `keys`. Handles both camelCase and snake_case."""
    for key in keys:
        if key in payload:
            return payload[key]
    return None


def _translate(payload: dict) -> tuple[dict, bool] | None:
    """(claude_payload, is_shell) for a Cursor PreToolUse payload.

    None when there is nothing to judge — no tool name, or a call carrying no
    arguments at all. That is a pass-through, not a failure.
    """
    name = _first(payload, "toolName", "tool_name", "name", "tool")
    if not isinstance(name, str) or not name:
        return None
    args = _first(payload, "toolInput", "tool_input", "args", "input")
    if not isinstance(args, dict):
        args = {}

    cwd = _first(payload, "cwd", "workspaceRoot", "workspace_root", "workspacePath", "workspace_path")

    if name.lower() in _SHELL_TOOLS:
        command = _pick(args, _COMMAND_KEYS)
        if command is None:
            return None
        claude: dict = {"tool_name": "Bash", "tool_input": {"command": command}}
        cwd = _pick(args, _CWD_KEYS) or cwd
        if isinstance(cwd, str) and cwd:
            claude["cwd"] = cwd
        return claude, True

    # Namespaced for non-shell tools so a Cursor tool cannot inherit unintended
    # Claude tool nuances. Anything not named falls to the generic path-field scan.
    claude = {"tool_name": "cursor:" + name, "tool_input": args}
    if isinstance(cwd, str) and cwd:
        claude["cwd"] = cwd
    return claude, False


# --- Verdicts ---------------------------------------------------------------

_MSG_NO_REPO = """CURSOR GUARD ADAPTER: blocked because the fleet guards could not be found.

This adapter enforces the same redlines as Claude Code by running the canonical
guards in agent-ops; it holds no rules of its own. It could not locate an
agent-ops checkout from {origin}, so no redline check ran on this call.

A check that could not run is not a pass (conventions/allowlists-fail-both-ways.md),
and under ADR-012 this hook is the only control bounding this lane - so it
denies rather than waving the call through.

Fix the wiring:
  - point the hook entry at the adapter inside the current clone, or
  - set AGENT_OPS_ROOT to the checkout path.
"""

_MSG_GUARD_MISSING = """CURSOR GUARD ADAPTER: blocked because {guard} is missing.

Found an agent-ops checkout at {root}, but {path} is not there. The redline that
guard enforces went unchecked on this call, so the call is denied rather than
silently unguarded (conventions/allowlists-fail-both-ways.md).

Restore the file, or disable the hook entry deliberately.
"""

_MSG_GUARD_BROKE = """CURSOR GUARD ADAPTER: blocked because {guard} could not return a verdict.

{detail}

The guard neither allowed nor blocked this call, so nothing checked it. Under
ADR-012 this hook is the only control on this lane, and an unrun check is not a
pass - so the call is denied.
"""

_MSG_INTERNAL = """CURSOR GUARD ADAPTER: blocked by an internal adapter error.

{detail}

The adapter could not complete a redline check, so it denies rather than fail
open.
"""


def deny(reason: str) -> None:
    """Emit Cursor block response and exit 2 with stderr.

    Both stdout JSON and exit code 2 + stderr are emitted so both stdout-parsing
    and exit-code-parsing hook runners catch the denial.
    """
    json.dump({"decision": "deny", "reason": reason}, sys.stdout)
    sys.stdout.flush()
    sys.stderr.write(reason)
    sys.exit(2)


def allow(payload: dict | None = None) -> None:
    """Pass through on allow.

    If payload is from cursor-agent (carrying cursor_version), emit explicit
    verdict {"permission": "allow"} because cursor-agent records empty stdout as
    a failed hook run. Otherwise exit 0 cleanly.
    """
    if isinstance(payload, dict) and "cursor_version" in payload:
        json.dump({"permission": "allow"}, sys.stdout)
        sys.stdout.flush()
    sys.exit(0)


def _run_guard(script: str, claude_payload: dict) -> tuple[bool, str]:
    """(blocked, reason) from one canonical guard."""
    proc = subprocess.run(
        [sys.executable, script],
        input=json.dumps(claude_payload),
        capture_output=True,
        text=True,
        timeout=_TIMEOUT,
        creationflags=_NO_WINDOW,
    )
    if proc.returncode == 2:
        return True, (proc.stderr.strip() or "(the guard gave no reason)")
    if proc.returncode == 0:
        return False, ""
    raise RuntimeError(
        f"exit status {proc.returncode}; stderr: {proc.stderr.strip()[:400]}"
    )


def main() -> None:
    payload = None
    try:
        # Decode UTF-8 BOM if prepended by Windows PowerShell wrappers
        raw = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
    except Exception:
        allow()

    try:
        payload = json.loads(raw)
    except Exception:
        allow()
    if not isinstance(payload, dict):
        allow()

    try:
        translated = _translate(payload)
        if translated is None:
            allow(payload)
        claude_payload, is_shell = translated

        root = _repo_root()
        if root is None:
            deny(_MSG_NO_REPO.format(origin=os.path.realpath(__file__)))

        for name, relative, shell_only in _GUARDS:
            if shell_only and not is_shell:
                continue
            script = os.path.join(root, relative)
            if not os.path.isfile(script):
                deny(_MSG_GUARD_MISSING.format(guard=name, root=root, path=relative))
            try:
                blocked, reason = _run_guard(script, claude_payload)
            except subprocess.TimeoutExpired:
                deny(_MSG_GUARD_BROKE.format(
                    guard=name, detail=f"It did not finish within {_TIMEOUT}s."))
            except Exception as exc:
                deny(_MSG_GUARD_BROKE.format(guard=name, detail=str(exc)))
            if blocked:
                deny(reason)
    except SystemExit:
        raise
    except Exception as exc:
        deny(_MSG_INTERNAL.format(detail=f"{type(exc).__name__}: {exc}"))

    allow(payload)


if __name__ == "__main__":
    main()
