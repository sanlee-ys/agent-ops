# `hooks/` — the fleet's redline guards

Canonical source for the guard hooks that enforce a fleet redline, per
[`decisions/ADR-013`](../decisions/ADR-013-guard-canonicality-line.md).
`credential-guard.py` is the one redline guard that lives elsewhere — in
[`security/`](../security/), where [ADR-002](../decisions/ADR-002-public-first-canonicality.md)
put it alongside its README and `posture.md`.

| File | Event / matcher | What it refuses |
| --- | --- | --- |
| [`git-staging-guard.py`](git-staging-guard.py) | `PreToolUse` / shells | whole-tree staging (`git add -A\|-u\|.`, `git commit -a`), which sweeps a parallel session's uncommitted work into this session's commit |
| [`published-history-guard.py`](published-history-guard.py) | `PreToolUse` / shells | a force-push or backward reset on `main` when the discarded range holds a commit the remote already has |
| [`config-change-guard.py`](config-change-guard.py) | `ConfigChange` | a settings change that leaves the file disarmed: a guard hook not wired where it can fire, `disableAllHooks`, `permissions.defaultMode: bypassPermissions`, an unrestricted-shell allow rule, or an `env` key that redirects model traffic |

These are **deployed, not imported**: the machine-config repo's setup scripts
symlink them (macOS/Linux) or copy them (Windows) into `~/.claude/hooks/`, so
this clone is load-bearing. Re-run the deploy after editing one, and check the
deployed copy before trusting it — a copy goes stale without dangling anything
(limit 6 in [`security/posture.md`](../security/posture.md)).

## `config-change-guard.py` v1.1: the gap between the name and the check

v1.0 checked two things — `disableAllHooks`, and whether four guard *names*
appeared as substrings of the serialized `hooks` blob. An audit found that both
directions were narrower than the name "config tamper guard" implies, and the
gap was not academic: a settings file could keep all four names, pass v1.0
cleanly, and still hand the session unrestricted power.

| Escalation | v1.0 | v1.1 |
| --- | --- | --- |
| `permissions.defaultMode: "bypassPermissions"` | allowed — `permissions` was never read | blocked |
| `permissions.allow: ["Bash"]` / `Bash(*)` / `Bash(:*)` | allowed | blocked |
| `env: {ANTHROPIC_BASE_URL: …}` — model traffic redirected | allowed | blocked |
| guard moved to `PostToolUse` (runs after the call; cannot refuse) | allowed — the name is still in the blob | blocked |
| guard given `"matcher": ""` (matches nothing) | allowed | blocked |
| command repointed at `credential-guard-disabled.py` | allowed — that string *contains* `credential-guard` | blocked |

The first three are new checks; the last three come from replacing the substring
search with a **structural** one — each guard must appear under its expected
event, with a non-empty matcher, and a command naming the exact `<guard>.py`
file. Every check is additive: nothing v1.0 refused is now allowed.

**The usability half is the load-bearing half.** This guard sits on the one file
a false positive cannot be repaired from — a wrong block bricks the config, and
the repair is itself a config change the guard blocks again. So each new check
fires only on an unambiguously dangerous value, never a merely unusual one: a
prefixed allow rule (`Bash(git status)`, `Bash(rm -rf:*)`) is ordinary allowlist
maintenance and is never flagged, an `env` block per se is normal, `plan` /
`acceptEdits` / `auto` are user preferences, and a *missing* `matcher` key means
"all tools" rather than neutering. Those near-miss shapes are pinned as allowed
in the suite alongside the escalations, so a future tightening has to break a
test on purpose.

Still out of scope, stated rather than claimed closed: `~/.claude.json` is not a
settings scope and never reaches this hook (its protection is credential-guard's
path block — which is why that write block has to stay); a command keeping the
exact `<guard>.py` filename but pointing at a gutted copy elsewhere; and any edit
made outside a Claude session.

