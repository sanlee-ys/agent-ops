#!/usr/bin/env python3
"""Measure rule adherence over local session transcripts. v1.

WHY THIS EXISTS. A rule file is written once and then assumed to work. Nothing
tests prose, so a rule that every session quietly ignores looks exactly like a
rule every session follows: the file is still there, and nothing turns red. That
is a DEAD RULE, and the only way to tell one from a live rule is to count.

WHAT IT MEASURES, AND WHAT IT CANNOT. A small closed set of rule signatures that
are mechanically detectable in a transcript. That set is not the rule corpus and
it never will be: most rules are about judgement, and judgement leaves no
regular expression behind. So the number this produces is a floor on violations,
never a compliance score, and a rule with zero hits may be perfectly observed or
may simply have no detector. `conventions/dead-rules-audit.md` carries the
limits in full; read it before quoting a number from here.

The four detectors, each named for the shape it finds rather than for the rule
it belongs to. That is deliberate — the shapes are generic, and the private rule
corpus that motivates them stays private:

  compound-inspection   a shell command chaining three or more READ-ONLY
                        segments with `&&` or `;`. Each segment may be
                        permitted on its own and the chain still prompts,
                        because a compound command is scored as a whole.
  cd-then-git           `cd <path> && git ...` instead of `git -C <path> ...`.
                        The first form scores the `cd` as a path read.
  em-dash               an em dash in assistant prose.
  venv-interpreter      a venv interpreter invoked by path
                        (`.venv/Scripts/python`, `.venv/bin/python`) instead of
                        through a launcher. An absolute interpreter path can
                        never match a prefix allowlist.

WHAT IT NEVER DOES. It never writes a file, it never modifies a transcript, and
it never sends anything anywhere. It opens transcripts read-only and prints to
stdout and stderr.

WHAT IT NEVER PRINTS. Assistant prose, user prose, and file contents. Examples
are COMMAND STRINGS only, truncated, and capped at three per rule. The em-dash
detector therefore reports counts with NO examples at all: its evidence is
prose, and printing prose to make a point about prose would put the transcript
in the report. A transcript holds the whole session; an audit of it must not
become a second copy.

Output: a human table on stdout, and the same data as JSON with `--json`.

Exit codes are the interface: 0 audit complete, 2 usage error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

MAX_EXAMPLES = 3
EXAMPLE_WIDTH = 120

# Tool names whose input carries a shell command line.
SHELL_TOOLS = {"Bash", "PowerShell", "Shell"}

# --- Detector: compound inspection ------------------------------------------
# Read-only leading verbs. A chain of these is the shape that prompts even when
# every segment is individually permitted, because a compound command is scored
# as one unit. Deliberately a closed list of INSPECTION verbs: a chain that
# mutates something (`git add && git commit && git push`) has a real ordering
# dependency and is not what this counts.
_READ_ONLY_VERBS = {
    "git", "gh", "ls", "dir", "cat", "head", "tail", "wc", "stat", "file",
    "echo", "pwd", "cd", "grep", "rg", "find", "which", "where", "type",
    "test-path", "get-content", "get-childitem", "get-item", "select-string",
    "python", "uv", "node", "npm", "cargo", "docker", "jq", "sort", "uniq",
}
# git/gh subcommands that only READ. A chain ending in a push or a merge is a
# real ordering dependency, so it must not be counted as inspection.
_READ_ONLY_SUBCOMMANDS = {
    "status", "log", "diff", "show", "branch", "remote", "ls-remote", "ls-files",
    "rev-parse", "describe", "config", "blame", "shortlog", "tag", "stash",
    "list", "view", "checks", "run", "pr", "issue", "api", "repo", "--version",
}
_SEGMENT_SPLIT = re.compile(r"&&|;|\|\|")

# --- Detector: cd-then-git ---------------------------------------------------
# The path may be quoted and may contain spaces, so a bare `[^\s;&|]+` misses
# `cd "/a path/repo" && git status` — the exact shape a Windows path produces.
_CD_THEN_GIT = re.compile(
    r"(?:^|[\s;&|])cd\s+(?:\"[^\"]*\"|'[^']*'|[^\s;&|]+)\s*(?:&&|;)\s*"
    r"git(?![\w-])",
    re.IGNORECASE,
)

# --- Detector: venv interpreter by path --------------------------------------
_VENV_INTERPRETER = re.compile(
    r"[\w.~$%{}/\\-]*\.venv[/\\](?:Scripts|bin)[/\\]python(?:3|\.exe)?(?![\w])",
    re.IGNORECASE,
)

# --- Detector: em dash -------------------------------------------------------
_EM_DASH = re.compile("[—–]")

DETECTORS = ("compound-inspection", "cd-then-git", "em-dash", "venv-interpreter")


def _leading_verb(segment: str) -> str:
    """The first bare command name in a segment, lowercased."""
    for token in segment.split():
        if "=" in token and not token.startswith("-"):
            continue
        if token.startswith("-"):
            continue
        name = re.split(r"[/\\]", token.strip("'\"").lower())[-1]
        return name[:-4] if name.endswith(".exe") else name
    return ""


def _subcommand(segment: str) -> str:
    """The second bare token, for `git status` / `gh pr list`."""
    bare = [t.strip("'\"").lower() for t in segment.split()
            if not t.startswith("-")]
    return bare[1] if len(bare) > 1 else ""


def _segment_is_read_only(segment: str) -> bool:
    verb = _leading_verb(segment)
    if verb not in _READ_ONLY_VERBS:
        return False
    if verb in ("git", "gh"):
        sub = _subcommand(segment)
        # `git -C <path> status` puts the path before the subcommand, so a
        # second bare token that is a path is skipped by taking the next one.
        if sub in ("-c", "-c"):
            return False
        return sub in _READ_ONLY_SUBCOMMANDS or _subcommand_after_path(segment)
    return True


def _subcommand_after_path(segment: str) -> bool:
    """True for `git -C <path> <read-only-sub>`, whose subcommand is third."""
    tokens = [t.strip("'\"") for t in segment.split()]
    for i, token in enumerate(tokens):
        if token in ("-C", "-c") and i + 2 < len(tokens):
            return tokens[i + 2].lower() in _READ_ONLY_SUBCOMMANDS
    return False


def is_compound_inspection(command: str) -> bool:
    """True for a chain of three or more read-only segments.

    Three, not two: a two-segment chain is cheap and common, and counting it
    would drown the signal the rule is actually about.
    """
    segments = [s.strip() for s in _SEGMENT_SPLIT.split(command) if s.strip()]
    if len(segments) < 3:
        return False
    return all(_segment_is_read_only(s) for s in segments)


def is_cd_then_git(command: str) -> bool:
    return bool(_CD_THEN_GIT.search(command))


def is_venv_interpreter(command: str) -> bool:
    return bool(_VENV_INTERPRETER.search(command))


def count_em_dashes(text: str) -> int:
    return len(_EM_DASH.findall(text or ""))


# --- Transcript walking ------------------------------------------------------


def parse_timestamp(value) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _truncate(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= EXAMPLE_WIDTH else text[:EXAMPLE_WIDTH - 3] + "..."


def iter_records(path: Path):
    """Yield parsed JSON objects from one transcript.

    Split on `\\n` only. `conventions/jsonl-splits-on-lf-only.md` records why:
    a lone CR inside a value is data, and framing on it corrupts the record. A
    line that does not parse is skipped rather than guessed at.
    """
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            yield record


def scan_record(record: dict, hits: dict, day: str) -> None:
    """Apply every detector to one assistant record.

    Only assistant records carry a tool call or model prose. A user record is
    the operator's own text and is never scanned, so nothing the operator wrote
    can reach a count or an example.
    """
    if record.get("type") != "assistant":
        return
    message = record.get("message")
    if not isinstance(message, dict):
        return
    for block in message.get("content") or []:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text":
            # COUNT ONLY. The evidence is prose, and prose never leaves here.
            found = count_em_dashes(block.get("text"))
            if found:
                hits["em-dash"][day]["count"] += found
            continue
        if kind != "tool_use" or block.get("name") not in SHELL_TOOLS:
            continue
        command = (block.get("input") or {}).get("command")
        if not isinstance(command, str) or not command:
            continue
        for rule, matched in (
            ("compound-inspection", is_compound_inspection(command)),
            ("cd-then-git", is_cd_then_git(command)),
            ("venv-interpreter", is_venv_interpreter(command)),
        ):
            if not matched:
                continue
            bucket = hits[rule][day]
            bucket["count"] += 1
            if len(bucket["examples"]) < MAX_EXAMPLES:
                bucket["examples"].append(_truncate(command))


def _empty_hits():
    return {rule: defaultdict(lambda: {"count": 0, "examples": []})
            for rule in DETECTORS}


def audit(root: Path, days: int, now: datetime | None = None) -> dict:
    """Walk every transcript under `root` and count rule signatures per day."""
    now = now or datetime.now(timezone.utc)
    window_start = now - timedelta(days=days)
    hits = _empty_hits()
    transcripts, records = 0, 0

    for path in sorted(root.glob("*/*.jsonl")):
        seen_in_file = False
        for record in iter_records(path):
            stamp = parse_timestamp(record.get("timestamp"))
            if stamp is None or stamp < window_start:
                continue
            seen_in_file = True
            records += 1
            scan_record(record, hits, stamp.date().isoformat())
        if seen_in_file:
            transcripts += 1

    return {
        "generated_at": now.isoformat(),
        "window_days": days,
        "window_start": window_start.isoformat(),
        "transcripts_in_window": transcripts,
        "records_in_window": records,
        "rules": {
            rule: {day: dict(bucket) for day, bucket in sorted(days_map.items())}
            for rule, days_map in hits.items()
        },
    }


# --- Reporting ---------------------------------------------------------------

_NO_EXAMPLES = {"em-dash"}


def format_report(result: dict) -> str:
    lines = [
        "dead-rules audit  window %d day(s) from %s"
        % (result["window_days"], result["window_start"][:10]),
        "  %d transcript(s), %d record(s) in window"
        % (result["transcripts_in_window"], result["records_in_window"]),
        "",
    ]
    for rule in DETECTORS:
        days_map = result["rules"].get(rule) or {}
        total = sum(b["count"] for b in days_map.values())
        lines.append("%-20s total %d" % (rule, total))
        if not total:
            lines.append("    no hits in window (see the limits: absence is "
                         "not proof of compliance)")
            lines.append("")
            continue
        for day, bucket in sorted(days_map.items()):
            if bucket["count"]:
                lines.append("    %s  %d" % (day, bucket["count"]))
        if rule in _NO_EXAMPLES:
            lines.append("    (no examples: the evidence is prose, and prose "
                         "never leaves the transcript)")
        else:
            shown = []
            for bucket in days_map.values():
                shown.extend(bucket["examples"])
            for example in shown[:MAX_EXAMPLES]:
                lines.append("    e.g. %s" % example)
        lines.append("")
    lines.append("This measures the DETECTABLE subset only. Absence of hits is "
                 "not proof of")
    lines.append("compliance. See conventions/dead-rules-audit.md.")
    return "\n".join(lines)


def default_root() -> Path:
    return Path.home() / ".claude" / "projects"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dead_rules_audit.py",
        description="Count mechanically detectable rule signatures in local "
                    "session transcripts. Reads only; writes nothing.",
    )
    parser.add_argument("--days", type=int, default=7, metavar="N",
                        help="window size in days (default 7)")
    parser.add_argument("--root", default=None, metavar="DIR",
                        help="transcript root (default the local session store)")
    parser.add_argument("--json", action="store_true",
                        help="emit JSON instead of the table")
    args = parser.parse_args(argv)

    if args.days < 1:
        parser.error("--days must be at least 1")
        return 2

    root = Path(args.root) if args.root else default_root()
    if not root.is_dir():
        parser.error("transcript root does not exist: %s" % root)
        return 2

    result = audit(root, args.days)
    if args.json:
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(format_report(result) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
