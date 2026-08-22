#!/usr/bin/env python3
"""Ground-truth snapshot of a repo, for reconciling an agent's claims against it.

THE PROBLEM. An agent's self-report is a CLAIM, not a record. "Opened PR #51",
"merged it", "pushed the branch" are sentences the agent wrote, and the agent
writes the same sentence whether the `gh` call succeeded, returned an error it
did not read, or never ran. `conventions/agent-success-signals.md` records the
same shape from the tool side: a green check means the step exited 0, not that
the work happened.

THE ANSWER IS MECHANICAL, NOT RHETORICAL. A session or an agentic loop compares
its own claims against this snapshot at the end of a cycle. The snapshot comes
from the systems of record - `gh` for the forge, `git` for the tree and the
remote - and never from the transcript. A claim with no matching record in the
snapshot is a fabrication or a silent failure, and the two are the same problem
for the reader: the report says work exists that does not.

WHAT IT COLLECTS, per repo:
  - open pull requests: number, title, head branch, creation time
  - pull requests merged since the window start
  - branches that ACTUALLY exist on the remote, from `git ls-remote`
  - the current branch
  - uncommitted paths, from `git status --porcelain`
  - the last local commit

`git ls-remote` rather than `git branch -r` is deliberate and is the one place
this script would be wrong if it followed the obvious route. `git branch -r`
prints a LOCAL cache of remote-tracking refs. It goes stale the moment another
machine or another session moves the remote, and it happily lists a branch that
was deleted an hour ago. A snapshot built to catch a false claim must not be
built from a cache that can carry one.

OUTPUT. JSON on stdout, a compact human table on stderr. The split is the
interface: pipe stdout into a comparison and read stderr yourself.

EXIT CODES are the interface: 0 snapshot complete, 1 one or more repos failed
(the JSON still carries the ones that worked, each failure named in its entry),
2 usage error.

It READS ONLY. It runs no command that writes, and it sends nothing anywhere.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

# A duration like `6h`, `90m`, `2d`, `3w`. Anything else is parsed as ISO-8601.
_DURATION = re.compile(r"^(\d+)\s*([smhdw])$", re.IGNORECASE)
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}

# `git ls-remote --heads` prints "<sha>\trefs/heads/<branch>".
_LS_REMOTE_LINE = re.compile(r"^([0-9a-f]{7,40})\s+refs/heads/(.+)$")

# `git status --porcelain` prints "XY <path>", and a rename prints
# "R  <old> -> <new>". The path starts at column 3.
_RENAME_ARROW = " -> "

_TIMEOUT = 30


class RepoError(RuntimeError):
    """A repo could not be snapshotted. Named, never swallowed."""


# --- Window -----------------------------------------------------------------


def parse_since(value: str, now: datetime | None = None) -> datetime:
    """An ISO-8601 datetime, or a duration before now (`6h`, `2d`, `90m`).

    A naive ISO value is read as UTC. The caller supplies `now` in tests so the
    parsing is deterministic without freezing the clock.
    """
    now = now or datetime.now(timezone.utc)
    text = value.strip()
    if not text:
        raise ValueError("--since is empty")
    match = _DURATION.match(text)
    if match:
        amount = int(match.group(1))
        return now - timedelta(seconds=amount * _UNIT_SECONDS[match.group(2).lower()])
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            "--since %r is neither a duration (6h, 90m, 2d, 3w) nor an ISO "
            "datetime" % value
        ) from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_timestamp(value: str) -> datetime | None:
    """A forge timestamp, or None when the field is absent or unreadable.

    None is a real answer here rather than an error: a pull request with no
    `mergedAt` is simply not merged, and the caller must not mistake that for a
    broken snapshot.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# --- Parsers ----------------------------------------------------------------
# Every parser below takes TEXT, not a subprocess. That is what lets the suite
# cover them with recorded output and no network.


