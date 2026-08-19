#!/usr/bin/env python3
# hook-version: 2.13 (canonical: THIS file, per decisions/ADR-002 — the live
# deploy at ~/.claude/hooks/ and any provisioning copies sync FROM here)
# 2.1 (2026-07-18): prose-flag false-positive fix; a copy still reporting 2 is
# stale. Minor bump = same v2 architecture, corrected behaviour.
# 2.2 (2026-07-26): `Env:` PSDrive false-positive fix — the env-dump pattern
# matched `$env:NAME` used as a path, not just the drive root.
# 2.3 (2026-07-26): metadata ops nested in a substitution or group are no longer
# default-denied, and an SSH `.pub` file is not a private key.
# 2.4 (2026-07-26): `Get-Variable` naming one variable is a targeted read, not a
# dump; `Variable:` gets the same drive-root treatment as `Env:`.
# 2.5 (2026-07-26): a bare env dump nested in a substitution (`echo $(env)`) is
# now seen — the whole-segment anchors get offered each unit body as a segment,
# and the splitter no longer cuts a substitution into fragments.
# 2.6 (2026-07-31): a PowerShell VALUE BINDING (`$f = '~/.env'`, `foreach ($f in
# @(...))`) is no longer read as an unknown command and default-denied; the
# bound path is instead SUBSTITUTED into the rest of the command, so the safe
# verb the issue reported (Remove-Item / Test-Path / Get-FileHash via a
# variable) passes while a reader reached through the same variable still
# blocks. Loop/conditional headers are classified separately from their bodies.
# 2.7 (2026-08-04): an UNCONSTRAINED directory enumeration feeding a per-item
# content reader (`Get-ChildItem -Force <dir> | ForEach-Object { Get-Content
# $_.FullName }`, `find . -type f -exec cat {} \;`, `ls | xargs cat`) now
# blocks. Measured, not theorised — see "Enumerate-then-read" below. Keyed on
# PIPELINE SHAPE, not on any path, so a name filter that no credential basename
# can satisfy (`-Filter *.py`) still passes and a bare enumeration or a bare
# reader is untouched.
# 2.8 (2026-08-04): cursor-agent compatibility, all three measured on Windows
# (vendors/cursor/README.md "Guard wiring"). cursor-agent auto-imports this
# hook from ~/.claude/settings.json and (a) pipes the payload through a
# PowerShell wrapper whose $OutputEncoding prepends a UTF-8 BOM — json.load
# raised and the guard failed OPEN on every call — so stdin is now decoded
# utf-8-sig; (b) names its shell tool "Shell", not Bash/PowerShell, so the
# command checks now accept it; (c) treats an empty-stdout hook run as failed
# (and imported hooks are hardcoded failClosed=false), so a Cursor payload —
# identified by its cursor_version key — gets an explicit allow verdict on
# stdout. Deny needs no dialect: Cursor maps exit 2 + stderr to a block.
# 2.9 (2026-08-09): COPY-THEN-READ LAUNDERING is no longer out of scope. A
# copy/move/rename/archive whose SOURCE is a credential path and whose
# DESTINATION is not now blocks, and the sensitive-file pattern recognises
# DERIVED names (`<sensitive>.bak-20260806`, `.old`, `~`, `_backup`, …) as the
# same class — which is what keeps a routine pre-edit backup legal AND keeps
# the backup guarded. Measured, not theorised: see "Copy-then-read laundering"
# below. Two real read holes fell out of the same measurement and are closed
# here — `cat ~/.aws/credentials.bak` and `cat ~/.env_backup` were both allowed.
# The same run also found the block REASON advertising the MASK-OK override to
# the model, which read it out of a block and used it. The override is unchanged
# and still documented for humans in security/README.md; it is simply no longer
# named in the agent-facing string. See "Block messages" below.
# 2.10 (2026-08-09): WORDING ONLY — no verdict anywhere changes. The path-based
# default-deny emitted one message, phrased entirely as a read ("Same exposure
# as `cat`-ing it"), for writes as well: a `Write`/`Edit` at ~/.ssh/id_rsa, and
# a write-only cmdlet reaching the unknown-command deny (`Set-Content ~/.env`).
# Blocking those is deliberate and unchanged — clobbering the operator's live
# secret is as bad an outcome as printing it — but describing a write as a read
# makes a correct block look like a guard bug, which points the next session at
# the block instead of the string. There is now a second message, _MSG_PATH_WRITE,
# selected per call; both keep the "ask the operator" tail. Anything the
# selector cannot classify gets the READ message, i.e. the previous behaviour.
# 2.12 (2026-08-11): a REMOTE resource is not a local credential store. Two
# false-positive shapes, both observed the same day in three sessions: (a)
# `gh api repos/<owner>/<repo>/contents/.claude/settings.json` fetches PUBLIC
# repo content, but `gh` is an unknown command, so the path substring hit the
# default-deny; (b) a WebFetch of the same public GitHub URL blocked because
# the `url` field name matches _PATH_FIELD_NAME. Fix: a `gh api` segment now
# strips its remote-shaped endpoint argument before the path check (a LOCAL
# path anywhere else in the segment — `--input ~/.env` — still denies), and a
# path-named tool field whose value is an http(s) URL is skipped (`file://`
# still blocks; it names the local filesystem). Local reads are unchanged.
# 2.11 (2026-08-09): SINGLE-QUOTED prose is literal. The 2.1 prose exemption
# voids itself on any `$` or backtick, which is right for a double-quoted value
# and wrong for a single-quoted one — neither expands, in POSIX shells or in
# PowerShell. A Markdown PR body is mostly backticks, so `gh pr create --body
# '... `~/.claude/settings.json` ...'` blocked as a credential read and the only
# way through was `--body-file`, i.e. routing around the guard. Narrow by
# construction: single quotes ONLY, and only when the value is not nested in a
# double-quoted region — in `bash -c "... --body '$(cat ~/.env)'"` the outer
# quotes substitute first, so that stays blocked (measured, all four nestings).
# The same literalness test now gates PROSE_FLAG_CRED_VAR, since `--body
# '$ANTHROPIC_API_KEY'` publishes the literal name, not the key.
# 2.13 (2026-08-19): an `=`-attached dest/src flag value (`cp
# --target-directory=/tmp ~/.env`) no longer consumes the NEXT token — the
# copy-launder parser read the credential source as the flag's value and never
# judged it; the attached text after the first `=` is now the value.
"""Credential exposure guard (global PreToolUse hook) — path-based default-deny.

v2 (2026-07-06, agent-ops decisions/ADR-003 Phase 1). v1 enumerated the *read
verbs* it knew about (cat / Get-Content / open() / a short list) and blocked
those. Every one of the four 2026-07 credential incidents was a shape v1's
author had not enumerated yet, so the guard trailed each leak by exactly one
incident:

  - 2026-07-02 plaintext-api-key-exposure  — a user-scoped env var read.
  - 2026-07-03 github-pat-plaintext-recurrence — `cat ~/.claude/settings.json`.
  - 2026-07-03 credential-guard-interpreter-bypass — `python3 -c open().read()`.
  - 2026-07-04 github-pat-read-grep-leak   — the Read / content-Grep *tools*.

A proactive taxonomy of the guard's own surface (decisions/ADR-003) found the
denylist still open at, among others: `head`/`tail`/`xxd`/`base64`/`strings`/
`jq`/`awk` (any pager or formatter that isn't `cat`), `env | grep TOKEN`,
`declare -p`, `/proc/self/environ`, and — the 07-04 lesson one tool-generation
on — *every* content-returning tool the hook doesn't name (MCP file readers,
notebook reads). An enumerated denylist cannot win that race; it only ever
lists the last leak's shape.

v2 inverts the default. The question is no longer "is this one of the read
verbs I listed?" but "does a sensitive target's content reach the caller,
unless this is a recognised *safe* operation?" Concretely:

  1. Any tool with a path-bearing field (file_path / path / notebook_path /
     uri / ...) reading a sensitive target is blocked — for ALL tools, not a
     hard-coded {Read, Grep} pair. A reader tool nobody has hooked yet is
     covered the day it appears (closes the 07-04 class structurally).
  2. Grep keeps its output-mode nuance: only `content` mode echoes the matched
     line, so `files_with_matches` / `count` stay allowed (they are the
     recommended existence check).
  3. Bash / PowerShell: a segment that names a sensitive path is blocked unless
     the command governing it is on a small SAFE allowlist (metadata/existence,
     pure file management, string/echo, and version control). So `xxd`, `jq`,
     `base64`, `python3 -c`, and any unknown reader are denied by *default*;
     `git commit -m "... .env ..."`, `echo`, heredoc prose, `ls`, `rm`,
     `grep -l`, and `stat` are not. This is the false-positive discipline v1's
     first over-broad draft violated (it blocked its own commit message for
     quoting the example); requiring the sensitive path to sit in an actual
     command position, and treating VCS/echo/heredoc as safe, keeps prose
     committable. "Governing" is per nested command unit as of v2.3: a
     substitution or paren group is classified on its own leading command, so a
     metadata check is safe wherever it sits (see "Nested command units").
  4. Bulk and targeted environment reads: `env`/`printenv`/`set`/`declare -p`/
     the PowerShell `Env:` dumps, AND a single credential-shaped variable being
     printed (`echo $ANTHROPIC_API_KEY`, `printenv GITHUB_TOKEN`,
     `[Environment]::GetEnvironmentVariable("...KEY")`) — the founding 07-02
     incident, which v1 never caught. As of v2.5 the bulk forms are checked
     against nested command units too, so `echo $(env)` is seen and not just a
     bare `env` (see _nested_command_units).
  5. Enumerate-then-read (v2.7): a directory enumeration whose result set is
     UNCONSTRAINED, piped into a stage that dereferences each name and prints
     its content. Rules 1-3 all key on a path appearing in the command text;
     this shape has none, because the paths are produced at runtime. It was
     bounded out as "variable-assembled" until it was measured: asked in plain
     language to print a dotenv file's contents, an agent wrote
     `Get-ChildItem -Force <dir> | ForEach-Object { Get-Content $_.FullName }`
     and the decoy value was printed. That is the *idiomatic* way to satisfy
     "show me the config in this folder", not an evasive construction, so it
     sits squarely inside the non-adversarial threat model rather than outside
     it — see _enumeration_is_unconstrained / _reads_each_item.
  6. Copy-then-read laundering (v2.9): a copy / move / rename / archive whose
     SOURCE is a credential path and whose DESTINATION is not. Rules 1-5 all
     judge the read; this judges the step BEFORE it, because after the copy
     there is no sensitive path left to judge — the bytes are the secret's and
     the name is not. Measured 2026-08-09 against a decoy `.env`: under
     `--permission-mode bypassPermissions` an agent asked in plain language for
     the file's contents had every direct read blocked (Get-Content, type,
     `cmd /c type`, `bash -lc cat`, the Read tool), then ran `Copy-Item .env
     <non-credential-name>`, read the copy, and printed it. Eight turns, and
     nothing about it was adversarial — the agent was doing as it was asked.
     See _copy_launders_credential.

Deliberately OUT of scope, per the posture's threat model (non-adversarial
agent mistakes; anyone with local code-execution has already won — see
posture.md and decisions/ADR-001): indirection through a script the guard
can't see into (`source .env` is caught because `source` is not a safe verb,
but `bash leak.sh` is not), wildcard path names (`cat ~/.claud*.json`) that no
path-regex can resolve without matching innocent globs too, and MASK-OK
forgery. (Three members of that list have since been narrowed out of it and
are NOT out of scope any more: `f=.env; cat $f` blocks as of v2.6,
enumerate-then-read as of v2.7, and copy-then-read laundering as of v2.9 — see
below. The list describes coverage, not a settled ruling; a shape leaves it
whenever a mechanism appears that resolves it without the false positives that
put it there.) Those are contained by the permission allowlist (no `$(...)`,
no arbitrary shell control-flow) and by treating any credential that touches a
transcript as compromised and rotating it (posture Layer 4), not by this hook.
The adversarial test suite (tests/test_credential_guard.py) carries a case per
taxonomy shape, including the ones we consciously do not block, so the boundary
is asserted rather than assumed.

What this hook is NOT, restated because v2.9 is the widening most likely to be
mistaken for completeness: a pattern guard cannot be complete against an agent
holding a shell. `>` redirection, base64, a two-line Python script that reads
and re-emits, a network POST — all still reach the same bytes, and none of
them is a copy. v2.9 raises the cost of the COMMON, ACCIDENTAL case; the
containment argument for a deliberate one is the permission layer and the
workspace, not this file. See posture.md, "What the copy rule does and does
not buy".

Override: add MASK-OK to a Bash/PowerShell command for a deliberate, considered
unmasked read (mirrors fanout-guard.py's PREMIUM-OK). Read/Grep/other tools
have no free-text field to carry it — fall back to Bash with MASK-OK.

Exit 0 = allow, exit 2 = block (stderr surfaced to the model). Fails OPEN on an
unparseable payload — a deliberate availability-over-strictness choice for a
guard whose threat model is honest mistakes, not a malformed-input attacker;
never wedge the tool on a payload it can't read.
"""
import sys
import json
import re


