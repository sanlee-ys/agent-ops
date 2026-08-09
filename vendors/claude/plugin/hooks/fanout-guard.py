#!/usr/bin/env python3
# hook-version: 1
# DERIVED COPY (draft plugin package). Canonical source: the operator's
# machine-config repo, at claude/hooks/fanout-guard.py. Edit canon, then
# re-copy; see this plugin's README for the drift hazard and the cutover
# that collapses the two.
"""Fan-out cost guard (global PreToolUse hook).

Blocks a Workflow (multi-agent fan-out) call unless it has (a) a token cap and
(b) — for a Fable fan-out specifically — an explicit premium acknowledgement.
This is the harness-level backstop for the pre-flight protocol in the operator's
fan-out cost-control playbook: state tier + estimate + a +Nk cap.
Sonnet and Opus are both fine fan-out defaults (San runs Opus fan-outs on
purpose); Fable is the "out of options" tier — ~2x Opus list price, and the
one confirmed to eat a whole 5-hour window solo (2026-07-02 incident).

Decision (corrected 2026-07-03 — Opus removed from the premium gate):

    no +Nk cap                     -> BLOCK  (state tier + cap, get a go-ahead)
    cap + fable                    -> BLOCK unless PREMIUM-OK is present
    cap + sonnet / opus / unspecified -> allow

Cap signals accepted: "+300k" / "+2M" / the word "budget" / "cap:" / "CAP-OK".
Premium acknowledgement: the token "PREMIUM-OK" anywhere in the call.

This is deliberately global (installed at ~/.claude/hooks and wired from the
global ~/.claude/settings.json), so it fires in EVERY repo and session — the
2026-07-02 incident happened in a session whose repo carried no such guard.

Known limitation (stated, not hidden): the hook sees only the Workflow
tool_input (the script + args), not the session's *default* model. A fan-out
whose agents INHERIT a premium session model without naming it in the script
won't trip the premium gate here. The mandatory cap is the backstop for that
case — and the habit that closes it is declaring the model tier explicitly in
fan-out scripts (an explicit `model: 'sonnet'`, or PREMIUM-OK when you mean it).

Reads the PreToolUse JSON on stdin. Exit 0 = allow, exit 2 = block (stderr is
surfaced back to the model). Fails open (exit 0) on any parse error so a
malformed payload never wedges the tool.
"""
import sys
import json
import re


def main():
    """Run the PreToolUse hook: allow or block a Workflow (fan-out) call.

    Reads the PreToolUse JSON payload from stdin. Non-Workflow tool calls
    are always allowed. A Workflow call is blocked if it has no token cap
    signal (e.g. "+300k", "budget", "cap:", or CAP-OK), and separately
    blocked if it targets the Fable tier without an explicit PREMIUM-OK
    acknowledgement.

    Exits 0 to allow the call, or writes a reason to stderr and exits 2 to
    block it. Also exits 0 (fails open) if stdin isn't valid JSON, so a
    malformed payload never wedges the tool.
    """
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # fail open: never block on a payload we can't read

    if data.get("tool_name") != "Workflow":
        sys.exit(0)

    blob = json.dumps(data.get("tool_input", {}))

    # 1) Cap gate. A fan-out with no ceiling is blocked outright.
    has_cap = (
        re.search(r"\+\s*\d+\s*[kKmM]\b", blob)
        or re.search(r"\b(budget|CAP-OK)\b", blob, re.IGNORECASE)
        or re.search(r"\bcap\s*[:=]", blob, re.IGNORECASE)
    )
    if not has_cap:
        sys.stderr.write(
            "FAN-OUT COST GUARD: this Workflow call has no token cap.\n"
            "One deep-research-class fan-out can burn a full 5-hour usage window.\n"
            "Before launching (see the fan-out cost-control playbook):\n"
            "  1) state the tier + rough token/time estimate,\n"
            "  2) propose a +Nk cap,\n"
            "  3) get the user's explicit go-ahead,\n"
            'then re-invoke with the cap in the args (e.g. "+300k").\n'
            "Override token if the user has already signed off: add CAP-OK.\n"
        )
        sys.exit(2)

    # 2) Fable gate. Sonnet and Opus fan-outs are fine by default (San runs
    #    Opus fan-outs deliberately). Fable is the "out of options" tier —
    #    the one lever that can eat a whole 5-hour window solo.
    fable = re.search(r"\bfable\b", blob, re.IGNORECASE)
    premium_ok = re.search(r"\bPREMIUM-OK\b", blob)
    if fable and not premium_ok:
        sys.stderr.write(
            "FAN-OUT COST GUARD: this fan-out targets claude-fable-5.\n"
            "Fable is the last-resort tier — a full fan-out on it is roughly your\n"
            "entire 5-hour window. Sonnet and Opus fan-outs are fine by default and\n"
            "don't hit this gate. If Fable is genuinely needed, say so and re-invoke\n"
            "with PREMIUM-OK in the args to confirm the cost is intended.\n"
        )
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
