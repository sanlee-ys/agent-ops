# `hooks/` — the fleet's redline guards

Canonical source for the guard hooks that enforce a fleet redline, per
[`decisions/ADR-013`](../decisions/ADR-013-guard-canonicality-line.md).
`credential-guard.py` is the one redline guard that lives elsewhere — in
[`security/`](../security/), where [ADR-002](../decisions/ADR-002-public-first-canonicality.md)
put it alongside its README and `posture.md`.

| File | Event / matcher | What it refuses |
| --- | --- | --- |
| [`git-staging-guard.py`](git-staging-guard.py) | `PreToolUse` / shells | whole-tree staging (`git add\|stage -A\|-u\|.`, any combined short flag carrying `A` or `u`, `git commit -a`), which sweeps a parallel session's uncommitted work into this session's commit. Override: `STAGE-ALL-OK` per command |
| [`published-history-guard.py`](published-history-guard.py) | `PreToolUse` / shells | any command that would move `main` backwards over a commit the remote already has — force-push, reset, `commit --amend`, `rebase`, `branch -f`/`-M`, `checkout -B`/`switch -C`, `update-ref`, `filter-branch`/`filter-repo`, or deleting the remote branch |
| [`config-change-guard.py`](config-change-guard.py) | `ConfigChange` | a settings change that leaves the file disarmed: a guard hook not wired where it can fire, `disableAllHooks`, `permissions.defaultMode: bypassPermissions`, an unrestricted-shell allow rule, or an `env` key that redirects model traffic |
| [`hook-tamper-guard.py`](hook-tamper-guard.py) | `PreToolUse` / all tools | a MUTATION of a **deployed** guard-chain file — a hook script under `~/.claude/hooks/`, `~/.grok/hooks/`, `~/.pi/agent/extensions/`, or the wiring in `~/.claude/settings.json`, `~/.cursor/hooks.json`, `~/.grok/config.toml`, `~/.gemini/config/hooks.json`, `~/.pi/agent/settings.json`. Reads stay allowed; the CANONICAL sources in this clone stay editable. Override: `DEPLOY-OK` per command |
| [`destructive-command-guard.py`](destructive-command-guard.py) | `PreToolUse` / shells | locally destructive commands, judged by a blast × reversibility score per rule id (`git reset --hard`, `git clean -f`, recursive deletes, …) — `git reset --soft` scores as safe and passes. Buckets: allow / warn / confirm / block; block = exit 2, which holds in every permission mode. Overrides: `RISK-OK` per command; `guard-scoring.json` per rule/cell; `AGENT_OPS_GUARD_SHADOW` logs without enforcement. See [ADR-015](../decisions/ADR-015-blast-reversibility-scoring-and-redaction.md) |

One more `PreToolUse` guard lives in [`security/`](../security/):
[`secret-redaction-guard.py`](../security/secret-redaction-guard.py) rewrites
instead of refusing — a literal secret value in `tool_input` is replaced with
`[REDACTED:<rule_id>]` and the call proceeds via
`hookSpecificOutput.updatedInput` (deny + exit 2 on the codex target, whose
contract cannot rewrite input). Same ADR.

These are **deployed, not imported**: the machine-config repo's setup scripts
symlink them (macOS/Linux) or copy them (Windows) into `~/.claude/hooks/`, so
this clone is load-bearing. Re-run the deploy after editing one, and check the
deployed copy before trusting it — a copy goes stale without dangling anything
(limit 6 in [`security/posture.md`](../security/posture.md)).

## `hook-tamper-guard.py` v1.0: the deployed copy, not the settings file

[`config-change-guard.py`](config-change-guard.py) and
[`hook-tamper-guard.py`](hook-tamper-guard.py) sound alike and protect different
things. Keep them apart by the event:

| | `config-change-guard.py` | `hook-tamper-guard.py` |
| --- | --- | --- |
| Event | `ConfigChange` | `PreToolUse` |
| Subject | the settings file's CONTENT after a change | the TOOL CALL that writes a deployed file |
| Asks | "is the guard chain still wired?" | "is this call rewriting a live guard?" |
| Sees | a `/config` edit no tool call produced | a `Write`, an `Out-File`, a `cp` |
| Timing | after the bytes land (documented limit) | before the bytes land |

Neither replaces the other, and the second closes a route the first cannot
reach: the deployed guard SCRIPTS. `config-change-guard.py` checks that
`credential-guard.py` is still registered under `PreToolUse` with a live
matcher. It cannot check what is inside that file. An `Edit` that replaces the
body of `~/.claude/hooks/credential-guard.py` with `sys.exit(0)` leaves every
registration intact and disarms the guard completely.

**Three rules keep it usable, and all three are pinned by
[`tests/test_hook_tamper_guard.py`](../tests/test_hook_tamper_guard.py):**

1. **Canonical stays editable.** Only DEPLOYED copies are protected. Every
   protected path is anchored to a home dot-config directory, so a path inside
   an agent-ops clone carries no such directory and never matches. Editing a
   guard here, and shipping it through a pull request, is the intended route and
   the guard must never stand in it.
