#!/usr/bin/env python3
"""Kit 2, claim 3: "the check actually ran".

This script reconciles a guard's own reported marker count against an
independent raw grep over the same files. It prints both numbers and their
difference.

The data source is the False Green material. The portfolio page
`src/pages/projects/false-green.astro` (live at
https://sanlee.me/projects/false-green.html) records six checks that reported
success for work that never ran. Its cheapest diagnostic is this one: reconcile
the gate's own reported count against a raw grep, once.

The guard is the portfolio's `scripts/check-published-metrics.cjs`. Its header
comment records the live failure: a marker pattern that required `data-metric`
to be the first attribute on the span matched nothing on three homepage
figures, and the gate stayed green. The fix added an attribute-order-tolerant
pattern and a parity counter, `unparsedMarkers()`.

Two counts come out of this script:

  guard count  the number of markers the guard's own exported parser,
               `markersIn()`, reads from each file. Node runs the guard's own
               code. This script holds no copy of the pattern.
  raw count    an independent regex count in Python of the raw marker text:
               `data-metric=` in HTML and `<!-- metric:` in Markdown.

The difference is raw minus guard. The expected difference is 0. A positive
difference is a marker the author wrote and the guard cannot see.

The file set is the one the guard walks: `.html` files under `dist/` and
`.md` files under the portfolio root, with the guard's own skip list. Both
counts run over the identical list.

The script runs offline. It calls only the parser functions that the guard
exports. It does not run the guard's main path, which fetches the metrics
artifact over the network.

If the portfolio checkout, its `dist/` build, its guard file, or `node` is
not present, the script prints UNMEASURED with the reason and exits 3. It does
not print a figure it did not measure.

Run from the agent-ops root:

    uv run python demos/talk-2026-09-30/kit2_reconcile_guard_count.py
    uv run python demos/talk-2026-09-30/kit2_reconcile_guard_count.py --dry-run
    uv run python demos/talk-2026-09-30/kit2_reconcile_guard_count.py --portfolio <path>

The default portfolio path is the sibling checkout `../portfolio`, relative to
the agent-ops root.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHECKER = Path("scripts") / "check-published-metrics.cjs"
ARTIFACT = "src/pages/projects/false-green.astro"
ARTIFACT_URL = "https://sanlee.me/projects/false-green.html"

# The guard's own skip list, copied from `claimFiles()` in the checker. The
# walk must match the guard's walk, or the two counts run over different files.
BUILD_DIRS = {"dist", "public", "src", "node_modules", "scripts"}

# The raw grep. Independent of the guard's parser on purpose.
RAW_HTML = re.compile(r"\bdata-metric=")
RAW_MD = re.compile(r"<!--\s*metric:")

# Node runs the guard's own exported functions. Input arrives on stdin as JSON
# so no path needs quoting inside the script text.
NODE_SCRIPT = r"""
const fs = require('fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const guard = require(input.checker);
const out = {};
for (const f of input.files) {
  const text = fs.readFileSync(f.abs, 'utf8');
  out[f.rel] = {
    parsed: guard.markersIn(text, f.rel).length,
    unparsed: guard.unparsedMarkers(text, f.rel),
  };
}
process.stdout.write(JSON.stringify(out));
"""

RULE = "-" * 72


def _display(path: Path) -> str:
    """A path for output. The home directory is shown as `~`."""
    try:
        return "~/" + path.resolve().relative_to(Path.home()).as_posix()
    except ValueError:
        return path.as_posix()


def _walk(root: Path, suffix: str) -> list[Path]:
    """The guard's `claimFiles()` walk: skip dot names and the build dirs."""
    found: list[Path] = []
    for entry in sorted(root.iterdir()):
        if entry.name.startswith(".") or entry.name in BUILD_DIRS:
            continue
        if entry.is_dir():
            found.extend(_walk(entry, suffix))
        elif entry.name.endswith(suffix):
            found.append(entry)
    return found


def _unmeasured(reason: str) -> int:
    print(RULE)
    print(f"UNMEASURED: {reason}")
    print("No figure is printed, because none was measured.")
    return 3


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--portfolio", type=Path, default=REPO.parent / "portfolio",
                        help="path to the portfolio checkout (default: ../portfolio)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the commands and patterns, run nothing")
    args = parser.parse_args()

    portfolio: Path = args.portfolio
    checker = portfolio / CHECKER
    dist = portfolio / "dist"

    print("Kit 2, claim 3: the check actually ran")
    print(f"portfolio:  {_display(portfolio)}")
    print(f"guard:      {CHECKER.as_posix()}")
    print(f"artifact:   {ARTIFACT} ({ARTIFACT_URL})")

    if args.dry_run:
        print("DRY RUN. Nothing below was executed.")
        print(RULE)
        print("1. Walk the guard's file set:")
        print("   .html under dist/, .md under the portfolio root,")
        print(f"   skip dot names and {sorted(BUILD_DIRS)}")
        print("2. Guard count, with the guard's own exported parser:")
        print("   node -e <script> < files.json")
        print("   script calls markersIn(text, file) and unparsedMarkers(text, file)")
        print("3. Raw count, independent Python regex over the same files:")
        print(f"   HTML: {RAW_HTML.pattern!r}    Markdown: {RAW_MD.pattern!r}")
        print("4. Print guard count, raw count, and raw minus guard. Expect 0.")
        return 0

    node = shutil.which("node")
    if node is None:
        return _unmeasured("`node` is not on PATH; the guard is JavaScript.")
    if not portfolio.is_dir():
        return _unmeasured(f"portfolio checkout not found at {_display(portfolio)}.")
    if not checker.is_file():
        return _unmeasured(f"{CHECKER.as_posix()} not found in the portfolio checkout.")
    if not dist.is_dir():
        return _unmeasured("portfolio dist/ is not built; run `npm run build` there.")

    html_files = _walk(dist, ".html")
    md_files = _walk(portfolio, ".md")
    files = [(p, p.relative_to(portfolio).as_posix()) for p in html_files + md_files]
    if not html_files:
        return _unmeasured("no .html under dist/; the guard would exit 1 here too.")

    print(RULE)
    print("DID: walked the guard's file set")
    print(f"  .html under dist/:          {len(html_files)}")
    print(f"  .md under the portfolio:    {len(md_files)}")

    # --- Guard count: the guard's own parser, run by node ----------------
    payload = {
        "checker": str(checker.resolve()),
        "files": [{"abs": str(p), "rel": rel} for p, rel in files],
    }
    proc = subprocess.run(
        [node, "-e", NODE_SCRIPT],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        return _unmeasured(f"node exited {proc.returncode}: "
                           f"{proc.stderr.strip()[:300]}")
    guard_per_file = json.loads(proc.stdout)
    guard_total = sum(v["parsed"] for v in guard_per_file.values())
    guard_unparsed = sum(v["unparsed"] for v in guard_per_file.values())

    # --- Raw count: an independent grep in Python over the same files ----
    raw_per_file: dict[str, int] = {}
    for p, rel in files:
        text = p.read_text(encoding="utf-8", errors="replace")
        pattern = RAW_MD if rel.endswith(".md") else RAW_HTML
        raw_per_file[rel] = len(pattern.findall(text))
    raw_total = sum(raw_per_file.values())

    print(RULE)
    print("DID: counted markers two ways over the identical file list")
    print("  guard count: node ran the guard's exported markersIn() per file")
    print(f"  raw count:   Python regex {RAW_HTML.pattern!r} on HTML, "
          f"{RAW_MD.pattern!r} on Markdown")
    print("EXPECTED: raw minus guard = 0")
    print(RULE)
    print("OBSERVED, per file with at least one marker:")
    print(f"  {'file':<52}{'guard':>6}{'raw':>6}{'diff':>6}")
    for rel in sorted(raw_per_file):
        g = guard_per_file[rel]["parsed"]
        r = raw_per_file[rel]
        if g == 0 and r == 0:
            continue
        print(f"  {rel:<52}{g:>6}{r:>6}{r - g:>6}")
    print(RULE)
    diff = raw_total - guard_total
    print("OBSERVED, totals:")
    print(f"  guard count (markersIn):            {guard_total}")
    print(f"  raw count (independent grep):       {raw_total}")
    print(f"  difference (raw minus guard):       {diff}")
    print(f"  guard's own parity backstop,")
    print(f"  unparsedMarkers() summed:           {guard_unparsed}")

    print(RULE)
    if diff != 0:
        print(f"RESULT: {diff} marker(s) present that the guard cannot see. Exit 1.")
        print("A marker the pattern cannot read is an absence, and an absence")
        print("looks the same as a pass.")
        return 1
    print("RESULT: the two counts agree. Exit 0.")
    print("The reconciliation is the check on the check. Run it once.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