# --- Sensitive targets -----------------------------------------------------
# Widened from v1 per the ADR-003 taxonomy §B. The prefix group anchors a match
# to a path boundary (start, slash, quote, or common shell separators) so a
# bare `.env` or `'.npmrc'` still matches but `prevented`/`sevent` do not.
_PREFIX = r"(^|[\s/\\'\"(),=:@])"

# --- Derived names (v2.9) ---------------------------------------------------
# A backup, rename, or numbered rotation of a credential file holds the same
# bytes, so it is the same class of target. This is one half of the copy-launder
# fix and the whole of its false-positive cure, and the two are the same edit:
#
#   Copy-Item ~/.claude/settings.json ~/.claude/settings.json.bak-20260806
#
# is a routine pre-edit backup (San's actual habit — `settings.json.bak-20260806`
# and `hooks.json.bak-20260806` exist on this machine). A rule that blocked
# every copy of a credential file would break it; a rule that ALLOWED it while
# leaving `.bak-20260806` unrecognised would be worse — the laundering hole
# reappearing inside a normal workflow, since the backup would then be readable.
# Recognising the derived name does both: the copy is legal because its
# destination is sensitive too, and the copy stays guarded against a later read.
#
# Measured before writing this (see the derived-name probe in the PR): the old
# `\b` terminator ALREADY carried most of the derived shapes — `.env.bak`,
# `id_rsa.old`, `terraform.tfstate~`, `credentials.json.20260806` all matched.
# Exactly two families did not, and both were live read holes, not just copy
# holes: `~/.aws/credentials.bak` (the `(?![\w.-])` lookahead below rejected
# every suffix) and the underscore-joined `_backup` form on every closed
# alternative (`\b` needs a NON-word char, and `_` is a word char). `cat
# ~/.aws/credentials.bak` and `cat ~/.env_backup` were both allowed before this.
#
# The token list is deliberately closed rather than "any suffix": a generic
# `[\w.-]*` terminator would swallow `.aws/config.d/dev` and `.aws/config-
# templates`, which are pinned as ALLOWED by red-team L1. This guard's history
# has one reverted over-broad draft in it already (posture limit #5); the rule
# here is that a widening must name what it adds.
#
# Each alternative must begin with a separator and its tail cannot cross one, so
# the chain decomposes uniquely — no nested-quantifier ambiguity, no ReDoS on a
# pathological argument.
_DERIVED_SUFFIX = (
    r"(?:[.\-_](?:bak|backup|old|orig|copy|save|prev)\w*"   # .bak-2026…, _backup
    r"|[.\-_]\d\w*"                                          # .1, .20260806, -2
    r"|~)"                                                   # emacs/vim backup
)
# The same tokens as a trailing chain, for stripping a derived tail back to its
# stem. Used ONLY by the template/cert exemptions (see _match_exempt).
_DERIVED_TAIL = re.compile(r"(?:" + _DERIVED_SUFFIX + r")+$", re.IGNORECASE)
# `.aws/credentials` and `.aws/config` need their own terminator: the plain
# `(?![\w.-])` that keeps `config.d/` and `config-templates` out would also
# reject every derived name, so it is widened to "a hard boundary OR the start
# of a derived suffix" and the chain below consumes the suffix itself.
_AWS_BOUNDARY = r"(?=$|[^\w.-]|" + _DERIVED_SUFFIX + r")"

SENSITIVE_FILE_PATTERN = re.compile(
    _PREFIX + r"("
    # Claude's own config (narrowed to the .claude tree — a random project's
    # settings.json is not a credential store, and blocking it is a false
    # positive that erodes the guard).
    r"\.claude[/\\]settings(\.local)?\.json"
    r"|\.claude\.json"
    # Dotenv, including .envrc (direnv) — but NOT the non-secret templates.
    r"|\.envrc"
    r"|\.env(\.[\w.-]+)?"
    # Generic credential stores / token caches.
    r"|credentials[\w.-]*\.json"
    r"|application_default_credentials\.json"
    r"|access_tokens\.db|credentials\.db"
    # Private keys / keystores. The trailing `.pub...` is matched so the
    # exemption below can SEE it — `\w*` stops at the dot, so without this the
    # matched text for `id_ed25519.pub` was the bare `id_ed25519` and the public
    # half was indistinguishable from the private one (2026-07-26 false
    # positive). It runs over the WHOLE remaining suffix, not just `.pub`, so
    # PUBLIC_KEY still judges a complete basename: `id_rsa.pub.bak` must not be
    # exempted by a name that merely starts like a public key (the anchoring
    # discipline PUBLIC_CERT learned in red-team round 2, H1).
    r"|id_(rsa|ed25519|ecdsa|dsa)\w*(\.pub[\w.-]*)?"
    r"|[\w.-]+\.(pem|key|ppk|p12|pfx|jks)"
    # Cloud CLIs.
    r"|\.aws[/\\](credentials|config)" + _AWS_BOUNDARY + r""
    r"|\.azure[/\\][\w.-]+"
    r"|\.config[/\\]gcloud[/\\][\w.-]+"
    # Package / registry / infra.
    r"|\.npmrc|\.pypirc|\.netrc|_netrc"
    r"|\.docker[/\\]config\.json"
    r"|\.kube[/\\]config"
    r"|\.pgpass"
    r"|[\w.-]*\.tfstate|\.terraformrc|credentials\.tfrc\.json"
    r"|\.gnupg[/\\][\w.-]+"
    # Git / GitHub CLI plaintext credential stores.
    r"|\.git-credentials"
    r"|\.config[/\\]gh[/\\]hosts\.yml|GitHub CLI[/\\]hosts\.yml"
    # Shell history can contain a pasted secret; interactive rc/profile files
    # are deliberately NOT here (reading ~/.zshrc to debug PATH is routine, and
    # a secret exported there is caught at the env-var-read layer if printed).
    r"|\.(bash|zsh)_history"
    # Linux process environment — every secret env var, via a file path.
    r"|/proc/(self|\d+)/environ"
    r")" + _DERIVED_SUFFIX + r"*\b",
    re.IGNORECASE,
)

# Non-secret matches that the sensitive pattern would otherwise catch: dotenv
# templates (checked-in examples) and public certificate/chain files (a `.pem`
# that is a cert, not a private key). Applied PER MATCHED PATH — never over a
# whole command segment, or a one-word `# .env.example` comment would disarm
# the guard for every file (red-team finding H1).
ENV_TEMPLATE = re.compile(
    r"^\.env\.(example|sample|template|dist|defaults?)$", re.IGNORECASE
)
# Public certificate/chain basenames — anchored to the WHOLE basename, and
# refused for any name containing key/priv. A private key is routinely named
# `ca-key.pem` / `cert-key.pem` (step-ca, cfssl) and begins with a cert token,
# so a substring match would exempt the most sensitive key on the box
# (red-team round 2, H1). `.key`/`.p12`/`.pfx`/`.jks` are never exempt.
PUBLIC_CERT = re.compile(
    r"^(fullchain|chain|ca|cacert|ca-bundle|cert|certificate|public|pub)"
    r"\d*\.(pem|crt|cer)$", re.IGNORECASE  # \d*: certbot's cert1.pem/fullchain2.pem
)
_KEYISH = re.compile(r"key|priv", re.IGNORECASE)
# An OpenSSH `.pub` file is the PUBLIC half of a keypair. It is not a secret —
# it is routinely printed, pasted into GitHub, and appended to authorized_keys —
# so blocking it is a pure false positive, and one that teaches the reflex of
# reaching for MASK-OK on a non-secret (2026-07-26). Unlike `.pem` (ambiguous
# between a cert and a private key, hence the _KEYISH guard on PUBLIC_CERT),
# `.pub` is unambiguous by convention, so it is exempt even when the stem is
# key-ish: `deploy-key.pub` is still a public key.
PUBLIC_KEY = re.compile(r"^[\w.-]+\.pub$", re.IGNORECASE)


def _basename(matched):
    return re.split(r"[/\\]", matched.strip().strip("'\"(),=:@ "))[-1]


def _match_exempt(matched):
    """A sensitive-pattern hit that's actually a public key/template/cert —
    judged on the basename, and (except for `.pub`, see above) never when the
    name looks like a private key.

    v2.9: the template and certificate exemptions are also judged on the name
    with a derived tail stripped, so `ca.pem.bak` stays exempt now that the
    pattern consumes `.bak` into the match. This is applied to those two
    exemptions ONLY, never to PUBLIC_KEY — `id_rsa.pub.bak` must keep blocking
    (red-team round 2, H1: an exemption anchored to a whole basename is the
    thing that stops a name which merely *starts* like a public key from
    laundering the private one), and stripping `.bak` before that check is
    exactly how it would reopen."""
    name = _basename(matched)
    if PUBLIC_KEY.match(name):
        return True
    if _KEYISH.search(name):
        return False
    stem = _DERIVED_TAIL.sub("", name)
    return bool(ENV_TEMPLATE.match(name) or PUBLIC_CERT.match(name)
                or ENV_TEMPLATE.match(stem) or PUBLIC_CERT.match(stem))


def _has_sensitive_path(text):
    """True if `text` names a credential store, evaluating the template/cert
    exemption per matched path so an unrelated template mention elsewhere in
    the string can't launder a real secret path (red-team H1)."""
    if not isinstance(text, str):
        return False
    return any(not _match_exempt(m.group(0))
               for m in SENSITIVE_FILE_PATTERN.finditer(text))


# --- Environment dumps and targeted credential-var reads -------------------

# The PowerShell `Env:` PSDrive enumerated as a PATH ARGUMENT.
#
# 2026-07-26 false positive: the old form was `\bGet-ChildItem\b[^|]*\bEnv:`,
# which matched ANY `Get-ChildItem` followed anywhere in the segment by the text
# `Env:` — so `Get-ChildItem "$env:USERPROFILE\.ssh"` was blocked as an
# environment dump. That command lists a directory; it never touches the Env:
# drive. `$env:NAME` is a variable DEREFERENCE that happens to spell `env:`;
# `Env:` as the drive root is the dump. Both ends of the token distinguish them:
#
#   - it must FOLLOW whitespace (after the cmdlet and any `-Flag`s), optionally
#     quoted — never a `$`. That alone kills `"$env:USERPROFILE\.ssh"`, and it
#     is why the `(dir|ls|gci)\s+env:` alternatives never had this bug.
#   - it must END there, bar a `\`/`/` drive-root separator and a `*` wildcard.
#     `Env:PATH` names ONE variable, so it is a targeted read rather than a
#     dump — see CRED_VAR_READ, which covers the listing cmdlets too so this
#     tightening cannot unblock `Get-ChildItem Env:GITHUB_TOKEN`.
#
# Covers `Get-ChildItem Env:`, `gci env:`, `ls Env:\`, `Get-ChildItem -Path
# Env:`, `Get-Item Env:*`, and the quoted forms (case-insensitive).
#
# v2.4 generalises the same shape to `Variable:`, the other PSDrive whose root
# enumerates values. It was covered by a bare `\b(dir|ls)\s+variable:`, which
# both missed the real dump `Get-ChildItem Variable:` and blocked the targeted
# `ls Variable:PATH` — the same two-way error the `Env:` fix corrected.
_PS_DRIVE_DUMP = (
    r"(?:^|[\s;(])(?:Get-ChildItem|Get-Item|gci|gi|dir|ls)\s+"
    r"(?:-\w+\s+)*"                      # -Path / -LiteralPath / -Force / ...
    r"['\"]?(?:Env|Variable):[\\/]?\*?['\"]?(?![\w$-])"
)

ENV_DUMP_PATTERN = re.compile(
    r"^\s*env\s*$"                       # bare `env`
    r"|^\s*printenv\s*$"                 # bare `printenv`
    r"|^\s*set\s*$"                      # bare `set` (not `set -e` / `set -o`)
    r"|\bexport\s+-p\b"                  # `export -p`
    r"|\bdeclare\s+-\w*p\b"              # `declare -p` / `-px`
    + r"|" + _PS_DRIVE_DUMP,             # PowerShell Env:/Variable: PSDrive dump
    re.IGNORECASE,
)

