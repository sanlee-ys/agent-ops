# `fleet-guards` — the guard chain as a Claude Code plugin (DRAFT)

**Status: draft artifact. NOT installed, NOT enabled, NOT the source of truth.**
The live guard chain is still wired the way it always was — the scripts deployed
to `~/.claude/hooks/` and registered in the user-scope `settings.json`. Nothing
in this directory is running.

## What this is

A packaging exercise, per the machine-state-audit principle: un-versioned machine
state should be versioned. Most of the chain already *was* versioned here
([`security/credential-guard.py`](../../../security/credential-guard.py),
[`hooks/`](../../../hooks/)), but as loose files plus a hand-maintained
`settings.json` registration that exists only on each machine. A plugin makes the
registration itself — event, matcher, timeout — a reviewable file.

Contents:

| File | Canonical source | Event (reconstructed) |
| --- | --- | --- |
| `hooks/credential-guard.py` | `security/credential-guard.py` (this repo) | `PreToolUse` / `Bash\|PowerShell\|Shell\|Grep` |
| `hooks/published-history-guard.py` | `hooks/published-history-guard.py` (this repo) | `PreToolUse` / `Bash\|PowerShell\|Shell` |
| `hooks/git-staging-guard.py` | `hooks/git-staging-guard.py` (this repo) | `PreToolUse` / `Bash\|PowerShell\|Shell` |
| `hooks/fanout-guard.py` | the machine-config repo's `claude/hooks/fanout-guard.py` | `PreToolUse` / `Workflow` |
| `hooks/config-change-guard.py` | deployed copy only (not previously versioned) | `ConfigChange` |

## `hooks/hooks.json` is RECONSTRUCTED, not extracted

The live `~/.claude/settings.json` was **deliberately not read** — it is guarded,
and the session had no need for it. Every event name, matcher and timeout in
`hooks/hooks.json` was inferred from each script's own header comments and its
`tool_name` dispatch. Matchers should be accurate (they come straight from the
`tool_name` checks in the code); **timeouts are a guess**, and hook *ordering*
within an event is not recoverable this way at all. Diff this file against the
live `settings.json` before trusting it.

The commands say `python3`. On Windows the live registration may use a different
interpreter path (cf. [`vendors/grok/hooks.windows.json`](../../grok/hooks.windows.json));
confirm at cutover.

## Drift hazard

Four of the five scripts here are **derived copies**. Editing them instead of
canon reintroduces exactly the drift class recorded as limit 6 in
[`security/posture.md`](../../../security/posture.md) — a copy that goes stale
without dangling anything. Until cutover: **edit canon, then re-copy.** The
mechanical fix at cutover is to wire these paths into
[`scripts/check-generated-drift.py`](../../../scripts/check-generated-drift.py),
which already exists for exactly this shape of committed-derived-output.

`config-change-guard.py` is the exception — this is currently its only versioned
copy, and it should be promoted to a canonical location in its own change.

## Cutover (a future session's job — do NOT do it as a side effect)

Installing this plugin while the same guards are registered in `settings.json`
**double-fires every guard**. Order matters:

1. Diff `hooks/hooks.json` against the live user-scope `settings.json`. Reconcile
   matchers, timeouts and ordering; the live file wins on every disagreement.
2. **Resolve the bootstrap problem first.** `config-change-guard.py` blocks a
   settings change that leaves the file without `credential-guard`,
   `published-history-guard`, `git-staging-guard` and `fanout-guard` by name.
   Moving those registrations *out* of `settings.json` and into a plugin is
   precisely the edit it is built to block — so the guard must learn about the
   plugin scope **before** step 4, or the cutover cannot be performed from inside
   a Claude session at all.
3. Install and enable the plugin.
4. Remove the four `PreToolUse` entries and the `ConfigChange` entry from
   `settings.json`.
5. **Verify no double-fire**, then verify the guards still block: run one known
   tripwire per guard and confirm exactly one block message each.
6. Decide what `~/.claude/hooks/` and the deploy step become — the plugin
   supersedes them, and leaving both is the drift hazard above, made live.

Steps 2 and 6 are decisions, not mechanics. They are why this is a draft.