2. **Reads stay allowed.** Reading a hook to learn what it refuses is ordinary
   work. Only a mutation blocks, and the copy family is judged by DESTINATION —
   a copy OUT of the deployed tree is a backup, a copy IN is a deploy. `mv` does
   NOT get that exemption: a move out removes the live guard, which is a delete
   wearing a different verb.
3. **A mention is not a mutation.** Heredoc bodies are stripped, the quoted
   value of a prose-bearing flag is blanked, and a path alone never blocks: the
   segment must also carry a mutator with that path as an argument. This guard
   is more exposed to the false positive than any other here, because the
   documents explaining it quote its protected paths on every line.

**A shell wrapper is re-checked, not pattern-matched.** `bash -c "<command>"`,
`pwsh -Command '<command>'` and `cmd /c <command>` carry a whole command, so the
body is split and judged by every rule above. The same goes for a heredoc whose
introducing line leads with an interpreter or a shell: `python - <<'PY'` carries
a program, not a message, and dropping it as prose would hide the mutator and
its target in one step. `bash deploy.sh` stays out of scope — that is a file the
guard cannot see into.

**The override is `DEPLOY-OK`,** placed anywhere in a Bash/PowerShell command.
It exists for exactly one job: a deliberate canonical-to-deploy sync. The block
message does not name it, which is the standing decision taken after a guard
advertised its own bypass and the model read it back out and used it.

**Deploying it is a separate human decision.** The guard is canonical here and
is wired into all four vendor adapters, so any lane that runs an adapter picks
it up from this clone. The Claude Code lane runs deployed copies instead, so it
gains nothing until the file is copied to `~/.claude/hooks/` and added to the
`PreToolUse` array. Until that happens, do NOT add `hook-tamper-guard` to
`config-change-guard.py`'s `REQUIRED_GUARDS`: that list is a wiring assertion,
and asserting a guard that is not deployed would block every settings change
until it is.

## `git-staging-guard.py` v1.2: two synonyms the v1.0 matcher never named

v1.0 matched the subcommand `add` and the exact flag tokens `-A`, `--all`,
`-u`, `--update`, `.`. Two whole-tree shapes fell outside that list, and both
were measured at exit 0 (allow) on 2026-08-11 before the fix:

| Command | v1.0 | v1.2 | Why it stages everything |
| --- | --- | --- | --- |
| `git stage -A` | allowed | blocked | `stage` is a **built-in synonym** for `add` — same options, same effect. Only the name `add` was matched |
| `git add -Au` | allowed | blocked | a valid **combined short flag**. v1.0 compared whole tokens, so it read `-Au` as an unknown flag and passed it |

The second one is the sharper miss, because the `commit` branch had already
solved it: `-am` was caught by scanning the letters of a combined short flag.
The `add` branch was written against a fixed token list on the same day and
never got the same treatment.

This is the repo's throughline again, inside a guard written *about* that
throughline: **a matcher covers the surface its author enumerated, not the
surface that exists.** So v1.2 matches the *operation* rather than the spelling
— both subcommand names, and any combined short flag carrying `A` or `u`.

**The widening is bounded and pinned.** No other `git add` short option uses
those letters (`-n`, `-N`, `-f`, `-i`, `-p`, `-e`, `-v`), so a letter match
cannot collide. `tests/test_git_staging_guard.py` pins that claim from both
sides: the new bypasses block, and `git add -N`, `git add -nv`, `git add -ip`,
`git stage src/api.py` and `git stash -u` still pass. The prose cases are
extended too — the guard must still be able to quote its own bypasses in a
commit message, which is what this section does.

## `config-change-guard.py` v1.2: the gap between the name and the check

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

**v1.2 enumerates six guards, not four.** `REQUIRED_GUARDS` is a literal list of
the repo's redline controls (ADR-013), and the list had fallen two entries behind
that ADR. v1.0 and v1.1 both named four guards — `credential-guard`,
`published-history-guard`, `git-staging-guard` and `fanout-guard` — so a settings
edit that unwired `destructive-command-guard` or `secret-redaction-guard` passed
the tamper check clean. v1.2 adds both, mapped to `PreToolUse`. This is the same
failure the v1.1 table records, one level up: **a list covers the controls its
author enumerated, not the controls that exist.** The structural check of v1.1 is
unchanged; it now runs over six names.

The widening has a deploy consequence, and it is the check working as specified:
a settings file that wires only the original four now fails. Wire the two ADR-015
guards in `~/.claude/settings.json` if they are not wired there already.

Still out of scope, stated rather than claimed closed: `~/.claude.json` is not a
settings scope and never reaches this hook (its protection is credential-guard's
path block — which is why that write block has to stay); a command keeping the
exact `<guard>.py` filename but pointing at a gutted copy elsewhere; and any edit
made outside a Claude session.

## `config-change-guard.py`: what is measured, and what is not

**Not yet measured, as of 2026-08-09 — do not credit this guard as enforcing
anything. v1.1 and v1.2 harden the logic and change nothing about this.** Two
facts have to hold for it to do its job, and neither has been observed on a live
harness:

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
not count — so the guard's logic being green in CI (37 cases as of v1.2) means
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
