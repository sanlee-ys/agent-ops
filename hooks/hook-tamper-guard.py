#!/usr/bin/env python3
# hook-version: 1.0 (2026-08-22)
"""Hook tamper guard (global PreToolUse hook) — protects the DEPLOYED guard chain.

WHAT IT PROTECTS, AND WHY IT IS NOT config-change-guard.py.

`hooks/config-change-guard.py` is a `ConfigChange` hook. It reads the settings
file after a change and asks whether the RESULT is safe. It cannot see a tool
call, and the harness fires it only for a settings scope.

This guard is a `PreToolUse` hook. It judges the TOOL CALL, before the write
lands, and its subject is the deployed files themselves:

  ~/.claude/hooks/*            the deployed guard scripts
  ~/.claude/settings.json      the wiring that registers them
  ~/.cursor/hooks.json         the Cursor lane's native registration
  ~/.grok/hooks/*              the Grok adapter and its fleet-guards.json
  ~/.grok/config.toml          the [compat.claude] hooks toggle
  ~/.gemini/config/hooks.json  the Antigravity lane's registration
  ~/.pi/agent/extensions/*     the Pi lane's guard extension
  ~/.pi/agent/settings.json    the Pi lane's wiring

Every path above is read from a vendor README in this repo (`vendors/cursor`,
`vendors/grok`, `vendors/gemini`, `vendors/pi`). The two hooks are therefore
complementary and neither replaces the other: config-change-guard sees a
`/config` edit this hook never receives, and this hook sees a `Write` or an
`Out-File` that config-change-guard only learns about after the bytes land.

THE THREAT. Under agent-ops ADR-012 guard wiring is the WHOLE of the fleet's
safety control. So the shortest path from a blocked call to an allowed one is
not a clever bypass — it is an edit that removes the guard. That edit is what an
agent produces while "fixing the hook", and it is inside the non-adversarial
threat model the other guards are written for. `security/posture.md` records the
same class from the other side: a stale deployed copy gives false coverage, and
false coverage is worse than none.

THE CANONICAL SOURCES STAY EDITABLE. This guard protects DEPLOYED copies only.
Editing `hooks/`, `security/` or `vendors/` inside an agent-ops clone is how a
guard evolves, and it goes out through a reviewed pull request. The distinction
needs no repo detection: every protected path is anchored to a HOME dot-config
directory (`.claude/hooks/`, `.grok/`, `.gemini/config/`, `.pi/agent/`), and a
clone path such as `<repo>/hooks/credential-guard.py` or
`<repo>/vendors/claude/plugin/hooks/hooks.json` carries no such directory.

DIRECTION MATTERS. A READ of a deployed guard is allowed. Reading a hook to see
what it refuses is ordinary work, and `security/credential-guard.py` already
governs the reads that matter (it treats `.claude/settings.json` and
`.claude.json` as credential stores). Only a MUTATION blocks:

  1. A write-shaped tool call whose path-bearing field targets a protected path.
     Keyed on the payload and the tool name, never on a fixed tool list, for the
     reason credential-guard v2 gives: a write tool nobody has enumerated yet is
     covered the day it appears.
  2. A shell segment that carries an actual MUTATION CONSTRUCT and names a
     protected path in an argument position of that same segment. The
     constructs are enumerated in _MUTATORS, _REDIRECT and _INLINE_WRITE below.

A MENTION IS NOT A MUTATION. This is the failure this guard is most exposed to,
because the prose that documents it quotes its own protected paths. An early
credential-guard draft blocked its own commit message for quoting an example
(`security/posture.md` limit 5), and `hooks/git-staging-guard.py` carries the
same lesson. So four separate defences run before any path check:

  - PROSE heredoc bodies are stripped (a PR body is a heredoc),
  - the quoted value of a prose-bearing flag (`-m`, `--body`, `--title`, ...) is
    blanked, exactly as credential-guard does,
  - quoted spans are masked before the redirection scan, so a `>` inside a
    sentence is not read as a redirect,
  - and a path alone never blocks. The segment must ALSO carry a mutator, in a
    command position, with the path as one of its arguments.

A CODE heredoc is the exception, and it is the one place where stripping would
be a hole rather than a courtesy: `python - <<'PY'` carries a program, not a
message. The introducing line's leading command decides, so an interpreter or
shell heredoc keeps its body and every rule here is applied to it.

`tests/test_hook_tamper_guard.py` pins each of these from both sides.

INDIRECTION THROUGH A SHELL IS NOT INDIRECTION. `bash -c "<command>"`,
`pwsh -Command '<command>'` and `cmd /c <command>` hand over a whole command
that this file already knows how to judge, so the body is RE-CHECKED rather
than pattern-matched. That is different from `bash deploy.sh`, which is a file
this guard cannot see into and stays out of scope.

COPY DIRECTION, AND WHY MOVE IS NOT COPY. `cp <canonical> <deployed>` is the
deploy, and it is blocked: the destination is a live guard. `cp <deployed>
<backup>` is a backup, and it is allowed: the original stays in place. `mv` does
NOT get that exemption in either direction — a move out of the deployed tree
REMOVES the live guard, which is the same end state as a delete. Copy is judged
by destination; move is judged by both ends.

Override: add DEPLOY-OK to a Bash/PowerShell command for a deliberate, considered
sync of a canonical guard onto its deployed copy (mirrors credential-guard's
MASK-OK and git-staging-guard's STAGE-ALL-OK). The block reasons in this file
DO NOT NAME IT. That is a standing decision in this repo, taken after a guard
advertised its own override in a block message and the model read it back out
and used it. The token is documented for humans in `hooks/README.md`.

FAILS OPEN on a payload it cannot read, which is the exit contract every
canonical guard in this repo shares and is deliberate rather than inherited.
This is a `PreToolUse` hook in Claude Code, where a hook that refuses everything
wedges the session — and `conventions/hooks-gate-their-own-repair.md` records
that every repair route is itself a tool call the wedged hook would refuse. A
guard whose subject is the guard chain must not be the thing that makes the
chain unrepairable. The vendor adapters invert this for their OWN failures, and
that inversion stays where it is: a lane whose harness fails open silently needs
a fail-closed adapter, and this file is not one.

WHAT IT DOES NOT CATCH, stated rather than claimed closed:
  - an edit made outside an agent session. A person with a shell has already won,
    which is `security/posture.md`'s founding boundary.
  - indirection through a script the guard cannot see into (`bash deploy.sh`).
  - a mutation assembled at runtime from variables this file does not resolve.
    credential-guard resolves literal bindings; this guard does not, and a
    widening here must name what it adds.
  - the deployed copy of THIS file being deleted. Nothing running inside a hook
    can catch its own removal.

Exit 0 = allow, exit 2 = block (stderr surfaced to the model).
"""
import json
import re
import sys

