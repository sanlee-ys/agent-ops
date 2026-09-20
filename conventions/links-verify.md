# Links — verify before sending (hard rule)

Canonical home for the link-verification rule shared across the repo fleet.
Consumer repos carry a compressed inline restatement wrapped in
`<!-- shared:links-verify -->` markers plus a pointer back here; this file is
the full text and rationale. Edit here, then propagate with
[`../scripts/sync-shared-blocks.py`](../scripts/sync-shared-blocks.py).

Added 2026-07-04 after repeated 404s from links given in chat. Any clickable
reference given to the user must actually resolve:

1. <a id="full-urls-only"></a>**Full URLs only.** Point at files with the complete
   `https://github.com/<owner>/<repo>/blob/<ref>/<path>` URL — never a
   local-clone path like `<repo-folder>/materials/foo.md`, whose leading
   repo-folder segment doubles when pasted after a GitHub branch URL and 404s.
2. <a id="verify-before-sending"></a>**Verify before sending.** Confirm the exact path exists on the exact ref
   before linking (e.g. GitHub MCP `get_file_contents`, or `git ls-tree
   origin/<branch> -- <path>` after a confirmed push). Unverified links do not
   get sent — say "unverified" instead.
3. <a id="branch-links-are-perishable"></a>**Branch links are perishable.** A `blob/<feature-branch>` URL dies when the
   branch merges and is deleted. Flag branch-scoped links as such; prefer
   `main` URLs once the work has merged.

If a link 404s, the failure mode was here — fix the process, not just the link.