def parse_ls_remote(text: str) -> list[str]:
    """Branch names from `git ls-remote --heads`, sorted.

    The remote is the only coordination point between machines, so this is the
    authoritative branch list. `git branch -r` is a local cache and is NOT used.
    """
    names = []
    for line in (text or "").splitlines():
        match = _LS_REMOTE_LINE.match(line.strip())
        if match:
            names.append(match.group(2))
    return sorted(set(names))


def parse_porcelain(text: str) -> list[dict]:
    """Uncommitted paths from `git status --porcelain`.

    A rename prints both halves; the NEW path is reported, because that is the
    file now on disk. The two status characters are kept verbatim so a caller
    can tell a staged change from an unstaged one.
    """
    out = []
    for line in (text or "").splitlines():
        if len(line) < 4:
            continue
        status, path = line[:2], line[3:].strip()
        if _RENAME_ARROW in path:
            path = path.split(_RENAME_ARROW, 1)[1]
        out.append({"status": status.strip() or status, "path": path.strip('"')})
    return out


def parse_pr_list(text: str) -> list[dict]:
    """Pull requests from `gh pr list --json ...`.

    Only the fields a claim can be checked against are kept. A malformed entry
    is dropped rather than guessed at: a half-read record is worse than a
    missing one, because it looks like corroboration.
    """
    try:
        rows = json.loads(text or "[]")
    except json.JSONDecodeError as exc:
        raise RepoError("gh returned output that is not JSON: %s" % exc) from exc
    if not isinstance(rows, list):
        raise RepoError("gh returned %s, expected a list" % type(rows).__name__)
    out = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("number"), int):
            continue
        out.append({
            "number": row["number"],
            "title": str(row.get("title") or ""),
            "head_branch": str(row.get("headRefName") or ""),
            "created_at": str(row.get("createdAt") or ""),
            "merged_at": str(row.get("mergedAt") or ""),
            "url": str(row.get("url") or ""),
        })
    return sorted(out, key=lambda r: r["number"])


def filter_merged_since(rows: list[dict], since: datetime) -> list[dict]:
    """Merged pull requests inside the window.

    An unparseable or absent `merged_at` drops the row. A pull request that
    cannot be dated cannot corroborate a claim about when it merged.
    """
    out = []
    for row in rows:
        merged = parse_timestamp(row.get("merged_at", ""))
        if merged is not None and merged >= since:
            out.append(row)
    return out


# --- Formatting -------------------------------------------------------------


def _truncate(text: str, width: int) -> str:
    """Collapse whitespace and cut to `width`.

    The marker is ASCII on purpose. A Windows console defaults to a code page
    that cannot encode a typographic ellipsis, and the table is written to
    stderr where an encoding error would replace the diagnostic with a
    traceback.
    """
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[: width - 3] + "..."


def format_table(snapshot: dict) -> str:
    """The compact human view. Goes to stderr; stdout carries the JSON."""
    lines = []
    for repo in snapshot.get("repos", []):
        lines.append("== %s" % repo.get("path", "?"))
        if repo.get("error"):
            lines.append("   ERROR: %s" % repo["error"])
            continue
        lines.append("   branch      %s" % (repo.get("current_branch") or "?"))
        head = repo.get("last_commit") or {}
        lines.append("   last commit %s %s" % (
            head.get("sha", "?")[:8], _truncate(head.get("subject", ""), 56)))
        dirty = repo.get("uncommitted") or []
        if dirty:
            lines.append("   uncommitted %d path(s)" % len(dirty))
            for entry in dirty[:10]:
                lines.append("     %-2s %s" % (entry["status"], entry["path"]))
            if len(dirty) > 10:
                lines.append("     ... and %d more" % (len(dirty) - 10))
        else:
            lines.append("   uncommitted none")
        remote = repo.get("remote_branches") or []
        lines.append("   remote      %d branch(es): %s" % (
            len(remote), _truncate(", ".join(remote), 60) or "none"))
        for label, key in (("open PR", "open_prs"), ("merged PR", "merged_prs")):
            rows = repo.get(key) or []
            if not rows:
                lines.append("   %-11s none" % (label + "s"))
                continue
            lines.append("   %-11s %d" % (label + "s", len(rows)))
            for row in rows:
                lines.append("     #%-5d %-28s %s" % (
                    row["number"], _truncate(row["head_branch"], 28),
                    _truncate(row["title"], 44)))
    lines.append("")
    lines.append("A claim with no matching record above is a fabrication or a "
                 "silent failure.")
    return "\n".join(lines)