# --- Protected targets ------------------------------------------------------
# Anchored to a HOME dot-config directory, which is what separates a deployed
# copy from a canonical source in an agent-ops clone. `~`, `$HOME`, `%USERPROFILE%`
# and an absolute home path all reduce to the same tail, so the patterns match
# the TAIL and never the home prefix — a literal user path cannot appear in this
# public repo anyway (scripts/redline-guard.py refuses it at commit time).
_SEP = r"[/\\]"

# A guard DIRECTORY is protected as well as the files in it. `rm -rf
# ~/.claude/hooks` and `rm ~/.claude/hooks/*` name no child file, and both
# disable a whole lane — so the child segment is optional and admits a glob.
# The `(?![\w-])` after each directory name stops `.claude/hooksfoo` matching.
_CHILD = r"(?![\w-])(?:" + _SEP + r"[\w.*?\[\]-]*)?"

_PROTECTED_PATTERNS = (
    # Claude Code: the deployed guard scripts and the wiring that registers them.
    r"\.claude" + _SEP + r"hooks" + _CHILD,
    r"\.claude" + _SEP + r"settings(\.local)?\.json",
    # Cursor: the native hook registration.
    r"\.cursor" + _SEP + r"hooks\.json",
    # Grok Build: the adapter, its reference config, and the compat toggle.
    r"\.grok" + _SEP + r"hooks" + _CHILD,
    r"\.grok" + _SEP + r"hooks\.json",
    r"\.grok" + _SEP + r"config\.toml",
    # Antigravity: the registration Antigravity reads.
    r"\.gemini" + _SEP + r"config" + _SEP + r"hooks\.json",
    # Pi: the guard extension and the agent settings that load it.
    r"\.pi" + _SEP + r"agent" + _SEP + r"extensions" + _CHILD,
    r"\.pi" + _SEP + r"agent" + _SEP + r"settings\.json",
)

