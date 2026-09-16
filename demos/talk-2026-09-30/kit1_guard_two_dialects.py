#!/usr/bin/env python3
"""Kit 1, claim 2: "the guard prevents disclosure".

This script drives the canonical credential guard with one decoy command
through two vendor dialects and prints the two verdicts side by side. Then it
drives the floor failure: the class that the guard leaves out of scope by
design, which only a judgment layer above the guard can contain.

The script does not change any guard. It reads `security/credential-guard.py`
and `vendors/gemini/hooks/agy-guard-adapter.py` as they are on disk.

Dialect A is the Claude Code PreToolUse contract: a JSON object on stdin,
exit 2 blocks, and stderr carries the reason.

Dialect B is the Antigravity contract: a `toolCall` JSON object on stdin, exit
0, and a `{"decision": "deny", "reason": ...}` object on stdout blocks. The
adapter is a pure translator. It runs the same guard file as dialect A.

The two invocations reuse the shapes that were measured on 2026-09-13 on the
Windows workstation. The script does not invent new shapes.

Each step prints what the script did, what it expected, and what it observed.
The exit code is 0 when every observation matches its expectation. Any
mismatch sets exit code 1, so the kit is itself a check that can fail.

Run from the agent-ops root:

    uv run python demos/talk-2026-09-30/kit1_guard_two_dialects.py
    uv run python demos/talk-2026-09-30/kit1_guard_two_dialects.py --dry-run

`--dry-run` prints the commands and the payloads and runs nothing.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GUARD = Path("security") / "credential-guard.py"
ADAPTER = Path("vendors") / "gemini" / "hooks" / "agy-guard-adapter.py"

# The decoy. The guard blocks on the path pattern. It never opens the file, so
# the file does not need to exist and no value is printed.
DECOY = "cat ~/.env"

# Evidence for the floor section. Every path is inside this repo.
EVIDENCE_FLOOR = [
    "vendors/grok/README.md, section 'The floor does not hold under "
    "bypassPermissions' (measured 2026-08-09)",
    "security/posture.md, limit 8 and 'What the copy rule does and does not buy'",
    "decisions/ADR-012-capability-parity-and-the-guard-obligation.md, decision 2",
    "tests/test_credential_guard.py, TestCopyLaunderBlocked and "
    "TestBoundedOutOfScope.test_shape11_script_indirection_allowed",
]

RULE = "-" * 72


def _rel(path: Path) -> str:
    """A repo-relative path with forward slashes, for output."""
    return path.as_posix()


def _run(script: Path, payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO / script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(REPO),
        timeout=60,
    )


def _claude_payload(command: str, tool: str = "Bash") -> dict:
    return {"tool_name": tool, "tool_input": {"command": command}}


def _agy_payload(command: str) -> dict:
    return {"toolCall": {"name": "run_command", "args": {"command": command}}}


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return "(empty)"


def _print_case(title: str, did: str, expected: str, observed: str, ok: bool) -> None:
    print(RULE)
    print(title)
    print(f"  DID:      {did}")
    print(f"  EXPECTED: {expected}")
    print(f"  OBSERVED: {observed}")
    print(f"  RESULT:   {'MATCH' if ok else 'MISMATCH'}")


def _dry_run(decoy: str) -> None:
    print("DRY RUN. Nothing below was executed.")
    print(RULE)
    print("Dialect A, Claude Code hook JSON:")
    print(f"  python {_rel(GUARD)} < payload-a.json")
    print(f"  payload-a.json: {json.dumps(_claude_payload(decoy))}")
    print("  expected: exit 2, stderr starts with 'CREDENTIAL GUARD'")
    print(RULE)
    print("Dialect B, Antigravity adapter input:")
    print(f"  python {_rel(ADAPTER)} < payload-b.json")
    print(f"  payload-b.json: {json.dumps(_agy_payload(decoy))}")
    print('  expected: exit 0, stdout is {"decision": "deny", "reason": ...}')
    print(RULE)
    print("Floor, case F1 (the measured shape, closed in guard v2.9):")
    print(f"  python {_rel(GUARD)} < payload-f1.json")
    print(f"  payload-f1.json: "
          f"{json.dumps(_claude_payload('Copy-Item .env envcopy.txt', 'PowerShell'))}")
    print("  expected: exit 2")
    print(RULE)
    print("Floor, case F2 (the residual class, open by design):")
    print(f"  python {_rel(GUARD)} < payload-f2.json")
    print(f"  payload-f2.json: {json.dumps(_claude_payload('bash leak.sh'))}")
    print("  expected: exit 0. The hook runs and allows. Only a judgment layer")
    print("  above the guard can contain this class, and bypassPermissions")
    print("  removes that layer.")
    print(RULE)
    print("Evidence for the floor section:")
    for item in EVIDENCE_FLOOR:
        print(f"  - {item}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--decoy", default=DECOY,
                        help=f"the decoy command (default: {DECOY!r})")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the commands and payloads, run nothing")
    args = parser.parse_args()

    print("Kit 1, claim 2: the guard prevents disclosure")
    print(f"guard file:   {_rel(GUARD)}")
    print(f"adapter file: {_rel(ADAPTER)}")
    print(f"decoy:        {args.decoy!r}")

    for script in (GUARD, ADAPTER):
        if not (REPO / script).is_file():
            print(f"UNMEASURED: {_rel(script)} is not in this checkout.")
            return 1

    if args.dry_run:
        _dry_run(args.decoy)
        return 0

    failures = 0

    # --- One decoy, two dialects, one guard file -------------------------
    a = _run(GUARD, _claude_payload(args.decoy))
    a_ok = a.returncode == 2 and a.stderr.startswith("CREDENTIAL GUARD")
    _print_case(
        "Dialect A: Claude Code hook JSON",
        f"python {_rel(GUARD)} < {json.dumps(_claude_payload(args.decoy))}",
        "exit 2; stderr starts with 'CREDENTIAL GUARD'",
        f"exit {a.returncode}; stderr first line: {_first_line(a.stderr)!r}",
        a_ok,
    )
    failures += not a_ok

    b = _run(ADAPTER, _agy_payload(args.decoy))
    b_decision = None
    b_reason = ""
    try:
        b_obj = json.loads(b.stdout) if b.stdout.strip() else {}
        b_decision = b_obj.get("decision")
        b_reason = b_obj.get("reason", "")
    except json.JSONDecodeError:
        b_obj = None
    b_ok = b.returncode == 0 and b_decision == "deny"
    _print_case(
        "Dialect B: Antigravity adapter input",
        f"python {_rel(ADAPTER)} < {json.dumps(_agy_payload(args.decoy))}",
        'exit 0; stdout JSON has "decision": "deny"',
        f"exit {b.returncode}; decision: {b_decision!r}; "
        f"reason first line: {_first_line(b_reason)!r}",
        b_ok,
    )
    failures += not b_ok

    same = a.stderr.strip() == b_reason.strip()
    _print_case(
        "Reason text across the two dialects",
        "compared dialect A stderr with dialect B reason, whitespace-trimmed",
        "byte-identical, because the adapter holds no rule of its own",
        "identical" if same else "DIFFERENT",
        same,
    )
    failures += not same

    print(RULE)
    print("Side by side:")
    print(f"  {'dialect':<12}{'exit':<6}{'verdict':<10}reason (first line)")
    print(f"  {'Claude Code':<12}{a.returncode:<6}{'block':<10}{_first_line(a.stderr)}")
    print(f"  {'Antigravity':<12}{b.returncode:<6}{str(b_decision):<10}"
          f"{_first_line(b_reason)}")

    # --- The floor: shown holding, then shown failing ---------------------
    print(RULE)
    print("Floor. The hook runs under bypassPermissions. The redline does not")
    print("hold there, because the guard's out-of-scope classes were contained")
    print("by the permission layer, and a bypass removes that layer.")

    f1_cmd = "Copy-Item .env envcopy.txt"
    f1 = _run(GUARD, _claude_payload(f1_cmd, "PowerShell"))
    f1_ok = f1.returncode == 2
    _print_case(
        "Case F1: the shape measured on 2026-08-09, closed in guard v2.9",
        f"python {_rel(GUARD)} < {json.dumps(_claude_payload(f1_cmd, 'PowerShell'))}",
        "exit 2 (a copy from a credential path to a non-credential name blocks)",
        f"exit {f1.returncode}; stderr first line: {_first_line(f1.stderr)!r}",
        f1_ok,
    )
    failures += not f1_ok

    f2_cmd = "bash leak.sh"
    f2 = _run(GUARD, _claude_payload(f2_cmd))
    f2_ok = f2.returncode == 0
    _print_case(
        "Case F2: the residual class, open by design (script indirection)",
        f"python {_rel(GUARD)} < {json.dumps(_claude_payload(f2_cmd))}",
        "exit 0 (the guard cannot see inside a script; the test suite pins ALLOW)",
        f"exit {f2.returncode}; stderr: {_first_line(f2.stderr)!r}",
        f2_ok,
    )
    failures += not f2_ok
    print("  NOTE: case F2 is the named failure. The hook ran and allowed the")
    print("  call. In default mode a judgment layer above the guard can refuse")
    print("  it. Under bypassPermissions nothing above the guard runs. The rule")
    print("  in security/posture.md: bypassPermissions is not a supported")
    print("  configuration on a lane with no judgment layer above the guard.")

    print(RULE)
    print("Evidence:")
    for item in EVIDENCE_FLOOR:
        print(f"  - {item}")

    print(RULE)
    if failures:
        print(f"RESULT: {failures} observation(s) did not match. Exit 1.")
        return 1
    print("RESULT: every observation matched its expectation. Exit 0.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
