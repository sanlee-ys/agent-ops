#!/usr/bin/env python3
"""Redline guard (pre-commit hook) — this repo's publication boundaries, enforced.

This repo is public and canonical (decisions/ADR-002): material is written
here first, so redaction happens at write time. "Redact carefully" is a
behavioral rule, and this repo's own incident series documents what those
are worth without a mechanical backstop. This is the backstop: every commit's
staged content is scanned for the ADR-001 boundary violations before it can
land.

What it blocks:
  1. Credential-shaped strings (GitHub token prefixes, Anthropic keys, AWS
     access key IDs, private-key blocks) — real, revoked, or "example".
  2. Private memory links ([[wiki-style]]) that leak the private notes layer.
  3. Local user paths (C:/Users/<name>, /c/Users/<name>) — publish ~-style
     paths instead.
  4. Identifying terms (the owner's username, employer names, private repo
     names). These ship as SHA-256 hashes, not literals — a guard that blocks
     private repo names can't have those names written in its own public
     source, or the guard file itself becomes the disclosure.
  5. Owner-slug repo references (sanlee-ys/<private-repo>) via the same
     hashed set.

Precision over reach: terms that are also common English words are flagged
only in repo-shaped contexts (within a few tokens of "repo"/"repository"/
"github"/"git" or in an owner slug), because a guard that fires on ordinary
prose gets routed around — the false-positive lesson from
security/credential-guard.py's history (see its docstring and
incidents/2026-07-03-credential-guard-interpreter-bypass.md).

Escape hatch: REDLINE_OK=1 <git commit ...> skips the guard for one commit,
for the rare legitimate case (e.g. documenting the guard itself). Using it
is a conscious act that should survive review.

Local extensions: an untracked .redlines.local file (one literal term per
line, gitignored) adds machine-local terms without publishing them.

Install:  git config core.hooksPath scripts/githooks
Verify:   stage a decoy violation and watch it block (see scripts/README.md).
"""

import hashlib
import os
import re
import subprocess
import sys

# --- 1-3: literal patterns, safe to publish -------------------------------

LITERAL_PATTERNS = [
    ("github token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("github fine-grained PAT", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    ("anthropic key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}")),
    ("aws access key id", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    # (?<!\\): an escaped open-bracket in regex source (r"\[[^\]]*\]") puts a
    # literal "[[" in the text without being a wiki link; a real link's opener
    # is never preceded by a backslash.
    ("private memory link", re.compile(r"(?<!\\)" + r"\[\[" + r"[^\]]+" + r"\]\]")),
    ("local user path", re.compile(r"(?:[Cc]:[\\/]+|/c/)Users[\\/]+\w+")),
]

# --- 4-5: hashed identifying terms -----------------------------------------
# sha256(lowercase term). ALWAYS-terms are violations wherever they appear;
# CONTEXT-terms are common English words and only count near repo-shaped
# neighbors or in an owner slug.

HASHED_ALWAYS = {
    "3b61ef0580146ffff7b93e52b9fe5af59f63c028a49f0e473ff4d99abb0dcdaa",
    "f40cc1299629259447e388440ce62167fc6caa3b9dc387640bf2e9621293a73e",
    "f0e80017af911cc5c875de1a783182177ce690983c94b8617666bf9505a61536",
    "4ef9bfe6a5402861fd19b51cdbe76e50ac1cd3cf36e3d20530d57f5dd13ab60e",
}

HASHED_REPO_CONTEXT = {
    "89b7505ad79ad4892d6f2f110320da7b79e4110e0117b8249de318688c3ad83b",
    "eab762a03fd979a04cc4706e6536d382bc89d2d1356afcd054a16b2235ecd471",
    "c2fb788c7deedbeaa296e424d4c2921b871a4f6cb4cf393c1c1105653ab399b4",
}

CONTEXT_WORDS = {"repo", "repos", "repository", "repositories", "github", "git"}
CONTEXT_WINDOW = 3  # tokens on either side

OWNER_SLUG = re.compile(r"sanlee-ys/([\w.-]+)")

WORD = re.compile(r"[A-Za-z0-9_]+")

# The guard's own source contains the patterns it hunts for; scanning itself
# would always fire. Same false-positive principle as above, applied to us.
EXEMPT = {"scripts/redline-guard.py"}


def sha(word: str) -> str:
    return hashlib.sha256(word.lower().encode()).hexdigest()


def staged_files() -> list:
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
        capture_output=True, check=True,
    ).stdout.decode("utf-8", "replace")
    return [f for f in out.split("\0") if f]


def staged_content(path: str):
    raw = subprocess.run(["git", "show", f":{path}"], capture_output=True).stdout
    if b"\0" in raw:  # binary
        return None
    return raw.decode("utf-8", "replace")


def mask(snippet: str) -> str:
    """Never echo a potential secret back in full — that would be incident 1."""
    s = snippet.strip()
    return s[:6] + f"...({len(s)} chars)" if len(s) > 8 else s


def local_terms() -> list:
    try:
        with open(".redlines.local", encoding="utf-8") as f:
            return [t.strip() for t in f if t.strip() and not t.startswith("#")]
    except FileNotFoundError:
        return []


def scan(path: str, text: str, extra_terms: list) -> list:
    violations = []
    lines = text.splitlines()

    for lineno, line in enumerate(lines, 1):
        for label, pat in LITERAL_PATTERNS:
            for m in pat.finditer(line):
                violations.append((path, lineno, label, mask(m.group(0))))
        for term in extra_terms:
            if term.lower() in line.lower():
                violations.append((path, lineno, "local redline term", mask(term)))
        for m in OWNER_SLUG.finditer(line):
            h = sha(m.group(1))
            if h in HASHED_ALWAYS or h in HASHED_REPO_CONTEXT:
                violations.append((path, lineno, "private repo slug", mask(m.group(0))))

    tokens = [(m.group(0), m.start()) for m in WORD.finditer(text)]
    words = [t[0].lower() for t in tokens]
    for i, w in enumerate(words):
        h = sha(w)
        if h in HASHED_ALWAYS:
            lineno = text.count("\n", 0, tokens[i][1]) + 1
            violations.append((path, lineno, "identifying term", mask(w)))
        elif h in HASHED_REPO_CONTEXT:
            lo, hi = max(0, i - CONTEXT_WINDOW), i + CONTEXT_WINDOW + 1
            if CONTEXT_WORDS & set(words[lo:hi]):
                lineno = text.count("\n", 0, tokens[i][1]) + 1
                violations.append((path, lineno, "private repo name in repo context", mask(w)))
    return violations


def main() -> int:
    if os.environ.get("REDLINE_OK") == "1":
        sys.stderr.write("redline-guard: skipped via REDLINE_OK=1 (conscious override)\n")
        return 0

    extra = local_terms()
    violations = []
    for path in staged_files():
        if path.replace("\\", "/") in EXEMPT:
            continue
        text = staged_content(path)
        if text is None:
            continue
        violations.extend(scan(path, text, extra))

    if not violations:
        return 0

    sys.stderr.write("REDLINE GUARD: this commit would publish boundary violations "
                     "(decisions/ADR-001, enforced per ADR-002):\n")
    for path, lineno, label, snippet in violations:
        sys.stderr.write(f"  {path}:{lineno}  [{label}]  {snippet}\n")
    sys.stderr.write(
        "\nFix the content (genericize, use placeholders, ~-style paths). If this\n"
        "block is itself the mistake, re-run with REDLINE_OK=1 and say why in the\n"
        "commit message.\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