# A path boundary before the dot-directory, so `my.claude/hooks/x` and a bare
# word ending in `.pi` cannot match. Mirrors credential-guard's _PREFIX.
_PATH_PREFIX = r"(^|[\s/\\'\"(),=:;@|>])"

PROTECTED_PATH = re.compile(
    _PATH_PREFIX + r"(?:[\w.~$%{}:-]*" + _SEP + r")*(?:"
    + r"|".join(_PROTECTED_PATTERNS) + r")",
    re.IGNORECASE,
)


def _names_protected_path(text):
    """True if `text` names a deployed guard-chain file."""
    if not isinstance(text, str):
        return False
    return bool(PROTECTED_PATH.search(text))


# --- Shell mutation constructs ----------------------------------------------
# A mutator must sit in a COMMAND POSITION — start of segment, or after a
# separator this guard's splitter did not already cut on. The splitter cuts on
# `;`, `|`, `&`, `&&`, `||` and newlines, so a leading-token test is enough.

# Verbs that modify or destroy a named file. `cp`/`mv`/`Copy-Item`/`Move-Item`
# are judged by DESTINATION (see _copy_targets_protected); the rest block on any
# protected argument.
_DESTROYERS = {
    "rm", "del", "erase", "unlink", "shred", "truncate", "rmdir",
    "remove-item", "ri", "rd", "clear-content", "rename-item", "ren", "rni",
    "new-item", "ni", "touch", "ln", "mklink", "chmod", "chown", "attrib",
    "set-content", "sc", "add-content", "ac", "out-file", "tee", "tee-object",
    "set-itemproperty", "new-itemproperty", "clear-itemproperty",
    "install", "patch", "dd", "curl", "wget", "invoke-webrequest", "iwr",
}
# Copy family: legal outward (a backup leaves the original in place), refused
# inward (a deploy replaces a live guard). Judged by DESTINATION only.
_COPIERS = {"cp", "copy", "copy-item", "cpi", "rsync", "install-item"}
# Move family: judged by BOTH ends. A move OUT of the deployed tree is not a
# backup - it REMOVES the live guard, which is the same end state as `rm`.
_MOVERS = {"mv", "move", "move-item", "mi"}
# Bulk mirrors whose argument grammar is not "source... destination":
# `robocopy <src-dir> <dst-dir> [file...]` puts the destination second, and
# `xcopy` carries mode flags in trailing positions. Rather than model three
# grammars, any protected argument blocks. These are rare enough that the
# conservative direction costs little, and guessing the grammar costs a hole.
_BULK_MIRRORS = {"robocopy", "xcopy"}

# In-place stream editors. `sed`/`perl` only mutate with an in-place flag; a
# plain `sed <file>` prints and is a read.
_INPLACE_FLAG = re.compile(r"(?:^|\s)-{1,2}(?:i|in-place)(?:[\w.=-]*)?(?=\s|$)")
_STREAM_EDITORS = {"sed", "gsed", "perl", "ruby"}

# Redirection into a path: `> x`, `>> x`, `1> x`, `Out-File x`, `Tee-Object x`.
_REDIRECT = re.compile(r"\d?>>?(?!&)\s*['\"]?([^\s'\"|;&]+)")

# A LANGUAGE interpreter one-liner. It is a mutation only when the body carries
# a write construct; `python -c "print(open(p).read())"` is a read and stays
# allowed.
_INTERPRETER = {"python", "python3", "py", "node", "nodejs", "ruby", "perl"}
# A SHELL wrapper takes a whole command as a string. `bash -c "rm <protected>"`
# was invisible while shells sat in _INTERPRETER, because `rm` is not a write
# construct any inline-write pattern names. The body is re-checked as a command
# instead of pattern-matched, so every rule in this file applies inside it.
_SHELL_WRAPPER = {"pwsh", "powershell", "bash", "sh", "zsh", "dash", "ksh",
                  "cmd", "cmd.exe"}
