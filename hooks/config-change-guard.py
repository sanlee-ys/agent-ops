#!/usr/bin/env python3
# hook-version: 1.2 (2026-08-19)
"""Config tamper guard (global ConfigChange hook) — keeps the guard chain wired.

The fleet's safety posture (agent-ops ADR-012) rests on a single mechanism:
every vendor has the PreToolUse guard hooks wired at tool time. Guard wiring is
the *whole* of the control — so a settings edit that quietly drops a guard, or
sets `disableAllHooks`, disarms the posture without tripping anything. That edit
is exactly the shape an agent produces while "cleaning up settings.json", which
puts it inside the non-adversarial threat model the other guards are written for.

This hook watches the two scopes that carry the guard chain — user settings
(~/.claude/settings.json) and managed/policy settings. project/local settings are
NOT watched: they can't carry the global chain, and blocking them would be noise.

v1.1 — WHAT THE NAME PROMISED, AND WHAT v1.0 ACTUALLY CHECKED

v1.0 checked two things: `disableAllHooks`, and whether four guard names appeared
as substrings of the serialized `hooks` blob. Both directions of that were too
narrow, and the gap was not academic — a settings file could keep all four names,
pass v1.0 cleanly, and still hand a session unrestricted power. Every check below
is additive; nothing v1.0 refused is now allowed.

  1. `permissions.defaultMode == "bypassPermissions"` is blocked. v1.0 never read
     `permissions` at all, so a single Edit adding that key disarmed the entire
     permission layer while leaving all four guard names present — i.e. v1.0
     reported the chain "intact" on a config that had none of its protection.
  2. `permissions.allow` entries granting unrestricted shell are blocked —
     `Bash`, `Bash(*)`, `Bash(:*)`, `Bash(*:*)` and the PowerShell/Shell
     equivalents. Same end state as (1), spelled differently. A rule with a real
     prefix (`Bash(git status)`) is an ordinary allowlist entry and is never
     flagged; narrowing those is a /doctor concern, not a tamper signal.
  3. `env` keys that redirect model traffic or plant ambient credentials are
     blocked. Deliberately a short, explicit list — an `env` block per se is
     normal and is not itself a problem.
  4. The guard-presence check is STRUCTURAL, not a substring over the whole
     serialized blob. v1.0 asked "does the string 'credential-guard' appear
     anywhere in `hooks`?", which passed for a guard moved to `PostToolUse`, a
     guard given an empty matcher, and a command repointed at
     `credential-guard-disabled.py` (that string *contains* `credential-guard`).
     v1.1 requires each guard to appear under its expected event, with a
     non-empty matcher, and a command referencing the exact `<guard>.py`
     filename.

MECHANISM NOTE (measured against the documented payload, code.claude.com/docs/
en/hooks.md): the ConfigChange payload carries only `config_source` and
`config_path` — there is no before/after diff. So this is a POST-CHANGE STATE
check, not a diff check: it reads the file at `config_path` and asks whether the
result is safe *now*. Practical consequence — it cannot tell "you removed it"
from "it was already missing", and it reports what is absent rather than what was
stripped. That is the honest limit of the available payload, and it is the right
direction for a guard: a settings file that lacks a guard fails whether the
current edit is what lost it or not.

The docs say ConfigChange fires before the configuration TAKES EFFECT, which
means a block prevents the in-memory reload, NOT the on-disk write. The bad file
is on disk either way. This guard is therefore a tripwire, not a gate, and must
never be the only thing standing between an agent and a dangerous settings edit.

STILL OUT OF SCOPE, stated rather than claimed closed:
  - `~/.claude.json` is NOT a settings scope and never reaches this hook. Its
    protection is credential-guard's path block — which is the whole reason that
    write block must stay.
  - A command keeping the exact `<guard>.py` filename but pointing at a gutted
    copy in a different directory.
  - Any edit made outside a Claude session. Containment there is the same as
    everywhere else: the file is version controlled, and a human reviews it.

STILL UNMEASURED — do not credit this guard as enforcing anything. Two facts must
hold for it to do its job, and as of 2026-08-09 neither has been observed on a
live harness: (a) whether `ConfigChange` fires at all when an Edit/Write *tool*
modifies a settings file, as opposed to an in-app `/config` change; and (b)
whether `{"decision": "block"}` with exit 0 actually vetoes the change. Three
independent attempts to measure this have now been closed off by the fleet's own
guard chain — the Edit/Write route is refused by credential-guard, the harness
separately denies writes under `.claude/`, and an attempt to stand up a scratch
probe rig was itself refused because composing the command requires naming a
Claude config path. Measuring it needs an INTERACTIVE session and a scratch
config; the procedure, and everything already ruled out, is in `hooks/README.md`.
Per `security/posture.md` limit 7, an unmeasured claim does not count.

FAILS OPEN, loudly — unchanged and deliberate. Any parse failure, missing file,
or unexpected payload allows the change and writes a diagnostic to stderr. The
asymmetry is the point: a false block here is a bricked config the user cannot
repair through Claude — the repair would itself be a config change this guard
blocks again — which is strictly worse than one missed tamper on a version-
controlled file. Every check above blocks only on an unambiguously dangerous
value, never on a merely unusual one.

Exit 0 = allow. Block is emitted as `{"decision": "block", "reason": ...}` on
stdout with exit 0 (the documented JSON form), with the reason mirrored to
stderr so it surfaces even if the JSON path is ignored.
"""
import sys
import json

