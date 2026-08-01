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
x; cat x`), **variable laundering** (`$k = $env:SECRET; Get-Variable k` — the
same shape one container down, see the `Get-Variable` section below),
indirection through a script the guard can't see into (`bash leak.sh`),
wildcard/variable-assembled path names (`cat ~/.claud*.json`), and
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

## `Get-Variable`: naming one variable is a read (v2.4)

`Get-Variable` prints every shell variable unless you ask for a specific one, so
v2 blocked it with `\bGet-Variable\b(?![^|]*-Name)` — *"no `-Name` flag anywhere
in the segment, so it must be a dump."* Measured against real commands, that
rule was wrong in three directions at once:

| Command | v2 | Correct |
| --- | --- | --- |
| `Get-Variable PATH` | blocked | allow — names one variable, positionally |
| `git checkout -b fix/get-variable-fp` | blocked | allow — it's a branch name |
| `rg 'Get-Variable' security/` | blocked | allow — you couldn't grep for the rule's own name |
| `Get-Variable -Name *` | **allowed** | block — `-Name` was an unconditional escape hatch, so a wildcard dump walked through it |
| `gv` | **allowed** | block — the alias was never named |

The `\b...\b` anchors matched the literal text anywhere in the segment rather
than in a command position — the same mistake as the v2.2 `Env:` bug one section
up. This one was found when the guard blocked the `git worktree add -b
fix/get-variable-...` that was creating the branch to fix it.

### The posture call

Narrowing row 1 raises a real question. The `Variable:` drive holds arbitrary
shell variables, so a laundered secret is invisible to `CRED_VAR_READ`, which
screens by *name*:

```powershell
$k = $env:ANTHROPIC_API_KEY   # the secret is now in a variable called `k`
Get-Variable k                # ...and `k` looks nothing like a credential
```

Blocking every unnamed `Get-Variable` did catch that. But it was never buying
the protection it appeared to: **`Get-Variable -Name k` — the same read, more
idiomatically spelled — was already allowed.** The rule caught laundering only
when the caller happened to use positional syntax, which is a coin flip, not a
control.

So the decision is to narrow, on the grounds that this makes an existing
boundary consistent rather than moving it. Variable laundering *is*
copy-then-read laundering (`cp secret x; cat x`) one container down, and that is
already explicitly out of scope for exactly this reason: the threat model is
non-adversarial agent mistakes, and an agent that assigns a secret to `$k` and
prints `$k` is not the failure this hook exists to stop. It is now listed with
the other bounded-out shapes above, and asserted as allowed in the suite, so the
boundary is a decision on the record instead of an accident of regex breadth.

The rule is now the natural one — **a dump is an invocation that names no
specific variable, or names a wildcard** — implemented as a token walk
(`_get_variable_is_dump`) rather than a lookahead, so `-Scope Global` (a flag
value) and `-ValueOnly PATH` (a switch plus a name) are read correctly. Closing
rows 4 and 5 means the change removes two false positives *and* two real gaps.

`Variable:` also gets the drive-root treatment `Env:` got in v2.2 (they share
`_PS_DRIVE_DUMP` now): `Get-ChildItem Variable:` blocks — it didn't before, since
only `dir`/`ls` were named — while `ls Variable:PATH` is a targeted read, and
`ls Variable:ANTHROPIC_API_KEY` still blocks on the credential-name screen.

## An anchored rule needs a segment to anchor to (v2.5)

`env` was blocked. `echo $(env)` was not — and it runs the same full dump. Also
allowed: `"$(env)"`, `echo $(printenv)`, `x=$(env)`, ``echo `env` ``. A
pre-existing gap, older than every fix above and confirmed on the pre-v2.2
baseline.

The cause is **not** a rule that is too narrow. The bare-dump rules are anchored
to a whole segment (`^\s*env\s*$`, `^\s*printenv\s*$`, `^\s*set\s*$`), and that
anchoring is load-bearing — it is the only reason `.venv/bin`, `--env-file`,
`conda env list`, `/usr/bin/env` and `env -u VAR cmd` don't match. Loosening it
would trade this gap for that whole family of false positives.

The cause is that the rules were only ever handed the **top-level** segment, so
a dump one container down never got the anchor's attention. A substitution body
is a command in its own right, so it is now offered to them as a segment —
recursively, and re-split first, because a body is a command *list*
(`$(cd /tmp; env)`).

Two narrower calls inside that fix, both pinned in `TestNestedEnvDump`:

- **Only the env-dump rule gets the extra pass.** `CRED_VAR_READ` and
  `MCP_GET_PATTERN` are un-anchored, so their search already sees inside a
  substitution. Running `CRED_VAR_READ` per unit would *newly break*
  `[bool]($env:API_KEY)` — its standalone-statement alternatives describe a
  statement that emits a value, and a unit body's value is consumed by the
  expression around it. The parenthesised spelling of the guard's own
  recommended existence check must not become a block.
- **The `git commit -m` prose skip does not extend to unit bodies.** That skip
  exempts a *message*; a substitution body is executed code whatever encloses
  it. So `git commit -m "document $(env) in the runbook"` blocks (double quotes
  run it) while the single-quoted spelling stays allowed (they don't).

### The splitter no longer cuts inside parentheses

Half the fix is in `_split_segments`. It used to split on `;`/`|`/`&` without
regard for parens, so `echo $(cd /tmp; env)` arrived as `echo $(cd /tmp` and
`env)` — and `^\s*env\s*$` cannot match `env)`. A fragment defeats an anchored
rule just as thoroughly as never being shown the text.

Segments now hold parentheses together. Nested units are re-split from their
bodies anyway, so nothing is lost. An unbalanced `(` stops splitting for the
rest of the command, which is safe rather than blinding: the trailing text still
lands inside a unit body (`_balanced` runs an unterminated group to end of
segment) and both callers re-split what they find. `echo ( ; cat ~/.env`,
`echo ( ; env`, and a quoted `echo "(" ; cat ~/.env` are all pinned as blocked.

## A binding is not a read (v2.6)

`Remove-Item '~/.claude/settings.json.bak' -Force` was allowed. Bind the path to
a variable first and the identical delete blocked:

```powershell
$f = '~/.claude/settings.json.bak'
Remove-Item $f -Force            # BLOCKED, same semantics
```

So did `foreach ($f in @(...)) { Remove-Item $f }`, and — sharpest —
`Test-Path` sitting in a loop header, which is the remediation the block message
itself recommends. `Get-FileHash`, on `SAFE_COMMANDS` precisely as a
digest-not-content read, blocked the same way.

`_leading_command` skipped the *bash* `VAR=val` prefix but not PowerShell's
`$var = ...` (leading `$`, and with spaces the `=` is its own token), nor a
`foreach (...)` header. So `lead` came back as `$f` — not a known command — and
fell to default-deny.

**The block was not buying coverage.** It is lexical, so the workaround is just
"don't write the literal": enumerate with `Get-ChildItem -Filter '*.bak'` and
delete `$_.FullName`, and the same file is removed with the string never
appearing. What it did buy was the reflex of reaching for `MASK-OK` on an
operation that reads nothing — which is the failure mode the posture cares
about most, and the reason a false positive on a security control is a real
cost rather than a cosmetic one.

Two rules, and **neither is safe without the other**:

1. **A pure value binding runs nothing**, so it is not a read. `$f = <literal>`
   and `foreach ($f in <literal>)` are inert. "Pure literal" is deliberately
   narrow (`_is_literal_value`): a quoted string, a bare path token, or an array
   literal of those, and nothing that can execute — no `$(`, no backtick, no
   `@(`-nested call. `$x = "$(cat ~/.env)"` is therefore *not* a binding and
   keeps blocking on its nested reader.
2. **The association survives.** Allowing the binding while ignoring what the
   body does with it would be a straight hole, so the bound literal is
   substituted back into the rest of the command before classification.
   `foreach ($f in @('~/.env')) { Get-Content $f }` is judged as
   `Get-Content @('~/.env')` and blocks; the same loop with `Remove-Item` is
   judged as `Remove-Item @('~/.env')` and passes. That is the whole point:
   the *verb* decides, not whether a variable was involved.

Substitution runs to a **fixpoint**, so a re-binding chain cannot walk the path
out one hop at a time (`$a = '~/.env'; $b = $a; Get-Content $b`). Bindings are
stored scope-stripped and matched with the scope prefix optional, because
`$global:f` and `$f` are the same variable and fixing only one direction leaves
the other open. Only a **sensitive** literal is ever registered, so nothing else
is rewritten.

Because the substituted path flows into the *ordinary* checks, the variable form
inherits all of them rather than just the leading-command one — `base64 $f`,
`cat < $f`, `tar -O -xf $f`, `git show HEAD:$f`, `python3 -c "...open($f)..."`
and the cross-stage `echo $f | xargs cat` all block.

### Header and body, separately but not independently

Loop and conditional headers are now classified apart from their bodies, which
is what lets a benign header carry a sensitive path without condemning the
segment (and fixes `if (Test-Path ~/.env) { Remove-Item ~/.env }`, previously
denied on the `if`). The trap in splitting them is losing the association: the
header is benign and the *body* is the read. Both halves are classified, and the
body against the path the header bound, so `foreach ($f in @('~/.env'))
{ Get-Content $f }` still blocks. An unbalanced group or brace fails toward
BLOCK.

A related classification gap fell out of this: an array literal is a paren
group, so its body is offered up as a segment of its own. A single element
already passed as a whole-quoted literal, but two or more (`'~/.env','~/.aws/
credentials'`) were judged on a "leading command" of the element list itself and
default-denied — which is why a two-file cleanup loop blocked while the one-file
version passed. A segment that is nothing but a value expression is now
recognised as data (`_is_literal_data`); a *bare word* is deliberately excluded,
since a bare word in command position is a command.

### What this deliberately is not

It is not a dataflow analyser. Anything whose right-hand side is not a pure
literal stays default-denied rather than being resolved — `$f = @{p='~/.env'}`,
`$a = $b = '~/.env'`, `$f += ...`, `$f[0] = ...`, backtick line-continuation
across segments. None of those is newly allowed; they keep their pre-2.6
behaviour or block. Pinned in `TestVariableBindingFalsePositive`.

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