_SHELL_C_FLAG = re.compile(
    r"(?:^|\s)(?:-{1,2}(?:c|command|encodedcommand)|/c|/k)(?=\s|$)",
    re.IGNORECASE,
)
_INLINE_WRITE = re.compile(
    r"""open\s*\([^)]*['"][wax]b?\+?['"]|write_text|writeFileSync|writeFile"""
    r"""|\.write\s*\(|os\.remove|os\.unlink|os\.replace|os\.rename|shutil\."""
    r"""(?:copy|move|rmtree)|Path\([^)]*\)\s*\.\s*(?:unlink|write)"""
    r"""|Set-Content|Out-File|Remove-Item|Add-Content""",
    re.IGNORECASE,
)

# `git checkout -- <path>` / `git restore <path>` overwrite a working file. The
# deployed tree is not a repo on a provisioned machine, so this is belt-and-
# braces rather than a measured route, and it is deliberately narrow.
_GIT_WRITE_SUB = {"checkout", "restore", "clean", "apply", "mv", "rm"}


def _strip_heredocs(command):
    """Blank PROSE heredoc bodies, and keep CODE ones.

    A PR body or a commit message is a heredoc, and its text routinely quotes
    the very paths this guard protects — so `git commit -F - <<'EOF' ... EOF`
    must not be read as a command. But a heredoc fed to an interpreter is not
    prose at all: `python - <<'PY'` followed by `Path('<protected>').unlink()`
    is executable code, and dropping it would hide both the mutator and its
    target in one step.

    So the introducing line decides. Its leading command is an interpreter or a
    shell wrapper -> the body is kept and is offered to the checks as its own
    text. Anything else (`git`, `gh`, `cat`) -> the body is prose and is
    dropped. Returns (text_to_check, [code_bodies]).
    """
    kept, bodies, buf = [], [], []
    terminator, is_code = None, False
    for line in command.split("\n"):
        if terminator is not None:
            if line.strip() == terminator:
                if is_code:
                    bodies.append("\n".join(buf))
                terminator, is_code, buf = None, False, []
            elif is_code:
                buf.append(line)
            continue
        kept.append(line)
        m = re.search(r"<<-?\s*['\"]?([A-Za-z_]\w*)['\"]?", line)
        if m:
            terminator = m.group(1)
            lead = _leading_command(line[:m.start()])
            is_code = lead in _INTERPRETER or lead in _SHELL_WRAPPER
    if terminator is not None and is_code:      # unterminated: keep what we saw
        bodies.append("\n".join(buf))
    return "\n".join(kept), bodies


# Prose-bearing flags, copied in shape from credential-guard so the two guards
# agree about what counts as a message rather than a path.
_PROSE_FLAG = (
    r"--(?:message|title|body|description|desc|notes?|comment|summary"
    r"|subject|reason|caption)(?![\w-])"
    r"|(?<![\w-])-m(?![\w-])"
)
_PROSE_FLAG_VALUE = re.compile(
    r"(?:" + _PROSE_FLAG + r")\s*=?\s*"
    r"(\"[^\"\\]*(?:\\.[^\"\\]*)*\"|'[^']*')",
    re.IGNORECASE,
)


def _strip_prose_flag_values(seg):
    """Blank the quoted value of a prose-bearing flag, so a path named inside a
    commit message or a PR body is not read as an argument position."""
    return _PROSE_FLAG_VALUE.sub(lambda m: m.group(0).replace(m.group(1), '""'),
                                 seg)


