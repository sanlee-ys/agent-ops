#!/usr/bin/env python3
# hook-version: 1.2 (2026-08-09) — the invariant check is no longer reachable
# from only `push` and `reset`. An audit found six other ways to drop a
# published commit from `main` (amend, rebase, branch -f/-M, checkout -B /
# switch -C, update-ref, filter-branch/filter-repo, and a remote-branch
# delete), every one of them uninspected. Rather than add six verb-specific
# checks — the move ADR-007 exists to reject — every guarded verb is now
# *normalised* into one `Rewrite` record and a single invariant check decides.
# See "ONE INVARIANT, MANY SPELLINGS" below.
# 1.1 (2026-08-04) — cursor-agent compatibility: BOM-tolerant
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

ONE INVARIANT, MANY SPELLINGS. v1.0 dispatched on two subcommands, `push` and
`reset`, and that was the shape ADR-007 warned against: a verb list is a list of
the ways somebody already thought of. `git commit --amend` on a pushed commit is
an ordinary slip, and it walked straight through. So did `git rebase -i HEAD~3`,
`git branch -f main <sha>`, `git checkout -B main <sha>`,
`git update-ref refs/heads/main <sha>`, `git filter-branch`, and
`git push --delete origin main`.

The fix is structural, not additive. Every one of those commands does the same
thing to the repository:

    `main`'s tip moves from OLD to NEW, and any commit reachable from OLD but
    not from NEW leaves the branch.

So each verb now has one job — *translate its own syntax into that sentence* —
and returns a `Rewrite(old, new, ...)`. Reading the syntax is unavoidably
per-verb; only git knows that `-M` takes its destination last. But the
**decision** is made exactly once, in `_check_rewrite`, and it is verb-blind: it
asks the repository which of the departing commits the remote already has. Add a
seventh spelling tomorrow and it writes an extractor, not a check.

A deletion (`push --delete`, `push origin :main`) and a whole-history rewrite
(`filter-branch`, `rebase --root`) are the same sentence with `NEW = nothing`.

WHAT IS NOT GUARDED, AND WHY. Three deliberate omissions, so the next reader
does not mistake them for gaps:

  - **`git pull --rebase`.** It replays your work *onto* the remote tip, so a
    published commit is never in the discarded range. It is also this guard's
    own recommended remedy; blocking it would leave no way out.
  - **`git rebase --continue|--abort|--skip`.** The rewrite was already decided
    at the `git rebase` that started it, which is where the check fires.
    Blocking mid-rebase strands the repo with no non-blocked escape.
  - **Local-only deletions** (`git branch -D main`, `git update-ref -d`). They
    drop a local ref; the remote still holds every commit, so the invariant —
    *published* commits don't get dropped — is not violated. `git push --delete`
    is the one that is, and it is guarded.
  - **`git update-ref --stdin`.** The refs arrive on stdin, which a PreToolUse
    hook cannot see. Recorded as a real residual hole rather than papered over.

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

CHEAP BY CONSTRUCTION. This runs on *every* Bash/PowerShell call, so the
expensive path has to stay rare. Three filters in ascending cost, and a command
that fails any of them never reaches the next:

  1. **String only, no subprocess.** Is this segment a git call, and does the
     verb carry the flag that makes it a rewrite at all? `git commit -m ...`,
     `git push`, `git branch --list` and `git checkout -b x` stop here, having
     cost nothing.
  2. **Local git, no network.** Is `main` the ref being moved, and does anything
     actually leave it? A fast-forward or a no-op stops here.
  3. **The network.** `ls-remote`, and a single `fetch` if the remote tip is not
     already local. Only a positively identified, genuinely destructive `main`
     rewrite gets this far.

FAIL OPEN, WITH ONE STATED EXCEPTION. Unparseable payload, no git binary, not a
repo, an unrecognised command — every one of those exits 0. A hook must not
break unrelated work. The exception: when the guard has positively identified a
rewrite of `main` but *cannot verify* what it would destroy (no network, no
auth, a ref that will not resolve), it blocks. Failing open there would reopen
the exact hole it was written to close, and the override is one token away.

