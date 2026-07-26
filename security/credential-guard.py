#!/usr/bin/env python3
# hook-version: 2.2 (canonical: THIS file, per decisions/ADR-002 — the live
# deploy at ~/.claude/hooks/ and any provisioning copies sync FROM here)
# 2.1 (2026-07-18): prose-flag false-positive fix; a copy still reporting 2 is
# stale. Minor bump = same v2 architecture, corrected behaviour.
# 2.2 (2026-07-26): `Env:` PSDrive false-positive fix — the env-dump pattern
# matched `$env:NAME` used as a path, not just the drive root.
"""Credential exposure guard (global PreToolUse hook) — path-based default-deny.

v2 (2026-07-06, claude-ops decisions/ADR-003 Phase 1). v1 enumerated the *read
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
     its leading command is on a small SAFE allowlist (metadata/existence,
     pure file management, string/echo, and version control). So `xxd`, `jq`,
     `base64`, `python3 -c`, and any unknown reader are denied by *default*;
     `git commit -m "... .env ..."`, `echo`, heredoc prose, `ls`, `rm`,
     `grep -l`, and `stat` are not. This is the false-positive discipline v1's
     first over-broad draft violated (it blocked its own commit message for
     quoting the example); requiring the sensitive path to sit in an actual
     command position, and treating VCS/echo/heredoc as safe, keeps prose
     committable.
  4. Bulk and targeted environment reads: `env`/`printenv`/`set`/`declare -p`/
     the PowerShell `Env:` dumps, AND a single credential-shaped variable being
     printed (`echo $ANTHROPIC_API_KEY`, `printenv GITHUB_TOKEN`,
     `[Environment]::GetEnvironmentVariable("...KEY")`) — the founding 07-02
     incident, which v1 never caught.

Deliberately OUT of scope, per the posture's threat model (non-adversarial
agent mistakes; anyone with local code-execution has already won — see
posture.md and decisions/ADR-001): copy-then-read laundering (`cp secret x;
cat x`), indirection through a script the guard can't see into (`source .env`
is caught because `source` is not a safe verb, but `bash leak.sh` is not),
wildcard / variable-assembled path names (`cat ~/.claud*.json`, `f=.env; cat
$f`) that no path-regex can resolve without matching innocent globs too, and
MASK-OK forgery. Those are contained by the permission allowlist (no `$(...)`,
no arbitrary shell control-flow) and by treating any credential that touches a
transcript as compromised and rotating it (posture Layer 4), not by this hook.
The adversarial test suite (tests/test_credential_guard.py) carries a case per
taxonomy shape, including the ones we consciously do not block, so the boundary
is asserted rather than assumed.

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
    # Private keys / keystores.
    r"|id_(rsa|ed25519|ecdsa|dsa)\w*"
    r"|[\w.-]+\.(pem|key|ppk|p12|pfx|jks)"
    # Cloud CLIs.
    r"|\.aws[/\\](credentials|config)(?![\w.-])"
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
    r")\b",
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


def _basename(matched):
    return re.split(r"[/\\]", matched.strip().strip("'\"(),=:@ "))[-1]


def _match_exempt(matched):
    """A sensitive-pattern hit that's actually a public template/cert — judged
    on the basename, and never when the name looks like a private key."""
    name = _basename(matched)
    if _KEYISH.search(name):
        return False
    return bool(ENV_TEMPLATE.match(name) or PUBLIC_CERT.match(name))


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
_PS_ENV_DRIVE = (
    r"(?:^|[\s;(])(?:Get-ChildItem|Get-Item|gci|gi|dir|ls)\s+"
    r"(?:-\w+\s+)*"                      # -Path / -LiteralPath / -Force / ...
    r"['\"]?Env:[\\/]?\*?['\"]?(?![\w$-])"
)

ENV_DUMP_PATTERN = re.compile(
    r"^\s*env\s*$"                       # bare `env`
    r"|^\s*printenv\s*$"                 # bare `printenv`
    r"|^\s*set\s*$"                      # bare `set` (not `set -e` / `set -o`)
    r"|\bexport\s+-p\b"                  # `export -p`
    r"|\bdeclare\s+-\w*p\b"              # `declare -p` / `-px`
    + r"|" + _PS_ENV_DRIVE +             # PowerShell Env: PSDrive dump
    r"|\bGet-Variable\b(?![^|]*-Name)"   # `Get-Variable` with no -Name = dump
    r"|\b(dir|ls)\s+variable:",
    re.IGNORECASE,
)

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
    + r"(?:-\w+\s+)*Env:\\?" + _CRED_VAR
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

# A credential-shaped var interpolated INTO a prose value publishes the secret
# (a PR body is a public surface). CRED_VAR_READ only recognises the echo family
# before a `$VAR`, so this shape was silently allowed before 2026-07-18; found
# by the regression test written for the false positive above.
PROSE_FLAG_CRED_VAR = re.compile(
    r"(?:" + _PROSE_FLAG + r")\s*=?\s*['\"][^'\"]*"
    r"\$(?:\{)?(?:env:)?" + _CRED_VAR,
    re.IGNORECASE,
)


def _strip_prose_flag_values(seg):
    """Blank out the quoted value of prose-bearing flags so a credential-store
    NAME mentioned in a message isn't read as a path position. Leaves the flag
    itself, and leaves any value that could expand ($ / backtick), in place."""
    def _blank(m):
        value = m.group(1)
        if _EXPANDABLE.search(value):
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
_SUBSTITUTION = re.compile(r"\$\(|`|<\(")  # command / process substitution

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
    (red-team round 4, #3)."""
    segs, buf, quote, i, n = [], [], None, 0, len(command)
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
        elif command[i:i + 2] in ("&&", "||"):
            segs.append("".join(buf)); buf = []; i += 2
        elif c in (";", "\n", "|", "&"):
            segs.append("".join(buf)); buf = []; i += 1
        else:
            buf.append(c)
            i += 1
    segs.append("".join(buf))
    return segs


