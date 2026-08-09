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
| [`config-change-guard.py`](config-change-guard.py) | `ConfigChange` | a settings change that leaves the file without one of the four guard hooks, or that sets `disableAllHooks` |

These are **deployed, not imported**: the machine-config repo's setup scripts
symlink them (macOS/Linux) or copy them (Windows) into `~/.claude/hooks/`, so
this clone is load-bearing. Re-run the deploy after editing one, and check the
deployed copy before trusting it — a copy goes stale without dangling anything
(limit 6 in [`security/posture.md`](../security/posture.md)).

## `config-change-guard.py`: what is measured, and what is not

**Not yet measured, as of 2026-08-09 — do not credit this guard as enforcing
anything.** Two facts have to hold for it to do its job, and neither has been
observed on a live harness:

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

Two things *were* measured on 2026-08-09, and they narrow the question rather
than answering it:

- **`credential-guard.py` refuses `Read` and `Write` on any `*/.claude/
  settings.json`** — including a throwaway one in a scratch directory. Its
  coverage is field-based, so every tool with a path-bearing field is in scope.
- **The harness independently denies writes under `.claude/`** in a
  non-interactive session even with `Write` allowlisted and
  `--permission-mode acceptEdits`.

So on a machine with this chain wired, **the Edit/Write route to a settings
change is closed twice over before `ConfigChange` would be reached at all.** The
event's remaining triggers are the interactive config UI, a plugin, or the
harness's own settings writer — none of which a headless session can exercise.
That is why this is unmeasured rather than merely untested: measuring it needs an
interactive session, and every route a script could take is one the guard chain
above is built to refuse.

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
