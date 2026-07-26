# credential-guard

A `PreToolUse` hook for Claude Code that blocks common ways a credential ends
up printed in the clear to a session transcript. It's a mechanical backstop,
not a policy document: the behavioral rule ("never print a credential-shaped
value unmasked") already failed twice before this existed. See
[`../posture.md`](../posture.md) for the reasoning behind treating this as a
hook rather than a habit, [`../incidents/`](../incidents/) for the specific
leaks that shaped it, and [`../decisions/ADR-003-delegation-maturity.md`](../decisions/ADR-003-delegation-maturity.md)
for the v1→v2 rewrite decision.

## v2: path-based default-deny

`hook-version: 2`. v1 was a **command-shape denylist** — it enumerated the read
verbs it knew about (`cat`, `Get-Content`, `open()`, a short list) and blocked
those. Every one of the four 2026-07 credential incidents was a shape v1's
author hadn't enumerated yet, so the guard trailed each leak by exactly one
incident. An enumerated denylist cannot win that race; it only ever lists the
last leak's shape.

v2 inverts the default. Instead of "is this one of the readers I listed?", the
question is "**does a sensitive target's content reach the caller, unless this
is a recognised _safe_ operation?**" A pager or formatter nobody thought to
list (`head`, `xxd`, `base64`, `jq`, `awk`), an interpreter one-liner, or a
content-returning tool that isn't hooked yet is denied **by default**; the
small set of things that legitimately name a credential path without reading it
(a `git commit` message, `ls`, `stat`, `rm`, `grep -l`, heredoc prose) is
allowed.

## What it hooks

- **Bash / PowerShell** — the `command` string, split into segments and checked
  for environment dumps, credential-shaped variable prints, `claude mcp get`,
  and sensitive-path reads (default-deny by the segment's leading command).
- **Grep** — blocked only when `output_mode` is `content` and the `path` (or a
  `glob`) targets a credential file. `files_with_matches` and `count` never
  echo the matched line, so they stay allowed — they're the recommended
  existence check.
- **Glob** — allowed. It returns paths, not content, so it can confirm a file
  exists (the safe fallback the guard itself recommends) but can't print a
  secret's value.
- **Every other tool** — blocked if *any* path-bearing field (`file_path`,
  `path`, `notebook_path`, `uri`, …) targets a credential file. This is the key
  v2 change: coverage is keyed on the field, not a hard-coded `{Read, Grep}`
  pair, so `Read`, notebook reads, and an MCP file-reader tool that doesn't
  exist yet are all covered by construction. It's the structural fix for the
  2026-07-04 tool-shape gap (`incidents/2026-07-04-github-pat-read-grep-leak.md`),
  which was "the hook only named Bash/PowerShell" one tool-generation earlier.

Because coverage is now field-based, wire the hook to match **as many tools as
your `settings.json` allows** (ideally all of them), not just the four v1
named — a tool the matcher doesn't route to is a tool the guard never sees.

## What it blocks

1. **Environment dumps** — `env`, `printenv`, bare `set`, `export -p`,
   `declare -p`, and the PowerShell `Env:` / `Variable:` dumps, including the
   dump-then-filter form (`env | grep -i token`) that v1's end-anchored pattern
   missed.
2. **Targeted credential-variable prints** — `echo $ANTHROPIC_API_KEY`,
   `printenv GITHUB_TOKEN`, `[Environment]::GetEnvironmentVariable("...KEY")`.
   This is the exact shape of the 2026-07-02 *founding* incident, which v1
   never caught.
3. **Reads of a credential store's content, by any means** — `cat`/`head`/
   `tail`/`xxd`/`base64`/`strings`/`jq`/`awk`/…, interpreter one-liners
   (`python -c open().read()`, `node`, `perl`, PowerShell `[IO.File]::…`),
   `< file` redirection into a reader, the `Read` tool, content-mode `Grep`, or
   any other tool's path field. Anything that names a sensitive path and whose
   governing command isn't on the safe allowlist is denied — "governing" being
   per nested command unit as of v2.3, so a metadata check is safe wherever it
   sits (see "Metadata operations, wherever they sit").
4. **`claude mcp get <name>`** — prints a registered server's stored env vars
   (secrets) by design. Use `claude mcp list` to check status without values.

The sensitive-path set covers the Claude config tree (`.claude/settings.json`,
`.claude.json`), `.env*` and `.envrc`, `credentials*.json` and token caches,
SSH and other private keys (`id_rsa`/`id_ed25519`/`id_ecdsa`/`*.pem`/`*.key`/
`*.p12`/…), cloud CLIs (`~/.aws`, `~/.azure`, gcloud), package/registry stores
(`.npmrc`, `.pypirc`, `.netrc`, `.docker/config.json`), infra
(`.kube/config`, `.pgpass`, `*.tfstate`), `.git-credentials`, the GitHub CLI
`hosts.yml`, shell history, and `/proc/*/environ`. Non-secret dotenv templates
(`.env.example`, `.env.sample`, …), public certificates, and SSH **`.pub`**
public keys are explicitly allowed — see "`.pub` is not a private key" below.

### What it deliberately does *not* block

The threat model is **non-adversarial agent mistakes**, not a determined local
attacker — anyone with local code execution has already won (see `posture.md`).
So a handful of shapes are left to the permission allowlist (no `$(...)`, no
arbitrary shell control-flow) and to Layer 4 (rotate any credential that
touches a transcript), not to this hook: copy-then-read laundering (`cp secret
x; cat x`), indirection through a script the guard can't see into (`bash
leak.sh`), wildcard/variable-assembled path names (`cat ~/.claud*.json`), and
`MASK-OK` forgery. These are asserted as *allowed* in the test suite so the
boundary is explicit — a well-meaning future change that blocks them (and
starts causing false positives) fails a test on purpose.

## The MASK-OK escape hatch

A full unmasked read is sometimes genuinely necessary — a deliberate secret
audit. Add `MASK-OK` anywhere in a Bash or PowerShell command to skip all
checks for that command. There's no equivalent for Read/Grep/other tools, since
they carry no free-text command — fall back to Bash/PowerShell with `MASK-OK`.

Exit code 0 allows the tool call; exit code 2 blocks it and surfaces the
message on stderr to the model. The hook fails **open** (exits 0) on an
unparseable payload — a conscious availability-over-strictness choice for a
guard whose threat model is honest mistakes, so a malformed payload never
wedges the tool.

## Tests: the adversarial suite (and CI)

[`../tests/test_credential_guard.py`](../tests/test_credential_guard.py) is the
mechanical version of the decoy smoke test below: one case (or more) per bypass
shape in the ADR-003 taxonomy, plus the false-positive/allow cases that keep
the guard usable. It drives the guard exactly as the harness does — a
PreToolUse JSON payload on stdin, asserting exit 0/2 — using stdlib `unittest`
only, so there's nothing to install. No real secret values appear in it; the
guard keys on paths and command shapes, so the fixtures reference sensitive
*paths* and fake variable *names*, never a token.

```
python -m unittest discover -s tests -p "test_*.py" -v
```

CI ([`../.github/workflows/ci.yml`](../.github/workflows/ci.yml)) runs it on
every push and PR. The point (ADR-003 Phase 1): the next bypass is caught by a
red build, not by a fifth postmortem.

## Canonical source and the sync obligation

Per [`../decisions/ADR-002-public-first-canonicality.md`](../decisions/ADR-002-public-first-canonicality.md),
**this file is canonical**; the live deploy at `~/.claude/hooks/` and any
machine-provisioning copies sync *from* here. The `hook-version` header is the
drift tripwire — bumping it (as this rewrite did, 1 → 2) means every copy is now
stale until re-synced. The major digit is the architecture generation (1 =
enumerated denylist, 2 = path-based default-deny); a **minor** bump (2 → 2.1) is
the same architecture with corrected behaviour, and still means every copy is
stale. A guard that's been rewritten in the repo but not
redeployed to a machine is not protecting that machine: "I wrote the guard" and
"the guard is active here" are two separate facts that each have to be checked
(the deployment-≠-authorship lesson from the uncapped-fanout postmortem).

## Prose arguments vs. path positions (v2.1)

A credential-store *name* mentioned in a message flag is prose, not a read.
`gh pr create --title "chore: add .env to .gitignore"` is allowed as of v2.1:
the value of an explicitly prose-bearing flag (`-m`, `--message`, `--title`,
`--body`, `--description`, `--notes`, `--comment`, `--summary`, `--subject`,
`--reason`, `--caption`) is treated as a message rather than a path position.

The exemption is deliberately narrow, and **still blocks** three neighbouring
shapes — these are not bugs, they are the fix's guard rails:

| Shape | Why it still blocks | What to do |
| --- | --- | --- |
| `--body-file X` / `-F X` / `--notes-file X` | These really do read `X`; posting `.env` into a PR body is exfil. `--body` does not match `--body-file`. | Correct — don't pass a credential file. |
| `--body /home/user/.env` (unquoted) | An unquoted value is an ordinary argument position, indistinguishable from a path. | Quote it: `--body "...".` |
| `--body "$(cat ~/.env)"` / `--body "$TOKEN"` | A `$` or backtick can expand a secret into the published message. | Use literal prose, or a `--body-file` pointing at a non-secret file. |

If prose genuinely trips the guard anyway (an unlisted flag, or text that must
contain a `$`), the workaround is to move the text into a file and pass it with
`--body-file` / `-F` — a non-sensitive path there is allowed, and it keeps the
default-deny posture intact rather than widening the flag allowlist.

## `Env:` the drive vs. `$env:` the variable (v2.2)

PowerShell spells two different things `env:`, and until v2.2 the env-dump
pattern could not tell them apart:

| Form | What it is | Guard |
| --- | --- | --- |
| `Get-ChildItem Env:` | The **Env: PSDrive** enumerated as a path argument — every variable, values included. | Blocked (dump) |
| `Get-ChildItem "$env:USERPROFILE\.ssh"` | A **variable dereference** used to build a path. Lists a directory; touches no variable's value. | Allowed |
| `Get-ChildItem Env:GITHUB_TOKEN` | One **named** variable printed. Not a dump, but still a credential print. | Blocked (targeted read) |
| `Get-ChildItem Env:PATH` | One named non-credential variable. | Allowed |

The rule was `\bGet-ChildItem\b[^|]*\bEnv:` — any `Get-ChildItem` followed
anywhere in the segment by the text `Env:` — so row 2 was blocked as an
environment dump (confirmed false positive, 2026-07-26). The tightened pattern
anchors **both ends** of the token: `Env:` must sit in the path-argument
position (following whitespace and any `-Flag`s, optionally quoted, never a
`$`), and must end there bar a `\`/`/` root separator and a `*` wildcard.

Narrowing "dump" to the bare drive root moves `Env:NAME` out of the dump rule,
so the credential-variable rule was widened to cover the listing cmdlets
(`Get-ChildItem`/`gci`/`dir`/`ls`, alongside the `Get-Item`/`Get-Content` forms
it already had). That pairing is the point: **a tightening that removes a false
positive has to be checked for the true positives it was incidentally
catching**, or the fix ships a hole. Both directions are pinned in
`TestEnvDriveFalsePositive`.

The Bash-side dump rules (`env`, `printenv`, `set`, `declare -p`) are not
exposed to this class — they are whole-segment anchored or flag-bearing, so a
literal `env` inside a path or argument (`.venv/`, `env/`, `--env-file`,
`/usr/bin/env`, `conda env list`) never matched. That's now asserted rather than
assumed, so a future widening of those rules fails a test on purpose.

## Metadata operations, wherever they sit (v2.3)

The guard has always recommended a metadata command as the safe alternative to a
read — its own block message says so. Until v2.3 that advice could be wrong,
because the exemption was **positional**: a segment was classified by its
*leading* command, so `Test-Path ~/.ssh/id_ed25519` passed, but the same call
wrapped in a substitution did not — the leading token was then a quoted string,
which is not a safe command, so the segment fell to default-deny.

The result was a self-contradicting block (confirmed false positive, 2026-07-26):

```
"ed25519: $(Test-Path $HOME\.ssh\id_ed25519.pub)"
  -> blocked, advising "use a metadata command (ls / stat / Test-Path)"
```

v2.3 classifies each **nested command unit** on its own terms — `$( )`, `` ` ` ``,
`<( )`, and bare `( )` groups — and then judges the outer command with those
units blanked. A metadata-only operation is therefore safe wherever it appears,
and these all pass now:

```
"$(Test-Path $HOME\.ssh\id_ed25519)"      if (Test-Path ~/.ssh/id_rsa) { ... }
[bool](Test-Path ~/.ssh/id_rsa)           Write-Output (Test-Path ~/.env)
```

Two properties keep the recursion from becoming a laundering hole, and both are
pinned in `TestNestedMetadataFalsePositive`:

| Shape | Why it still blocks |
| --- | --- |
| `cat $(echo ~/.ssh/id_rsa)` | Clearing a unit must not hide the path from a reader that **receives** it. Only a unit whose output is a bare value (`Test-Path`, `test`) stops the outer command from being scrutinised; `echo`/`ls`/a bare quoted path hand the path text onward, so the outer command is still judged. |
| `"$(Test-Path ~/.ssh/id_rsa; cat ~/.ssh/id_rsa)"` | A unit body is a command **list**, so it is re-split before classifying — otherwise a reader rides in behind the metadata op. The top-level splitter can't catch this: it leaves separators inside quotes alone, which is where the shape lives. |

A paren inside a *quoted* string stays literal text and is not treated as a
unit, so `python3 -c "print(open('~/.claude.json').read())"` is not torn into
fragments that each look harmless.

### `.pub` is not a private key

The same report surfaced a second, independent defect: `id_ed25519.pub` matched
the private-key pattern. A `.pub` file is the **public** half of a keypair —
printed, pasted into GitHub, appended to `authorized_keys` as a matter of
routine. Blocking it was a pure false positive, and the kind that teaches
reaching for `MASK-OK` on a non-secret, which erodes the guard.

`.pub` is now exempt. Unlike `.pem` — ambiguous between a certificate and a
private key, hence the `key`/`priv` guard on the cert exemption — `.pub` is
unambiguous by convention, so `deploy-key.pub` is exempt too. The exemption is
still anchored to the **whole basename**: `id_rsa.pub.bak` does not qualify, the
same discipline that keeps `ca-key.pem` out of the certificate exemption.

## Installing it (standalone)

`credential-guard.py` is a self-contained, **stdlib-only** Python 3 script
(`sys`, `json`, `re` — nothing to `pip install`, no package, no dependencies).
Installing it is two steps: drop the file somewhere Claude Code can run it, and
point a `PreToolUse` hook at it.

1. **Get the file.** Copy it anywhere on the machine; the convention is
   `~/.claude/hooks/`:

   ```sh
   mkdir -p ~/.claude/hooks
   curl -fsSL https://raw.githubusercontent.com/sanlee-ys/claude-ops/main/security/credential-guard.py \
     -o ~/.claude/hooks/credential-guard.py
   ```

2. **Wire the hook** in `~/.claude/settings.json`. The hook is a single script
   invoked once per matching tool call via stdin/stdout — the standard shape
   for a Claude Code `PreToolUse` hook. Match `*` (every tool): with v2's
   field-based coverage, any unmatched tool is a blind spot, so a single
   wildcard matcher is both the simplest and the most complete wiring.

   ```json
   {
     "hooks": {
       "PreToolUse": [
         {
           "matcher": "*",
           "hooks": [
             {
               "type": "command",
               "command": "python3 \"$HOME/.claude/hooks/credential-guard.py\""
             }
           ]
         }
       ]
     }
   }
   ```

   This is the exact shape we run in production (minus an unrelated fan-out
   guard on the `Workflow` matcher). On Windows, ensure a `python3` (or an
   aliased `python`) is on `PATH`, or the hook fails open. The matcher/command
   JSON schema is versioned by the Claude Code harness, not by this repo — if a
   future version changes it, this block is the thing to re-check; consult
   Claude Code's own hooks documentation for the current shape.

Then verify it's actually live with the decoy smoke test below — installed and
active are two separate facts.

## Verifying the live install: the decoy-file smoke test

The automated suite proves the guard's *logic* against the repo copy. It does
**not** prove the guard is installed and active on *this machine* — that's the
separate fact above. Verify the live deploy with a decoy:

1. Create a harmless decoy with a shape the pattern matches, e.g.
   `credentials-test.json` containing a fake, obviously-not-real value.
2. Try to read it through each covered path: `cat`/`head`/`Get-Content` in
   Bash/PowerShell, a Read tool call, a content-mode Grep, and a non-`cat`
   reader like `base64`. Each should be blocked with the guard's message.
3. Confirm `files_with_matches`/`count`-mode Grep and a metadata check
   (`stat`/`Test-Path`) against the same file still succeed.
4. Try a Bash/PowerShell read with `MASK-OK` and confirm it goes through.
5. Delete the decoy file.

A hook that looks right on inspection but hasn't been exercised against a real
blocked case and a real allowed case — on the machine that's supposed to be
protected — isn't verified yet.