One case that looks like that exception and is not: a remote *named* but not
configured. That is not an unanswered question — it is the answer. Nothing in
the repo has ever been published, so nothing can be dropped, and it exits 0. A
configured-but-unreachable `origin` still fails closed. The distinction matters
now that `commit --amend` is guarded: without it, amending on `main` in any
`git init` scratch repo would block, and a guard that fires on scratch repos is
one that gets switched off.

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

# Same idea for rebase. `-S`/`--gpg-sign` is deliberately absent: its value is
# optional and attached in practice (`-Skeyid`), so treating the next token as
# its value would swallow the upstream and fail the guard open.
_REBASE_VALUE_FLAGS = {
    "--onto",
    "-x",
    "--exec",
    "-s",
    "--strategy",
    "-X",
    "--strategy-option",
}

# Sub-commands of an *in-progress* rebase. The decision was already made at the
# `git rebase` that started it; blocking these only strands the repo.
_REBASE_CONTROL = {
    "--continue",
    "--abort",
    "--skip",
    "--quit",
    "--edit-todo",
    "--show-current-patch",
}

# `-M` and `-C` are `--move`/`--copy` with `--force` folded in.
_BRANCH_FORCE_FLAGS = {"-f", "--force", "-M", "-C"}
_BRANCH_MOVE_FLAGS = {"-m", "--move", "-M", "-c", "--copy", "-C"}

# `git checkout -B` / `git switch -C` force-create, which clobbers an existing
# branch. Lowercase `-b`/`-c` fail when the branch exists, so they cannot.
_FORCE_CREATE_FLAGS = {"-B", "-C", "--force-create"}


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


def _resolve(repo: str | None, rev: str) -> str | None:
    """The commit sha for ``rev``, or None if it will not resolve."""
    return git(repo, "rev-parse", "--verify", f"{rev}^{{commit}}")


def _rev_list(repo: str | None, *args: str) -> list[str] | None:
    out = git(repo, "rev-list", *args)
    if out is None:
        return None
    return out.splitlines()


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


def _describe_shas(repo: str | None, shas: list[str]) -> list[str]:
    """One-line summaries for an explicit commit set, newest-first order kept."""
    if not shas:
        return []
    out = git(repo, "log", "--no-walk", "--format=%h %an  %s", *shas[:MAX_LISTED])
    return out.splitlines() if out else []


def _current_branch(repo: str | None) -> str | None:
    return git(repo, "rev-parse", "--abbrev-ref", "HEAD")


def _looks_like_remote_name(remote: str) -> bool:
    """True for `origin`, false for a URL or a filesystem path.

    A URL or path is pushable without being configured, so it must never take
    the "not configured, therefore nothing is published" short-circuit.
    """
    return bool(remote) and not any(c in remote for c in ":/\\.")


def _short_ref(ref: str) -> str:
    if ref.startswith("refs/heads/"):
        return ref[len("refs/heads/") :]
    if ref.startswith("refs/"):
        return ref.rsplit("/", 1)[-1]
    return ref


class Verdict:
    """A block decision plus the text explaining it."""

    def __init__(self, message: str) -> None:
        self.message = message


# `old` is the remote's tip, which only the network knows. Used by the push
# checks, where the ref being overwritten lives on the far side.
REMOTE_TIP = object()


class Rewrite:
    """What a command would do to `main`, said in one sentence.

    ``old`` is the tip being abandoned (a rev expression, or ``REMOTE_TIP``);
    ``new`` is the proposed tip, or ``None`` when nothing of the old branch
    survives. Everything downstream of this record is verb-blind.
    """

    def __init__(
        self,
        action: str,
        old: object,
        new: str | None,
        template: str,
        remedy: str = "",
        remote: str = "origin",
        target: str = "",
    ) -> None:
        self.action = action
        self.old = old
        self.new = new
        self.template = template
        self.remedy = remedy
        self.remote = remote
        self.target = target