# --- Collection -------------------------------------------------------------


def _run(args: list[str], cwd: str) -> str:
    """Run a read-only command and return its stdout. Raises RepoError."""
    try:
        proc = subprocess.run(
            args, cwd=cwd, capture_output=True, text=True, timeout=_TIMEOUT
        )
    except FileNotFoundError as exc:
        raise RepoError("%s is not on PATH" % args[0]) from exc
    except subprocess.TimeoutExpired as exc:
        raise RepoError("%s did not finish within %ss" % (args[0], _TIMEOUT)) from exc
    if proc.returncode != 0:
        raise RepoError("%s exited %d: %s" % (
            " ".join(args[:3]), proc.returncode, (proc.stderr or "").strip()[:300]))
    return proc.stdout


_PR_FIELDS = "number,title,headRefName,createdAt,mergedAt,url"


def collect(path: str, since: datetime, runner=_run) -> dict:
    """One repo's ground-truth snapshot. `runner` is injected for the suite."""
    repo: dict = {"path": path}
    try:
        repo["current_branch"] = runner(
            ["git", "-C", path, "rev-parse", "--abbrev-ref", "HEAD"], path).strip()
        head = runner(
            ["git", "-C", path, "log", "-1", "--format=%H%x1f%s%x1f%cI"], path).strip()
        sha, _, rest = head.partition("\x1f")
        subject, _, committed = rest.partition("\x1f")
        repo["last_commit"] = {"sha": sha, "subject": subject,
                               "committed_at": committed}
        repo["uncommitted"] = parse_porcelain(
            runner(["git", "-C", path, "status", "--porcelain"], path))
        repo["remote_branches"] = parse_ls_remote(
            runner(["git", "-C", path, "ls-remote", "--heads", "origin"], path))
        open_prs = parse_pr_list(runner(
            ["gh", "pr", "list", "--state", "open", "--limit", "100",
             "--json", _PR_FIELDS], path))
        merged = parse_pr_list(runner(
            ["gh", "pr", "list", "--state", "merged", "--limit", "100",
             "--json", _PR_FIELDS], path))
        repo["open_prs"] = open_prs
        repo["merged_prs"] = filter_merged_since(merged, since)
    except RepoError as exc:
        repo["error"] = str(exc)
    return repo


def build_snapshot(paths: list[str], since: datetime, runner=_run) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "since": since.isoformat(),
        "repos": [collect(p, since, runner) for p in paths],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="reconcile.py",
        description="Ground-truth snapshot of a repo, for checking an agent's "
                    "claims against the systems of record.",
    )
    parser.add_argument("--repo", action="append", required=True, metavar="PATH",
                        help="repo to snapshot; repeat for more than one")
    parser.add_argument("--since", default="6h", metavar="WHEN",
                        help="window start: a duration (6h, 90m, 2d, 3w) or an "
                             "ISO datetime. Default 6h")
    args = parser.parse_args(argv)

    try:
        since = parse_since(args.since)
    except ValueError as exc:
        parser.error(str(exc))
        return 2

    snapshot = build_snapshot(args.repo, since)
    sys.stderr.write(format_table(snapshot) + "\n")
    json.dump(snapshot, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 1 if any(r.get("error") for r in snapshot["repos"]) else 0


if __name__ == "__main__":
    sys.exit(main())
