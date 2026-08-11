#!/usr/bin/env python3
# hook-version: 1.2 (2026-08-11) — two measured bypasses of the v1.0 matcher,
# both of which stage the whole tree and both of which exited 0 before this
# change: `git stage -A` (`stage` is a built-in synonym for `add`, and only
# `add` was matched) and `git add -Au` (a combined short flag; only the exact
# tokens `-A` and `-u` were matched). The `commit` branch had already handled
# combined shorts via `-am`; the `add` branch had not. Same failure shape as
# every other guard in this repo: the matcher covered the surface its author
# enumerated, not the surface that existed.
# 1.1 (2026-08-04) — cursor-agent compatibility: BOM-tolerant
# stdin (its Windows PowerShell wrapper prepends a UTF-8 BOM that made
# json.load raise, failing the guard open), its shell tool's name "Shell"
# accepted alongside Bash/PowerShell, and an explicit allow verdict on stdout
# for Cursor payloads (it marks empty-stdout runs failed, and imports hooks
# failClosed=false). See security/credential-guard.py 2.8 and
# vendors/cursor/README.md "Guard wiring" for the measurements.
# 1.0 (2026-07-19)
"""Git staging guard (global PreToolUse hook) — no whole-tree staging.

WHY. San runs several Claude sessions at once across sibling repos and two
machines. A repo's working tree routinely holds uncommitted work that the
current session did not create and cannot see the purpose of. ``git add -A`` /
``-u`` / ``.`` and ``git commit -a`` stage *whatever is dirty*, not *what I
changed*, so they silently sweep another session's in-flight work into an
unrelated commit.

This happened twice on 2026-07-18/19:

  - ``git add -A`` committed a nested repository's gitlink that the session had
    never touched (fixed with ``git rm --cached`` in a follow-up).
  - ``git add -u`` swept six files of another session's in-flight work — one of
    them a couple of thousand lines — into a one-line docs commit, which then
    went to the default branch. Left in place with a ``git notes`` scope
    correction rather than rewriting a branch other machines may have pulled.

Neither was destructive. Both were avoidable. The second happened *after* the
first was already a known lesson in the same session, which is the actual
finding: this is a reflex, and a behavioural rule has now failed twice. The
durable fix for a reflex is a mechanism, not an intention.

WHAT IS BLOCKED. Only whole-tree staging:

    git add   -A | --all | -u | --update | .
    git stage -A | --all | -u | --update | .   (`stage` is a git synonym for `add`)
    git add   -Au | -fA | … (any combined short flag containing 'A' or 'u')
    git commit -a | --all | -am (any combined short flag containing 'a')

WHAT IS NOT. Explicit paths — ``git add src/api.py tests/test_api.py`` — which
is the correct habit this leaves as the path of least resistance. Also fine:
``git commit -m``, ``git add -p``, ``git -C <repo> add <path>``, and every
other git subcommand.

FALSE-POSITIVE DISCIPLINE. The credential guard's v1 blocked its own commit
message for quoting an example, and that lesson is inherited here — this hook
was written on a day whose commit messages repeatedly quote ``git add -u`` as
the thing that went wrong. So:

  - heredoc BODIES are stripped before scanning (commit messages live there);
  - a flag only counts in an actual command position, after a leading ``git``;
  - quoted strings are not command positions, so ``-m "used git add -A"`` and
    ``echo 'git add -A'`` both pass.

OVERRIDE. Prefix the command with ``STAGE-ALL-OK`` when whole-tree staging is
genuinely correct — a fresh repo's first commit, or a tree you have just
verified is exclusively yours. It is deliberately a per-command opt-in, not a
setting: the point is that the decision gets made rather than defaulted.
"""

from __future__ import annotations

import json
import re
import shlex
import sys

OVERRIDE = "STAGE-ALL-OK"

# Heredoc bodies are prose (commit messages, PR bodies). Strip them first, or
# this hook blocks the very commits that document why it exists.
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1.*?^\2\s*$", re.DOTALL | re.MULTILINE)

# Shell segment separators. A compound command is scanned segment by segment so
# `git status && git add -A` is caught in its second half.
_SPLIT = re.compile(r"&&|\|\||[;\n|&]")

_ADD_WHOLE_TREE = {"-A", "--all", "-u", "--update", "--no-ignore-removal"}

# `git stage` is a built-in synonym for `git add` — same options, same effect.
# v1.0 matched the subcommand name rather than the operation, so `git stage -A`
# passed. Match both names.
_ADD_SUBCOMMANDS = {"add", "stage"}

# Short options of `git add` whose presence means "the whole tree", wherever
# they appear in a combined short flag. `git add -Au` is valid and stages
# everything; v1.0 compared whole tokens, so it saw an unknown flag and allowed
# it. No other `git add` short option uses these letters (`-n`, `-N`, `-f`,
# `-i`, `-p`, `-e`, `-v`), so a letter match here cannot collide.
_ADD_WHOLE_TREE_LETTERS = set("Au")


