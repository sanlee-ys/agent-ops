#!/usr/bin/env python3
# hook-version: 1.1 (2026-08-04) — cursor-agent compatibility: BOM-tolerant
# stdin (its Windows PowerShell wrapper prepends a UTF-8 BOM that made
# json.load raise, failing the guard open), its shell tool's name "Shell"
# accepted alongside Bash/PowerShell, and an explicit allow verdict on stdout
# for Cursor payloads (it marks empty-stdout runs failed, and imports hooks
# failClosed=false). See security/credential-guard.py 2.8 and
# vendors/cursor/README.md "Guard wiring" for the measurements.
# 1.0 (2026-07-26)
"""Published-history guard (global PreToolUse hook) — don't drop published commits from `main`.

WHY. On 2026-07-26 two sessions worked one direct-to-main repo — so no PR gate
anywhere — in the same clone. Session A committed `4278c51` and pushed it.
Session B, holding an older idea of where `main` was, ran
`git reset --soft de133f2`, recommitted its own work, and force-pushed over the
top. Session A's commit was recovered only because it was still in the reflog
and could be cherry-picked back. Nothing announced the loss — it surfaced when a
later edit could not find its own text.

WHAT THE EXISTING GATES COULD NOT SEE. Both halves of that sequence looked
locally correct, and both were correctly allowed:

  - `git reset --soft` destroys nothing on disk. Session B even tagged a backup
    first. The auto-mode classifier blocks resets under the heading
    "[Irreversible Local Destruction]", and a soft reset is honestly not that.
  - `git push --force-with-lease` was, at the time, absent from the force-push
    `ask` rules (which listed `--force` and `-f` only), so it fell through to the
    `git push` allow rule. Its lease then *passed*, because a background fetch
    had already refreshed the tracking ref — the failure mode San had recorded
    the same day.

The fact that would have condemned both commands — *the range you are dropping
contains a commit you did not write, and it is already on the remote* — is not
in the command string. It is in the repository. No prefix rule and no classifier
reading the command can reach it, which is why this guard is stateful: it asks
git, at the moment of the call.

WHAT IS BLOCKED. Two shapes, one invariant (`main` only — see below):

  1. A **history-rewriting push** (`--force`, `-f`, `--force-with-lease[=...]`,
     `--force-if-includes`, a `+refspec`, or `--mirror`) that would drop commits
     the remote currently has.
  2. A **backward `git reset`** whose discarded range contains commits that are
     already published. This is the earlier and cheaper catch: it fires before
     the session builds anything on a doomed base. In the incident it would have
     fired 49 seconds before the destructive push.

GROUND TRUTH IS `ls-remote`, NOT THE TRACKING REF. The tracking ref is what
defeated `--force-with-lease` here, so the guard never consults it. It asks the
remote directly — the same discipline ADR-004's regression suite adopted, for
the same reason: a local ref can look correct when the remote has moved.

`main` ONLY, DELIBERATELY. A force-push to a feature branch is one session's own
lane, is the normal way to clean up a PR, and merge-deletes anyway. Guarding it
would generate constant noise for no risk and get the whole hook routed around.
The exposure this exists for is the direct-to-main repo, where there is no PR
gate and every session pushes to the one shared ref. Non-`main` refs pass
silently.

FAIL OPEN, WITH ONE STATED EXCEPTION. Unparseable payload, no git binary, not a
repo, an unrecognised command — every one of those exits 0. A hook must not
break unrelated work. The exception: when the guard has positively identified a
rewrite of `main` but *cannot verify* what it would destroy (no network, no
auth, a ref that will not resolve), it blocks. Failing open there would reopen
the exact hole it was written to close, and the override is one token away.

OVERRIDE. Prefix the command with `REWRITE-MAIN-OK` when dropping published
commits is genuinely the intent — San's de-identification squash of `career` on
2026-06-30 is the standing example of a legitimate one. Per-command on purpose,
like `STAGE-ALL-OK`: the point is that the decision gets made rather than
defaulted.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys

OVERRIDE = "REWRITE-MAIN-OK"

# The one ref worth guarding. See the module docstring.
PROTECTED_BRANCH = "main"

# Local git calls are cheap; ls-remote crosses the network.
LOCAL_TIMEOUT = 5
REMOTE_TIMEOUT = 12

# Never print an unbounded wall of commits into a hook message.
MAX_LISTED = 12

# Heredoc bodies are prose — commit messages and PR bodies quoting the very
# commands this guard blocks. Strip them before scanning, per the lesson
# git-staging-guard.py inherited from credential-guard's v1.
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1.*?^\2\s*$", re.DOTALL | re.MULTILINE)

_SPLIT = re.compile(r"&&|\|\||[;\n|&]")

_FORCE_FLAGS = {"--force", "-f", "--force-if-includes", "--mirror"}

# Flags that take a separate value, so the next token is not a positional.
_PUSH_VALUE_FLAGS = {"--repo", "-o", "--push-option", "--exec", "--receive-pack"}


def _strip_prose(command: str) -> str:
    return _HEREDOC.sub(" ", command)


def _dequote(token: str) -> str:
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        return token[1:-1]
    return token


def _tokens(segment: str) -> list[str]:
    """Tokenize one segment, tolerating unbalanced quotes.

    NON-POSIX MODE, DELIBERATELY. `shlex` in posix mode treats a backslash as
    an escape character and silently eats it, so a Windows-style
    `git -C D:\\work\\repo push --force` tokenizes with the repo path mangled
    into `D:workrepo`. The repo then fails to resolve and the guard waves the
    command through — failing *open* on the single most dangerous shape it
    exists to catch, on the platform this actually runs on. Non-posix mode
    keeps backslashes intact; quotes survive on the token and are stripped
    here instead.

    The property this shares with posix mode is the one that matters: a quoted
    string stays a single token, so a flag inside `-m "... push --force ..."`
    is a token *value* and never a command-position flag.
    """
    for candidate in (segment, segment + '"'):
        try:
            return [_dequote(t) for t in shlex.split(candidate, posix=False)]
        except ValueError:
            continue
    return [_dequote(t) for t in segment.split()]


def _git_invocation(tokens: list[str]) -> tuple[str | None, list[str]] | None:
    """Return (repo_dir_from_-C, tokens_after_git) or None if not a git call."""
    if not tokens:
        return None
    lead = tokens[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if lead not in {"git", "git.exe"}:
        return None
    repo_dir: str | None = None
    rest = tokens[1:]
    while rest:
        if rest[0] == "-C" and len(rest) > 1:
            repo_dir = rest[1]
            rest = rest[2:]
        elif rest[0] in {"-c", "--git-dir", "--work-tree", "--namespace"}:
            rest = rest[2:]
        elif rest[0].startswith("-"):
            rest = rest[1:]
        else:
            break
    return repo_dir, rest


def git(repo: str | None, *args: str, timeout: int = LOCAL_TIMEOUT) -> str | None:
    """Run a read-only git command. None on any failure."""
    cmd = ["git"]
    if repo:
        cmd += ["-C", repo]
    cmd += list(args)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _is_ancestor(repo: str | None, older: str, newer: str) -> bool | None:
    """True/False, or None when the question could not be answered."""
    cmd = ["git"]
    if repo:
        cmd += ["-C", repo]
    cmd += ["merge-base", "--is-ancestor", older, newer]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=LOCAL_TIMEOUT)
    except Exception:
        return None
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    return None


def _remote_head(repo: str | None, remote: str, branch: str) -> str | None:
    """The remote's actual tip for ``branch``, straight from the remote.

    Deliberately not the tracking ref: a stale-then-refreshed tracking ref is
    what let `--force-with-lease` through in the incident this guard exists for.
    """
    out = git(repo, "ls-remote", remote, f"refs/heads/{branch}", timeout=REMOTE_TIMEOUT)
    if out is None:
        return None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == f"refs/heads/{branch}":
            return parts[0]
    return ""  # reached the remote; the branch simply is not there yet


def _ensure_local(repo: str | None, remote: str, branch: str, sha: str) -> bool:
    """Make ``sha`` inspectable locally, fetching once if need be.

    A clone that has not fetched since the remote moved does not hold the
    remote tip, and every ancestry question about it then answers "unknown" —
    which, without this, the guard reads as "nothing published is at risk". In
    the incident the resetting session was in exactly that state, so this is
    not a corner case: it is the state the guard is most often called in.
    """
    if git(repo, "cat-file", "-e", f"{sha}^{{commit}}") is not None:
        return True
    git(repo, "fetch", "--quiet", remote, branch, timeout=REMOTE_TIMEOUT)
    return git(repo, "cat-file", "-e", f"{sha}^{{commit}}") is not None


def _describe(repo: str | None, rev_range: str, limit: int = MAX_LISTED) -> list[str]:
    out = git(repo, "log", "--format=%h %an  %s", f"-{limit}", rev_range)
    return out.splitlines() if out else []


def _current_branch(repo: str | None) -> str | None:
    return git(repo, "rev-parse", "--abbrev-ref", "HEAD")


def _push_target(args: list[str]) -> tuple[str, str | None, bool]:
    """(remote, branch_or_None, rewrites) parsed from `git push` arguments."""
    rewrites = False
    positionals: list[str] = []
    skip_next = False
    for arg in args:
        if skip_next:
            skip_next = False
            continue
        if arg in _PUSH_VALUE_FLAGS:
            skip_next = True
            continue
        if arg in _FORCE_FLAGS or arg.startswith("--force-with-lease"):
            rewrites = True
            continue
        if arg.startswith("-"):
            continue
        positionals.append(arg)

    remote = positionals[0] if positionals else "origin"
    branch: str | None = None
    if len(positionals) > 1:
        refspec = positionals[1]
        if refspec.startswith("+"):
            rewrites = True
            refspec = refspec[1:]
        # src:dst — the remote-side name is what matters.
        branch = refspec.split(":")[-1] if refspec else None
        if branch:
            branch = branch.rsplit("/", 1)[-1] if branch.startswith("refs/") else branch
    return remote, branch, rewrites


class Verdict:
    """A block decision plus the text explaining it."""

    def __init__(self, message: str) -> None:
        self.message = message


def _check_push(repo: str | None, args: list[str]) -> Verdict | None:
    remote, branch, rewrites = _push_target(args)
    if not rewrites:
        return None  # a plain push cannot destroy remote history; git refuses it

    if branch is None:
        branch = _current_branch(repo)
    if branch != PROTECTED_BRANCH:
        return None  # feature branches are one session's own lane

    remote_sha = _remote_head(repo, remote, branch)
    if remote_sha is None:
        return Verdict(
            _CANNOT_VERIFY.format(
                action=f"force-push to {remote}/{branch}",
                reason=f"`git ls-remote {remote}` did not answer",
                override=OVERRIDE,
            )
        )
    if remote_sha == "":
        return None  # branch does not exist on the remote; nothing to destroy

    local = git(repo, "rev-parse", "HEAD")
    if local is None:
        return None  # not a usable repo; stay out of the way

    if not _ensure_local(repo, remote, branch, remote_sha):
        return Verdict(
            _CANNOT_VERIFY.format(
                action=f"force-push to {remote}/{branch}",
                reason=f"the remote tip {remote_sha[:9]} could not be fetched for inspection",
                override=OVERRIDE,
            )
        )

    ancestor = _is_ancestor(repo, remote_sha, local)
    if ancestor is True:
        return None  # fast-forward; --force is redundant but harmless
    if ancestor is None:
        return Verdict(
            _CANNOT_VERIFY.format(
                action=f"force-push to {remote}/{branch}",
                reason="the local/remote relationship could not be determined",
                override=OVERRIDE,
            )
        )

    dropped = _describe(repo, f"{local}..{remote_sha}")
    return Verdict(
        _PUSH_BLOCK.format(
            remote=remote,
            branch=branch,
            count=len(dropped),
            plural="" if len(dropped) == 1 else "s",
            listing="\n".join(f"    {line}" for line in dropped) or "    (unreadable)",
            override=OVERRIDE,
        )
    )


def _check_reset(repo: str | None, args: list[str]) -> Verdict | None:
    targets = [a for a in args if not a.startswith("-")]
    if "--" in args:  # `git reset -- <paths>` is a pathspec unstage, not a move
        return None
    if not targets:
        return None  # bare `git reset` unstages; it does not move the branch

    branch = _current_branch(repo)
    if branch != PROTECTED_BRANCH:
        return None

    target = targets[0]
    head = git(repo, "rev-parse", "HEAD")
    if head is None or git(repo, "rev-parse", "--verify", f"{target}^{{commit}}") is None:
        return None  # cannot resolve; not this hook's business to guess

    out = git(repo, "rev-list", f"{target}..HEAD")
    if not out:
        return None  # nothing leaves the branch

    dropping = out.splitlines()

    remote_sha = _remote_head(repo, "origin", branch)
    if remote_sha is None:
        return Verdict(
            _CANNOT_VERIFY.format(
                action=f"reset of {branch} back to {target}",
                reason="`git ls-remote origin` did not answer",
                override=OVERRIDE,
            )
        )
    if remote_sha == "":
        return None

    if not _ensure_local(repo, "origin", branch, remote_sha):
        return Verdict(
            _CANNOT_VERIFY.format(
                action=f"reset of {branch} back to {target}",
                reason=f"the remote tip {remote_sha[:9]} could not be fetched for inspection",
                override=OVERRIDE,
            )
        )

    published = [c for c in dropping if _is_ancestor(repo, c, remote_sha) is True]
    if not published:
        return None  # your own unpushed work; the reflog has you covered

    listing = _describe(repo, f"{target}..HEAD")
    ahead = git(repo, "rev-list", "--count", f"HEAD..{remote_sha}") or "?"
    return Verdict(
        _RESET_BLOCK.format(
            branch=branch,
            target=target,
            count=len(published),
            plural="" if len(published) == 1 else "s",
            listing="\n".join(f"    {line}" for line in listing) or "    (unreadable)",
            ahead=ahead,
            remote=remote_sha[:9],
            override=OVERRIDE,
        )
    )


_PUSH_BLOCK = """PUBLISHED-HISTORY GUARD: this force-push would delete {count} commit{plural} from {remote}/{branch}.

