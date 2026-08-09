#!/usr/bin/env python3
# adapter-version: 1.0 (2026-08-08) — wires the fleet guards into Grok Build
# under decisions/ADR-012's guard obligation.
"""Grok Build PreToolUse adapter for the fleet guards.

WHAT THIS IS NOT. It is not a second implementation of the redlines. The rules
live in exactly one place each — `security/credential-guard.py`,
`hooks/git-staging-guard.py`, `hooks/published-history-guard.py` — and this
file never inspects a command, never matches a path, and holds no pattern of
its own. `security/posture.md` limit #6 records what the other choice costs: a
duplicated copy of guard logic drifted out of sync and shipped a gap that had
already been fixed in the original. So the adapter is a pure TRANSLATOR. It
rewrites Grok's tool call into the Claude Code PreToolUse payload the canonical
guards already read, runs them unmodified as subprocesses, and rewrites their
verdict back into Grok's response format. A redline change lands in the guards
and reaches this lane with no edit here.

WHY AN ADAPTER AT ALL — THE SILENT NO-OP.

Grok ships `[compat.claude] hooks = true` by default, which scans
`~/.claude/settings.json` and loads the fleet guards. `grok inspect --json`
duly lists all three as `pre_tool_use` hooks, so the wiring LOOKS present. It
is not. Grok's stdin envelope is **camelCase**:

    {"hookEventName": "pre_tool_use", "toolName": "run_terminal_command",
     "toolInput": {"command": "..."}, "permissionMode": "default", ...}

The guards read `data.get("tool_name")` and `data.get("tool_input")`. Against a
camelCase payload both come back empty, no branch matches, and the guard exits
0 — allow. Measured 2026-08-08 on grok 1.0.0 (3cd0d0cbce): the identical
command `cat <decoy>/.env` exits 2 with the guard's reason under the snake_case
payload and exits 0 silently under Grok's. Grok's own docs state the divergence
(`user-guide/10-hooks.md`, "camelCase input"). So the compat import is not a
partial control; it is a control that has never once fired.

THE TWO CONTRACTS.

  Claude Code  ->  {"tool_name": "Bash", "tool_input": {"command": ...}} on
                   stdin; exit 0 allows, exit 2 blocks with stderr as reason.
  Grok Build   ->  {"toolName": ..., "toolInput": {...}} on stdin; a
                   {"decision": "deny", "reason": ...} object on stdout blocks,
                   and exit 2 is an explicit deny in its own right.

Grok honours exit 2 natively, which is what the guards already do — so unlike
the Antigravity adapter this one has no verdict inversion to perform. What it
still must do is translate the *payload* (or nothing matches) and carry the
guard's *reason* across, since Grok documents stderr as the feedback channel
for `Stop`/`SubagentStop` gates and the stdout `reason` for `PreToolUse`. The
adapter therefore emits BOTH: the deny JSON on stdout and exit 2. They agree,
and either one alone is sufficient, so a swallowed stdout still blocks.

ALLOW PRINTS NOTHING, DELIBERATELY. Grok documents `{"decision": "allow"}` as a
valid response, and the adapter never sends it. An explicit allow from a hook
is an *approval*, not a neutral pass, and whether it short-circuits Grok's
permission mode is not something this repo has measured. Exit 0 with empty
stdout is the documented success path and is unambiguously neutral: the call
proceeds into the normal permission flow instead of past it. A guard must not
widen permissions as a side effect of not objecting.

FAIL CLOSED, AND NOT LIKE THE GUARDS IT CALLS. The canonical guards fail OPEN
on an unparseable payload — availability over strictness for a threat model of
honest mistakes. This adapter inverts that for its own failures. Grok's hook
runner is documented fail-open on every failure class: "All hook failures
(timeouts, crashes, malformed output, missing required env vars) are fail-open
... Only an explicit `deny` decision returned by the hook blocks a tool call."
So here a broken hook is indistinguishable from no hook — the control vanishes
silently and every later call is unguarded. `conventions/allowlists-fail-both-ways.md`
and `conventions/agent-trigger-authorization.md` say the same thing about that
shape: a check that could not run is not a pass. So:

  - guards not found on disk (repo moved, clone deleted) -> DENY, loudly.
  - a guard crashes, or times out                        -> DENY, naming it.
  - an internal error anywhere in this file              -> DENY.
  - stdin that is not a tool call we recognise           -> pass through. That
    is not a failure; it is a payload with nothing to judge.

The one hole that cannot be closed from inside: if THIS FILE is deleted or its
configured path stops resolving, the hook command fails to launch and Grok
fails open. Nothing running inside the hook can catch that. Recorded in
`vendors/grok/README.md` as a residual gap rather than papered over.

NO CONSOLE WINDOWS. On Windows the guards are spawned with CREATE_NO_WINDOW.
Bare `python3` on a provisioned Windows box resolves to the WindowsApps App
Execution Alias, which allocates a visible conhost and re-execs — the 2026-08-06
orphaned-hook-window incident. Two defences: the deployed hook command names an
absolute interpreter (see `hooks.windows.json`), and the child spawns here go
through `sys.executable`, which is the real interpreter rather than the alias,
with the no-window flag on top.

OVERRIDES come free. Each guard's escape hatch (`MASK-OK`, `STAGE-ALL-OK`,
`REWRITE-MAIN-OK`) is a token in the command string, and the command string is
passed through verbatim, so the overrides work here exactly as they do in
Claude Code without this file knowing they exist.
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

# published-history-guard reaches the network (`git ls-remote`, 12s ceiling) and
# may fetch, so the per-guard budget has to clear that with room to spare. The
# `timeout` on the hook entry must in turn clear the sum of these — Grok's
# default is 5 SECONDS and a timed-out hook fails open, so an unset timeout is
# not a slow guard, it is no guard.
_TIMEOUT = 45

# Windows: keep the guard subprocesses from allocating a console window.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


# --- Grok -> Claude Code payload --------------------------------------------
# Grok's shell tool. `run_terminal_command` is the name in the hook payload
# example and the tool-alias table (`Bash` -> `run_terminal_command`);
# `run_terminal_cmd` appears in the headless `--disallowed-tools` examples, and
# Cursor-compat routing can surface `Shell`. All of them carry a COMMAND rather
# than a set of fields, which is the only reason this file needs to know any
# tool name at all. Everything else is handed over as-is.
_SHELL_TOOLS = {
    "run_terminal_command", "run_terminal_cmd", "shell", "bash", "powershell",
}

# Key holding the command line, lowercased for lookup. Observed: `command`.
# The alternatives are cheap insurance against a rename in a tool this file
# cannot see the schema for.
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
    """First present value among `keys`. Grok's wire format is camelCase, but
    hooks registered through the grok-agent-sdk arrive snake_cased, so both
    spellings are accepted rather than guessing which side registered us."""
    for key in keys:
        if key in payload:
            return payload[key]
    return None


def _translate(payload: dict) -> tuple[dict, bool] | None:
    """(claude_payload, is_shell) for a Grok PreToolUse payload.

    None when there is nothing to judge — no tool name, or a call carrying no
    arguments at all. That is a pass-through, not a failure.
    """
    name = _first(payload, "toolName", "tool_name")
    if not isinstance(name, str) or not name:
        return None
    args = _first(payload, "toolInput", "tool_input")
    if not isinstance(args, dict):
        args = {}

    cwd = _first(payload, "cwd", "workspaceRoot", "workspace_root")

    if name.lower() in _SHELL_TOOLS:
        command = _pick(args, _COMMAND_KEYS)
        if command is None:
            return None
        # "Bash" and "PowerShell" are treated identically by the guard, which
        # applies BOTH dialects' rules to whichever it is handed. That is the
        # conservative direction and it is what we want: the adapter does not
        # know which shell Grok will use, so it should not have to guess.
        claude: dict = {"tool_name": "Bash", "tool_input": {"command": command}}
        cwd = _pick(args, _CWD_KEYS) or cwd
        if isinstance(cwd, str) and cwd:
            claude["cwd"] = cwd            # published-history-guard needs a repo
        return claude, True

    # Deliberately namespaced so a Grok tool can never inherit the semantics of
    # a Claude tool that happens to share its name. `Grep` in the guard means
    # Claude Code's Grep, whose `output_mode` nuance lets an existence check
    # through; Grok's `grep` is a different tool with different arguments, and
    # inheriting that nuance by accident would be a silent hole. Anything not
    # named falls to the generic path-field scan — the tool-shape-agnostic
    # default-deny that is the structural fix for the 2026-07-04 gap, where a
    # reader tool nobody had enumerated yet walked straight past a hard-coded
    # tool list.
    claude = {"tool_name": "grok:" + name, "tool_input": args}
    if isinstance(cwd, str) and cwd:
        claude["cwd"] = cwd
    return claude, False


# --- Verdicts ---------------------------------------------------------------

_MSG_NO_REPO = """GROK GUARD ADAPTER: blocked because the fleet guards could not be found.

