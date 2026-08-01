# Postmortem: credential-guard.py had an interpreter-based bypass — found by audit, not by a leak

**Date:** 2026-07-03 | **Duration:** ~3 hours across discovery, an overcorrection, and the real fix | **Severity:** Near-miss (real gap in a security control, found proactively by audit and never exploited; nothing was exposed)
**Status:** Resolved

## Summary

While proactively auditing machine config and hooks (unrelated starting
point: "any gaps, leaks, vulnerabilities, risks — I want to know"),
`credential-guard.py` — the hook built after four prior plaintext-secret
leaks (see incidents/2026-07-02-plaintext-api-key-exposure.md,
incidents/2026-07-03-github-pat-plaintext-recurrence.md,
incidents/2026-07-04-github-pat-read-grep-leak.md) — was tested against a case it
had never been tested against: reading a sensitive file via an interpreter
one-liner instead of `cat`/`type`/`Get-Content`. A `python3 -c
"open('<path to a local config file>').read()"`-style command sailed through with no block at all,
confirmed live (with the result redacted inline before being printed,
never exposing the real token). A related, older gap was found in the same
pass: the embedded fallback copy of this same hook in a bootstrap script
(used only by the copy-paste bootstrap path) had not
been updated when the canonical hook was extended in a prior session — a
fresh machine provisioned via paste-bootstrap would have gotten a guard
that still had that earlier gap.

## Impact

- No credential was exposed by this incident — the bypass was demonstrated
  with output redaction built into the same test command.
- A live, exploitable gap existed in the specific mechanism built to
  prevent the four prior leaks: any future interpreter-based read of
  a local credential-bearing config file, `.env*`, or similar — even an
  accidental one, not a malicious one — would have printed the file's
  content, including a live GitHub PAT, unblocked.
- `python`, `python3`, and `py` are all in the always-allow permissions
  list (no user prompt) *and* were unmatched by the guard's regex — the
  specific combination that removes both layers of defense at once.
- The bootstrap script's embedded fallback carried a separately-stale
  version of the same hook, meaning the fix for a *previous* incident
  (Read/Grep coverage) had not fully propagated either.

## Root cause

**Primary — command-shape enumeration, not capability-based detection.**
`READ_COMMANDS` matched only `\b(cat|type|Get-Content|gc)\b` as literal
words. Each prior extension to this hook (env-dump patterns, an MCP-config
read command, then Read/Grep tool coverage) closed the *specific* vector the
triggering incident had used — never a general sweep of "what else can
read and print a file's bytes." A `python3`/`node`/`perl` one-liner, or
PowerShell's `[System.IO.File]::ReadAllText(...)`, is functionally
identical to `cat` for this purpose but was never enumerated. This is the
same root cause as the Read/Grep gap one incident earlier
(incidents/2026-07-04-github-pat-read-grep-leak.md), recurring at a third layer:
env-dump commands → tool names → interpreter languages. A guard keyed on
an enumerated list is only as complete as that list.

**Secondary — a real boundary bug in the file-path pattern.** While
building the fix, `SENSITIVE_FILE_PATTERN`'s prefix anchor
(`(^|[/\\])`) turned out to only match a filename immediately preceded by
a path separator or start-of-string. Bare references like `cat .env` or
`'.npmrc'` (preceded by a space or a quote, not a slash) went unmatched
even with a real read command present — a second, independent hole found
only because the fix's own test suite exercised that exact shape.

**Near-miss — an overcorrection that would have traded one failure mode
for another.** The first fix attempt widened the rule to "block any
segment that merely *mentions* a sensitive filename, unless it matches a
narrow existence-check allowlist." This is broader than necessary and was
caught immediately: it blocked its own commit message for quoting the
vulnerable example command in prose. Reverted in favor of "require an
actual read construct in the same segment" — closes the same bypass
without flagging plain mentions.

**Tertiary — duplicated logic that wasn't re-synced.** The bootstrap
script's embedded credential-guard heredoc exists for a
legitimate reason (the copy-paste bootstrap path has no clone to read the
canonical file from), but a prior session's fix to the canonical hook
never propagated there. Any fix to security-relevant logic that exists in
more than one place for a structural reason needs an explicit "and the
other copy/copies" step, not an assumption that "the hook" means one file.