# --------------------------------------------------------------------------
# Intent extraction. One function per verb, and each has exactly one job:
# translate this verb's syntax into a `Rewrite`. No verdicts are reached here,
# and every one of them bails on string evidence alone before spending a
# subprocess.
# --------------------------------------------------------------------------


def _push_target(args: list[str]) -> tuple[str, list[tuple[str, str]], bool, bool]:
    """(remote, [(src, dst)], rewrites, deletes) parsed from `git push` args."""
    rewrites = False
    deletes = False
    positionals: list[str] = []
    skip_next = False
    for arg in args:
        if skip_next:
            skip_next = False
            continue
        if arg in _PUSH_VALUE_FLAGS:
            skip_next = True
            continue
        if arg in {"--delete", "-d"}:
            deletes = True
            continue
        if arg in _FORCE_FLAGS or arg.startswith("--force-with-lease"):
            rewrites = True
            continue
        if arg.startswith("-"):
            continue
        positionals.append(arg)

    remote = positionals[0] if positionals else "origin"
    specs: list[tuple[str, str]] = []
    for raw in positionals[1:]:
        spec = raw
        if spec.startswith("+"):
            rewrites = True
            spec = spec[1:]
        if ":" in spec:
            src, dst = spec.split(":", 1)
            if src == "":
                deletes = True  # `git push origin :main` is a delete
        else:
            src = dst = spec
        specs.append((src, _short_ref(dst)))
    return remote, specs, rewrites, deletes


def _rewrite_from_push(repo: str | None, args: list[str]) -> Rewrite | None:
    remote, specs, rewrites, deletes = _push_target(args)
    if not (rewrites or deletes):
        return None  # a plain push cannot destroy remote history; git refuses it

    if deletes:
        targets = [dst for _, dst in specs]
        if not targets:
            return None  # `git push --delete` with no ref is a git error
        if PROTECTED_BRANCH not in targets:
            return None  # deleting a feature branch is routine cleanup
        return Rewrite(
            action=f"deletion of {remote}/{PROTECTED_BRANCH}",
            old=REMOTE_TIP,
            new=None,
            template=_DELETE_BLOCK,
            remote=remote,
        )

    if "--mirror" in args:
        # `--mirror` pushes every local ref regardless of what is checked out,
        # so the local `main` is the proposed tip no matter where HEAD is.
        source = f"refs/heads/{PROTECTED_BRANCH}"
    elif specs:
        matching = [src for src, dst in specs if dst == PROTECTED_BRANCH]
        if not matching:
            return None  # feature branches are one session's own lane
        source = matching[0] or "HEAD"
    else:
        if _current_branch(repo) != PROTECTED_BRANCH:
            return None
        source = "HEAD"

    return Rewrite(
        action=f"force-push to {remote}/{PROTECTED_BRANCH}",
        old=REMOTE_TIP,
        new=source,
        template=_PUSH_BLOCK,
        remote=remote,
    )


def _rewrite_from_reset(repo: str | None, args: list[str]) -> Rewrite | None:
    if "--" in args:  # `git reset -- <paths>` is a pathspec unstage, not a move
        return None
    targets = [a for a in args if not a.startswith("-")]
    if not targets:
        return None  # bare `git reset` unstages; it does not move the branch

    if _current_branch(repo) != PROTECTED_BRANCH:
        return None

    return Rewrite(
        action=f"reset of {PROTECTED_BRANCH} back to {targets[0]}",
        old="HEAD",
        new=targets[0],
        template=_RESET_BLOCK,
        target=targets[0],
    )


