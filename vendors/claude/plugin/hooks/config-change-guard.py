#!/usr/bin/env python3
# hook-version: 1.0 (2026-08-09)
"""Config tamper guard (global ConfigChange hook) — keeps the guard chain wired.

The fleet's safety posture (agent-ops ADR-012) rests on a single mechanism:
every vendor has the PreToolUse guard hooks wired at tool time. Guard wiring is
the *whole* of the control — so a settings edit that quietly drops a guard, or
sets `disableAllHooks`, disarms the posture without tripping anything. That edit
is exactly the shape an agent produces while "cleaning up settings.json", which
puts it inside the non-adversarial threat model the other guards are written for.

This hook watches the two scopes that carry the guard chain — user settings
(~/.claude/settings.json) and managed/policy settings — and blocks a change that
leaves the resulting file without one of:

    credential-guard, published-history-guard, git-staging-guard, fanout-guard

or with `disableAllHooks` enabled. project/local settings are NOT watched: they
can't carry the global chain, and blocking them would be noise.

MECHANISM NOTE (measured against the documented payload, code.claude.com/docs/
en/hooks.md): the ConfigChange payload carries only `config_source` and
`config_path` — there is no before/after diff. So this is a POST-CHANGE STATE
check, not a diff check: it reads the file at `config_path` and asks whether the
chain is intact *now*. Practical consequence — it cannot tell "you removed it"
from "it was already missing", and it reports what is absent rather than what was
stripped. That is the honest limit of the available payload, and it is the right
direction for a guard: a settings file that lacks a guard fails whether the
current edit is what lost it or not.

Deliberately out of scope, matching credential-guard.py's posture: a rename or a
path change that keeps the guard's NAME but points at a neutered script, and any
edit made outside a Claude session (this only fires on in-session changes).
Containment for those is the same as everywhere else — the file is version
controlled, and a human reviews it.

FAILS OPEN, loudly. A broken guard must never wedge settings edits: any parse
failure, missing file, or unexpected payload allows the change and writes a
diagnostic to stderr. The asymmetry is deliberate — the cost of a false block
here is a bricked config the user cannot repair through Claude, which is strictly
worse than the cost of one missed tamper on a version-controlled file.

Exit 0 = allow. Block is emitted as `{"decision": "block", "reason": ...}` on
stdout with exit 0 (the documented JSON form), with the reason mirrored to
stderr so it surfaces even if the JSON path is ignored.
"""
import sys
import json

# Guard scripts whose presence in the hooks config is the safety posture.
# Matched as substrings of the serialized hooks block, so the check is
# indifferent to how the command is spelled ($HOME vs an absolute path,
# python3 vs uv run) — it only asks whether the guard is still referenced.
REQUIRED_GUARDS = (
    "credential-guard",
    "published-history-guard",
    "git-staging-guard",
    "fanout-guard",
)

# Only the scopes that can carry the global guard chain.
WATCHED_SOURCES = {"user_settings", "policy_settings"}


def _allow():
    sys.exit(0)


def _block(reason):
    sys.stderr.write(reason)
    print(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)


def _fail_open(why):
    sys.stderr.write("config-change-guard: failing open — %s\n" % why)
    sys.exit(0)


def main():
    try:
        raw = sys.stdin.read()
    except Exception as exc:                      # pragma: no cover
        _fail_open("could not read stdin (%s)" % exc)
    try:
        # utf-8-sig: a PowerShell-wrapped caller can prepend a BOM, which made
        # credential-guard v2.7 fail open on every call (see its v2.8 note).
        data = json.loads(raw.encode("utf-8", "replace").decode("utf-8-sig"))
    except Exception as exc:
        _fail_open("unparseable payload (%s)" % exc)
    if not isinstance(data, dict):
        _fail_open("payload is not an object")

    source = data.get("config_source")
    if source not in WATCHED_SOURCES:
        _allow()

    path = data.get("config_path")
    if not isinstance(path, str) or not path:
        _fail_open("no config_path in a %s payload" % source)

    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            settings = json.load(fh)
    except FileNotFoundError:
        _fail_open("config_path does not exist: %s" % path)
    except Exception as exc:
        # An edit mid-write, or JSONC the loader accepts and we don't: allowing
        # is the only safe move — see FAILS OPEN above.
        _fail_open("could not parse %s (%s)" % (path, exc))
    if not isinstance(settings, dict):
        _fail_open("%s is not a settings object" % path)

    problems = []

    if settings.get("disableAllHooks"):
        problems.append(
            "  - disableAllHooks is set, which disarms EVERY hook at once"
        )

    hooks_blob = json.dumps(settings.get("hooks", {}))
    missing = [g for g in REQUIRED_GUARDS if g not in hooks_blob]
    if missing:
        problems.append(
            "  - these guard hooks are no longer registered: "
            + ", ".join(missing)
        )

    if not problems:
        _allow()

    _block(
        "CONFIG-CHANGE GUARD: this change would leave %s without part of the\n"
        "fleet guard chain:\n%s\n"
        "Guard wiring is the whole of the safety control (agent-ops ADR-012), so\n"
        "removing or disabling a guard is not an edit an agent makes on its own.\n"
        "The change has been blocked. If San genuinely intends it, he makes it\n"
        "by hand in %s, outside a Claude session.\n"
        % (path, "\n".join(problems), path)
    )


if __name__ == "__main__":
    main()