## What went well

- **Found by proactively testing a capability, not by waiting for a fifth
  leak.** This is the first finding in this lineage caught by an audit
  rather than by exploitation.
- **The exploit was demonstrated live, safely.** Confirmed the bypass with
  a real `python3` one-liner against a real local config file, with redaction built
  into the same command so the actual secret was never printed unmasked —
  same discipline as the code-level fix, applied to the *testing* of the
  gap itself.
- **The overcorrection was caught by dogfooding, not by review.** The
  overly broad first draft wasn't caught by re-reading the regex — it was
  caught by trying to actually commit with it in place, in the same
  session, before it ever reached a real workflow.
- **Verified with an 18-case smoke test**, not just "does it block the bad
  command": the original four leak vectors, the new interpreter bypass,
  every new file-pattern addition, an explicit override, and explicit false-positive
  checks (plain `.json` files, prose mentions, existence-only checks like
  `Test-Path`/`grep -l`) — a fix that only re-tests the bug it was written
  for can silently break unrelated legitimate use.
- **The embedded-fallback drift was confirmed with the same test suite**,
  not eyeballed: extracted the actual heredoc content into a real file and
  ran the identical 18 cases against it side by side with the canonical
  hook, rather than assuming a diff "looked right."

## Fixes applied (2026-07-03)

| Fix | What | Where |
|---|---|---|
| Widened read-construct detection | Added `open(`, `readFileSync(`/`readFile(`, `ReadAllText(`/`ReadAllBytes(`/`ReadAllLines(`, `.read()`/`.readlines()`, and shell `<` redirection alongside the original `cat`/`type`/`Get-Content`/`gc` — still gated on an actual read construct being present, not just a filename mention | security/credential-guard.py |
| Fixed the boundary bug | Prefix anchor widened from `(^|[/\\])` to `(^|[\s/\\'"(),=:])` so bare references (`cat .env`, `'.npmrc'`) are matched | security/credential-guard.py |
| Widened file coverage | Added `.aws/credentials`, `.aws/config`, `.npmrc`, `.netrc`, `.docker/config.json`, `.kube/config`, `.pgpass`, gcloud's `application_default_credentials.json`, GitHub CLI's `hosts.yml` | security/credential-guard.py |
| Reverted the overcorrection | Dropped the "block any mention unless allowlisted" draft after it blocked its own commit message; kept the narrower "requires an actual read construct" rule | security/credential-guard.py |
| Synced the embedded fallback | Ported the same fixed logic into the paste-bootstrap embedded heredoc, which had drifted from the canonical hook after a prior session's Read/Grep fix | bootstrap script (private config repo) |
| Verified | 18-case smoke test run against both the canonical hook and the extracted embedded fallback; identical pass on every case | This machine |
| Committed + pushed | Committed to a private config repo (two commits: interpreter bypass + file coverage, and embedded fallback sync) | private config repo |

## Lessons learned

**Stop enumerating vectors reactively; ask what capability is actually
being blocked.** This is the third time this exact lesson has been
re-learned at a different layer (env-dump commands, then Read/Grep tools,
now interpreter languages). The question that would have caught all three
at once is "what are every possible way to get this file's bytes printed
to stdout," not "what command did the last leak use." A command/tool
enumeration will always be finite and always trail the next new way to do
the same thing.

**Test a fix by trying to use it for real, not just by re-running the
original bug.** The overcorrection passed every test aimed at the actual
vulnerability — it only failed when used for its real purpose (writing a
commit message). A fix's own dogfooding is a test case the original bug
report never suggests.

**Duplicated security logic needs an explicit sync step baked into the
fix process, not an assumption of "the hook" as singular.** The embedded
fallback existing for a real reason (no-clone bootstrap) doesn't make it
exempt from a fix — it makes it a second thing to remember every time,
which is exactly the kind of thing that gets forgotten under the pressure
of fixing the "real" copy. Same root pattern as the console-flash
incident's generated-file drift (see
debug-notes/2026-07-04-graphify-console-flash-three-surfaces.md), one layer over:
that one was a fix living in a place nobody version-controlled; this one
was a fix living in only one of two version-controlled places.