def _rewrite_from_commit(repo: str | None, args: list[str]) -> Rewrite | None:
    """`git commit --amend` replaces the tip — a rewrite whenever it is pushed.

    This is the ordinary-accident case the verb list missed: amending is a
    reflex, and on a direct-to-main repo the tip is usually already published.
    """
    if "--amend" not in args:
        return None
    if _current_branch(repo) != PROTECTED_BRANCH:
        return None
    # The parent survives the amend; the current tip does not. A root commit
    # has no parent, so nothing survives.
    parent = _resolve(repo, "HEAD~1")
    return Rewrite(
        action="`git commit --amend` on the tip of `main`",
        old="HEAD",
        new=parent,
        template=_REWRITE_BLOCK,
        remedy=(
            "Amending replaces a commit the remote already has. Land the change as a\n"
            "new commit instead - it is the same content, and nobody's clone breaks:\n"
            "    git -C <repo> commit -m '<what changed>'"
        ),
    )


def _rewrite_from_rebase(repo: str | None, args: list[str]) -> Rewrite | None:
    """A rebase replays `<upstream>..HEAD`, so those commits leave the branch.

    `git pull --rebase` is not this verb and is never guarded: it replays onto
    the remote tip, so nothing published is in the range. It is also the remedy
    this guard recommends.
    """
    if any(a in _REBASE_CONTROL for a in args):
        return None  # an in-progress rebase; the decision was made earlier

    positionals: list[str] = []
    skip_next = False
    for arg in args:
        if skip_next:
            skip_next = False
            continue
        if arg in _REBASE_VALUE_FLAGS:
            skip_next = True
            continue
        if arg.startswith("-"):
            continue
        positionals.append(arg)

    # `git rebase [--onto <newbase>] [<upstream> [<branch>]]` — `--onto`'s value
    # is consumed above, so the positionals line up either way.
    branch = positionals[1] if len(positionals) > 1 else _current_branch(repo)
    if branch != PROTECTED_BRANCH:
        return None

    old = positionals[1] if len(positionals) > 1 else "HEAD"
    if "--root" in args:
        upstream = None  # every commit on the branch is replayed
    elif positionals:
        upstream = positionals[0]
    else:
        upstream = "@{upstream}"  # bare `git rebase`; git errors if unset

    return Rewrite(
        action="`git rebase` of `main`",
        old=old,
        new=upstream,
        template=_REWRITE_BLOCK,
        remedy=(
            "A rebase gives every replayed commit a new sha, so the published ones stop\n"
            "existing. Replay only your *unpushed* work instead:\n"
            "    git -C <repo> pull --rebase        # onto the remote tip, rewrites nothing published\n"
            "    git -C <repo> log --oneline -5     # confirm both sides survived"
        ),
    )


def _rewrite_from_branch(repo: str | None, args: list[str]) -> Rewrite | None:
    """`git branch -f main <sha>` / `git branch -M <src> main` move the ref.

    Neither requires `main` to be checked out, which is why the current-branch
    test the other verbs use does not apply here — the branch is named.
    """
    flags = {a for a in args if a.startswith("-")}
    if not (flags & _BRANCH_FORCE_FLAGS):
        return None  # `--list`, `-a`, `--show-current`, plain create: harmless
    positionals = [a for a in args if not a.startswith("-")]
    if not positionals:
        return None

    if flags & _BRANCH_MOVE_FLAGS:
        # `git branch -M [<oldname>] <newname>` — the destination is last, and
        # it is the ref that gets clobbered.
        dest = positionals[-1]
        source = positionals[-2] if len(positionals) > 1 else "HEAD"
    else:
        # `git branch -f <name> [<start-point>]`
        dest = positionals[0]
        source = positionals[1] if len(positionals) > 1 else "HEAD"

    if _short_ref(dest) != PROTECTED_BRANCH:
        return None

    return Rewrite(
        action=f"`git branch` overwrite of `{PROTECTED_BRANCH}`",
        old=f"refs/heads/{PROTECTED_BRANCH}",
        new=source,
        template=_REWRITE_BLOCK,
        remedy=_MOVE_REF_REMEDY,
    )