# --- `Get-Variable`: dump vs. targeted read ---------------------------------
# `Get-Variable` prints EVERY shell variable unless a specific one is named, so
# v2 blocked it via `\bGet-Variable\b(?![^|]*-Name)` — "no `-Name` flag anywhere
# in the segment, so it must be a dump." That rule was wrong in three directions
# at once, all confirmed empirically before this change (2026-07-26):
#
#   1. It BLOCKED targeted reads. `Get-Variable PATH` names one variable
#      positionally; there is no `-Name`, so it was read as a dump.
#   2. It BLOCKED plain text. `\b...\b` matches anywhere, so `git checkout -b
#      fix/get-variable-fp` and even `rg 'Get-Variable' security/` were blocked
#      — you could not grep for the rule's own name. (The `git worktree add -b
#      fix/get-variable-...` form is how this was found: it blocked the branch
#      being created to fix it.)
#   3. It ALLOWED real dumps. `-Name` anywhere was an unconditional escape
#      hatch, so `Get-Variable -Name *` — a full dump — passed. So did the `gv`
#      alias, which the pattern never named.
#
# The posture question this raises is whether narrowing (1) costs protection:
# the `Variable:` drive holds arbitrary shell variables, so a laundered secret
# (`$k = $env:ANTHROPIC_API_KEY; Get-Variable k`) is invisible to the name-based
# CRED_VAR_READ screen. The answer is that the breadth was never buying that
# protection: `Get-Variable -Name k` — the same read, more idiomatically spelled
# — was already allowed. It caught laundering only when the caller happened to
# use positional syntax. Variable-laundering is the copy-launder shape
# (`cp secret x; cat x`) that posture.md already bounds OUT of scope for exactly
# this reason, so this makes an existing boundary consistent rather than moving
# it. See security/README.md, "`Get-Variable`: naming one variable is a read".
#
# The rule is now the natural one: a dump is an invocation that names no
# specific variable, or names a wildcard.
_GET_VARIABLE = re.compile(r"(?:^|[\s;(])(?:Get-Variable|gv)(?![\w-])",
                           re.IGNORECASE)
# Flags whose next token is the flag's own value, not a variable name.
_GV_VALUE_FLAGS = {
    "-scope", "-erroraction", "-errorvariable", "-warningaction",
    "-warningvariable", "-informationaction", "-informationvariable",
    "-outvariable", "-outbuffer", "-pipelinevariable",
}
# Flags whose value IS the variable name (or a pattern for it).
_GV_NAME_FLAGS = {"-name", "-include", "-exclude"}


def _is_wildcard_name(token):
    """A variable name that globs — `*`, `AWS_*`, `-Name '*'` — enumerates many
    variables, so it is a dump however it was spelled."""
    name = token.strip().strip("'\"")
    return not name or "*" in name or "?" in name


def _get_variable_is_dump(seg):
    """True if a `Get-Variable` in `seg` prints every variable rather than a
    named one. Walks the tokens after the cmdlet: the first token that is a
    variable name (positional, or the value of -Name/-Include/-Exclude) decides
    it; switches and flag values are skipped. No name at all = full dump."""
    m = _GET_VARIABLE.search(seg)
    if not m:
        return False
    toks = seg[m.end():].split()
    i = 0
    while i < len(toks):
        tok = toks[i]
        low = tok.lower()
        if low in _GV_NAME_FLAGS:
            # `-Name` with nothing after it is a malformed dump, not a read.
            return i + 1 >= len(toks) or _is_wildcard_name(toks[i + 1])
        if low in _GV_VALUE_FLAGS:
            i += 2                           # flag consumes its value
            continue
        if tok.startswith("-"):
            i += 1                           # a switch (-ValueOnly, -Force)
            continue
        return _is_wildcard_name(tok)        # first positional = the name
    return True                              # nothing named = every variable

# A CLI subcommand that prints a registered server's stored env (incl. secrets)
# by design — pure command-shape, no file/path involved (the 07-03 addendum).
MCP_GET_PATTERN = re.compile(r"\bclaude\s+mcp\s+get\b", re.IGNORECASE)

# Credential-shaped environment variable names (the 07-02 founding shape).
_CRED_VAR = (
    r"\w*(?:API[_-]?KEY|SECRET[_-]?KEY|ACCESS[_-]?KEY|PRIVATE[_-]?KEY"
    r"|SECRET_ACCESS_KEY|_KEY|_TOKEN|_SECRET|PASSWORD|PASSWD|_PAT"
    r"|ANTHROPIC_API_KEY|GITHUB_PERSONAL_ACCESS_TOKEN|GH_TOKEN|GITHUB_TOKEN"
    r"|OPENAI_API_KEY|AWS_SECRET_ACCESS_KEY)\w*"
)
CRED_VAR_READ = re.compile(
    # printenv NAME
    r"\bprintenv\s+" + _CRED_VAR
    # echo/print $NAME, ${NAME}, $env:NAME
    + r"|(?:echo|printf|print|write-host|write-output)\b[^\n]*"
    + r"\$(?:\{)?(?:env:)?" + _CRED_VAR
    # [Environment]::GetEnvironmentVariable("NAME"...) and the PSVariable
    # GetValue("env:NAME") form (red-team round 2, M2).
    + r"|GetEnvironmentVariable\(\s*['\"]?" + _CRED_VAR
    + r"|GetValue\(\s*['\"]?env:" + _CRED_VAR
    # a bare `$env:NAME` that stands alone, or a double-quoted string that leads
    # with it (both emit the value in PowerShell) — round 2, M1. NOT a cast/test
    # like `[bool]$env:NAME`, which is the recommended existence check.
    + r"|^\s*\$env:" + _CRED_VAR + r"\s*$"
    + r"|^\s*\"[^\"\n]*\$(?:\{)?env:" + _CRED_VAR
    # PowerShell single-var reads: Get-Item / Get-Content / gi / gc Env:NAME
    # (the dump forms need `*`; a single named read printed the value) — M1.
    # The LISTING cmdlets belong here too: `Get-ChildItem Env:GITHUB_TOKEN` and
    # `ls Env:GH_TOKEN` print one variable's value, and until 2026-07-26 they
    # were caught only incidentally, by the over-broad env-dump pattern that the
    # `$env:`-as-a-path false positive forced us to tighten (_PS_ENV_DRIVE).
    # Without this line that tightening would have opened a real hole.
    + r"|(?:Get-Item|Get-Content|Get-ChildItem|gi|gc|gci|dir|ls)\s+"
    + r"(?:-\w+\s+)*(?:Env|Variable):\\?" + _CRED_VAR
    # herestring feeding a credential var to a command's stdin — round 1, M2.
    + r"|<<<\s*['\"]?\$(?:\{)?(?:env:)?" + _CRED_VAR,
    re.IGNORECASE,
)


# --- Prose arguments vs. path positions ------------------------------------
# 2026-07-18 false positive: `gh pr create --title "chore: add .env to
# .gitignore" --body "..."` was blocked. Nothing there reads a file — `.env` is
# prose inside a message flag. v2 knew exactly one prose carrier (`git commit
# -m`, handled by the _GIT_SAFE_SUB allowlist), so every other tool taking a
# message flag inherited the default-deny.
#
# The distinction the guard can draw safely is POSITIONAL: the value of an
# explicitly prose-bearing flag is a message, not a path. Three limits keep this
# from becoming the permissive regex that would undo the posture:
#
#   1. Flag names are an exact allowlist, anchored with (?![\w-]) so `--body`
#      does NOT match `--body-file` / `--notes-file`. The *-file and -F forms
#      really do read the named file (posting .env into a PR body is exfil), so
#      they keep default-deny — same reasoning as the git -F case in round 5.
#   2. Only a QUOTED value is exempt. An unquoted `--body /home/user/.env` sits
#      in an ordinary argument position and is indistinguishable from a path.
#   3. A quoted value containing `$` or a backtick is NOT exempt — it can expand
#      a secret or substitute a reader into the argument. Those keep flowing to
#      the normal checks, so `--body "$(cat ~/.env)"` still blocks while
#      `--body "$(cat notes.md)"` still passes.
_PROSE_FLAG = (
    r"--(?:message|title|body|description|desc|notes?|comment|summary"
    r"|subject|reason|caption)(?![\w-])"
    r"|(?<![\w-])-m(?![\w-])"
)
# Flag, optional `=`, then a single- or double-quoted value (double-quoted form
# tolerates backslash escapes, matching _split_segments' escape handling).
_PROSE_FLAG_VALUE = re.compile(
    r"(?:" + _PROSE_FLAG + r")\s*=?\s*"
    r"(\"[^\"\\]*(?:\\.[^\"\\]*)*\"|'[^']*')",
    re.IGNORECASE,
)
_EXPANDABLE = re.compile(r"[$`]")

# 2026-08-09 false positive: a PR body written in Markdown is mostly backticks,
# and limit 3 above voids the prose exemption on any `$` or backtick. So
# `gh pr create --body '... `~/.claude/settings.json` ...'` was blocked as a
# credential read, though a single-quoted value cannot read anything: in POSIX
# shells AND in PowerShell, `$` and backtick inside '...' are literal. The
# author's only route was `--body-file`, i.e. routing around the guard — the
# failure mode posture.md names as the reason a guard must not block prose.
#
# The exemption is for SINGLE quotes only, and only when the value is not
# itself sitting inside a double-quoted region. That second half is the whole
# subtlety: in `bash -c "gh pr create --body '$(cat ~/.env)'"` the OUTER double
# quotes expand before the inner single quotes are ever interpreted, so the
# secret is substituted and the value is not literal at all. Measured: all
# three nested shapes stay blocked because of this check.
def _inside_double_quotes(text, index):
    """True if `index` falls inside an unescaped double-quoted region."""
    in_dq = False
    i = 0
    while i < index and i < len(text):
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == '"':
            in_dq = not in_dq
        i += 1
    return in_dq


def _is_literal_quoted(seg, start, value):
    """True if `value` at `start` in `seg` cannot expand anything.

    Conservative by construction: anything that is not a plainly single-quoted,
    non-nested value falls through to the existing expandable check.
    """
    return value[:1] == "'" and not _inside_double_quotes(seg, start)

# A credential-shaped var interpolated INTO a prose value publishes the secret
# (a PR body is a public surface). CRED_VAR_READ only recognises the echo family
# before a `$VAR`, so this shape was silently allowed before 2026-07-18; found
# by the regression test written for the false positive above.
PROSE_FLAG_CRED_VAR = re.compile(
    r"(?:" + _PROSE_FLAG + r")\s*=?\s*(['\"])[^'\"]*"
    r"\$(?:\{)?(?:env:)?" + _CRED_VAR,
    re.IGNORECASE,
)


def _prose_flag_publishes_cred_var(seg):
    """True if a message flag interpolates a credential var into its value.

    A non-nested single-quoted value is skipped: it publishes the literal text
    `$ANTHROPIC_API_KEY`, not the key. Same reasoning as `_is_literal_quoted`,
    and the nested case still counts because the outer quotes expand first.
    """
    for m in PROSE_FLAG_CRED_VAR.finditer(seg):
        if _is_literal_quoted(seg, m.start(), m.group(1)):
            continue
        return True
    return False


def _strip_prose_flag_values(seg):
    """Blank out the quoted value of prose-bearing flags so a credential-store
    NAME mentioned in a message isn't read as a path position. Leaves the flag
    itself, and leaves any value that could expand ($ / backtick), in place."""
    def _blank(m):
        value = m.group(1)
        if not _is_literal_quoted(seg, m.start(), value) and _EXPANDABLE.search(value):
            return m.group(0)
        return m.group(0).replace(value, '""')
    return _PROSE_FLAG_VALUE.sub(_blank, seg)


# --- Bash/PowerShell command classification --------------------------------

# Leading commands that may name a sensitive path WITHOUT reading its content
# to stdout: existence/metadata checks, pure file management (delete/move/perm),
# navigation, string/echo, and version control. Everything else that names a
# sensitive path is treated as a read and blocked (default-deny).
SAFE_COMMANDS = {
    # existence / metadata (emit a name, size, or hash — never the content)
    "ls", "dir", "ll", "la", "vdir", "stat", "file", "test", "[", "[[",
    "du", "df", "wc", "readlink", "realpath", "basename", "dirname", "tree",
    "md5sum", "sha1sum", "sha256sum", "sha512sum", "shasum", "cksum", "b2sum",
    "get-filehash",
    # navigation / no-op / string
    "cd", "pushd", "popd", ":", "true", "false", "echo", "printf", "print",
    # file management (no file content to stdout)
    "rm", "unlink", "rmdir", "mkdir", "touch", "chmod", "chown", "chgrp",
    "truncate", "mv", "cp", "ln", "install", "mktemp", "shred",
    # NB: `git` is NOT here — it reads from the object store and via `-f`/`-c`
    # (git show / cat-file / grep / diff / config -f / -c core.pager=cat), so it
    # is classified per-subcommand in _reads_sensitive_path, not trusted wholesale.
    # PowerShell metadata / file-management cmdlets
    "test-path", "get-item", "get-childitem", "resolve-path", "split-path",
    "remove-item", "new-item", "move-item", "copy-item", "rename-item",
    "get-location", "set-location", "get-acl",
}

# Commands that MODIFY a named file and print none of its prior content. They
# are NOT in SAFE_COMMANDS and must never be moved there: they are unknown to
# _reads_sensitive_path, so they default-deny, and that is the intended verdict
# (clobbering a credential store is the outcome the default-deny exists for).
# This set decides WORDING ONLY — which of _MSG_PATH / _MSG_PATH_WRITE the
# block carries. A wrong entry therefore mis-describes a block; it can never
# create or remove one. test_write_only_commands_still_block pins both halves
# so a stale entry fails the suite rather than the next audit
# (conventions/allowlists-fail-both-ways.md).
_WRITE_ONLY_COMMANDS = {
    "set-content", "add-content", "clear-content", "out-file",
    "set-itemproperty", "new-itemproperty", "clear-itemproperty",
}