# Guard scripts whose presence in the hooks config is the safety posture, mapped
# to the hook event each one must be registered under. v1.0 matched these as
# substrings anywhere in the serialized hooks block; v1.1 checks the structure,
# so a guard relocated to a non-blocking event no longer passes. v1.2 adds the
# two ADR-015 guards — per ADR-013 this list is a literal enumeration of the
# repo's redline controls, and it had fallen behind that ADR by two entries.
REQUIRED_GUARDS = {
    "credential-guard": "PreToolUse",
    "published-history-guard": "PreToolUse",
    "git-staging-guard": "PreToolUse",
    "fanout-guard": "PreToolUse",
    "destructive-command-guard": "PreToolUse",
    "secret-redaction-guard": "PreToolUse",
}

# Only the scopes that can carry the global guard chain.
WATCHED_SOURCES = {"user_settings", "policy_settings"}

# Permission modes an agent must never set on its own. `bypassPermissions`
# removes the permission layer wholesale. Other modes (plan, acceptEdits,
# default, auto) are ordinary user preferences and are NOT policed here.
FORBIDDEN_MODES = {"bypassPermissions"}

# Allow-rule bodies that amount to "any shell command". Compared after stripping
# whitespace; a bare tool name with no parenthesised body allows every
# invocation of that tool, so it is included.
_UNRESTRICTED_BODIES = {"*", ":*", "*:*", ""}
_SHELL_TOOLS = {"Bash", "PowerShell", "Shell"}

# env keys that redirect model traffic or plant ambient credentials. Deliberately
# short: the presence of an `env` block is normal and is not itself a problem.
FORBIDDEN_ENV_KEYS = {
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
}


def _allow():
    sys.exit(0)


def _block(reason):
    sys.stderr.write(reason)
    print(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)


def _fail_open(why):
    sys.stderr.write("config-change-guard: failing open — %s\n" % why)
    sys.exit(0)


def _rule_is_unrestricted_shell(rule):
    """True for an allow rule granting arbitrary shell execution.

    Conservative by construction: only the exact unrestricted forms count. A rule
    with a real prefix (`Bash(git status)`, `Bash(gh pr view *)`) is a normal
    allowlist entry and is never flagged — a guard that fires on ordinary
    allowlist maintenance would be routed around within a week.
    """
    if not isinstance(rule, str):
        return False
    rule = rule.strip()
    if rule in _SHELL_TOOLS:                      # bare `Bash` allows everything
        return True
    if "(" not in rule or not rule.endswith(")"):
        return False
    tool, _, body = rule.partition("(")
    if tool.strip() not in _SHELL_TOOLS:
        return False
    return body[:-1].strip() in _UNRESTRICTED_BODIES


def _guard_is_wired(settings, guard, expected_event):
    """Structural check that `guard` is registered somewhere it can actually fire.

    Requires, under the expected event: a non-empty matcher, and a hook whose
    command references the exact `<guard>.py` filename. That last detail is what
    catches a command repointed at `credential-guard-disabled.py` — a substring
    search for `credential-guard` matches that string, but `credential-guard.py`
    does not appear in it.
    """
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return False
    entries = hooks.get(expected_event)
    if not isinstance(entries, list):
        return False
    needle = guard + ".py"
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        # An absent matcher key means "all tools" in Claude Code; an explicitly
        # empty matcher is the neutering shape, so only the latter is rejected.
        if "matcher" in entry and not str(entry.get("matcher") or "").strip():
            continue
        for hook in entry.get("hooks") or []:
            if not isinstance(hook, dict):
                continue
            if needle in str(hook.get("command") or ""):
                return True
    return False


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
        # An edit caught mid-write, or JSONC the loader accepts and we don't:
        # allowing is the only safe move — see FAILS OPEN above.
        _fail_open("could not parse %s (%s)" % (path, exc))
    if not isinstance(settings, dict):
        _fail_open("%s is not a settings object" % path)

    problems = []

    if settings.get("disableAllHooks"):
        problems.append(
            "  - disableAllHooks is set, which disarms EVERY hook at once"
        )

    # --- v1.1: the permission layer itself ---------------------------------
    perms = settings.get("permissions")
    if isinstance(perms, dict):
        mode = perms.get("defaultMode")
        if isinstance(mode, str) and mode.strip() in FORBIDDEN_MODES:
            problems.append(
                "  - permissions.defaultMode is %r, which removes the permission\n"
                "    layer for every session" % mode.strip()
            )
        allow_rules = perms.get("allow")
        if isinstance(allow_rules, list):
            unrestricted = [r for r in allow_rules if _rule_is_unrestricted_shell(r)]
            if unrestricted:
                problems.append(
                    "  - permissions.allow grants unrestricted shell: "
                    + ", ".join(repr(r) for r in unrestricted)
                )

    # --- v1.1: ambient env injection ---------------------------------------
    env = settings.get("env")
    if isinstance(env, dict):
        flagged = sorted(k for k in env if str(k).strip().upper() in FORBIDDEN_ENV_KEYS)
        if flagged:
            problems.append(
                "  - env sets keys that redirect model traffic or plant ambient\n"
                "    credentials: " + ", ".join(flagged)
            )

    # --- v1.1: structural guard-chain check (replaces the substring test) ---
    missing = [
        g for g, event in sorted(REQUIRED_GUARDS.items())
        if not _guard_is_wired(settings, g, event)
    ]
    if missing:
        problems.append(
            "  - these guard hooks are not wired where they can fire: "
            + ", ".join(missing)
        )

    if not problems:
        _allow()

    _block(
        "CONFIG-CHANGE GUARD: this change would leave %s in an unsafe state:\n%s\n"
        "Guard wiring is the whole of the safety control (agent-ops ADR-012), so\n"
        "removing a guard, or handing a session unrestricted permissions, is not\n"
        "an edit an agent makes on its own.\n"
        "The change has been blocked. If San genuinely intends it, he makes it\n"
        "by hand in %s, outside a Claude session.\n"
        % (path, "\n".join(problems), path)
    )


if __name__ == "__main__":
    main()