def _leading_command(seg):
    """The first real command token in a segment, minus wrappers and VAR=val."""
    toks = seg.strip().lstrip("(").strip().split()
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


# tar writing to an archive file emits no secret content to the caller (like
# `cp`), so it's safe — UNLESS it extracts to stdout (`-O`/`--to-stdout`, incl.
# the clustered old-style `xfO`/`xOf`/`xzfO` form, red-team round 2 H2) or
# writes the archive to stdout (a bare `-`), which does surface the bytes.
_TAR_TO_STDOUT = re.compile(
    r"--to-stdout\b"
    r"|--to-command\b"                        # runs a reader per member (round 3)
    r"|(?<![\w-])-O\b"
    r"|(?<!\S)-(?=\s|$)"
    r"|\btar\s+-?[a-zA-Z]*O[a-zA-Z]*\b"
)


def _reads_sensitive_path(seg):
    """True if the segment reads a sensitive target's content (default-deny)."""
    if not _has_sensitive_path(seg):
        return False
    lead = _leading_command(seg)
    if lead in GREP_FAMILY:
        return not GREP_SAFE_FLAG.search(seg)          # content grep = read
    if lead == "tar":
        return bool(_TAR_TO_STDOUT.search(seg) or _SUBSTITUTION.search(seg))
    if lead == "git":
        # git prints object/file content via show/cat-file/grep/diff/config -f,
        # `-c core.pager=cat`, or `log -p`. commit/add/etc. only name the path.
        if _SUBSTITUTION.search(seg) or _GIT_DANGER_FLAG.search(seg):
            return True
        sub = _git_subcommand(seg)
        if sub in _GIT_READ_SUB:
            return True
        return sub not in _GIT_SAFE_SUB                # unknown subcommand → deny
    if lead in SAFE_COMMANDS:
        if lead == "find" and re.search(r"-exec(dir)?\b", seg):
            return True                                # find -exec <reader>
        return bool(_SUBSTITUTION.search(seg))         # echo $(cat secret) etc.
    return True                                        # unknown cmd → default deny


def block(message):
    """Write a block reason to stderr and exit with the hook's block code."""
    sys.stderr.write(message)
    sys.exit(2)


# --- Block messages --------------------------------------------------------