# grep-family: a read (prints matched lines) UNLESS in an existence/count mode,
# which is exactly the safe alternative this guard recommends.
GREP_FAMILY = {"grep", "egrep", "fgrep", "rg", "ag", "ripgrep", "select-string"}
GREP_SAFE_FLAG = re.compile(
    r"(?<!\w)-{1,2}(l|L|c|q|files-with-matches|files-without-match"
    r"|count|quiet)\b"
)

# Prefixes that wrap a command without changing what it does.
_WRAPPERS = {"sudo", "command", "time", "nice", "nohup", "exec", "builtin",
             "\\", "then", "do", "else", "elif"}

# --- Nested command units (v2.3) -------------------------------------------
# 2026-07-26 false positive: `"ed25519: $(Test-Path $HOME\.ssh\id_ed25519.pub)"`
# was blocked with a message recommending Test-Path. Both halves of that
# contradiction were real bugs. The `.pub` half is fixed by PUBLIC_KEY above;
# this is the other half.
#
# v2 classified a segment by its LEADING command only, and treated the mere
# PRESENCE of `$(` as disqualifying. So the metadata exemption was positional:
# `Test-Path ~/.ssh/id_rsa` reached it, but `"$(Test-Path ~/.ssh/id_rsa)"` and
# `if (Test-Path ~/.ssh/id_rsa)` did not — the leading token was a quoted string
# or `if`, neither of which is a safe command, so both fell to default-deny.
#
# v2.3 classifies every nested command unit on its own terms instead: each
# substitution / group body is recursively classified, and the outer command is
# then judged with those bodies blanked out. A metadata-only operation is
# therefore permitted wherever it appears, while a content read anywhere inside
# still denies the whole segment.
#
# The property that keeps this from becoming a laundering hole: blanking a unit
# must not hide a path from a reader that RECEIVES it. `cat $(echo ~/.ssh/id_rsa)`
# has no literal path in its outer text, but `echo` emits the path for `cat` to
# read. So a cleared unit only stops the outer command from being scrutinised
# when its output is a bare value — a boolean or a status — rather than the path
# text itself (_VALUE_ONLY below).


def _balanced(seg, start):
    """Scan from `start` (just past an opening paren) to its match. Returns
    (index after the closing paren, body). An unbalanced group — which happens
    because _split_segments cuts on `|`/`&` without regard for parens — runs to
    end of segment, the conservative direction (more text gets classified)."""
    depth, j, n = 1, start, len(seg)
    while j < n and depth:
        if seg[j] == "(":
            depth += 1
        elif seg[j] == ")":
            depth -= 1
        j += 1
    return j, (seg[start:j - 1] if depth == 0 else seg[start:])


def _sub_units(seg):
    """(start, end, body) for each command unit nested in `seg`.

    `$( )`, `<( )` and backticks are recognised inside double quotes as well as
    outside, because both shells expand them there — that is exactly the
    reported shape. A bare `( )` group is a unit only OUTSIDE quotes: a paren
    inside a quoted string is literal text, and diving into it would tear
    `python3 -c "print(open('~/.claude.json').read())"` apart into fragments
    that individually look harmless."""
    units, i, n, quote = [], 0, len(seg), None
    while i < n:
        c = seg[i]
        if c == "\\" and quote != "'" and i + 1 < n:
            i += 2                      # escaped char, same rule as the splitter
            continue
        if quote:
            if c == quote:
                quote = None
                i += 1
                continue
            if quote == "'":
                i += 1                  # single quotes suppress all expansion
                continue
            # inside "..." — fall through; $( and ` still expand
        elif c in ("'", '"'):
            quote = c
            i += 1
            continue
        if seg.startswith("$(", i) or seg.startswith("<(", i):
            j, body = _balanced(seg, i + 2)
            units.append((i, j, body))
            i = j
        elif c == "`":
            j = seg.find("`", i + 1)
            end = n if j == -1 else j + 1
            units.append((i, end, seg[i + 1:n if j == -1 else j]))
            i = end
        elif c == "(" and not quote:
            j, body = _balanced(seg, i + 1)
            units.append((i, j, body))
            i = j
        else:
            i += 1
    return units


def _nested_command_units(seg, _depth=0):
    """Every nested unit body in `seg`, recursively, re-split into segments.

    Used by the COMMAND-SHAPE rules, which the path rules don't need: several of
    them are anchored to a whole segment (`^\\s*env\\s*$`, `^\\s*printenv\\s*$`,
    `^\\s*set\\s*$`), and that anchoring is load-bearing — it is the only reason
    `.venv/bin`, `--env-file`, `conda env list` and `/usr/bin/env` don't match.
    But main() only ever handed those rules the top-level segment, so a dump one
    container down never got the anchor's attention: `echo $(env)` and `"$(env)"`
    ran a full environment dump while a bare `env` was blocked (gap predating
    v2.2/v2.3, confirmed against the pre-2.2 baseline).

    The fix is not to loosen the anchor — that would resurrect the false
    positives it exists to prevent — but to offer each unit body to it as a
    segment in its own right, which is what it is. Bodies are re-split because a
    body is a command LIST (`$(cd x; env)`), the same reason
    _reads_sensitive_path re-splits them."""
    out = []
    if _depth >= 8:
        return out
    for _, _, body in _sub_units(seg):
        for part in _split_segments(body):
            part = part.strip()
            if not part:
                continue
            out.append(part)
            out.extend(_nested_command_units(part, _depth + 1))
    return out


def _blank_units(seg, units):
    """`seg` with every nested unit removed, leaving the outer command alone."""
    for start, end, _ in reversed(units):
        seg = seg[:start] + seg[end:]
    return seg


# Sub-unit commands whose output is a bare VALUE — a boolean or an exit status,
# never the path text and never the file content. Only these let a cleared unit
# stop the enclosing command from being scrutinised. Everything else (`ls`,
# `echo`, `realpath`, or a unit that is just a quoted path) is assumed to hand
# the path onward, so `cat $(echo ~/.ssh/id_rsa)` and
# `[IO.File]::ReadAllText("$HOME/.claude.json")` still reach default-deny.
_VALUE_ONLY = {"test-path", "test", "[", "[[", "true", "false", ":"}

# An outer that is nothing but one quoted string runs no reader: PowerShell
# emits the literal, and a shell can only fail to exec it. This is what makes
# `"ed25519: $(Test-Path ...)"` inert once its substitution has been cleared.
_WHOLLY_QUOTED = re.compile(
    r"""^\s*(?:'[^']*'|"[^"\\]*(?:\\.[^"\\]*)*")\s*$"""
)

# git subcommands that never print file/object content (they only NAME paths,
# e.g. in a `-m` message) vs. those that do. A git segment naming a sensitive
# path is a read unless its subcommand is benign and it carries no
# content-forcing flag (-p/--patch/-G/-S), config injection (-c), pager
# override, or command substitution.
_GIT_SAFE_SUB = {
    "add", "commit", "status", "push", "pull", "fetch", "clone", "checkout",
    "switch", "branch", "tag", "stash", "init", "remote", "reset", "restore",
    "mv", "rm", "merge", "rebase", "cherry-pick", "revert", "describe",
    "rev-parse", "notes", "log",
}
_GIT_READ_SUB = {
    "show", "cat-file", "grep", "diff", "blame", "annotate", "config", "var",
    "whatchanged", "ls-tree", "ls-files",
}
_GIT_DANGER_FLAG = re.compile(
    # `git -c key=val` (config injection) — anchored to the git-global position
    # so the `commit -c <commit>` reuse-message subcommand option isn't
    # conflated with it (red-team round 6, LOW false positive).
    r"\bgit\s+-c\s|--to-|core\.pager|(?<!\w)-p\b|--patch\b|(?<!\w)-[GS]\b"
    # -F/--file reads the named file as the message (unlike -m prose), so a
    # sensitive -F arg is a real content read (red-team round 5, #2).
    r"|(?<!\w)-F\b|--file(=|\b)"
)
# Message-bearing git subcommands: their arg is prose, so the env-dump /
# credential-var / mcp-get checks (which would false-positive on a commit
# message discussing those forms) are skipped for these — and ONLY these, so a
# `git -c alias.x='!printenv KEY' x` alias-exec is still checked (round 4, #2).
_GIT_MSG_CMD = re.compile(r"^\s*git\s+(commit|tag|stash|notes)\b", re.IGNORECASE)
# A git `-c <key>=!<cmd>` sets a shell-escape alias — arbitrary code execution
# (hence arbitrary secret exfil) config-injected into one invocation. It's the
# same arbitrary-exec class as $(...) / `bash x.sh`, but since it wears a `git`
# disguise the message-command skip would wave the env/var checks through, so
# block the form itself (red-team round 4, #2).
_GIT_ALIAS_EXEC = re.compile(r"\bgit\b.*?-c\s+[\w.]+=\s*['\"]?!")


def _git_subcommand(seg):
    """The git subcommand, skipping global flags (`-c name=val`, `-C dir`)."""
    toks = seg.strip().split()
    i = 1  # toks[0] is the normalized `git`
    while i < len(toks):
        t = toks[i]
        if t in ("-c", "-C", "--exec-path", "--git-dir", "--work-tree"):
            i += 2
            continue
        if t.startswith("-"):
            i += 1
            continue
        return t.lower()
    return ""


def _split_segments(command):
    """Split a command into pipeline/list segments on shell operators
    (`&&`, `||`, `|`, `;`, `&`, newline) but NOT inside quotes — a `&` or `|`
    within a "..." commit message must not create a spurious segment
    (red-team round 4, #3) — and NOT inside parentheses.

    The paren rule (v2.5) keeps a substitution intact. Cutting through one left
    FRAGMENTS, and a fragment defeats the whole-segment anchors the command-shape
    rules rely on: `echo $(cd /tmp; env)` used to split into `echo $(cd /tmp` and
    `env)`, and `^\\s*env\\s*$` cannot match `env)` because of the orphaned paren.
    Nested units are re-split from their bodies anyway (_nested_command_units,
    _reads_sensitive_path), so holding the substitution together here loses no
    coverage and gains the anchor.

    An unbalanced `(` therefore stops splitting for the rest of the command. That
    is safe rather than blinding: the trailing text still lands inside a unit
    body via _sub_units, whose _balanced() runs an unterminated group to end of
    segment, and both callers re-split what they find there."""
    return [seg for seg, _ in _scan_segments(command)]


def _scan_segments(command):
    """_split_segments' scanner, returning (segment, following separator) pairs
    (the last segment's separator is ""). The separator is discarded by
    _split_segments and needed by _pipelines, which cares about `|`
    specifically: a pipeline's stages share a data flow that `;`-separated
    commands do not."""
    segs, buf, quote, depth, i, n = [], [], None, 0, 0, len(command)
    while i < n:
        c = command[i]
        # A backslash escapes the next char outside single quotes, so `\"`
        # inside a "..." string is a literal quote, not a close — tracking it as
        # a close swallowed the following `; cat .env` into a phantom quoted span
        # (red-team round 5, #1). Consume the escaped pair verbatim.
        if c == "\\" and quote != "'" and i + 1 < n:
            buf.append(c)
            buf.append(command[i + 1])
            i += 2
        elif quote:
            buf.append(c)
            if c == quote:
                quote = None
            i += 1
        elif c in ("'", '"'):
            quote = c
            buf.append(c)
            i += 1
        elif c == "(":
            depth += 1
            buf.append(c)
            i += 1
        elif c == ")":
            depth = max(0, depth - 1)
            buf.append(c)
            i += 1
        elif depth:                        # inside ( ... ): not a separator
            buf.append(c)
            i += 1
        elif command[i:i + 2] in ("&&", "||"):
            segs.append(("".join(buf), command[i:i + 2])); buf = []; i += 2
        elif c in (";", "\n", "|", "&"):
            segs.append(("".join(buf), c)); buf = []; i += 1
        else:
            buf.append(c)
            i += 1
    segs.append(("".join(buf), ""))
    return segs


def _pipelines(command):
    """Runs of segments joined by `|`, as lists of stages. Every segment lands
    in exactly one run, so a command with no pipe yields single-stage runs."""
    out, cur = [], []
    for seg, sep in _scan_segments(command):
        cur.append(seg)
        if sep != "|":
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


