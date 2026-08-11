#!/usr/bin/env python3
# hook-version: 1.0 (2026-08-11)
"""Secret-redaction guard (PreToolUse hook) — redact-and-allow for secret VALUES.

WHAT THIS ADDS. `credential-guard.py` judges credential *paths*: a command
that reads `~/.env` blocks, because redacting the path would break the
command. This guard judges credential *values*: a literal secret already
present in `tool_input` (a pasted key in a command, a token in file content
about to be written). A path read must block; a literal value can be REMOVED
and the call can proceed. So this guard rewrites instead of refusing:

  1. Recursively walk every string in `tool_input`.
  2. Replace each matched secret with `[REDACTED:<rule_id>]`.
  3. Return an allow verdict with `hookSpecificOutput.updatedInput` set to the
     rewritten input, and a `permissionDecisionReason` naming the redaction
     count and the matched types.

The design is ported from the public secguard project (Apache-2.0 + Commons
Clause); the code is a fresh Python implementation. See decisions/ADR-015.

VENDOR SPLIT. Rewrite-and-allow needs a hook contract that honours
`updatedInput`. Claude Code and cursor-agent do. Codex does not — it also
ignores an `ask` verdict — so for `--target codex` a finding gets a deny
verdict plus the exit-2 backstop instead. Wire the flag per vendor at deploy
time; the default is the Claude contract.

PATTERNS. High-precision, prefix-anchored token shapes only (AKIA…, ghp_…,
sk-ant-…, xoxb-…, a private-key block, a user:password URL). No entropy
heuristics: a false redaction silently corrupts the tool call, which is worse
than the miss — the path-based guard and the permission layer still stand
behind this one. Markers this guard emits never re-match, so a double scan is
idempotent.

SHADOW MODE. AGENT_OPS_GUARD_SHADOW truthy: log what would be redacted (types
and count only — never the values) and change nothing.

WHAT THIS IS NOT. Not a replacement for credential-guard.py, and not
complete: an obfuscated or split secret passes. This raises the cost of the
common accident — a live token pasted into a command or a file — and keeps
the call working instead of failing it.
"""

from __future__ import annotations

import json
import os
import re
import sys

SHADOW_ENV = "AGENT_OPS_GUARD_SHADOW"

# rule_id -> (keyword prefilter, pattern). The keyword makes the common clean
# path one `in` check per rule; the pattern's `secret` group is what gets
# replaced. Prefix-anchored shapes only — see "PATTERNS" above.
RULES: list[tuple[str, str, re.Pattern]] = [
    ("aws_access_key", "AKIA",
     re.compile(r"(?P<secret>AKIA[0-9A-Z]{16})(?![0-9A-Z])")),
    ("github_pat", "gh",
     re.compile(r"(?P<secret>gh[pousr]_[A-Za-z0-9]{36,255})")),
    ("github_fine_grained_pat", "github_pat_",
     re.compile(r"(?P<secret>github_pat_[A-Za-z0-9_]{82})")),
    ("anthropic_api_key", "sk-ant-",
     re.compile(r"(?P<secret>sk-ant-[A-Za-z0-9_-]{20,})")),
    ("openai_api_key", "sk-proj-",
     re.compile(r"(?P<secret>sk-proj-[A-Za-z0-9_-]{20,})")),
    ("stripe_api_key", "sk_",
     re.compile(r"(?P<secret>sk_(?:live|test)_[A-Za-z0-9]{16,})")),
    ("slack_token", "xox",
     re.compile(r"(?P<secret>xox[baprs]-[A-Za-z0-9-]{10,})")),
    ("jwt", "eyJ",
     re.compile(r"(?P<secret>eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}"
                r"\.[A-Za-z0-9_-]{8,})")),
    ("private_key_block", "PRIVATE KEY",
     re.compile(r"(?P<secret>-----BEGIN [A-Z ]*PRIVATE KEY-----"
                r"[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----)")),
    ("connection_string", "://",
     re.compile(r"[a-z][a-z0-9+.-]*://[^\s:/@'\"]+:(?P<secret>[^\s/@'\"]+)@")),
]


def redact_text(text: str) -> tuple[str, list[str]]:
    """(redacted text, matched rule ids). Longest-first per position; a span
    already replaced is never rescanned, so markers are idempotent."""
    found: list[str] = []
    for rule_id, keyword, pattern in RULES:
        if keyword not in text:
            continue
        def _sub(m: re.Match, rid=rule_id) -> str:
            found.append(rid)
            s, e = m.span("secret")
            return m.group(0)[: s - m.start()] + f"[REDACTED:{rid}]" \
                + m.group(0)[e - m.start():]
        text = pattern.sub(_sub, text)
    return text, found


def redact_value(value):
    """(rewritten value, matched rule ids) for any JSON value, recursively."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        out, found = {}, []
        for k, v in value.items():
            out[k], f = redact_value(v)
            found.extend(f)
        return out, found
    if isinstance(value, list):
        out, found = [], []
        for v in value:
            r, f = redact_value(v)
            out.append(r)
            found.extend(f)
        return out, found
    return value, []


def _is_shadow() -> bool:
    raw = os.environ.get(SHADOW_ENV, "").strip().lower()
    return raw not in {"", "0", "off", "false"}


def _allow(payload) -> None:
    if isinstance(payload, dict) and "cursor_version" in payload:
        print('{"permission": "allow"}')
    sys.exit(0)


def main() -> None:
    target = "codex" if "--target" in sys.argv and "codex" in sys.argv else "claude"

    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        sys.exit(0)  # fail open on an unreadable payload, like the other guards

    tool_input = data.get("tool_input")
    if not isinstance(tool_input, (dict, list, str)):
        _allow(data)

    updated, found = redact_value(tool_input)
    if not found:
        _allow(data)

    types = sorted(set(found))
    summary = f"Redacted {len(found)} credential(s). Types: {', '.join(types)}"
    event = data.get("hook_event_name") or "PreToolUse"

    if _is_shadow():
        sys.stderr.write(
            f"[secret-redaction-guard][shadow] would redact (logged only): "
            f"{summary}\n"
        )
        _allow(data)

    if target == "codex":
        # Codex ignores `ask` and does not honour updatedInput, so a finding
        # is a deny there, with the exit-2 backstop.
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": event,
                "permissionDecision": "deny",
                "permissionDecisionReason": summary,
            },
            "systemMessage": summary,
        }))
        sys.stderr.write(f"SECRET-REDACTION GUARD: {summary}\n")
        sys.exit(2)

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": event,
            "permissionDecision": "allow",
            "permissionDecisionReason": summary,
            "updatedInput": updated,
        }
    }))
    sys.stderr.write(f"[secret-redaction-guard] {summary}\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