This adapter enforces the same redlines as Claude Code by running the canonical
guards in agent-ops; it holds no rules of its own. It could not locate an
agent-ops checkout from {origin}, so no redline check ran on this call.

A check that could not run is not a pass (conventions/allowlists-fail-both-ways.md),
and under ADR-012 this hook is the only control bounding this lane - so it
denies rather than waving the call through.

Fix the wiring, from a shell or another harness:
  - point the hook entry in ~/.grok/hooks/ at the adapter inside the current
    clone, or
  - set AGENT_OPS_ROOT to the checkout path.
To disable the guard deliberately, remove the hook file or disable the entry
in the /hooks modal.
"""

_MSG_GUARD_MISSING = """GROK GUARD ADAPTER: blocked because {guard} is missing.

Found an agent-ops checkout at {root}, but {path} is not there. The redline that
guard enforces went unchecked on this call, so the call is denied rather than
silently unguarded (conventions/allowlists-fail-both-ways.md).

Restore the file, or remove the hook entry to disable the guard deliberately.
"""

_MSG_GUARD_BROKE = """GROK GUARD ADAPTER: blocked because {guard} could not return a verdict.

{detail}

The guard neither allowed nor blocked this call, so nothing checked it. Under
ADR-012 this hook is the only control on this lane, and an unrun check is not a
pass - so the call is denied.
"""

_MSG_INTERNAL = """GROK GUARD ADAPTER: blocked by an internal adapter error.