def _split_segments(command):
    """Split on shell separators, but never inside quotes. A `|` or `&` inside a
    quoted message must not create a segment (credential-guard learned the same
    thing from a commit message that contained one)."""
    segs, buf, quote, i, n = [], [], None, 0, len(command)
    while i < n:
        c = command[i]
        if c == "\\" and quote != "'" and i + 1 < n:
            buf.append(c)
            buf.append(command[i + 1])
            i += 2
            continue
        if quote:
            buf.append(c)
            if c == quote:
                quote = None
            i += 1
            continue
        if c in ("'", '"'):
            quote = c
            buf.append(c)
            i += 1
            continue
        if command[i:i + 2] in ("&&", "||"):
            segs.append("".join(buf))
            buf = []
            i += 2
            continue
        if c in (";", "\n", "|", "&"):
            segs.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    segs.append("".join(buf))
    return segs


# `env` belongs here: `env rm <protected>` runs rm, and without this the leading
# command came back as `env` and nothing matched.
_WRAPPERS = {"sudo", "doas", "env", "command", "time", "nice", "nohup", "exec",
             "builtin", "then", "do", "else", "elif", "&", "\\"}
_ASSIGN = re.compile(r"^[A-Za-z_]\w*=")
# Wrapper options whose NEXT token is the option's value, not the command.
# `sudo -u root rm <path>` resolved to a leading command of `root` without
# this. A closed list, because guessing costs a missed mutator either way.
_WRAPPER_VALUE_FLAGS = {"-u", "--user", "-g", "--group", "-c", "--close-from",
                        "-n", "--adjustment", "-d", "--chdir", "-p", "--prompt",
                        "-h", "--host", "-r", "--role", "-t", "--type"}


def _tokens(seg):
    """Whitespace tokens of a segment, with surrounding quotes removed."""
    return [t.strip("'\"") for t in seg.split() if t.strip()]


def _skip_prefix(toks):
    """Index of the first token that is the command itself.

    Skips wrappers, env-var assignments, and any FLAG that precedes the command.
    The flag rule matters for `sudo -u root rm <protected>`: without it the
    leading command came back as `-u` and the segment matched nothing. A real
    command name never starts with `-`, so skipping leading flags cannot hide
    one.
    """
    i = 0
    while i < len(toks):
        tok = toks[i]
        low = tok.lower()
        if low in _WRAPPERS or _ASSIGN.match(tok):
            i += 1
            continue
        if tok.startswith("-"):
            i += 2 if (low in _WRAPPER_VALUE_FLAGS and "=" not in tok) else 1
            continue
        return i
    return len(toks)


def _leading_command(seg):
    """The command a segment actually runs, past wrappers, env prefixes, flags,
    and a leading interpreter path. Returns a lowercased bare name."""
    toks = _tokens(seg)
    i = _skip_prefix(toks)
    if i >= len(toks):
        return ""
    name = re.split(r"[/\\]", toks[i].lower())[-1]
    return name[:-4] if name.endswith(".exe") else name


def _arguments(seg):
    """Tokens after the leading command, flags included. A flag VALUE is an
    argument too, which is what makes `Out-File -FilePath <path>` visible."""
    toks = _tokens(seg)
    i = _skip_prefix(toks)
    return toks[i + 1:] if i < len(toks) else []


# Flags whose NEXT token is the flag's own value rather than a path position.
# Deliberately a closed list. An "any flag consumes the next token" rule looked
# conservative and was not: `cp source -f <protected>` skipped the destination
# as though it were `-f`'s value, and the deploy went through.
_VALUE_FLAGS = {
    "-t", "--target-directory", "-s", "--suffix", "--backup",
    "-destination", "-dest", "-path", "-literalpath", "-topath", "-filter",
    "-include", "-exclude", "-newname", "-erroraction", "-force:",
}
# Flags that NAME a destination, whatever the positional grammar is.
_DEST_FLAGS = {"-destination", "-dest", "-topath", "-t", "-newname",
               "--target-directory", "--destination"}


def _positional_arguments(seg):
    """Arguments with flags, and the value of a KNOWN value-taking flag,
    removed — used only where the DESTINATION position matters."""
    out, args, i = [], _arguments(seg), 0
    while i < len(args):
        tok = args[i]
        if tok.startswith("-"):
            name = tok.lower().split("=", 1)[0]
            if "=" not in tok and name in _VALUE_FLAGS and i + 1 < len(args):
                i += 2
                continue
            i += 1
            continue
        out.append(tok)
        i += 1
    return out


