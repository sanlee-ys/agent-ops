#!/usr/bin/env python3
# adapter-version: 1.0 (2026-08-04) — closes decisions/ADR-012 item 4.
"""Antigravity PreToolUse adapter for the fleet guards.

WHAT THIS IS NOT. It is not a second implementation of the redlines. The
credential rules live in exactly one place — `security/credential-guard.py` —
and this file never inspects a command, never matches a path, and holds no
pattern of its own. `security/posture.md` limit #6 records what the other
choice costs: a duplicated copy of the guard's logic drifted out of sync and
shipped a gap that had already been fixed in the original. So the adapter is a
pure TRANSLATOR. It rewrites Antigravity's tool call into the Claude Code
PreToolUse payload the canonical guards already read, runs them unmodified as
subprocesses, and rewrites their verdict back into Antigravity's response
format. Any change to the redlines happens in the guards and reaches this lane
with no edit here — which is the property that makes the drift impossible
rather than merely unlikely.

WHY AN ADAPTER AT ALL. ADR-012 made capability parity the fleet default and
retired "Antigravity defaults to read-only". That deleted the only thing
bounding this lane, so guard wiring became the sole remaining control and the
adapter became an owed deliverable rather than a nice-to-have.

THE TWO CONTRACTS, AND WHY THEY NEED TRANSLATING.

  Claude Code  ->  {"tool_name": "Bash", "tool_input": {"command": ...}} on
                   stdin; exit 0 allows, exit 2 blocks with stderr as the
                   reason.
  Antigravity  ->  {"toolCall": {"name": ..., "args": {...}}, ...} on stdin;
                   a JSON object on stdout carries the decision.

MEASURED SEMANTICS (2026-08-04, this machine, agy CLI). Every line below was
observed, not read off the documentation — the deny path had never been
exercised anywhere before this:

  - `{"decision": "deny", "reason": "..."}` HARD-BLOCKS the call, and the
    reason is surfaced to the model verbatim. It blocks even under
    `--dangerously-skip-permissions`; that flag governs the permission system,
    and the hook is a separate code path upstream of it. The guard is a real
    floor, not a speed bump.
  - EMPTY STDOUT is the pass-through. This is the non-obvious one and it is
    why the adapter prints nothing on allow: `{}` is NOT neutral. A well-formed
    response carrying no `decision` is read as a deny with an empty reason, and
    every tool call in the probe run died that way. Emitting
    `{"decision": "allow"}` would be worse still — it AUTO-APPROVES, bypassing
    the permission reviewer the store actually relies on. Silence is the only
    output that leaves the normal flow intact.
  - A HOOK THAT ERRORS FAILS OPEN. Non-zero exit, or a command that cannot be
    launched, and the tool call proceeds anyway (observed: a bad script path
    logged `pre-tool hook failed` and the command still ran). This inverts
    Claude Code, where a missing PreToolUse script is a hard error. It is the
    reason for the fail-CLOSED rule below.

FAIL CLOSED, DELIBERATELY, AND NOT LIKE THE GUARDS IT CALLS. The canonical
guards fail OPEN on an unparseable payload — availability over strictness for a
threat model of honest mistakes. This adapter inverts that for its own
failures, because the asymmetry above changes what a failure means. In Claude
Code a broken hook wedges the session, so the breakage announces itself. Here a
broken hook is indistinguishable from no hook: the control vanishes silently
and every subsequent call is unguarded. `conventions/allowlists-fail-both-ways.md`
and `conventions/agent-trigger-authorization.md` both say the same thing about
that shape — a check that could not run is not a pass. So:

  - guards not found on disk (repo moved, clone deleted) -> DENY, loudly.
  - a guard crashes, or times out -> DENY, naming which one.
  - an internal error anywhere in this file -> DENY.
  - stdin that is not a tool call we recognise -> pass through. That is not a
    failure; it is a payload with nothing to judge.

The one hole that cannot be closed from inside: if THIS FILE is deleted or its
path in `hooks.json` stops resolving, the hook command fails to launch and
Antigravity fails open. Nothing running inside the hook can catch that. It is
recorded in `vendors/gemini/README.md` as a residual gap rather than papered
over.

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
    # hook-tamper is NOT shell-only: it judges Write/Edit payloads as well as
    # shell commands, because both routes reach a deployed guard file.
    ("hook-tamper-guard", os.path.join("hooks", "hook-tamper-guard.py"), False),
)

# published-history-guard reaches the network (`git ls-remote`, 12s ceiling) and
# may fetch, so the per-guard budget has to clear that with room to spare. The
# `timeout` in hooks.json must in turn clear the sum of these.
_TIMEOUT = 45


# --- Antigravity -> Claude Code payload -------------------------------------
# Tool names are the lowercased step type minus its CORTEX_STEP_TYPE_ prefix,
# and the shell-running ones are the only names this file needs to know: they
# are the calls whose payload is a COMMAND rather than a set of fields, so they
# are the only ones whose mapping is not mechanical. Everything else is handed
# over as-is and judged by the guard's field scan, which is tool-shape-agnostic
# by design (it is the structural fix for the 2026-07-04 gap, where a reader
# tool nobody had enumerated yet walked straight past a hard-coded tool list).
_SHELL_TOOLS = {"run_command", "shell_exec", "send_command_input"}

# The arg key holding the command line, lowercased for lookup. Observed:
# `CommandLine` on run_command. The alternatives are cheap insurance against a
# rename in a tool this file cannot see the schema for.
_COMMAND_KEYS = ("commandline", "command", "cmd")
_CWD_KEYS = ("cwd", "workingdirectory", "workingdir", "directory")


def _pick(args: dict, keys: tuple[str, ...]) -> str | None:
    """First value in `args` whose key matches one of `keys`, case-insensitively."""
    lowered = {str(k).lower(): v for k, v in args.items()}
    for key in keys:
        value = lowered.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _translate(payload: dict) -> tuple[dict, bool] | None:
    """(claude_payload, is_shell) for an Antigravity PreToolUse payload.

    None when there is nothing to judge — no tool call, or a call carrying no
    arguments at all. That is a pass-through, not a failure.
    """
    call = payload.get("toolCall")
    if not isinstance(call, dict):
        return None
    name = call.get("name")
    if not isinstance(name, str) or not name:
        return None
    args = call.get("args")
    if not isinstance(args, dict):
        args = {}

    if name in _SHELL_TOOLS:
        command = _pick(args, _COMMAND_KEYS)
        if command is None:
            return None
        # "Bash" and "PowerShell" are treated identically by the guard, which
        # applies BOTH dialects' rules to whichever it is handed. That is the
        # conservative direction and it is what we want: the adapter does not
        # know which shell Antigravity will use, so it should not have to guess.
        claude = {"tool_name": "Bash", "tool_input": {"command": command}}
        cwd = _pick(args, _CWD_KEYS)
        if cwd is None:
            paths = payload.get("workspacePaths")
            if isinstance(paths, list) and paths and isinstance(paths[0], str):
                cwd = paths[0]
        if cwd:
            claude["cwd"] = cwd            # published-history-guard needs a repo
        return claude, True

    # Deliberately namespaced so it can never collide with a name the guard
    # special-cases. `Grep` there means Claude Code's Grep, with its
    # output-mode nuance; an Antigravity tool that happens to be called `grep`
    # is a different tool with different args, and inheriting that nuance by
    # accident would be a silent hole. Anything not named falls to the generic
    # path-field scan, which is exactly where an unknown tool belongs.
    return {"tool_name": "agy:" + name, "tool_input": args}, False


# --- Verdicts ---------------------------------------------------------------

_MSG_NO_REPO = """ANTIGRAVITY GUARD ADAPTER: blocked because the fleet guards could not be found.