_MSG_PATH = (
    "CREDENTIAL GUARD (v2, path-based default-deny): this reads the content of a\n"
    "known credential-store target (Claude config / .env / SSH or other private\n"
    "keys / cloud, registry, or infra credential files / shell history /\n"
    "/proc/*/environ). Same exposure as `cat`-ing it, regardless of the reader\n"
    "used. To check existence without printing the value, use a metadata command\n"
    "(ls / stat / Test-Path) or grep in files_with_matches / count mode. If a full\n"
    "unmasked read is genuinely needed, re-invoke via Bash with MASK-OK in the\n"
    "command and having weighed the exposure.\n"
)
_MSG_ENV = (
    "CREDENTIAL GUARD: this dumps the environment (env / printenv / set /\n"
    "declare -p / Get-ChildItem Env:). Every credential-shaped var (*_TOKEN,\n"
    "*_KEY, *_SECRET) currently set gets printed in the clear. Check a specific\n"
    "non-secret var instead, e.g. `[bool]$env:VARNAME`. Re-invoke with MASK-OK\n"
    "if a full dump is genuinely needed and you've weighed the exposure.\n"
)
_MSG_VAR = (
    "CREDENTIAL GUARD: this prints a credential-shaped environment variable in\n"
    "the clear (this is the 2026-07-02 founding incident's exact shape). If you\n"
    "only need to know whether it's set, test `[bool]$env:NAME` or a\n"
    "truncated/masked read. Re-invoke with MASK-OK for a deliberate audit.\n"
)
_MSG_GREP = (
    "CREDENTIAL GUARD: content-mode Grep against a known credential-store file\n"
    "prints the full matched line — including the secret value next to the key.\n"
    "Use output_mode=files_with_matches or count instead, or Bash with MASK-OK\n"
    "if you genuinely need the value.\n"
)
_MSG_MCP = (
    "CREDENTIAL GUARD: `claude mcp get <name>` prints that server's stored env\n"
    "vars (including secrets) in the clear. Use `claude mcp list` to check\n"
    "connection status without revealing values, or Bash with MASK-OK if you\n"
    "genuinely need the stored value.\n"
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


def main():
    """PreToolUse hook: allow (exit 0) or block (exit 2) the tool call on stdin.

    Grep is checked for content-mode reads of sensitive paths; Bash/PowerShell
    commands are split into segments and checked for env dumps, credential-var
    prints, and sensitive-path reads (default-deny by leading command); Glob is
    allowed (it returns paths, not content); every other tool has all its
    path-bearing fields checked against the sensitive-target pattern. Fails open
    (exit 0) on an unparseable payload.
    """
    try:
        data = json.load(sys.stdin)
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
        sys.exit(0)

    if tool_name in ("Bash", "PowerShell"):
        command = tool_input.get("command", "")
        if not command or "MASK-OK" in command:
            sys.exit(0)
        command = _strip_heredocs(command)
        # `echo <path> | xargs <reader>` feeds the path to a downstream reader
        # across segment boundaries (round 3, #2). Only the pipeline stage that
        # actually EMITS the path (echo/printf/ls/find/…) counts — `git log --
        # .env | xargs echo` emits hashes, not the file, so it isn't a read
        # (round 4, #4).
        xm = re.search(r"\|\s*xargs\b", command)
        if xm:
            producer = re.split(r"[;\n&]|&&|\|\||\|", command[:xm.start()])[-1]
            producer = producer.split("#")[0]
            if _leading_command(producer) in (
                    "echo", "printf", "print", "ls", "find", "realpath",
                    "readlink") and _has_sensitive_path(producer):
                block(_MSG_PATH)
        # Quote-aware split on every shell separator, including a single `&`
        # (backgrounding — `true & cat ~/.env` otherwise hid the reader behind a
        # safe leading command, round 3 #1) but not inside quotes (round 4 #3).
        for seg in _split_segments(command):
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
            if PROSE_FLAG_CRED_VAR.search(seg):
                block(_MSG_VAR)
            # A prose flag's quoted value is a message, not a path position, so
            # the remaining checks run against the segment with those values
            # blanked (2026-07-18 false positive). Expandable values survive the
            # blanking and are still scanned.
            scan = _strip_prose_flag_values(seg)
            if not _GIT_MSG_CMD.match(scan):
                if ENV_DUMP_PATTERN.search(scan):
                    block(_MSG_ENV)
                if CRED_VAR_READ.search(scan):
                    block(_MSG_VAR)
                if MCP_GET_PATTERN.search(scan):
                    block(_MSG_MCP)
            if _reads_sensitive_path(scan):
                block(_MSG_PATH)
        sys.exit(0)

    # Glob returns paths, not content — it can confirm a file exists (the safe
    # fallback the guard itself recommends) but cannot print a secret's value.
    if tool_name == "Glob":
        sys.exit(0)

    # Every other tool (Read, NotebookEdit, MCP file readers, ...): block if any
    # path-named field targets a sensitive file. This is the default-deny that
    # closes the tool-shape gap by construction — reads OR writes to a
    # credential store (overwriting ~/.ssh/id_rsa is as bad an outcome as
    # printing it; the human-runs-credentials protocol covers legitimate cases,
    # with Bash + MASK-OK as the escape hatch).
    if _field_targets_sensitive(tool_input):
        block(_MSG_PATH)
    sys.exit(0)


if __name__ == "__main__":
    main()