# --- Value bindings and control-flow headers (v2.6) ------------------------
# 2026-07-31 false-positive class (agent-ops#14): a segment that BINDS a
# sensitive path to a variable, or names it in a loop header, was default-denied
# even when every operation actually applied to it is on SAFE_COMMANDS. The
# inline form passed and the identical operation via a variable blocked:
#
#     Remove-Item '~/.claude/settings.json.bak' -Force          # ALLOWED
#     $f = '~/.claude/settings.json.bak'; Remove-Item $f -Force # BLOCKED
#
# _leading_command skipped the *bash* `VAR=val` prefix but not PowerShell's
# `$var = ...` (leading `$`, and with spaces the `=` is its own token), so `lead`
# came back as `$f` / `foreach($f` — not a known command — and fell to
# default-deny. Case D was the sharpest: the block message recommends Test-Path,
# and then blocked Test-Path for sitting in a foreach header.
#
# The block was not buying coverage there. It is lexical, so the workaround is
# just "don't write the literal" (`Get-ChildItem -Filter '*.bak'` then delete
# `$_.FullName` removes the same file and passes). What it did buy was the
# reflex of reaching for MASK-OK on a non-read, which is the failure mode the
# posture cares about most.
#
# Two rules, and they only work together:
#
#   1. A binding is not a read. `$f = <pure literal>` and `foreach ($f in
#      <pure literal>)` run no command at all, so they are inert. "Pure literal"
#      is deliberately narrow (_is_literal_value): a quoted string, a bare path
#      token, or an array literal of those, and NOTHING that can execute — no
#      `$(`, no backtick, no `@(`-nested call. `$x = "$(cat ~/.env)"` therefore
#      is NOT a binding and keeps blocking on its nested reader.
#   2. The association must survive. Allowing the binding while ignoring what
#      the body does with it would be a straight hole, so the bound literal is
#      SUBSTITUTED back into every other segment before classification
#      (_collect_bindings / _apply_bindings). `foreach ($f in @('~/.env')) {
#      Get-Content $f }` is judged as `Get-Content @('~/.env')` and blocks; the
#      same loop with `Remove-Item` is judged as `Remove-Item @('~/.env')` and
#      passes, which is the whole point.
#
# Substitution is run to a FIXPOINT so a re-binding chain can't launder the path
# one hop at a time (`$a = '~/.env'; $b = $a; Get-Content $b`) — that shape is
# adjacent to the copy-launder class posture.md bounds out of scope, but it is
# cheap to hold here and this change is what would have opened it.
#
# NOTE (conservative call): this does NOT make the guard a dataflow analyser.
# Anything whose right-hand side is not a pure literal stays default-denied
# rather than being resolved — `$f = @{p='~/.env'}`, `$a = $b = '~/.env'`,
# backtick line-continuation across segments. Those keep their pre-2.6
# behaviour or block; none of them is newly allowed.

# An optional index suffix on an assignment target (`$f[0] = ...`).
_INDEX = r"\[[^\]]*\]"
# `$f = `, `${f} = `, `$global:f = `, `$f[0] = ` — the assignment PREFIX only.
_PS_ASSIGN_PREFIX = re.compile(
    r"^\s*\$\{?([A-Za-z_][\w:.]*)\}?(?:" + _INDEX + r")?\s*=\s*"
)
# Anything that can RUN something inside a value. `@(` is included because an
# array subexpression can hold a call; a literal array is handled explicitly
# before this is consulted.
_EXECUTES = re.compile(r"\$\(|`|@\(")
# A bare (unquoted) value token: one word, no quoting or shell metacharacters.
_BARE_VALUE = re.compile(r"^[^\s'\"();|&{}]+$")
_CONTROL_KW = re.compile(
    r"^\s*(?:foreach|for|while|if|elseif|switch)\s*\(", re.IGNORECASE)
# `foreach ($f in <value>)` — the enumerator half of a loop header.
_FOREACH_IN = re.compile(
    r"^\s*\$\{?([A-Za-z_][\w:.]*)\}?\s+in\s+(.*)$", re.IGNORECASE | re.DOTALL)
# PowerShell scope prefixes: `$global:f` and `$f` name the SAME variable, so a
# binding is stored under the scope-STRIPPED name and every REFERENCE is matched
# with the prefix optional. Fixing only one direction leaves the other open:
# `$global:f = '~/.env'; Get-Content $f` needs the store side, and
# `$f = '~/.env'; Get-Content $global:f` needs the reference side.
# `env:` is deliberately NOT in this list — `$env:f` is a different namespace,
# not another spelling of `$f`.
_SCOPE_PREFIX = re.compile(r"^(?:global|script|local|private|using):",
                           re.IGNORECASE)
_SCOPE_ALT = r"(?:global:|script:|local:|private:|using:)?"


def _var_ref(name):
    """Regex matching every spelling of a reference to `name` — bare, braced,
    and scope-qualified."""
    return r"\$\{?" + _SCOPE_ALT + re.escape(name) + r"\}?(?![\w:])"


def _substitute(text, name, value):
    """Replace every reference to `name` in `text` with the literal `value`.
    Non-recursive by construction (`re.sub` never rescans a replacement), so a
    self-referential binding cannot loop."""
    return re.sub(_var_ref(name), lambda _m, v=value: v, text,
                  flags=re.IGNORECASE)


def _split_commas(text):
    """Top-level comma split, respecting quotes and nesting."""
    out, buf, quote, depth = [], [], None, 0
    for c in text:
        if quote:
            if c == quote:
                quote = None
        elif c in ("'", '"'):
            quote = c
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth = max(0, depth - 1)
        elif c == "," and not depth:
            out.append("".join(buf))
            buf = []
            continue
        buf.append(c)
    out.append("".join(buf))
    return out


def _is_literal_value(v, _depth=0):
    """True if `v` is a pure PowerShell VALUE and runs nothing: a quoted string,
    a bare path token, or an array literal of those. Deliberately narrow — the
    whole safety of the binding rule rests on this returning False for anything
    that could execute."""
    v = v.strip().rstrip(";").strip()
    if not v or _depth >= 4:
        return False
    parts = [p for p in _split_commas(v) if p.strip()]
    if len(parts) > 1:                      # bare array literal: 'a','b'
        return all(_is_literal_value(p, _depth + 1) for p in parts)
    if v.startswith("@(") or v.startswith("("):
        end, inner = _balanced(v, v.index("(") + 1)
        if v[end:].strip():                 # trailing text after the array
            return False
        parts = [p for p in _split_commas(inner) if p.strip()]
        return bool(parts) and all(_is_literal_value(p, _depth + 1)
                                   for p in parts)
    if _EXECUTES.search(v):
        return False                        # `$(...)`, backtick, `@(`-call
    if v[0] in "'\"":
        return bool(_WHOLLY_QUOTED.match(v))
    return bool(_BARE_VALUE.match(v))


def _is_literal_list(v):
    """A comma-separated list of pure literals — an array's ELEMENT list, which
    is data rather than a command.

    Reached because an array literal is a paren group, so `@('~/.env','~/.aws/
    credentials')` gets its body offered up as a segment in its own right:
    `'~/.env','~/.aws/credentials'`. A single quoted element already fell out as
    _WHOLLY_QUOTED; two or more did not, and were classified on a "leading
    command" of `'~/.env','~/.aws/credentials'` — an unknown command, so
    default-deny. That is what made a two-file cleanup loop block while the
    one-file version passed."""
    parts = [p for p in _split_commas(v) if p.strip()]
    return len(parts) > 1 and all(_is_literal_value(p) for p in parts)


def _is_literal_data(v):
    """`v` is a VALUE expression rather than a command: a quoted string, an
    array literal, or a comma list of those.

    This is _is_literal_value MINUS its bare-token branch, and the omission is
    the point: a bare word sitting in command position IS a command, so only
    the forms that are unambiguously data qualify. `'~/.env'` already fell out
    as _WHOLLY_QUOTED; `@('~/.env')` and `'~/.env','~/.aws/credentials'` did
    not, and were judged on leading "commands" of `@` and `'~/.env',...`. Array
    literals reach this as segments in their own right because an array is a
    paren group, so its body gets re-split and offered up — which is how a
    nested `foreach ($g in @($f))` ended up denied on the `@`."""
    v = v.strip().rstrip(";").strip()
    if not v:
        return False
    if not (v[0] in "'\"" or v.startswith("@(") or v.startswith("(")
            or _is_literal_list(v)):
        return False
    return _is_literal_value(v)


def _control_flow_split(seg):
    """(header, body, hstart) for `foreach (...) {...}` / `if (...) {...}` /
    `while (...)`, else None. The header is the parenthesised enumerator or
    condition, `hstart` its offset in `seg`, and the body everything after the
    closing paren.

    `hstart` is returned so a caller can rebuild the segment verbatim around an
    edited header — reconstructing it by length arithmetic silently drops the
    closing paren when the group is unbalanced, which mangles the very shape
    this exists to read.

    Splitting header from body is what lets a benign header carry a sensitive
    path without condemning the segment — but the caller MUST classify the body
    too, and against the path the header bound, or the split becomes the hole."""
    m = _CONTROL_KW.match(seg)
    if not m:
        return None
    open_idx = m.end() - 1                   # the `(` the pattern ended on
    end, header = _balanced(seg, open_idx + 1)
    return header, seg[end:], open_idx + 1


def _strip_block_braces(text):
    """Drop a `{ ... }` wrapper from a loop/conditional body."""
    text = text.strip()
    if text.startswith("{"):
        text = text[1:]
        if text.rstrip().endswith("}"):
            text = text.rstrip()[:-1]
    return text


def _binding_name(var):
    """The key a binding is stored under: lowercased and scope-stripped, so
    `$global:f` and `$f` resolve to the same entry."""
    return _SCOPE_PREFIX.sub("", var.lower())


def _ps_binding(seg):
    """(var, literal_value, tail) if `seg` OPENS with a pure value binding.

    Two shapes: an assignment `$f = <literal>` (tail empty — the value is the
    rest of the segment) and a `foreach ($f in <literal>)` header (tail is the
    loop body). None if the right-hand side runs anything at all, which is what
    keeps `$x = "$(cat ~/.env)"` and `$x = Get-Content ~/.env` out."""
    cf = _control_flow_split(seg)
    if cf is not None:
        header, tail, _ = cf
        fm = _FOREACH_IN.match(header)
        if fm and _is_literal_value(fm.group(2)):
            return fm.group(1), fm.group(2).strip(), tail
        return None
    m = _PS_ASSIGN_PREFIX.match(seg)
    if m and _is_literal_value(seg[m.end():]):
        return m.group(1), seg[m.end():].strip().rstrip(";").strip(), ""
    return None


def _apply_bindings(seg, bindings):
    """Substitute every variable known to hold a sensitive literal with that
    literal, so a read reached THROUGH the variable is judged against the real
    path.

    The binding's own DECLARATION position is left alone — `$f` on the left of
    an `=`, and the `$f in` of a loop header, are inert text, and rewriting them
    would both destroy the shape _ps_binding needs to recognise and inject a
    bare path literal into a command position that never had one."""
    if not bindings:
        return seg
    cf = _control_flow_split(seg)
    if cf is not None:
        header, body, hstart = cf
        fm = _FOREACH_IN.match(header)
        split = fm.start(2) if fm else 0      # keep `$f in ` verbatim
        edited = header[:split] + _apply_all(header[split:], bindings)
        # seg[hstart + len(header):] begins at the closing paren (or is empty
        # for an unbalanced group), so this rebuilds the segment exactly.
        close = seg[hstart + len(header):len(seg) - len(body)]
        return (seg[:hstart] + edited + close
                + _apply_all(body, bindings))
    m = _PS_ASSIGN_PREFIX.match(seg)
    if m:
        return seg[:m.end()] + _apply_all(seg[m.end():], bindings)
    return _apply_all(seg, bindings)


def _apply_all(text, bindings):
    for name, value in bindings.items():
        text = _substitute(text, name, value)
    return text


def _collect_bindings(segments):
    """Variables bound to a SENSITIVE literal anywhere in the command, resolved
    to a fixpoint so a re-binding chain (`$a = '~/.env'; $b = $a; cat $b`)
    cannot launder the path one hop at a time."""
    bindings = {}
    for _ in range(8):
        changed = False
        for seg in segments:
            b = _ps_binding(_apply_bindings(seg.strip(), bindings))
            if b is None or not _has_sensitive_path(b[1]):
                continue
            name = _binding_name(b[0])
            if bindings.get(name) != b[1]:
                bindings[name] = b[1]
                changed = True
        if not changed:
            break
    return bindings


def _leading_command(seg):
    """The first real command token in a segment, minus wrappers and VAR=val.

    A PowerShell assignment prefix is stripped like bash's `VAR=val`, so the
    lead resolves from the RIGHT-HAND SIDE: `$h = Get-FileHash x` leads with
    `get-filehash` (safe) and `$x = Get-Content ~/.env` leads with `get-content`
    (a read) instead of both coming back as `$h`/`$x` and default-denying."""
    seg = _PS_ASSIGN_PREFIX.sub("", seg.strip().lstrip("(").strip(), count=1)
    toks = seg.strip().split()
    i = 0
    while i < len(toks):
        t = toks[i]
        if t in _WRAPPERS or re.match(r"^[A-Za-z_]\w*=", t):
            i += 1
            continue
        break
    if i >= len(toks):
        return ""
    return toks[i].split("/")[-1].split("\\")[-1].lower()


