# Reference shelf

Notes that are **not** conventions. Nothing here tells anyone what to do.

A convention in [`../conventions/`](../conventions/) is a rule with a check: it
constrains work happening now, and something in the repo is expected to comply
with it. These are the other kind of finding — a worked implementation of a
problem this fleet does not currently have, written down so that *if* it ever
does, the design work is already done and does not get re-derived badly under
time pressure.

The bar for filing here: the problem is one this fleet could plausibly hit, the
reference implementation is public and readable, and the interesting content is
the **edge cases someone already paid for** rather than the happy path — because
the happy path is the part anyone would get right unaided.

Read these when you are about to build the thing they describe. Not before.

- [`edit-tool-matching.md`](edit-tool-matching.md) — the matching and
  error-reporting algorithm for a string-replacement file-edit tool: exact
  before fuzzy, uniqueness enforced after the fuzzy hit, normalization that
  never reaches disk, per-edit-index errors.
- [`terminal-rendering.md`](terminal-rendering.md) — the two primitives that
  make a hand-written terminal UI not tear and not need a framework:
  synchronized-output escapes around any multi-line repaint, and whole-screen
  render diffed by string equality.

Sources are cited by project and path. Both current entries come from a read of
[pi](https://github.com/earendil-works/pi) (MIT), the same read behind the
pi-derived conventions.