Already on the remote, and gone if this proceeds:
{listing}

Another session may have written these, and may already have pulled them. On
2026-07-26 this exact shape erased a sibling session's commit in `career`; it was
recovered from the reflog by luck, not by design.

If your branch has diverged, rebase onto the remote instead of overwriting it:
    git -C <repo> pull --rebase        # replay your work on top of theirs
    git -C <repo> log --oneline -5     # confirm both sides survived
    git -C <repo> push                 # a plain push now suffices

If dropping those published commits really is the intent - a deliberate history
rewrite, like the de-identification squash - prefix the command with {override}.
"""

_RESET_BLOCK = """PUBLISHED-HISTORY GUARD: this reset would drop {count} published commit{plural} from {branch}.

`git reset ... {target}` discards these, and the remote already has them:
{listing}

origin/{branch} is at {remote} and is {ahead} commit(s) ahead of you, so this
branch has diverged - another session pushed while you were working. Resetting
does not resolve that; it just builds your next commits on a base the remote has
moved past, and the force-push that follows is what destroys their work.

Rebase onto what the remote has instead:
    git -C <repo> pull --rebase        # replay your work on top of theirs
    git -C <repo> log --oneline -5     # confirm both sides survived

If you are deliberately rewriting published history, prefix with {override}.
"""

_CANNOT_VERIFY = """PUBLISHED-HISTORY GUARD: cannot verify what this {action} would destroy.