def _strip_prose(command: str) -> str:
    """Remove heredoc bodies so quoted prose is never read as a command."""
    return _HEREDOC.sub(" ", command)


def _tokens(segment: str) -> list[str]:
    """Tokenize one segment, tolerating unbalanced quotes.

    shlex is used so that quoted text collapses into single tokens: a flag
    inside a quoted string is then a token *value*, never a command-position
    flag, which is what keeps `-m "swept by git add -u"` passing.
    """
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        try:
            return shlex.split(segment + '"', posix=True)
        except ValueError:
            return segment.split()


def _git_invocation(tokens: list[str]) -> list[str] | None:
    """Return the tokens after `git` (and any global flags), or None if not git."""
    if not tokens:
        return None
    lead = tokens[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if lead not in {"git", "git.exe"}:
        return None
    rest = tokens[1:]
    # Skip global flags that take a value (-C <path>, -c <k=v>) and bare ones.
    while rest:
        if rest[0] in {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}:
            rest = rest[2:]
        elif rest[0].startswith("-"):
            rest = rest[1:]
        else:
            break
    return rest


def _offence(tokens: list[str]) -> str | None:
    """Return a description of the whole-tree staging offence, or None."""
    rest = _git_invocation(tokens)
    if not rest:
        return None
    sub, args = rest[0], rest[1:]

    # `--` ends option parsing; everything after it is a pathspec, which is the
    # explicit form this hook wants people to use.
    if "--" in args:
        args = args[: args.index("--")]

    if sub in _ADD_SUBCOMMANDS:
        for arg in args:
            if arg in _ADD_WHOLE_TREE:
                return f"git {sub} {arg}"
            if arg == ".":
                return f"git {sub} ."
            # Combined short flags: `-Au`, `-fA`. A single leading dash, no
            # second dash (so `--amend`-shaped long options never reach here),
            # letters only, and one of them means whole-tree.
            if (
                len(arg) > 2
                and arg[0] == "-"
                and arg[1] != "-"
                and arg[1:].isalpha()
                and _ADD_WHOLE_TREE_LETTERS & set(arg[1:])
            ):
                return f"git {sub} {arg}"
        return None

    if sub == "commit":
        for arg in args:
            if arg in {"-a", "--all"}:
                return f"git commit {arg}"
            # Combined short flags: -am, -av, -amend is NOT a thing (--amend is
            # long-form), so a leading single dash with 'a' among the letters.
            if (
                len(arg) > 1
                and arg[0] == "-"
                and arg[1] != "-"
                and "a" in arg[1:]
                and arg[1:].isalpha()
            ):
                return f"git commit {arg}"
        return None

    return None


MESSAGE = """GIT STAGING GUARD: `{offence}` stages whatever is dirty, not what you changed.

Parallel Claude sessions leave uncommitted work in these trees that this session
did not create. On 2026-07-18/19 this exact shape twice swept another session's
work into an unrelated commit - the second time onto the default branch, after
the first was already a known lesson in the same session.

Do this instead:
    git -C <repo> status --porcelain          # look at what is actually dirty
    git -C <repo> add path/one path/two       # name the files you changed
    git -C <repo> show --stat HEAD            # confirm the commit's scope

If whole-tree staging really is correct here (a fresh repo's first commit, or a
tree you have just verified is exclusively yours), prefix the command with
{override} - a per-command decision, on purpose.
"""


def _allow(payload) -> None:
    """Allow (exit 0), with an explicit stdout verdict for Cursor payloads —
    cursor-agent marks an empty-stdout hook run as failed and fails open."""
    if isinstance(payload, dict) and "cursor_version" in payload:
        print('{"permission": "allow"}')
    sys.exit(0)


def main() -> None:
    """Block whole-tree staging in Bash/PowerShell/Shell commands."""
    try:
        # utf-8-sig: cursor-agent's Windows wrapper pipes the payload with a
        # leading BOM; json.load on the text stream raised and failed open.
        data = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        sys.exit(0)  # Never fail a tool call because the hook could not parse.

    # "Shell" is cursor-agent's single shell tool, same tool_input shape.
    if data.get("tool_name") not in {"Bash", "PowerShell", "Shell"}:
        _allow(data)

    command = data.get("tool_input", {}).get("command", "")
    if not isinstance(command, str) or not command.strip():
        _allow(data)

    if OVERRIDE in command:
        _allow(data)

    for segment in _SPLIT.split(_strip_prose(command)):
        offence = _offence(_tokens(segment.strip()))
        if offence:
            sys.stderr.write(MESSAGE.format(offence=offence, override=OVERRIDE))
            sys.exit(2)

    _allow(data)


if __name__ == "__main__":
    main()