def _mask_quoted(seg):
    """`seg` with the CONTENT of every quoted span replaced by spaces.

    Used only by the redirection scan. `echo 'example: > <protected>'` writes
    nothing — the `>` is inside a quoted literal — but an unmasked scan read it
    as a redirect and blocked a sentence. Length is preserved so nothing else
    that indexes into the segment shifts.
    """
    out, quote = [], None
    i, n = 0, len(seg)
    while i < n:
        c = seg[i]
        if c == "\\" and quote != "'" and i + 1 < n:
            out.append("  ")
            i += 2
            continue
        if quote:
            out.append(" " if c != quote else c)
            if c == quote:
                quote = None
            i += 1
            continue
        if c in ("'", '"'):
            quote = c
            out.append(c)
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _copy_targets_protected(seg):
    """True if a copy writes INTO a protected path.

    The destination is the last positional argument for the POSIX forms and for
    `Copy-Item`; `-Destination <path>` names it explicitly, so the flag value is
    checked as well. A copy whose SOURCE alone is protected is a backup and
    stays allowed — see COPY DIRECTION in the module docstring.
    """
    positional = _positional_arguments(seg)
    if positional and _names_protected_path(positional[-1]):
        return True
    args = _arguments(seg)
    for idx, tok in enumerate(args):
        name, _, attached = tok.lower().partition("=")
        if name in _DEST_FLAGS:
            value = attached or (args[idx + 1] if idx + 1 < len(args) else "")
            if _names_protected_path(value):
                return True
    return False


def _redirects_into_protected(seg):
    """True if the segment redirects output into a protected path.

    Quoted spans are masked first: a `>` inside a quoted literal redirects
    nothing, and scanning the raw segment blocked ordinary prose.
    """
    return any(_names_protected_path(m.group(1))
               for m in _REDIRECT.finditer(_mask_quoted(seg)))


def _shell_wrapper_body(seg):
    """The command string a shell wrapper was handed, or None.

    `bash -c "<command>"`, `pwsh -Command '<command>'` and `cmd /c <command>`
    all run a whole command this guard already knows how to judge. Returning the
    body lets it be RE-CHECKED rather than pattern-matched, so every rule in
    this file applies inside the wrapper instead of only the ones an inline-
    write regex happens to name.
    """
    if _leading_command(seg) not in _SHELL_WRAPPER:
        return None
    m = _SHELL_C_FLAG.search(seg)
    if not m:
        return None
    body = seg[m.end():].strip()
    if len(body) >= 2 and body[0] == body[-1] and body[0] in "'\"":
        body = body[1:-1]
    return body or None


_MAX_WRAPPER_DEPTH = 4


def _segment_mutates_protected(seg, _depth=0):
    """True if this segment MUTATES a deployed guard-chain file.

    Requires both halves: a mutation construct in a command position, and a
    protected path among that command's arguments. Either half alone is allowed,
    which is what keeps prose and reads out of the block set.
    """
    seg = seg.strip()
    if not seg:
        return False

    # Redirection is judged on the whole segment: `echo x > <protected>` has a
    # harmless leading command and is still a write.
    if _redirects_into_protected(seg):
        return True

    lead = _leading_command(seg)
    if not lead:
        return False

    # A shell wrapper carries a whole command. Re-check it, so every rule here
    # applies inside `bash -c "..."` and `cmd /c ...` too.
    if lead in _SHELL_WRAPPER and _depth < _MAX_WRAPPER_DEPTH:
        body = _shell_wrapper_body(seg)
        if body:
            return any(_segment_mutates_protected(_strip_prose_flag_values(s),
                                                  _depth + 1)
                       for s in _split_segments(body))
        return False

    args = _arguments(seg)
    names_protected = any(_names_protected_path(a) for a in args)

    if lead in _COPIERS:
        return _copy_targets_protected(seg)

    if lead in _MOVERS:
        # BOTH ends. A move out of the deployed tree removes the live guard,
        # which is the same end state as a delete — it is not a backup.
        return names_protected

    if lead in _BULK_MIRRORS:
        return names_protected

    if lead in _DESTROYERS:
        return names_protected

    if lead in _STREAM_EDITORS:
        return names_protected and bool(_INPLACE_FLAG.search(seg))

    if lead in _INTERPRETER:
        # Only an inline program counts. `python deploy.py` is indirection this
        # guard cannot see into, and it is named as out of scope. A heredoc-fed
        # interpreter is handled separately, in _strip_heredocs.
        if not re.search(r"(?:^|\s)-{1,2}(?:c|e)(?=\s|$)", seg, re.IGNORECASE):
            return False
        return _names_protected_path(seg) and bool(_INLINE_WRITE.search(seg))

    if lead == "git":
        sub = next((a.lower() for a in args if not a.startswith("-")), "")
        return sub in _GIT_WRITE_SUB and names_protected

    return False