{detail}

The adapter could not complete a redline check, so it denies rather than fail
open. Grok fails OPEN on every hook failure class, which would make a broken
guard indistinguishable from no guard - this deny is what keeps that
distinguishable.
"""


def deny(reason: str) -> None:
    """Emit Grok's block response and exit.

    Both channels, on purpose. The stdout `decision` is what Grok surfaces to
    the model as the reason; exit 2 is an explicit deny in its own right and
    is honoured even if the stdout body is never parsed. They agree, so either
    alone is sufficient and the deny survives losing one of them.
    """
    json.dump({"decision": "deny", "reason": reason}, sys.stdout)
    sys.stdout.flush()
    sys.stderr.write(reason)
    sys.exit(2)


def allow() -> None:
    """Pass through. Prints NOTHING on purpose — see the module docstring: an
    explicit `{"decision": "allow"}` is an approval, and a guard must not widen
    permissions as a side effect of not objecting."""
    sys.exit(0)


def _run_guard(script: str, claude_payload: dict) -> tuple[bool, str]:
    """(blocked, reason) from one canonical guard, driven exactly as the Claude
    Code harness drives it: JSON on stdin, exit 0 allow / exit 2 block."""
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
    # Any other code is the guard failing, not deciding.
    raise RuntimeError(
        f"exit status {proc.returncode}; stderr: {proc.stderr.strip()[:400]}"
    )


def main() -> None:
    try:
        # utf-8-sig for the same reason the canonical guards decode that way:
        # a Windows wrapper that pipes the payload through PowerShell prepends
        # a BOM, and a strict decode turns the guard into a silent no-op.
        raw = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
    except Exception:
        allow()                        # nothing to judge; not a failed check

    try:
        payload = json.loads(raw)
    except Exception:
        allow()                        # same posture as the canonical guards
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
            # git-staging-guard and published-history-guard exit 0 immediately
            # for any tool that is not Bash/PowerShell, so skipping them for a
            # non-shell call is provably behaviour-preserving - it drops a
            # process spawn, never a check.
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
            except Exception as exc:                 # crashed, not decided
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
