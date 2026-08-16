#!/usr/bin/env python3
# adapter-version: 1.0 (2026-08-16). Pi tool_call translator under ADR-012.
"""Pi tool_call adapter for the fleet guards.

This file is a translator. It is not a second copy of the redline rules.
The rules live in security/credential-guard.py, hooks/git-staging-guard.py,
and hooks/published-history-guard.py. This file does not inspect a command.
This file does not match a path. This file holds no pattern of its own.

security/posture.md limit 6 records the cost of a second copy: the copy
drifts and ships a gap that the original already fixed.

This adapter rewrites a Pi tool_call into the Claude Code PreToolUse
payload that the canonical guards already read. It runs those guards
unmodified as subprocesses. It writes the verdict for the Pi extension.
A redline change lands in the guards and reaches this lane with no edit
here.

Pi contract:
  stdin is JSON. The event uses toolName and input. The TypeScript
  extension may also send tool_name, toolInput, and tool_input.
  A pass prints nothing and exits 0. A deny prints a short reason on
  stdout and exits 2. Do not print {"decision": "allow"}.

Claude Code contract:
  {"tool_name": "Bash", "tool_input": {"command": ...}} on stdin.
  Exit 0 allows. Exit 2 blocks. The reason is on stderr.

Allow prints nothing on purpose. An explicit allow is an approval.
A guard must not widen permissions when it does not object.

Fail closed. The canonical guards fail open on an unparseable payload.
This adapter does the opposite for its own failures:
  - missing checkout: deny
  - missing guard: deny
  - guard crash or timeout: deny
  - internal error: deny
  - stdin that is not a tool call: pass. That payload has nothing to judge.

On Windows, spawn each guard with CREATE_NO_WINDOW. Use sys.executable
so the child is the real interpreter, not a WindowsApps alias.

Overrides ride in the command string (MASK-OK, STAGE-ALL-OK,
REWRITE-MAIN-OK). This file does not need to know those tokens.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

# --- Locate the canonical guards -------------------------------------------
# Resolve the checkout. Do not copy the guards. AGENT_OPS_ROOT wins so a
# machine that keeps the clone in an unusual place needs no edit here.
# Else walk up from this file's real path (realpath, so a symlink resolves
# into the repo) and stop at the first directory that holds the marker.
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


# Guards run in order. The first block wins. credential-guard is first
# because it is the redline with an incident history behind every clause.
_GUARDS = (
    ("credential-guard", os.path.join("security", "credential-guard.py"), False),
    ("git-staging-guard", os.path.join("hooks", "git-staging-guard.py"), True),
    ("published-history-guard",
     os.path.join("hooks", "published-history-guard.py"), True),
)

# published-history-guard reaches the network (`git ls-remote`, 12s ceiling)
# and may fetch, so the per-guard budget must clear that with room to spare.
_TIMEOUT = 45

# Windows: keep the guard subprocesses from allocating a console window.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


# --- Pi -> Claude Code payload ---------------------------------------------
# Pi shell tools. `bash` is the built-in. `shell` is the same shape if a
# later tool uses that name. Both carry a COMMAND rather than a set of
# fields, which is the only reason this file needs to know any tool name.
# Everything else is handed over as-is.
_SHELL_TOOLS = {
    "bash", "shell",
}

# Key that holds the command line, lowercased for lookup. Observed: `command`.
# The alternatives are cheap insurance against a rename in a tool this file
# cannot see the schema for.
_COMMAND_KEYS = ("command", "commandline", "cmd", "script")
_CWD_KEYS = ("cwd", "workingdirectory", "workingdir", "directory")


def _pick(args: dict, keys: tuple[str, ...]) -> str | None:
    """Return the first value in `args` whose key matches one of `keys`."""
    lowered = {str(k).lower(): v for k, v in args.items()}
    for key in keys:
        value = lowered.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _first(payload: dict, *keys):
    """Return the first present value among `keys`.

    Pi docs use toolName and input. The TypeScript extension also sends
    tool_name, toolInput, and tool_input. Accept both spellings.
    """
    for key in keys:
        if key in payload:
            return payload[key]
    return None


def _translate(payload: dict) -> tuple[dict, bool] | None:
    """Return (claude_payload, is_shell) for a Pi tool_call payload.

    Return None when there is nothing to judge. No tool name, or a shell
    call with no command, is a pass-through, not a failure.
    """
    name = _first(payload, "toolName", "tool_name")
    if not isinstance(name, str) or not name:
        return None
    args = _first(payload, "toolInput", "tool_input", "input")
    if not isinstance(args, dict):
        args = {}

    cwd = _first(payload, "cwd", "workspaceRoot", "workspace_root")

    if name.lower() in _SHELL_TOOLS:
        command = _pick(args, _COMMAND_KEYS)
        if command is None:
            return None
        # The guard treats Bash and PowerShell the same. It applies both
        # dialects. That is the conservative direction. This adapter does
        # not know which shell Pi will use, so it must not guess.
        claude: dict = {"tool_name": "Bash", "tool_input": {"command": command}}
        cwd = _pick(args, _CWD_KEYS) or cwd
        if isinstance(cwd, str) and cwd:
            claude["cwd"] = cwd
        return claude, True

    # Namespace every non-shell tool so a Pi tool cannot inherit Claude
    # tool semantics. Grep in the guard means Claude Code Grep, whose
    # output_mode nuance lets an existence check through. Pi grep is a
    # different tool with different arguments. A silent inherit would be
    # a hole. Anything not named falls to the generic path-field scan.
    claude = {"tool_name": "pi:" + name, "tool_input": args}
    if isinstance(cwd, str) and cwd:
        claude["cwd"] = cwd
    return claude, False


# --- Verdicts ---------------------------------------------------------------

_MSG_NO_REPO = (
    "PI GUARD ADAPTER: blocked because the fleet guards could not be found. "
    "This file holds no rules. It could not locate an agent-ops checkout "
    "from {origin}, so no redline check ran. A check that could not run "
    "is not a pass. Set AGENT_OPS_ROOT to the checkout path."
)

_MSG_GUARD_MISSING = (
    "PI GUARD ADAPTER: blocked because {guard} is missing. "
    "Found an agent-ops checkout at {root}, but {path} is not there. "
    "The redline that guard enforces went unchecked, so this call is "
    "denied. A check that could not run is not a pass."
)

_MSG_GUARD_BROKE = (
    "PI GUARD ADAPTER: blocked because {guard} could not return a verdict. "
    "{detail} "
    "The guard neither allowed nor blocked this call, so nothing checked "
    "it. A check that could not run is not a pass."
)

_MSG_INTERNAL = (
    "PI GUARD ADAPTER: blocked by an internal adapter error. "
    "{detail} "
    "The adapter could not complete a redline check, so it denies rather "
    "than fail open."
)


def deny(reason: str) -> None:
    """Print the reason on stdout and exit 2.

    The TypeScript extension reads stdout as the block reason.
    """
    sys.stdout.write(reason)
    if reason and not reason.endswith("\n"):
        sys.stdout.write("\n")
    sys.stdout.flush()
    sys.exit(2)


def allow() -> None:
    """Pass through. Print nothing.

    Do not emit {"decision": "allow"}. An explicit allow is an approval.
    A guard must not widen permissions when it does not object.
    """
    sys.exit(0)


def _run_guard(script: str, claude_payload: dict) -> tuple[bool, str]:
    """Return (blocked, reason) from one canonical guard.

    Drive the guard the same way Claude Code drives it: JSON on stdin,
    exit 0 allow, exit 2 block.
    """
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
    try:
        # utf-8-sig: a Windows wrapper that pipes through PowerShell may
        # prepend a BOM. A strict decode would turn this adapter into a
        # silent no-op.
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
            allow()
        claude_payload, is_shell = translated

        root = _repo_root()
        if root is None:
            deny(_MSG_NO_REPO.format(origin=os.path.realpath(__file__)))

        for name, relative, shell_only in _GUARDS:
            # git-staging-guard and published-history-guard exit 0 at once
            # for any tool that is not Bash/PowerShell. Skip them for a
            # non-shell call. That drops a process spawn, never a check.
            if shell_only and not is_shell:
                continue
            script = os.path.join(root, relative)
            if not os.path.isfile(script):
                deny(_MSG_GUARD_MISSING.format(
                    guard=name, root=root, path=relative))
            try:
                blocked, reason = _run_guard(script, claude_payload)
            except subprocess.TimeoutExpired:
                deny(_MSG_GUARD_BROKE.format(
                    guard=name,
                    detail=f"It did not finish within {_TIMEOUT}s.",
                ))
            except Exception as exc:
                deny(_MSG_GUARD_BROKE.format(guard=name, detail=str(exc)))
            if blocked:
                deny(reason)
    except SystemExit:
        raise
    except Exception as exc:
        deny(_MSG_INTERNAL.format(detail=f"{type(exc).__name__}: {exc}"))

    allow()


if __name__ == "__main__":
    main()