def _rewrite_from_force_create(repo: str | None, args: list[str]) -> Rewrite | None:
    """`git checkout -B main <sha>` / `git switch -C main <sha>`.

    Same move as `git branch -f`, spelled by the command people actually reach
    for. Lowercase `-b`/`-c` refuse to clobber an existing branch, so they are
    not a rewrite and are not matched.
    """
    for i, arg in enumerate(args):
        if arg not in _FORCE_CREATE_FLAGS or i + 1 >= len(args):
            continue
        dest = args[i + 1]
        if _short_ref(dest) != PROTECTED_BRANCH:
            return None
        source = "HEAD"
        if i + 2 < len(args) and not args[i + 2].startswith("-"):
            source = args[i + 2]
        return Rewrite(
            action=f"force-create of `{PROTECTED_BRANCH}`",
            old=f"refs/heads/{PROTECTED_BRANCH}",
            new=source,
            template=_REWRITE_BLOCK,
            remedy=_MOVE_REF_REMEDY,
        )
    return None


def _rewrite_from_update_ref(repo: str | None, args: list[str]) -> Rewrite | None:
    """`git update-ref refs/heads/main <sha>` — the ref move with no safety net.

    `--stdin` is not covered: the refs arrive on a stream a PreToolUse hook
    cannot read. `-d` is not covered either — deleting the *local* ref loses
    nothing the remote still has.
    """
    if "--stdin" in args:
        return None
    positionals: list[str] = []
    skip_next = False
    for arg in args:
        if skip_next:
            skip_next = False
            continue
        if arg == "-m":
            skip_next = True
            continue
        if arg.startswith("-"):
            continue
        positionals.append(arg)

    if len(positionals) < 2:
        return None  # a delete, or malformed; either way no new tip is proposed
    if positionals[0] not in {PROTECTED_BRANCH, f"refs/heads/{PROTECTED_BRANCH}"}:
        return None

    return Rewrite(
        action=f"`git update-ref` of `{PROTECTED_BRANCH}`",
        old=f"refs/heads/{PROTECTED_BRANCH}",
        new=positionals[1],
        template=_REWRITE_BLOCK,
        remedy=_MOVE_REF_REMEDY,
    )


def _whole_history_rewrite() -> Rewrite:
    """Nothing of the old branch survives, so `new` is None and the invariant
    check compares the old tip against the remote directly."""
    return Rewrite(
        action=f"whole-history rewrite of `{PROTECTED_BRANCH}`",
        old=f"refs/heads/{PROTECTED_BRANCH}",
        new=None,
        template=_REWRITE_BLOCK,
        remedy=(
            "A whole-history rewrite cannot avoid dropping the published commits - that\n"
            "is what it is for. Make sure every clone on every machine is idle and can be\n"
            "re-cloned afterwards, then re-run with the override."
        ),
    )


def _rewrite_from_filter_branch(repo: str | None, args: list[str]) -> Rewrite | None:
    """`git filter-branch [<filter opts>] [-- <rev-list options>]`.

    The rev-list portion after `--` names what gets rewritten; with none, it is
    HEAD, which only matters when HEAD is `main`.
    """
    revs = args[args.index("--") + 1 :] if "--" in args else []
    named = [r for r in revs if not r.startswith("-")]
    if "--all" in revs or any(_short_ref(r) == PROTECTED_BRANCH for r in named):
        return _whole_history_rewrite()
    if named:
        return None  # some other ref is being rewritten
    if _current_branch(repo) != PROTECTED_BRANCH:
        return None
    return _whole_history_rewrite()


def _rewrite_from_filter_repo(repo: str | None, args: list[str]) -> Rewrite | None:
    """`git filter-repo` — the modern spelling, and it rewrites every ref by
    default rather than just HEAD, so what is checked out is irrelevant."""
    return _whole_history_rewrite()