## `config-change-guard.py`: what is measured, and what is not

**Not yet measured, as of 2026-08-09 — do not credit this guard as enforcing
anything. v1.1 hardens the logic and changes nothing about this.** Two facts have
to hold for it to do its job, and neither has been observed on a live harness:

1. **Does `ConfigChange` fire?** The event is documented (Claude Code hooks
   reference: *"When a configuration file changes during a session"*, matched on
   configuration source), but this guard has never been seen receiving a payload.
2. **Does `{"decision": "block"}` veto the change?** The same reference lists
   `ConfigChange` as blockable — *"Blocks the configuration change from taking
   effect (except `policy_settings`)"* — but that is a doc claim, not a
   measurement.

The guard **fails open by design**, so "nothing happened" is ambiguous: it is
equally consistent with the hook never firing and with the hook firing and
allowing. Its stderr diagnostic is what distinguishes the two.

Three things *were* measured on 2026-08-09, and they narrow the question rather
than answering it:

- **`credential-guard.py` refuses `Read` and `Write` on any `*/.claude/
  settings.json`** — including a throwaway one in a scratch directory. Its
  coverage is field-based, so every tool with a path-bearing field is in scope.
- **The harness independently denies writes under `.claude/`** in a
  non-interactive session even with `Write` allowlisted and
  `--permission-mode acceptEdits`.
- **A parent session cannot even stand up the rig.** The v1.1 session tried the
  obvious remaining route — spawn a headless child (`claude -p`) in a scratch
  directory with `--settings` wiring a log-only `ConfigChange` probe, and have
  the child attempt the write. The *parent's* `Bash` call was refused by
  `credential-guard.py` before the child ever started, because composing the
  command requires naming a Claude config path in the command text. That block
  is correct behaviour and was **not** worked around; the probe log was
  confirmed never created, so no measurement data exists. A third independent
  closure, from a direction the two above did not cover.

So on a machine with this chain wired, **every route to `ConfigChange` from
inside a Claude session is closed before the event would be reached at all** —
the child's write by two mechanisms, and the parent's setup by a third. The
event's remaining triggers are the interactive config UI, a plugin, or the
harness's own settings writer — none of which a headless session can exercise.
That is why this is unmeasured rather than merely untested: measuring it needs an
interactive session, and every route a script could take is one the guard chain
above is built to refuse.

**This is the honest state, not a placeholder for a guess.** Per
[`security/posture.md`](../security/posture.md) limit 7, an unmeasured claim does
not count — so the guard's logic being green in CI (36 cases as of v1.1) means
"it would refuse the right things if it ran", and nothing more.

### One limit already visible from the documentation

`WATCHED_SOURCES` covers `user_settings` **and** `policy_settings`, but the
hooks reference says a `ConfigChange` block does not apply to `policy_settings`.
If that holds, the `policy_settings` half of this guard can warn on stderr and
cannot refuse. Left in place deliberately — a diagnostic on a managed-settings
change is still worth having — but it must not be counted as enforcement.

### How to measure it (interactive session, on a scratch config)

Never against the live `~/.claude/settings.json`: a false block there is a
bricked config that cannot be repaired from inside Claude, which is the exact
asymmetry the guard's own docstring is written around.

1. In a scratch directory, start an interactive session with the probe wired at
   `ConfigChange` — a script that appends its stdin payload to a log and exits 0.
   Wire it with `--settings '<json>'` so no settings file has to be authored.
2. Change that project's configuration through the harness's own UI (approve a
   permission prompt so it is persisted, or use the config panel).
3. Read the log. A payload proves fact 1 and shows the real `config_source` /
   `config_path` field names.
4. Swap the probe for one that prints `{"decision": "block", "reason": "..."}`
   and repeat. Then check the file on disk: unchanged proves fact 2, changed
   proves the verdict is advisory.

Only after both come back positive does this guard get credited in
`security/posture.md`.