{reason}, so the guard cannot tell whether commits from another session are
about to be dropped from `main`.

This is the one case where the guard fails closed rather than open: the whole
point of it is that this operation is unrecoverable once it lands, and "the
network was down" is not a reason to find out afterwards.

Check the remote by hand, or - if you are confident - prefix with {override}.
"""


def _allow(payload) -> None:
    """Allow (exit 0), with an explicit stdout verdict for Cursor payloads —
    cursor-agent marks an empty-stdout hook run as failed and fails open."""
    if isinstance(payload, dict) and "cursor_version" in payload:
        print('{"permission": "allow"}')
    sys.exit(0)


def main() -> None:
    try:
        # utf-8-sig: cursor-agent's Windows wrapper pipes the payload with a
        # leading BOM; json.load on the text stream raised and failed open.
        data = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        sys.exit(0)

    # "Shell" is cursor-agent's single shell tool, same tool_input shape.
    if data.get("tool_name") not in {"Bash", "PowerShell", "Shell"}:
        _allow(data)

    command = data.get("tool_input", {}).get("command", "")
    if not isinstance(command, str) or not command.strip():
        _allow(data)

    if OVERRIDE in command:
        _allow(data)

    cwd = data.get("cwd") or None

    for segment in _SPLIT.split(_strip_prose(command)):
        parsed = _git_invocation(_tokens(segment.strip()))
        if not parsed:
            continue
        repo_dir, rest = parsed
        if not rest:
            continue
        repo = repo_dir or cwd
        sub, args = rest[0], rest[1:]

        try:
            if sub == "push":
                verdict = _check_push(repo, args)
            elif sub == "reset":
                verdict = _check_reset(repo, args)
            else:
                continue
        except Exception:
            continue  # a guard that crashes must not take the session with it

        if verdict:
            sys.stderr.write(verdict.message)
            sys.exit(2)

    _allow(data)


if __name__ == "__main__":
    main()
