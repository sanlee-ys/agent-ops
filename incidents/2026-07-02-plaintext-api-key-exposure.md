# Postmortem: Plaintext API key exposed in session transcript

**Date:** 2026-07-02 | **Duration:** instant (one command) | **Severity:** SEV2 (real credential exposed, no confirmed misuse)
**Status:** Resolved

## Summary

While debugging a 401 from an external CLI (`graphify`), Claude ran a
PowerShell command to check for a persisted `ANTHROPIC_API_KEY`. It masked
the session-scoped check but not the user-scoped one, printing a full live
API key into the conversation transcript.

## Impact

- One real Anthropic API key exposed in plaintext in a session log.
- No confirmed downstream misuse.
- Forced an out-of-band response: all API keys deleted and rotated.

## Timeline

| Time | Event |
|---|---|
| T+0 | `graphify extract` fails with `401 invalid x-api-key`. |
| T+1 | Claude checks env vars to debug: masks the session-scoped `$env:ANTHROPIC_API_KEY` check (prefix + length only), but the user-scoped `[Environment]::GetEnvironmentVariable(..., "User")` line has no masking. |
| T+2 | Command output includes the full key in the clear. |
| T+3 | Claude flags its own mistake immediately, recommends rotation. |
| T+4 | All API keys deleted, rotation started with per-service labels (e.g. `graphify-api-key`) so a future compromise is scoped to one service. |

## Root cause (5 whys)

1. Why did a key get printed? -> The debug command had no masking on one of its two lookups.
2. Why was one lookup masked and not the other? -> They were written as two separate one-off checks in the same command block, not through a shared "always truncate" helper.
3. Why no shared helper / rule? -> There's no standing rule that *any* command capable of echoing a credential-shaped value must default to masked output.
4. Why didn't that rule already exist? -> Credential handling had been case-by-case judgment, not a hard default -- this is the first time it was tested and failed.
5. Root cause: no absolute default to mask potential-secret output; it was left to per-command discretion, which is fine until one command forgets.

## What went well

- The mistake was self-flagged in the same turn it happened, not discovered later.
- Keys were deleted before Claude finished suggesting rotation -- fast independent reaction.
- No hook or process needed to catch this in hindsight -- a simple absolute rule closes it.

## What went poorly

- The masking pattern existed right next to the unmasked one in the same command and wasn't applied consistently -- a "should have been obvious" miss.

## Action items

| Action | Owner | Priority | Status |
|---|---|---|---|
| Delete + rotate all API keys, label per-service (`graphify-api-key`, etc.) | Operator | P0 | Done |
| Standing rule for Claude: never print a credential-shaped value unmasked, including in "just checking if it's set" debug commands -- always truncate/redact by default, no exceptions | Claude (behavioral) | P0 | Adopted going forward |
| Prefer boolean/prefix-only checks (`[bool]$env:X`, first-N-chars) over full-value dumps for *any* env var named `*KEY*`, `*SECRET*`, `*TOKEN*` | Claude (behavioral) | P1 | Adopted going forward |

## Lessons learned

A rule applied inconsistently is worse than no rule -- it creates false confidence. "Mask secrets" needs to be a default behavior triggered by the shape of the request (any command touching a `*_KEY`/`*_TOKEN`/`*_SECRET` var), not something re-decided per command.

This incident is one of a series from the same week; see also
incidents/2026-07-02-uncapped-premium-fanout.md,
incidents/2026-07-03-github-pat-plaintext-recurrence.md,
incidents/2026-07-03-credential-guard-interpreter-bypass.md,
incidents/2026-07-04-github-pat-read-grep-leak.md, and
debug-notes/2026-07-04-graphify-console-flash-three-surfaces.md.
The standing rule from this incident is one input into the credential-guard
hook (`security/credential-guard.py` in this repo), built out further in the
later incidents in this series.