def _strip_heredocs(command):
    """Drop heredoc *bodies* so prose written into a file isn't scanned as
    commands (the `cat > notes <<EOF ... .env ... EOF` false-positive class).
    The line carrying the `<<` is kept — that one is a real command."""
    out, delim = [], None
    for line in command.split("\n"):
        if delim is None:
            out.append(line)
            m = re.search(r"<<-?\s*['\"]?([A-Za-z_]\w*)['\"]?", line)
            if m:
                delim = m.group(1)
        elif line.strip() == delim:
            delim = None
    return "\n".join(out)


# tar extracting to stdout (`-O`/`--to-stdout`, incl. the clustered old-style
# `xfO`/`xOf`/`xzfO` form, red-team round 2 H2) or writing the archive to stdout
# (a bare `-`) surfaces the bytes directly, so it is a READ and gets the read
# message. Writing to an archive FILE used to be exempt here, on the reasoning
# that it "emits no secret content to the caller (like `cp`)" — which is the
# copy-launder ruling, and v2.9 overturned it. That case is now caught upstream
# by _copy_launders_credential (`tar` is in _ARCHIVE_OR_BULK), so this pattern
# is left judging only the stdout forms, which is all it was ever about.
_TAR_TO_STDOUT = re.compile(
    r"--to-stdout\b"
    r"|--to-command\b"                        # runs a reader per member (round 3)
    r"|(?<![\w-])-O\b"
    r"|(?<!\S)-(?=\s|$)"
    r"|\btar\s+-?[a-zA-Z]*O[a-zA-Z]*\b"
)


# --- Remote resources (v2.12) -----------------------------------------------
# The guard protects LOCAL credential stores. A path that names a file inside a
# REMOTE resource — a GitHub API endpoint, an http(s) URL — is a substring of
# someone else's public tree, not a read of this machine's secrets. Three
# sessions on 2026-08-11 hit this on `gh api repos/<owner>/<repo>/contents/
# .claude/settings.json` (public repo content; `gh` is an unknown command, so
# the segment fell to default-deny).
#
# The rule stays narrow by direction: the stripper only ever REMOVES a token
# that is remote-shaped (a gh REST route or an http(s) URL). It can never
# remove a local path, so a `gh api` call that also reads a local file
# (`--input ~/.env`, `-F body=@~/.env`) keeps its sensitive token and still
# denies. `gh` subcommands other than `api` are untouched.
_REMOTE_URL = re.compile(r"^https?://", re.IGNORECASE)
_GH_API_ENDPOINT = re.compile(
    r"^(?:https?://[\w.-]+)?/?"
    r"(?:repos|orgs|users|user|gists|search|graphql|rate_limit|meta)(?:/|$)",
    re.IGNORECASE,
)


def _strip_gh_api_endpoint(seg):
    """`seg` with a `gh api` call's remote endpoint argument removed.

    Returns `seg` unchanged unless the segment is a `gh api` invocation. Only
    the FIRST remote-shaped positional token after `api` is removed — the
    endpoint. Every flag, flag value, and local-looking token stays, so the
    caller's path check still sees a local read carried by the same command."""
    toks = _tokens(seg)
    gh_at = None
    for i, t in enumerate(toks):
        if t.split("/")[-1].split("\\")[-1].lower() == "gh":
            gh_at = i
            break
    if gh_at is None or gh_at + 1 >= len(toks) or toks[gh_at + 1].lower() != "api":
        return seg
    out, stripped = [], False
    for i, t in enumerate(toks):
        if (not stripped and i > gh_at + 1 and not t.startswith("-")
                and _GH_API_ENDPOINT.match(t)):
            stripped = True
            continue
        out.append(t)
    return " ".join(out)


def _reads_sensitive_path(seg, _depth=0):
    """True if the segment reads a sensitive target's content (default-deny).

    Nested units are classified first, then the outer command is judged with
    them blanked — so a metadata-only operation is safe wherever it sits, and a
    content read anywhere inside denies the whole segment."""
    if not _has_sensitive_path(seg):
        return False

    # 0. A pure VALUE BINDING runs nothing, so it is not a read (v2.6). It is
    #    checked FIRST, ahead of the nested-unit pass: a `foreach ($f in @(...))`
    #    header is a paren group, so that pass would otherwise judge it on its
    #    leading `$f` and deny before the binding rule was ever consulted.
    #
    #    The body still has to be classified — against the bound path, which is
    #    substituted in so the association survives the header/body split. That
    #    is what keeps `foreach ($f in @('~/.env')) { Get-Content $f }` blocking
    #    while the same loop with Remove-Item passes.
    # A whole segment that is nothing but a VALUE runs nothing at all.
    if _is_literal_data(seg):
        return False

    if _depth < 8:
        bound = _ps_binding(seg)
        if bound is not None:
            var, value, tail = bound
            tail = _substitute(tail, _binding_name(var), value)
            return any(
                _reads_sensitive_path(part, _depth + 1)
                for part in _split_segments(_strip_block_braces(tail))
                if part.strip()
            )

        # A loop/conditional that is NOT a binding still wants its header and
        # body judged separately, or a safe body inherits the deny that the
        # `if`/`foreach` keyword earns as an "unknown command":
        # `if (Test-Path ~/.env) { Remove-Item ~/.env }`. Both halves are
        # classified, so a reader in either still denies the whole segment.
        cf = _control_flow_split(seg)
        if cf is not None:
            header, body, _ = cf
            if _reads_sensitive_path(header, _depth + 1):
                return True
            return any(
                _reads_sensitive_path(part, _depth + 1)
                for part in _split_segments(_strip_block_braces(body))
                if part.strip()
            )

    # 1. A reader nested anywhere inside denies the segment outright. A unit
    #    body is a command LIST, so it is re-split before classifying: without
    #    that, `"$(Test-Path ~/.ssh/id_rsa; cat ~/.ssh/id_rsa)"` would be judged
    #    on `Test-Path` alone and the chained reader would ride in behind it.
    #    (The top-level splitter can't do this for us — it leaves separators
    #    inside quotes alone, which is where this shape lives.)
    units = _sub_units(seg)
    hands_path_outward = False
    for _, _, body in units:
        for part in _split_segments(body):
            if not part.strip():
                continue
            if _depth < 8 and _reads_sensitive_path(part, _depth + 1):
                return True
            if (_has_sensitive_path(part)
                    and _leading_command(part) not in _VALUE_ONLY):
                hands_path_outward = True

    # 2. Judge the outer command with those units removed.
    outer = _blank_units(seg, units)
    if _WHOLLY_QUOTED.match(outer):
        return False                                   # a literal, not a command
    if not _has_sensitive_path(outer) and not hands_path_outward:
        return False                                   # every path sat in a
        # cleared unit that emits only a boolean — `if (Test-Path ~/.ssh/id_rsa)`
    lead = _leading_command(outer)
    if lead in GREP_FAMILY:
        return not GREP_SAFE_FLAG.search(outer)        # content grep = read
    if lead == "tar":
        return bool(_TAR_TO_STDOUT.search(outer))
    if lead == "git":
        # git prints object/file content via show/cat-file/grep/diff/config -f,
        # `-c core.pager=cat`, or `log -p`. commit/add/etc. only name the path.
        if _GIT_DANGER_FLAG.search(outer):
            return True
        sub = _git_subcommand(outer)
        if sub in _GIT_READ_SUB:
            return True
        return sub not in _GIT_SAFE_SUB                # unknown subcommand → deny
    if lead == "gh":
        # `gh api <remote endpoint>` reads REMOTE content; judge the segment
        # with the endpoint removed so a local path still denies (v2.12).
        return _has_sensitive_path(_strip_gh_api_endpoint(outer))
    if lead in SAFE_COMMANDS:
        if lead == "find" and re.search(r"-exec(dir)?\b", outer):
            return True                                # find -exec <reader>
        return False
    return True                                        # unknown cmd → default deny


# --- Copy-then-read laundering (v2.9) --------------------------------------
# The guard is invoked once per tool call with NO memory between calls, so the
# obvious fix — taint the destination and catch the later read — is not
# available: it would need persistent state, and a stale or missing taint file
# is a new failure mode on a guard whose whole value is that it cannot fail
# quietly. The stateless equivalent is to refuse the COPY, judged entirely from
# the one command in front of us:
#
#     source matches the sensitive pattern, destination does not  ->  block
#
# That is the whole rule, and it is why the derived-name widening above is not a
# separate courtesy: it is what makes the rule's *allowed* half correct.
#
# Direction is load-bearing, not decoration. `cp .env.example .env` is a routine
# bootstrap — non-sensitive source, sensitive destination — and a rule keyed on
# "this command names a credential file and also names something else" would
# block it. So sources and destination are identified, not just collected.
#
# What is NOT here, and why. `robocopy`, `xcopy`, `zip`, `Compress-Archive`,
# `7z`, and every interpreter equivalent (`shutil.copy`/`shutil.move`,
# `os.rename`/`os.replace`, `fs.copyFileSync`/`renameSync`,
# `[System.IO.File]::Copy/Move`) were driven against the pre-v2.9 guard and are
# ALREADY blocked — not by any copy rule, but because none of them is on
# SAFE_COMMANDS, so a segment naming a credential path under them hits rule 3's
# default-deny. Listing them below therefore changes no behaviour today; they
# are listed so that adding one to SAFE_COMMANDS later cannot silently open the
# laundering path. This is the allowlists-fail-both-ways discipline applied to a
# denylist: name the shape you rely on being covered, so a future edit has to
# break a test to uncover it.
#
# `tar` is the one that DID change, and the reason is worth stating. It carried
# an explicit exemption — "tar writing to an archive file emits no secret
# content to the caller (like `cp`), so it's safe" — resting verbatim on the
# claim this whole change overturns. `tar czf backup.tgz ~/.env` was allowed and
# is now blocked; the pinned test asserting it allowed is flipped, deliberately.
# An archive's name is never a credential name, so archiving a credential is
# always the sensitive-source/non-sensitive-destination shape.
_PAIRWISE_COPY = {
    "cp", "mv", "install", "ln",                       # POSIX
    "copy", "move", "ren", "rename",                   # cmd.exe / PS aliases
    "copy-item", "move-item", "rename-item",           # PowerShell cmdlets
    "cpi", "mi", "rni", "ci",                          # PowerShell aliases
}
_ARCHIVE_OR_BULK = {
    "tar", "zip", "7z", "7za", "gzip", "bzip2", "xz", "rar",
    "compress-archive", "robocopy", "xcopy",
}
# PowerShell parameters that name the destination explicitly. `cp -t DIR SRC…`
# is here too: without it the target directory reads as a source and the last
# source reads as the destination, which inverts the whole judgement.
_DEST_FLAGS = {"-destination", "-dest", "-newname", "-t", "--target-directory"}
_SRC_FLAGS = {"-path", "-literalpath", "-source"}
# cmd.exe spells its switches `/Y`, `/S`, `/R:3`. Only these commands are given
# that reading, because `/tmp` is indistinguishable from a switch by shape and
# treating an absolute POSIX path as a flag silently drops it from the operand
# list — which is how `cp -t /tmp ~/.env` first slipped through this rule.
_CMD_STYLE = {"copy", "move", "ren", "rename", "xcopy", "robocopy"}


def _tokens(seg):
    """Whitespace-split a segment, respecting quotes and dropping them. Good
    enough for operand identification — anything with a substitution in it has
    already been judged by the nested-unit pass."""
    out, buf, quote = [], [], None
    for c in seg.strip():
        if quote:
            if c == quote:
                quote = None
            else:
                buf.append(c)
        elif c in ("'", '"'):
            quote = c
        elif c.isspace():
            if buf:
                out.append("".join(buf))
                buf = []
        else:
            buf.append(c)
    if buf:
        out.append("".join(buf))
    return out


def _copy_operands(seg):
    """(sources, destination) for a pairwise copy/move/rename segment, or None
    if the shape cannot be read confidently.

    The destination is an explicit `-Destination`/`-NewName`/`-t` value when one
    is present, else the last positional operand — which is the convention every
    command in _PAIRWISE_COPY follows."""
    toks = _tokens(seg)
    cmd_style = _leading_command(seg) in _CMD_STYLE
    # Skip the wrappers _leading_command skips, then the command itself, so
    # `sudo cp …` does not read `cp` as an operand.
    i = 0
    while i < len(toks) and (toks[i] in _WRAPPERS
                             or re.match(r"^[A-Za-z_]\w*=", toks[i])):
        i += 1
    i += 1
    dest, positional = None, []
    while i < len(toks):
        tok = toks[i]
        low = tok.lower().split("=")[0]
        if low in _DEST_FLAGS:
            # `--target-directory=/tmp` carries its value in the same token.
            # Consuming the NEXT token instead ate the credential source, so
            # `cp --target-directory=/tmp ~/.env` was judged sourceless (v2.13).
            if "=" in tok:
                dest = tok.split("=", 1)[1]
                i += 1
                continue
            if i + 1 < len(toks):
                dest = toks[i + 1]
                i += 2
                continue
        if low in _SRC_FLAGS:
            if "=" in tok:
                positional.append(tok.split("=", 1)[1])
                i += 1
                continue
            if i + 1 < len(toks):
                positional.append(toks[i + 1])
                i += 2
                continue
        if tok.startswith("-") or (cmd_style and tok.startswith("/")):
            i += 1                                     # a switch
            continue
        positional.append(tok)
        i += 1
    if dest is None:
        if len(positional) < 2:
            return None
        dest = positional.pop()
    return positional, dest


