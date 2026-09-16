# Postmortem: GitHub PAT exposed at rest — same failure mode, second time in a week

**Date:** 2026-07-03 | **Duration:** instant (one command) | **Severity:** SEV2 (real credential exposed twice in one week, no confirmed misuse)
**Status:** Resolved

## Summary

While auditing an unrelated hook bug (see incidents/2026-07-02-uncapped-premium-fanout.md),
Claude ran a config-file read (`cat ~/.claude/settings.json`) to check the
global `PreToolUse` hook wiring. The file's `env` block held a live GitHub
fine-grained PAT in plaintext; the full token printed to the session
transcript. Same failure shape as incidents/2026-07-02-plaintext-api-key-exposure.md
(an API key printed via an unmasked env-var debug check) — a credential-shaped
value dumped by a routine diagnostic command, six days apart.

## Impact

- A live GitHub fine-grained PAT (select-repos, PR/Issues RW, Contents RO)
  exposed in plaintext at rest and re-printed to a transcript.
- Revoking it broke the GitHub plugin integration (confirmed — it disconnected
  immediately after revocation and restart), so it was load-bearing, not dead
  config.
- No confirmed misuse.

## Root cause (5 whys)

1. Why did the token print? A routine read of a config file that happened to
   contain a plaintext secret.
2. Why was a secret sitting in a readable config file at all? The GitHub
   plugin's own manifest does header templating —
   `"Authorization": "Bearer ${GITHUB_PERSONAL_ACCESS_TOKEN}"` — which reads
   from the host process environment. The only supported way to supply that
   was a global env var.
3. Why does a global env var cause a leak? Claude Code's Bash/PowerShell tool
   calls inherit the app's process environment. Any credential placed there
   to satisfy the plugin's `${VAR}` substitution is *by construction* visible
   to every shell command that session runs — not a storage-location bug, a
   design constraint of that specific plugin.
4. Why wasn't this caught after the first incident (2026-07-02)? That
   postmortem's fix was a **behavioral** rule ("never print a
   credential-shaped value unmasked"), not a mechanical one. A behavioral
   rule has no enforcement between two occurrences of the same command shape.
5. Root cause: (a) the plugin's design required a globally-visible credential
   with no scoped alternative, and (b) the only guard against printing it was
   "remember not to," which had already failed once.

## What went well

- Caught and flagged in the same turn, same as the first incident.
- Root cause was traced to the actual mechanism (manifest-level header
  templating), not just "be more careful" — the fix addresses the structural
  cause, not only the symptom.
- Verified the `gh` CLI's separate OAuth token (keyring-backed) was never
  involved — the safe credential the session had been using throughout was
  unaffected.
- Verified the specific capability worried about losing (secret-scanning
  lookups) was not actually lost — the same GitHub feature is reachable
  directly through the `gh` CLI on the already-safe token.

## Fixes applied (2026-07-03)

| Fix | What | Where |
|---|---|---|
| Removed the plaintext token | Deleted the token from `env` in `~/.claude/settings.json` | This machine |
| Disabled the leaky plugin | Its `${VAR}`-templated HTTP auth structurally requires a global env var | This machine |
| Mechanical credential guard (the real fix — closes the gap the first incident's behavioral rule didn't) | New `PreToolUse` hook, `security/credential-guard.py`: blocks bulk env dumps (`env`, `printenv`, `Get-ChildItem Env:`) and full reads of known credential-store files (`settings.json`, `.claude.json`, `.env*`, `credentials*.json`, SSH keys, `*.pem`) via Bash/PowerShell. Override: a literal marker string in the command. | Committed to a private config repo, deployed to this machine, and verified with smoke tests before calling it done — not just "wrote the fix" |
| Token revoked | Old PAT deleted on GitHub's side | User-performed (no API access for this from the assistant side) |

## Open / next step

The old PAT is revoked; the plugin is disabled and currently not providing
GitHub tools. Replacement path (not yet done at time of writing): register a
stdio GitHub MCP server with a fresh token passed only as that one
subprocess's scoped env var, run **by the user directly in their own
terminal** (not through Claude's Bash tool) so the new token never enters a
transcript or tool-call history at all. Scoping the env var to a single
subprocess launch means it does not join the host process's general
environment, so it cannot be dumped by a Bash/PowerShell command the way the
plugin's credential could. This mirrors a note that this same migration had
been attempted once before and never actually persisted — this time, verify
registration and a real tool call after restart before considering it done.

**Closed (2026-09-16).** San registered the stdio `github` server on
2026-07-04 and a live `list_commits` call verified it the same day (the
2026-07-04 incident in this directory names that server and its scopes). The
server runs on the Windows PC only; `claude mcp list` on that PC shows
`github ... ✔ Connected` on 2026-09-16. The Mac has no MCP servers and uses
the `gh` CLI for all GitHub work (verified 2026-08-03 with `claude mcp list`
on the Mac, which returned `No MCP servers configured`).

## Addendum: a third exposure, same day, closing the loop

After a new PAT was generated and the scoped stdio GitHub server registered
directly in the user's own terminal (per the plan above — the new token
never entered a transcript at registration time), Claude ran a CLI verify
command to check the registration succeeded. That command prints a
registered server's stored env vars — including the secret value — in the
clear by design. The brand-new token printed straight into the transcript,
minutes after being created. Same failure shape, third time, via a command
shape the just-written credential guard didn't cover yet — it only watched
Bash/PowerShell env-dump and file-read patterns, not the CLI's own
subcommands.

Fixed same-day: added a third blocked pattern to the guard (the CLI's
"get server config" subcommand is blocked; the "list servers" subcommand,
which shows connection status without values, stays allowed), synced across
the local deploy and the private config repo, smoke-tested, committed, and
pushed. While writing the commit message about this fix, the guard correctly
fired on the literal blocked command string appearing in prose — a false
positive from pattern-matching the whole command blob rather than just
executed subcommands, worked around by rephrasing rather than loosening the
regex.

The new token was rotated again as a result (fourth token in one week across
the incidents in this series).

## Lessons learned

A behavioral rule that already failed once should be treated as disproven,
not reinforced with a stronger warning — the fix has to be mechanical the
second time. Also: "where is the secret stored" is the wrong question when a
plugin's own design requires a credential to be globally visible to the host
process; the right question is "does anything in this environment still need
a global credential at all," and the answer here was no — a scoped,
subprocess-local credential covers the same functionality.

**Sharper lesson from the addendum:** a mechanical guard's coverage is only
as good as the command shapes someone thought to enumerate. Having written
the guard once already left a live gap (the CLI verify subcommand) that a
routine verification step walked straight into. This is the same "wrote the
fix" vs. "the fix protects you" gap named in the deployment-gap lesson from
the uncapped fan-out incident (incidents/2026-07-02-uncapped-premium-fanout.md)
— it recurred here in miniature, one command shape at a time, within the
same session that was actively trying to close it. Treat every new
credential-touching command as a candidate for the guard's pattern list going
forward, not just the ones already seen failing.