This adapter enforces the same redlines as Claude Code by running the canonical
guards in agent-ops; it holds no rules of its own. It could not locate an
agent-ops checkout from {origin}, so no redline check ran on this call.

A check that could not run is not a pass (conventions/allowlists-fail-both-ways.md),
and under ADR-012 this hook is the only control bounding this lane - so it
denies rather than waving the call through.

Fix the wiring, from a shell or another harness:
  - point ~/.gemini/config/hooks.json at the adapter inside the current clone, or
  - set AGENT_OPS_ROOT to the checkout path.
To disable the guard deliberately, set "enabled": false on the hook entry.
"""

_MSG_GUARD_MISSING = """ANTIGRAVITY GUARD ADAPTER: blocked because {guard} is missing.

Found an agent-ops checkout at {root}, but {path} is not there. The redline that
guard enforces went unchecked on this call, so the call is denied rather than
silently unguarded (conventions/allowlists-fail-both-ways.md).

Restore the file, or set "enabled": false on the hook entry in
~/.gemini/config/hooks.json to disable the guard deliberately.
"""

_MSG_GUARD_BROKE = """ANTIGRAVITY GUARD ADAPTER: blocked because {guard} could not return a verdict.

{detail}

The guard neither allowed nor blocked this call, so nothing checked it. Under
ADR-012 this hook is the only control on this lane, and an unrun check is not a
pass - so the call is denied.
"""

_MSG_INTERNAL = """ANTIGRAVITY GUARD ADAPTER: blocked by an internal adapter error.

{detail}

The adapter could not complete a redline check, so it denies rather than fail
open. Antigravity fails OPEN when a hook errors, which would make a broken
guard indistinguishable from no guard - this deny is what keeps that
distinguishable.
"""


def deny(reason: str) -> None:
    """Emit Antigravity's hard-block response and exit."""
    json.dump({"decision": "deny", "reason": reason}, sys.stdout)
    sys.exit(0)


def allow() -> None:
    """Pass through. Prints NOTHING on purpose — see the module docstring: `{}`
    is read as a deny, and `{"decision": "allow"}` auto-approves past the
    permission reviewer. Silence is the only neutral answer."""
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
        raw = sys.stdin.read()
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