def _effective_dest(dest, src):
    """The destination PATH a copy actually produces.

    `cp ~/.env ~/backup/` does not launder anything — the copy is still called
    `.env`, so it is still a credential path and still guarded. A destination
    that is syntactically a directory therefore inherits the source's basename.
    A directory named WITHOUT a trailing separator (`cp ~/.env /tmp`) cannot be
    told apart from a file target without touching the filesystem, which this
    hook deliberately never does, so it is judged as a file and blocks — the
    conservative direction, and the remedy is one character."""
    d = dest.strip()
    if d in (".", "..") or d.endswith(("/", "\\")):
        return d.rstrip("/\\") + "/" + _basename(src)
    return d


def _copy_launders_credential(seg):
    """True if `seg` copies/moves/archives a credential path to a destination
    that is not itself recognised as a credential path."""
    lead = _leading_command(seg)
    if lead in _ARCHIVE_OR_BULK:
        # An archive member list has no destination worth parsing: the archive
        # is the destination and it never carries a credential name.
        return _has_sensitive_path(seg)
    if lead not in _PAIRWISE_COPY:
        return False
    operands = _copy_operands(seg)
    if operands is None:
        return _has_sensitive_path(seg)                # unreadable shape: block
    sources, dest = operands
    return any(_has_sensitive_path(src)
               and not _has_sensitive_path(_effective_dest(dest, src))
               for src in sources)


# --- Enumerate-then-read (v2.7) --------------------------------------------
# Every rule above needs a sensitive path to appear in the command TEXT. This
# one does not, because there is none to find: the paths are produced at runtime
# by a directory listing. Measured 2026-08-04 against a decoy `.env` holding a
# fabricated value — an agent asked in plain language to print a dotenv file's
# contents wrote `Get-ChildItem -Force <dir> | ForEach-Object { Get-Content
# $_.FullName }` and the value was printed.
#
# Why this is not the copy-launder class posture.md bounds out. Laundering
# (`cp secret x; cat x`) needs the guard to model the FILESYSTEM: an artifact
# created out of band, whose relationship to the secret exists only in history
# the guard cannot see. Here nothing is copied and no history is involved — a
# reader is applied directly to a live enumeration, inside one command, and the
# whole shape is present in the text. What the earlier ruling actually said was
# that "no path-regex can resolve this without matching innocent globs too."
# True, and this rule is not a path-regex; it keys on the pipeline's SHAPE.
#
# The false-positive discipline that decides the exact rule. Two commands have
# identical structure and very different risk:
#
#     Get-ChildItem -Filter *.py <dir> | %{ Get-Content $_.FullName }   # fine
#     Get-ChildItem -Force        <dir> | %{ Get-Content $_.FullName }   # leak
#
# The difference is whether the enumeration's result set can be shown to EXCLUDE
# credential files. A filename constraint that no credential basename can
# satisfy proves it; nothing else does. So the rule is: an enumerator with no
# such constraint, feeding a stage that dereferences each name. A bare
# `Get-ChildItem` is untouched (it prints names, not content), a bare
# `Get-Content` is untouched (rules 1-3 already judge its literal path), and
# `ls | head` / `ls | cat` are untouched because they consume the LISTING as
# text and never open a file. When it does fire, the fix is one flag, which is
# the property that keeps a guard from being routed around.
#
# Residual, stated rather than claimed closed: an unconstrained enumeration that
# reaches a reader through a variable across commands
# (`$fs = Get-ChildItem d; $fs | %{ gc $_ }`) is not a single pipeline and is
# not caught. That IS the dataflow class, and it stays out of scope.

# Commands whose output is a set of filesystem names discovered at runtime.
_ENUMERATORS = {"ls", "dir", "vdir", "ll", "la", "tree", "find", "fd",
                "get-childitem", "gci"}

# Basenames the sensitive pattern matches on their own. A filename glob is
# proved safe by matching NONE of them, so this list failing open (a probe that
# is not actually sensitive, or a whole credential family with no probe) would
# silently widen what counts as "constrained" — test_probes_are_sensitive pins
# every entry against SENSITIVE_FILE_PATTERN so a drifted probe fails the suite
# rather than the next audit (conventions/allowlists-fail-both-ways.md).
_SENSITIVE_PROBES = (
    ".env", ".envrc", ".env.production", ".claude.json", "credentials.json",
    "application_default_credentials.json", "id_rsa", "id_ed25519",
    "server.pem", "server.key", "keystore.p12", ".npmrc", ".pypirc", ".netrc",
    ".pgpass", ".git-credentials", "terraform.tfstate", ".bash_history",
    "access_tokens.db",
)

# Flags whose value is a filename pattern rather than a directory or a switch.
_NAME_PATTERN_FLAGS = {"-filter", "-include", "-name", "-iname"}

# Commands that print a named file's CONTENT. Broader than SAFE_COMMANDS' mirror
# image on purpose: this list only ever decides whether an already-unconstrained
# enumeration is being dereferenced, so a generous entry costs nothing elsewhere.
_ITEM_READERS = (
    "cat", "tac", "nl", "head", "tail", "more", "less", "bat", "xxd", "od",
    "strings", "base64", "hexdump", "type", "get-content", "gc",
)
_READER_TOKEN = re.compile(
    r"(?:^|[\s;(|{&])(?:sudo\s+)?(?:" + "|".join(_ITEM_READERS) + r")(?![\w-])",
    re.IGNORECASE,
)
_XARGS_READER = re.compile(r"\bxargs\b", re.IGNORECASE)
_EXEC_READER = re.compile(r"-exec(?:dir)?(?![\w-])", re.IGNORECASE)
_FOREACH = re.compile(r"(?:^|[\s;(|{&])(?:foreach-object|foreach|%)(?![\w-])",
                      re.IGNORECASE)
# The per-item variable a ForEach-Object body uses to name the current file.
_ITEM_VAR = re.compile(r"\$(?:_|PSItem)(?![\w])", re.IGNORECASE)


def _glob_excludes_sensitive(pattern):
    """True if the filename glob `pattern` cannot match ANY known credential
    basename — the only evidence available that an enumeration's results are
    safe. `*` and `*.json` fail this; `*.py` and `*.md` pass it."""
    rx = []
    for ch in _basename(pattern):
        rx.append(".*" if ch == "*" else "." if ch == "?" else re.escape(ch))
    matcher = re.compile("".join(rx) + r"\Z", re.IGNORECASE)
    return not any(matcher.match(p) for p in _SENSITIVE_PROBES)


def _enumeration_is_unconstrained(seg):
    """True if `seg` leads with a directory enumerator whose results could
    include a credential file: it carries no filename constraint at all, or one
    a credential basename could satisfy."""
    if _leading_command(seg) not in _ENUMERATORS:
        return False
    patterns, toks = [], seg.split()
    for i, tok in enumerate(toks):
        if tok.lower() in _NAME_PATTERN_FLAGS and i + 1 < len(toks):
            patterns.append(toks[i + 1])
        elif not tok.startswith("-") and ("*" in tok or "?" in tok):
            patterns.append(tok)
    return not patterns or not all(_glob_excludes_sensitive(p)
                                   for p in patterns)


def _reads_each_item(stage):
    """True if `stage` dereferences the names it is handed and prints their
    CONTENT. A stage that consumes the listing as text (`| head`, `| cat`,
    `| Select-Object`) does not: `cat` reading stdin opens nothing."""
    if _XARGS_READER.search(stage) or _EXEC_READER.search(stage):
        return bool(_READER_TOKEN.search(stage))
    if _FOREACH.search(stage):
        return bool(_READER_TOKEN.search(stage) and _ITEM_VAR.search(stage))
    return False


def _enumerate_then_read(command):
    """True if any pipeline in `command` runs an unconstrained enumeration into
    a per-item content reader. `find -exec cat {} \\;` needs stage 0 itself
    checked, since there the reader rides inside the producer."""
    for stages in _pipelines(command):
        if not _enumeration_is_unconstrained(stages[0].strip()):
            continue
        if any(_reads_each_item(s) for s in stages):
            return True
    return False


def block(message):
    """Write a block reason to stderr and exit with the hook's block code."""
    sys.stderr.write(message)
    sys.exit(2)


# --- Block messages --------------------------------------------------------
#
# THESE STRINGS ARE AGENT-FACING. The harness hands stderr to the model
# verbatim, so anything written here is an instruction the model will read while
# it is actively looking for a way past this block. Until 2026-08-09 every one
# of them ended by naming the MASK-OK override — and in the run that produced
# this file's v2.9 changes, the agent read that sentence out of a block it had
# just received, quoted it back, and used it. An escape hatch designed as a
# HUMAN judgement call ("having weighed the exposure" is a person's call, not a
# model's) was being advertised to, and exercised by, the party whose mistakes
# this guard exists to catch.
#
# So the override is no longer named here. It is unchanged and still works
# (see main()), and it stays documented in security/README.md — which is what a
# human reads. What each message now says instead is the action actually wanted
# from an agent that hits one of these: stop, and ask the operator.
#
# This is NOT claimed as a security boundary, and _OVERRIDE_LINE is not a
# secret: MASK-OK is a fixed, public token in a public repo, and a model that
# knows this codebase can produce it unprompted. What it removes is the reflex —
# the guard handing over its own bypass at the worst possible moment. The
# posture's false-positive lesson in the mirror: a control that teaches reaching
# for the override erodes itself.
_OVERRIDE_LINE = (
    "If this is genuinely necessary, STOP and ask the operator to authorise it.\n"
    "Do not work around this block.\n"
)

_MSG_PATH = (
    "CREDENTIAL GUARD (v2, path-based default-deny): this reads the content of a\n"
    "known credential-store target (Claude config / .env / SSH or other private\n"
    "keys / cloud, registry, or infra credential files / shell history /\n"
    "/proc/*/environ). Same exposure as `cat`-ing it, regardless of the reader\n"
    "used. To check existence without printing the value, use a metadata command\n"
    "(ls / stat / Test-Path) or grep in files_with_matches / count mode.\n"
    + _OVERRIDE_LINE
)
# The same default-deny, worded for the other direction. _MSG_PATH used to be
# emitted for both, so a `Write` at ~/.ssh/id_rsa came back described as a read
# ("same exposure as `cat`-ing it") — which is not what happened, and reads as a
# guard bug rather than a ruling. An agent that believes the message is wrong
# goes looking for the wrong fix. Blocking the write is deliberate: the
# tool-shape default-deny below has always covered writes, because clobbering
# the operator's live secret is as bad an outcome as printing it.
_MSG_PATH_WRITE = (
    "CREDENTIAL GUARD (v2, path-based default-deny): this WRITES TO or MODIFIES\n"
    "a known credential-store target (Claude config / .env / SSH or other\n"
    "private keys / cloud, registry, or infra credential files). Nothing is\n"
    "printed, so this is not a leak — it is blocked as a CLOBBER: it replaces or\n"
    "destroys the operator's live secret, and the guard cannot tell a repair\n"
    "from a destruction. To inspect the file without changing it, use a metadata\n"
    "command (ls / stat / Test-Path).\n"
    + _OVERRIDE_LINE
)
_MSG_ENV = (
    "CREDENTIAL GUARD: this dumps the environment (env / printenv / set /\n"
    "declare -p / Get-ChildItem Env:). Every credential-shaped var (*_TOKEN,\n"
    "*_KEY, *_SECRET) currently set gets printed in the clear. Check a specific\n"
    "non-secret var instead, e.g. `[bool]$env:VARNAME`.\n"
    + _OVERRIDE_LINE
)
_MSG_VAR = (
    "CREDENTIAL GUARD: this prints a credential-shaped environment variable in\n"
    "the clear (this is the 2026-07-02 founding incident's exact shape). If you\n"
    "only need to know whether it's set, test `[bool]$env:NAME` or a\n"
    "truncated/masked read.\n"
    + _OVERRIDE_LINE
)
_MSG_GREP = (
    "CREDENTIAL GUARD: content-mode Grep against a known credential-store file\n"
    "prints the full matched line — including the secret value next to the key.\n"
    "Use output_mode=files_with_matches or count instead.\n"
    + _OVERRIDE_LINE
)
_MSG_MCP = (
    "CREDENTIAL GUARD: `claude mcp get <name>` prints that server's stored env\n"
    "vars (including secrets) in the clear. Use `claude mcp list` to check\n"
    "connection status without revealing values.\n"
    + _OVERRIDE_LINE
)
_MSG_ENUM = (
    "CREDENTIAL GUARD: this pipes an UNCONSTRAINED directory listing into a\n"
    "per-item content reader, so it prints whatever happens to be in that\n"
    "directory — including a .env, an SSH key, or a credential JSON. No path is\n"
    "named in the command, which is exactly why the path checks don't see it.\n"
    "Constrain the enumeration to names that cannot be credential files (e.g.\n"
    "`-Filter *.py`, `find . -name '*.md'`), or read the specific files you\n"
    "want by name.\n"
    + _OVERRIDE_LINE
)
_MSG_COPY = (
    "CREDENTIAL GUARD: this copies (or moves, renames, or archives) a known\n"
    "credential-store file to a destination that is NOT recognised as one. The\n"
    "copy holds the same bytes under a name the guard no longer protects, so\n"
    "every read check is bypassed from that point on — this is the copy-then-read\n"
    "shape, and it is blocked at the copy because after it there is nothing left\n"
    "to recognise. A BACKUP is fine: keep the credential name and add a derived\n"
    "suffix (`settings.json.bak-20260806`, `.env.old`, `credentials~`), which\n"
    "stays protected. To reference the file without copying it, use a metadata\n"
    "command (ls / stat / Test-Path).\n"
    + _OVERRIDE_LINE
)
_MSG_GIT = (
    "CREDENTIAL GUARD: `git -c <key>=!<cmd>` config-injects a shell alias —\n"
    "arbitrary command execution that can read any secret while wearing a git\n"
    "disguise. Run the intended command directly (so the guard can see it),\n"
    "not through a git alias escape.\n"
)