def _text_mutates_protected(text, _depth=0):
    """Split `text` into segments, blank prose values, and judge each one."""
    return any(
        _segment_mutates_protected(_strip_prose_flag_values(seg), _depth)
        for seg in _split_segments(text)
    )


# --- Tool-call shape --------------------------------------------------------
# Same construction as credential-guard: judge the FIELD NAME, not a fixed tool
# list, so a write tool nobody has enumerated yet is covered on the day it
# appears. That is the structural lesson of the 2026-07-04 tool-shape gap.
_PATH_FIELD_NAME = re.compile(
    r"path|file|dir|uri|src|source|dest|location|target", re.IGNORECASE
)
_WRITE_CONTENT_FIELD = re.compile(
    r"^(content|contents|text|file_text|new_str|new_string|new_source|"
    r"replacement|edits|patch|diff|changes)$", re.IGNORECASE
)
# A patch body names its own targets in header lines, so a tool that takes a
# whole diff carries the path nowhere a path-FIELD scan can see it. These are
# the header forms in unified diff, git's extended header, and the apply-patch
# envelope. Scanned only inside a content field, never over free prose.
_PATCH_TARGET = re.compile(
    r"^(?:\+\+\+|---)\s+(?:[ab]/)?(\S+)"
    r"|^diff --git\s+\S+\s+(\S+)"
    r"|^\*\*\*\s+(?:Update|Add|Delete)\s+File:\s*(\S+)",
    re.MULTILINE,
)
_WRITE_TOOL_NAME = re.compile(
    r"write|edit|create|update|replace|delete|remove|rename|move|notebook",
    re.IGNORECASE
)
_REMOTE_URL = re.compile(r"^https?://", re.IGNORECASE)


def _patch_targets_protected(text):
    """True if a diff/patch body names a protected path in a HEADER line.

    Header lines only. A protected path quoted inside an added or removed line
    is content, and blocking on it would refuse a patch that merely documents
    the guard — the same false positive the prose rules exist to prevent.
    """
    if not isinstance(text, str):
        return False
    for match in _PATCH_TARGET.finditer(text):
        target = next((g for g in match.groups() if g), "")
        if target and target != "/dev/null" and _names_protected_path(target):
            return True
    return False


def _field_targets_protected(obj, key_is_pathy=False):
    """Recursively true if a path-named field targets a deployed guard file.

    `key_is_pathy` carries the enclosing key's path-ness into list elements, so
    `{"paths": ["~/.claude/hooks/credential-guard.py"]}` is seen.

    A CONTENT field is never treated as a path, even when its name contains
    `source` or `file`. `_PATH_FIELD_NAME` matches substrings, so `new_source`
    and `file_text` both looked pathy — and a notebook cell that merely
    documents a protected path was blocked. A content field is instead scanned
    as a PATCH, which is precise about what a diff actually modifies.
    """
    if isinstance(obj, str):
        if _REMOTE_URL.match(obj.strip()):
            # A public URL that happens to spell a protected path is a remote
            # resource, not this machine's guard chain (credential-guard v2.12
            # closed the same false positive).
            return False
        return key_is_pathy and _names_protected_path(obj)
    if isinstance(obj, list):
        return any(_field_targets_protected(x, key_is_pathy) for x in obj)
    if isinstance(obj, dict):
        for key, value in obj.items():
            if _WRITE_CONTENT_FIELD.match(str(key)):
                if _patch_targets_protected(value):
                    return True
                continue
            if _field_targets_protected(
                    value, key_is_pathy or bool(_PATH_FIELD_NAME.search(str(key)))):
                return True
        return False
    return False