# The verb list answers only "what would this do to the ref?" — a syntax
# question, and syntax is per-verb. Whether it gets blocked is decided once,
# below, by the repository.
_EXTRACTORS = {
    "push": _rewrite_from_push,
    "reset": _rewrite_from_reset,
    "commit": _rewrite_from_commit,
    "rebase": _rewrite_from_rebase,
    "branch": _rewrite_from_branch,
    "checkout": _rewrite_from_force_create,
    "switch": _rewrite_from_force_create,
    "update-ref": _rewrite_from_update_ref,
    "filter-branch": _rewrite_from_filter_branch,
    "filter-repo": _rewrite_from_filter_repo,
}


# --------------------------------------------------------------------------
# The invariant, asked once.
# --------------------------------------------------------------------------


def _cannot_verify(rw: Rewrite, reason: str) -> Verdict:
    return Verdict(
        _CANNOT_VERIFY.format(action=rw.action, reason=reason, override=OVERRIDE)
    )


def _check_rewrite(repo: str | None, rw: Rewrite) -> Verdict | None:
    """Would this rewrite drop a commit the remote already has?

    Verb-blind on purpose: by this point `git commit --amend` and
    `git push --force` are the same record, and the answer comes from the
    repository rather than from the command string.
    """
    # --- Phase 2 of the cost ladder: local git only, no network yet. ---
    new_sha: str | None = None
    if rw.new is not None:
        new_sha = _resolve(repo, rw.new)
        if new_sha is None:
            return None  # the proposed tip will not resolve; git would fail too

    old_sha: str | None = None
    discarded: list[str] = []
    if rw.old is not REMOTE_TIP:
        old_sha = _resolve(repo, str(rw.old))
        if old_sha is None:
            return None  # no such local ref; nothing of ours is at stake
        if new_sha is not None:
            listed = _rev_list(repo, f"{new_sha}..{old_sha}")
            if not listed:
                return None  # fast-forward or no-op: the branch loses nothing
            discarded = listed

    # A remote that is named but not configured is not "cannot verify" — it is
    # verified: nothing in this repo has ever been published, so nothing can be
    # dropped. Without this, `git commit --amend` on `main` in any `git init`
    # scratch repo would fail closed, and a guard that fires on scratch repos is
    # a guard that gets switched off. Deliberately narrow: only a bare remote
    # *name* short-circuits, so `git push --force <url> main` still goes to the
    # network, and a configured-but-unreachable `origin` still fails closed.
    if _looks_like_remote_name(rw.remote):
        configured = git(repo, "remote")
        if configured is not None and rw.remote not in configured.split():
            return None

    # --- Phase 3: the network. Only a real `main` rewrite reaches this line. ---
    remote_sha = _remote_head(repo, rw.remote, PROTECTED_BRANCH)
    if remote_sha is None:
        return _cannot_verify(rw, f"`git ls-remote {rw.remote}` did not answer")
    if remote_sha == "":
        return None  # the branch is not on the remote; nothing is published yet
    if not _ensure_local(repo, rw.remote, PROTECTED_BRANCH, remote_sha):
        return _cannot_verify(
            rw,
            f"the remote tip {remote_sha[:9]} could not be fetched for inspection",
        )

    if rw.old is REMOTE_TIP:
        old_sha = remote_sha

    if new_sha is None:
        # Nothing of the old branch survives (a delete, `--root`, filter-branch).
        # Everything the old tip and the remote share is lost.
        base = git(repo, "merge-base", str(old_sha), remote_sha)
        if not base:
            return None  # unrelated histories; nothing published is dropped
        counted = git(repo, "rev-list", "--count", base)
        published_count = int(counted) if counted and counted.isdigit() else 1
        listing = _describe(repo, base)
    elif rw.old is REMOTE_TIP:
        ancestor = _is_ancestor(repo, remote_sha, new_sha)
        if ancestor is True:
            return None  # fast-forward; --force is redundant but harmless
        if ancestor is None:
            return _cannot_verify(
                rw, "the local/remote relationship could not be determined"
            )
        # Every commit reachable from the remote tip is by definition published.
        published = _rev_list(repo, f"{new_sha}..{remote_sha}") or []
        if not published:
            return None
        published_count = len(published)
        listing = _describe_shas(repo, published)
    else:
        # The discarded commits that the remote also has. One rev-list rather
        # than an ancestry probe per commit, and exactly equivalent: reachable
        # from the remote tip *is* an ancestor of it.
        on_remote = _rev_list(repo, f"{new_sha}..{remote_sha}")
        if on_remote is None:
            return None  # cannot enumerate; local-scope posture is fail-open
        remote_set = set(on_remote)
        published = [c for c in discarded if c in remote_set]
        if not published:
            return None  # your own unpushed work; the reflog has you covered
        published_count = len(published)
        listing = _describe_shas(repo, published)

    ahead = git(repo, "rev-list", "--count", f"HEAD..{remote_sha}") or "?"
    return Verdict(
        rw.template.format(
            action=rw.action,
            remedy=rw.remedy,
            remote=rw.remote,
            branch=PROTECTED_BRANCH,
            target=rw.target,
            count=published_count,
            plural="" if published_count == 1 else "s",
            listing="\n".join(f"    {line}" for line in listing) or "    (unreadable)",
            ahead=ahead,
            sha=remote_sha[:9],
            override=OVERRIDE,
        )
    )