# A tool-input field carries a path if its NAME looks path-like. Checked on ALL
# tools (not a fixed {Read, Grep} pair), so a reader tool that isn't hooked yet
# is covered — the structural fix for the 2026-07-04 tool-shape gap. Matching on
# the field *name* (not every string value) means an odd field like
# `target_file` / `filename` / `abs_path` / a `paths` array is still caught
# (red-team H2), while a `content` / `old_string` field that merely mentions a
# path is not falsely blocked.
_PATH_FIELD_NAME = re.compile(
    r"path|file|dir|uri|url|src|source|dest|location|target", re.IGNORECASE
)


def _looks_like_path(v):
    """A value is a filesystem path, not prose, if it has a separator, starts
    like a path, or has no spaces. Gates the field scan so a pathy-NAMED field
    holding a human label ("backup of .env") isn't blocked (round 2, L2)."""
    v = v.strip()
    return bool(v) and ("/" in v or "\\" in v
                        or v.startswith(("~", ".")) or " " not in v)


def _field_targets_sensitive(obj, key_is_pathy=False):
    """Recursively true if any path-named field (or element of one) targets a
    credential store. `key_is_pathy` carries the enclosing key's path-ness down
    into list elements so `{"paths": ["~/.claude.json"]}` is caught. The field
    name is a bounded heuristic — a reader tool using an unforeseen field name
    is a known residual gap (posture threat model), not a claimed-closed case."""
    if isinstance(obj, str):
        # An http(s) URL is a remote resource, not a local path — a public
        # file that happens to be NAMED `.claude/settings.json` is not this
        # machine's secret (v2.12). `file://` does not match and still blocks:
        # it names the local filesystem.
        if _REMOTE_URL.match(obj.strip()):
            return False
        return key_is_pathy and _looks_like_path(obj) and _has_sensitive_path(obj)
    if isinstance(obj, list):
        return any(_field_targets_sensitive(x, key_is_pathy) for x in obj)
    if isinstance(obj, dict):
        return any(
            _field_targets_sensitive(
                v, key_is_pathy or bool(_PATH_FIELD_NAME.search(str(k))))
            for k, v in obj.items()
        )
    return False


# A tool call that carries a NEW value for its target is modifying it, whatever
# the tool is called. Keyed on the PAYLOAD first and the tool name only as a
# fallback, for the same reason _field_targets_sensitive is keyed on field names
# rather than a {Read, Grep} pair: an unhooked write tool should still be
# described correctly (the 2026-07-04 tool-shape gap's own lesson).
_WRITE_CONTENT_FIELD = re.compile(
    r"^(content|contents|text|file_text|new_str|new_string|new_source|"
    r"replacement|edits)$", re.IGNORECASE
)
# Names that modify by construction even with no body in the payload (a delete,
# a rename, a touch). Secondary to the field check, never primary.
_WRITE_TOOL_NAME = re.compile(
    r"write|edit|create|update|replace|delete|remove|rename|move", re.IGNORECASE
)


def _is_write_shaped(tool_name, tool_input):
    """True if this tool call MODIFIES its path target rather than reading it.

    Wording only — BOTH branches block, so this function cannot change a
    verdict. When neither signal fires it returns False and the caller emits the
    read message, which is the pre-2026-08-09 behaviour for every tool: a call
    this cannot classify is described exactly as it was before."""
    if any(_WRITE_CONTENT_FIELD.match(str(k)) for k in tool_input):
        return True
    return bool(_WRITE_TOOL_NAME.search(str(tool_name or "")))


def _allow(payload):
    """Allow (exit 0), speaking Cursor's dialect when the caller is Cursor.

    cursor-agent imports this hook and marks an empty-stdout run as failed —
    and its imported-hook wiring is hardcoded failClosed=false, so that
    "failure" silently allows. An explicit verdict makes the allow a measured
    success instead. Only a Cursor payload (cursor_version key) gets the JSON;
    Claude Code's own payloads exit bare so its stdout contract is untouched.
    """
    if isinstance(payload, dict) and "cursor_version" in payload:
        print('{"permission": "allow"}')
    sys.exit(0)


def main():
    """PreToolUse hook: allow (exit 0) or block (exit 2) the tool call on stdin.

    Grep is checked for content-mode reads of sensitive paths; Bash/PowerShell
    (and Cursor's "Shell") commands are split into segments and checked for env
    dumps, credential-var prints, and sensitive-path reads (default-deny by
    leading command); Glob is allowed (it returns paths, not content); every
    other tool has all its path-bearing fields checked against the
    sensitive-target pattern. Fails open (exit 0) on an unparseable payload.
    """
    try:
        # utf-8-sig: cursor-agent's Windows hook wrapper pipes the payload
        # through PowerShell with a BOM-emitting $OutputEncoding; json.load on
        # the text stream raised on that BOM and the guard failed open.
        data = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    except Exception:
        sys.exit(0)

    tool_name = data.get("tool_name")
    tool_input = data.get("tool_input", {})
    if not isinstance(tool_input, dict):
        tool_input = {}

    # Grep: only content mode echoes the matched line. Check both the explicit
    # path and a glob that targets a sensitive file (path may be omitted).
    if tool_name == "Grep":
        if tool_input.get("output_mode") == "content":
            for field in ("path", "glob"):
                v = tool_input.get(field, "")
                if _has_sensitive_path(v):
                    block(_MSG_GREP)
        _allow(data)

    # "Shell" is cursor-agent's single shell tool; its tool_input carries the
    # same {"command": ...} shape as Claude Code's Bash/PowerShell.
    if tool_name in ("Bash", "PowerShell", "Shell"):
        command = tool_input.get("command", "")
        if not command or "MASK-OK" in command:
            _allow(data)
        command = _strip_heredocs(command)
        # `echo <path> | xargs <reader>` feeds the path to a downstream reader
        # across segment boundaries (round 3, #2). Only the pipeline stage that
        # actually EMITS the path (echo/printf/ls/find/…) counts — `git log --
        # .env | xargs echo` emits hashes, not the file, so it isn't a read
        # (round 4, #4).
        segments = _split_segments(command)
        # Variables bound to a sensitive literal anywhere in this command. The
        # bound path is substituted back in below, so a binding and the read
        # that consumes it can be split across segments (`$f = '~/.env'; cat
        # $f`) without the read losing sight of the path (v2.6). Resolved up
        # here because the xargs producer check needs it too: `$f = '~/.env';
        # echo $f | xargs cat` has no literal path in the producer.
        bindings = _collect_bindings(segments)
        xm = re.search(r"\|\s*xargs\b", command)
        if xm:
            producer = re.split(r"[;\n&]|&&|\|\||\|", command[:xm.start()])[-1]
            producer = _apply_bindings(producer.split("#")[0], bindings)
            if _leading_command(producer) in (
                    "echo", "printf", "print", "ls", "find", "realpath",
                    "readlink") and _has_sensitive_path(producer):
                block(_MSG_PATH)
        # The producer above needs a LITERAL sensitive path. An unconstrained
        # directory enumeration feeding a per-item reader has none — the paths
        # only exist at runtime — so it is judged on pipeline shape (v2.7).
        if _enumerate_then_read(command):
            block(_MSG_ENUM)
        # Quote-aware split on every shell separator, including a single `&`
        # (backgrounding — `true & cat ~/.env` otherwise hid the reader behind a
        # safe leading command, round 3 #1) but not inside quotes (round 4 #3).
        for seg in segments:
            seg = seg.strip()
            if not seg:
                continue
            # A git message-bearing subcommand's arg is prose, so skip the
            # command-shape checks (env/var/mcp) that would false-positive on a
            # commit message discussing them (round 3 #4) — but NOT for other
            # git forms, so `git -c alias.x='!printenv KEY' x` is still caught
            # (round 4 #2). The sensitive-path read check always runs.
            if _GIT_ALIAS_EXEC.search(seg):
                block(_MSG_GIT)
            # Interpolating a credential var into a message flag publishes it.
            # Checked on the RAW segment, before prose values are blanked.
            if _prose_flag_publishes_cred_var(seg):
                block(_MSG_VAR)
            # A prose flag's quoted value is a message, not a path position, so
            # the remaining checks run against the segment with those values
            # blanked (2026-07-18 false positive). Expandable values survive the
            # blanking and are still scanned.
            scan = _strip_prose_flag_values(seg)
            if not _GIT_MSG_CMD.match(scan):
                if ENV_DUMP_PATTERN.search(scan) or _get_variable_is_dump(scan):
                    block(_MSG_ENV)
                if CRED_VAR_READ.search(scan):
                    block(_MSG_VAR)
                if MCP_GET_PATTERN.search(scan):
                    block(_MSG_MCP)
            # A dump one container down (`echo $(env)`) never reached the rules
            # above, because they need a whole segment to work on. Two do:
            # ENV_DUMP_PATTERN's bare forms are segment-anchored, and
            # _get_variable_is_dump walks the tokens after the cmdlet TO THE END
            # of what it is given — so on `echo $(Get-Variable)` it reads the
            # trailing `)` as the variable being named and calls it a targeted
            # read. Both need the unit body handed to them as a segment.
            #
            # CRED_VAR_READ and MCP_GET_PATTERN do NOT: they are un-anchored, so
            # the search over `scan` already sees inside a substitution. Running
            # CRED_VAR_READ per unit would newly break `[bool]($env:API_KEY)`,
            # since its standalone-statement alternatives (`^\s*\$env:NAME\s*$`)
            # describe a statement that EMITS a value, and a unit body's value is
            # consumed by the expression around it.
            #
            # The _GIT_MSG_CMD prose skip is deliberately NOT applied here: it
            # exempts a commit MESSAGE, and a substitution body is executed code
            # whatever encloses it, so `git commit -m "$(env)"` really does dump
            # the environment into the message. Prose can't reach this pass
            # anyway — single quotes suppress expansion, and a paren inside a
            # double-quoted string is not treated as a unit.
            for unit in _nested_command_units(scan):
                if ENV_DUMP_PATTERN.search(unit) or _get_variable_is_dump(unit):
                    block(_MSG_ENV)
            # Only the PATH check gets the binding substitution: the
            # command-shape rules above key on verbs and variable NAMES, and
            # splicing a path literal into them buys nothing while widening
            # their blast radius.
            resolved = _apply_bindings(scan, bindings)
            # The copy check runs BEFORE the read check and only ever ADDS a
            # block: every command it examines (cp/mv/Copy-Item/tar/…) is one
            # the read check already treats as safe, so it cannot loosen
            # anything, and it gets the binding substitution for the same reason
            # the read check does (`$f = '~/.env'; Copy-Item $f x.txt`).
            if _copy_launders_credential(resolved):
                block(_MSG_COPY)
            if _reads_sensitive_path(resolved):
                # Same verdict either way; only the wording is chosen here. A
                # write-only cmdlet reaches this line through the unknown-
                # command default-deny, which is correct as a BLOCK and wrong
                # as the word "reads".
                block(_MSG_PATH_WRITE
                      if _leading_command(resolved) in _WRITE_ONLY_COMMANDS
                      else _MSG_PATH)
        _allow(data)

    # Glob returns paths, not content — it can confirm a file exists (the safe
    # fallback the guard itself recommends) but cannot print a secret's value.
    if tool_name == "Glob":
        _allow(data)

    # Every other tool (Read, NotebookEdit, MCP file readers, ...): block if any
    # path-named field targets a sensitive file. This is the default-deny that
    # closes the tool-shape gap by construction — reads OR writes to a
    # credential store (overwriting ~/.ssh/id_rsa is as bad an outcome as
    # printing it; the human-runs-credentials protocol covers legitimate cases,
    # with Bash + MASK-OK as the escape hatch).
    if _field_targets_sensitive(tool_input):
        block(_MSG_PATH_WRITE if _is_write_shaped(tool_name, tool_input)
              else _MSG_PATH)
    _allow(data)


if __name__ == "__main__":
    main()
