#!/usr/bin/env python3
"""Sync marker-delimited shared blocks across the fleet's CLAUDE.md files.

Some guidance (e.g. the link-verification hard rule) is identical across many
repos. Rather than copy-paste it — and let the copies drift — the canonical
text lives here in claude-ops (the operating-layer canon, ADR-002), and each
consumer repo carries a compressed restatement wrapped in marker comments:

    <!-- shared:links-verify v1 — canonical: <url> -->
    ...block...
    <!-- /shared:links-verify -->

This is the CLAUDE.md analogue of ``scripts/sync-claude-hooks``: it operates on
sibling clones (all repos checked out next to each other) and is the drift
tripwire for the shared blocks.

    python scripts/sync-shared-blocks.py --check   # report drift, exit 1 if any
    python scripts/sync-shared-blocks.py           # rewrite drifted blocks in place

Consumers are **discovered**, not enumerated: the script scans every sibling
``<repo>/CLAUDE.md`` under ``--root`` for shared-block markers, so this public
file names no repositories. ``--root`` defaults to the parent directory of this
repo. The first time a repo adopts a block, stamp the marker block in by hand
(replacing the old prose section); thereafter this script maintains it.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

_CANON_BASE = "https://github.com/sanlee-ys/claude-ops/blob/main/conventions"


def _canonical_url(slug: str) -> str:
    """URL of the canonical convention file backing a shared block."""
    return f"{_CANON_BASE}/{slug}.md"


CANONICAL_URL = _canonical_url("links-verify")

# Canonical compressed blocks, keyed by slug. The full text between the markers
# is what every consumer carries verbatim — edit here and re-run to propagate.
BLOCKS = {
    "links-verify": (
        "<!-- shared:links-verify v1 -->\n"
        "## Links — verify before sending (hard rule)\n"
        "\n"
        "Links given in chat must resolve: **full "
        "`github.com/<owner>/<repo>/blob/<ref>/<path>` URLs only**, **verify the "
        "path exists on the ref before sending** (unverified → say so), and "
        "**branch links are perishable** (prefer `main` once merged). Full rule "
        f"+ rationale: [claude-ops `conventions/links-verify.md`]({CANONICAL_URL}).\n"
        "<!-- /shared:links-verify -->"
    ),
    "parallel-sessions": (
        "<!-- shared:parallel-sessions v1 -->\n"
        "## Working across parallel sessions (hard rule)\n"
        "\n"
        "Sessions cannot see each other's uncommitted work — **`main` is the only "
        "shared coordination point**. So: **one concern per session → one branch → "
        "one PR**; check open PRs and branches before starting; branch from fresh "
        "`main` and merge fast; **serialize the collision hotspots** and parallelize "
        "by independent *file*, not by task; keep the wiring for any generated or "
        "aggregated file in one hand. Full rule + the triple-build incident that "
        "produced it: [claude-ops `conventions/parallel-sessions.md`]"
        f"({_canonical_url('parallel-sessions')}).\n"
        "<!-- /shared:parallel-sessions -->"
    ),
}

# Matches any <!-- shared:SLUG ... --> ... <!-- /shared:SLUG --> block and
# captures the slug, so consumers are found by scanning, not by a hardcoded
# (and possibly private) repo list.
_BLOCK_RE = re.compile(
    r"<!-- shared:(?P<slug>[\w-]+)\b.*?-->.*?<!-- /shared:(?P=slug) -->",
    re.DOTALL,
)


def _claude_mds(root: Path) -> list[Path]:
    return sorted(p for p in root.glob("*/CLAUDE.md") if p.is_file())


def _iter_blocks(text: str):
    for m in _BLOCK_RE.finditer(text):
        yield m


def check(root: Path) -> int:
    issues = 0
    seen = 0
    for path in _claude_mds(root):
        repo = path.parent.name
        for m in _iter_blocks(path.read_text(encoding="utf-8")):
            seen += 1
            slug = m.group("slug")
            canonical = BLOCKS.get(slug)
            if canonical is None:
                print(f"UNKNOWN  {repo}: shared:{slug} has no canonical entry")
                issues += 1
            elif m.group(0) != canonical:
                print(f"DRIFT    {repo}: shared:{slug} differs from canonical")
                issues += 1
            else:
                print(f"ok       {repo}: shared:{slug}")
    if not seen:
        print("no shared-block markers found under", root)
    print(f"\n{issues} issue(s)" if issues else "\nall shared blocks in sync")
    return 1 if issues else 0


def write(root: Path) -> int:
    changed = 0
    for path in _claude_mds(root):
        repo = path.parent.name
        text = path.read_text(encoding="utf-8")
        new = text
        for m in list(_iter_blocks(text)):
            slug = m.group("slug")
            canonical = BLOCKS.get(slug)
            if canonical is None or m.group(0) == canonical:
                continue
            new = new.replace(m.group(0), canonical)
        if new != text:
            path.write_text(new, encoding="utf-8")
            print(f"updated  {repo}")
            changed += 1
    print(f"\n{changed} file(s) updated")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Sync/verify shared CLAUDE.md blocks across sibling repos.")
    ap.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[2],
        help="directory holding the sibling repo clones "
             "(default: parent of this repo)")
    ap.add_argument(
        "--check", action="store_true",
        help="report drift and exit non-zero if any; do not write")
    args = ap.parse_args()
    return check(args.root) if args.check else write(args.root)


if __name__ == "__main__":
    raise SystemExit(main())