_MOVE_REF_REMEDY = (
    "Moving the `main` ref does the same damage as a reset, without even the\n"
    "reflog entry a reset leaves on the branch you were on. Point it somewhere\n"
    "that still contains the remote's tip, or look before you move it:\n"
    "    git -C <repo> fetch origin main\n"
    "    git -C <repo> log --oneline FETCH_HEAD -5"
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

origin/{branch} is at {sha} and is {ahead} commit(s) ahead of you, so this
branch has diverged - another session pushed while you were working. Resetting
does not resolve that; it just builds your next commits on a base the remote has
moved past, and the force-push that follows is what destroys their work.

Rebase onto what the remote has instead:
    git -C <repo> pull --rebase        # replay your work on top of theirs
    git -C <repo> log --oneline -5     # confirm both sides survived

If you are deliberately rewriting published history, prefix with {override}.
"""

_REWRITE_BLOCK = """PUBLISHED-HISTORY GUARD: this {action} would drop {count} published commit{plural} from `{branch}`.

Rewritten away, and the remote already has them:
{listing}

{remote}/{branch} is at {sha}. Another session may have written these commits and
may already have pulled them. On 2026-07-26 a rewrite of this shape erased a
sibling session's commit in `career`; it was recovered from the reflog by luck,
not by design.

{remedy}

If rewriting published history really is the intent - a deliberate rewrite, like
the de-identification squash - prefix the command with {override}.
"""

_DELETE_BLOCK = """PUBLISHED-HISTORY GUARD: this would delete {remote}/{branch} outright, discarding {count} published commit{plural}.

The most recent of them:
{listing}

Deleting the shared branch is not a rewrite of it - it is the whole branch at
once, and every session that has not pulled loses the base it is working on.
There is no reflog on the remote.

If you meant to delete a feature branch, name it:
    git -C <repo> push --delete origin <branch-name>

If deleting {remote}/{branch} really is the intent, prefix with {override}.
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

        extractor = _EXTRACTORS.get(sub)
        if extractor is None:
            continue

        try:
            rewrite = extractor(repo, args)
            verdict = _check_rewrite(repo, rewrite) if rewrite else None
        except Exception:
            continue  # a guard that crashes must not take the session with it

        if verdict:
            sys.stderr.write(verdict.message)
            sys.exit(2)

    _allow(data)


if __name__ == "__main__":
    main()