def _is_write_shaped(tool_name, tool_input):
    """True if this tool call MODIFIES its target rather than reading it.

    Unlike credential-guard's function of the same name, this one CHOOSES A
    VERDICT rather than a wording: a read of a deployed guard is allowed. Keyed
    on the payload first and the tool name second, for the reason above.
    """
    if any(_WRITE_CONTENT_FIELD.match(str(k)) for k in tool_input):
        return True
    return bool(_WRITE_TOOL_NAME.search(str(tool_name or "")))


# --- Verdicts ---------------------------------------------------------------
# THIS STRING IS AGENT-FACING. The harness hands stderr to the model verbatim,
# so it is read by the party actively looking for a way past the block. It does
# NOT name the override (repo standing decision, commit 7ac9048): a guard that
# hands over its own bypass at the worst possible moment erodes itself. What it
# says instead is the action actually wanted — stop, and ask the operator.
_MSG = (
    "HOOK TAMPER GUARD: this MODIFIES a deployed guard-chain file (a hook script\n"
    "under a harness config directory, or the settings that register it).\n"
    "Under agent-ops ADR-012 guard wiring is the whole of the fleet's safety\n"
    "control, so disarming a guard is not an edit an agent makes on its own -\n"
    "and a guard file that has been quietly changed gives false coverage, which\n"
    "is worse than no guard at all.\n"
    "The CANONICAL sources in the agent-ops clone are not protected by this\n"
    "guard. Change a guard there, open a pull request, and let the deploy be a\n"
    "separate step a person runs.\n"
    "Reading these files is allowed; only writing them is refused.\n"
    "If this is genuinely necessary, STOP and ask the operator to authorise it.\n"
    "Do not work around this block.\n"
)


def block():
    sys.stderr.write(_MSG)
    sys.exit(2)


def _allow(payload):
    """Allow. cursor-agent marks an empty-stdout hook run as failed and its
    imported-hook wiring is hardcoded failClosed=false, so a Cursor payload gets
    an explicit verdict; every other harness gets a bare exit 0 so its stdout
    contract is untouched (credential-guard v2.8 measured this)."""
    if isinstance(payload, dict) and "cursor_version" in payload:
        print('{"permission": "allow"}')
    sys.exit(0)


def main():
    """PreToolUse hook: allow (exit 0) or block (exit 2) the tool call on stdin."""
    try:
        # utf-8-sig: a PowerShell wrapper prepends a BOM, and a strict decode
        # turned credential-guard v2.7 into a silent no-op on every call.
        data = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    except Exception:
        sys.exit(0)                       # fail open — see the module docstring
    if not isinstance(data, dict):
        sys.exit(0)

    tool_name = data.get("tool_name")
    tool_input = data.get("tool_input", {})
    if not isinstance(tool_input, dict):
        tool_input = {}

    if tool_name in ("Bash", "PowerShell", "Shell"):
        command = tool_input.get("command", "")
        if not isinstance(command, str) or not command:
            _allow(data)
        if "DEPLOY-OK" in command:
            _allow(data)
        outer, code_bodies = _strip_heredocs(command)
        if _text_mutates_protected(outer):
            block()
        # A heredoc fed to an interpreter or a shell is CODE, not a message. It
        # is judged on its own rather than dropped with the prose bodies.
        for body in code_bodies:
            if _text_mutates_protected(body) or (
                    _names_protected_path(body) and _INLINE_WRITE.search(body)):
                block()
        _allow(data)

    # Readers return content, never modify it. credential-guard governs the
    # reads that carry an exposure; this guard has nothing to add to them.
    if tool_name in ("Read", "Grep", "Glob"):
        _allow(data)

    if _is_write_shaped(tool_name, tool_input) and _field_targets_protected(tool_input):
        block()
    _allow(data)


if __name__ == "__main__":
    main()
