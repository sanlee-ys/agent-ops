#!/usr/bin/env python3
"""Stale-generated-file CI gate — rebuild, diff, fail on drift.

Several repos commit build output next to its source (a static site's
``index.html``, a generated SVG, a rendered graph). The failure mode is always
the same: someone edits the source, forgets the rebuild, and ships a stale
artifact — the learning-notes site did exactly this, and its repo-local
``generated-files`` CI job was the fix. This script is that job generalized
(ADR-003 backlog disposition, 2026-07-06): run the repo's build, ``git diff``
the declared outputs, fail if anything moved. Deterministic — no judgment
calls, no LLM, just "does a fresh build reproduce what's committed?"

The only per-repo variables are the build command(s) and the watched paths, so
they live in a small TOML file at the consumer repo's root
(``.generated-drift.toml`` by default) — one named ``[check.*]`` table per
generator; each runs its builds, then fails if any watched path changed or
appeared untracked:

    [check.site]
    build = ["python build_site.py", "python build_graph.py"]
    watch = ["index.html", "concept-map.html", "assets/category-map.svg"]

``watch`` entries are git pathspecs, so globs work (``assets/*.svg``). Run it
locally from the repo root (``python path/to/check-generated-drift.py``) or
from CI via this repo's reusable workflow
(``.github/workflows/generated-drift.yml``).

Exit codes — kept distinct so a red build says *what kind* of red:
    0  every watched path reproduced exactly
    1  DRIFT: a build changed (or newly created) a watched path — the committed
       output is stale; rebuild and commit
    2  anything else: missing/invalid config, a watched path already dirty
       before the build ran (can't tell pre-existing edits from drift), or a
       build command failing

Stdlib only (``tomllib`` is stdlib on the fleet-standard Python 3.11+), same
as every other guard here, so CI needs nothing installed.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from pathlib import Path

DRIFT = 1
ERROR = 2


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True
    )


def _status(root: Path, pathspecs: list[str]) -> str:
    """Porcelain status limited to the watched pathspecs — covers both
    modified tracked files and untracked new build outputs."""
    proc = _git(root, "status", "--porcelain=v1", "--", *pathspecs)
    if proc.returncode != 0:
        print(f"ERROR: git status failed: {proc.stderr.strip()}", file=sys.stderr)
        sys.exit(ERROR)
    return proc.stdout.strip()


def _load_checks(config_path: Path) -> list[dict]:
    if not config_path.is_file():
        print(
            f"ERROR: no config at {config_path} — this gate needs named "
            "[check.*] tables (build commands + watched paths); see the "
            "script docstring for the format.",
            file=sys.stderr,
        )
        sys.exit(ERROR)
    with config_path.open("rb") as f:
        data = tomllib.load(f)
    tables = data.get("check")
    if not isinstance(tables, dict) or not tables:
        print(f"ERROR: {config_path} defines no [check.*] tables.", file=sys.stderr)
        sys.exit(ERROR)
    checks = []
    for name, entry in tables.items():
        if not isinstance(entry, dict) or not entry.get("build") or not entry.get("watch"):
            print(
                f"ERROR: [check.{name}] needs both a non-empty 'build' list "
                "and a non-empty 'watch' list.",
                file=sys.stderr,
            )
            sys.exit(ERROR)
        checks.append({"name": name, **entry})
    return checks


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Rebuild generated files and fail if committed output drifted."
    )
    ap.add_argument(
        "--config",
        type=Path,
        default=Path(".generated-drift.toml"),
        help="per-repo TOML config (default: .generated-drift.toml in --root)",
    )
    ap.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="repo root the builds run in (default: current directory)",
    )
    args = ap.parse_args()
    root = args.root.resolve()
    config_path = args.config if args.config.is_absolute() else root / args.config
    checks = _load_checks(config_path)

    # Pre-flight ALL watched paths before running ANY build: a path that's
    # already dirty makes drift unattributable (is that your edit, or a stale
    # build?), and an earlier check's build must not poison a later check's
    # baseline. Distinct exit code — this is operator error, not drift.
    all_watch = [spec for check in checks for spec in check["watch"]]
    dirty = _status(root, all_watch)
    if dirty:
        print(
            "ERROR: watched paths are already modified before any build ran —\n"
            "commit or stash these first so drift is attributable:\n" + dirty,
            file=sys.stderr,
        )
        return ERROR

    drifted: list[str] = []
    for check in checks:
        name = check["name"]
        for cmd in check["build"]:
            print(f"[{name}] $ {cmd}")
            proc = subprocess.run(cmd, shell=True, cwd=root)
            if proc.returncode != 0:
                print(
                    f"ERROR: [{name}] build command failed "
                    f"(exit {proc.returncode}): {cmd}",
                    file=sys.stderr,
                )
                return ERROR
        status = _status(root, check["watch"])
        if status:
            drifted.append(name)
            diff_stat = _git(
                root, "--no-pager", "diff", "--stat", "--", *check["watch"]
            ).stdout.strip()
            print(f"[{name}] DRIFT — watched paths changed after a fresh build:")
            print(status)
            if diff_stat:
                print(diff_stat)
        else:
            print(f"[{name}] ok — committed output reproduced exactly")

    if drifted:
        # ::error:: renders as an annotation on GitHub Actions; harmless locally.
        print(
            f"::error::Generated files are stale ({', '.join(drifted)}) — "
            "run the build(s) and commit the output."
        )
        return DRIFT
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
