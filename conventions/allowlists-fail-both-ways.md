# Allowlists — fail in both directions (hard rule)

Any allowlist, exemption set or "known exception" list enforced by a gate has to
be able to fail **twice**: once when something violates it, and once when an
entry in it no longer has a subject. A list that only fails the first way is not
a control, it is a comment that used to be true.

This is a claude-ops-local convention — no consumer repo mirrors it, so there is
no shared block to propagate.

Every entry carries a one-line reason, in the list itself. Not in a commit
message, not in a PR thread: the person deciding whether the entry can go is
looking at the list, and the reason is the whole input to that decision.

## The mechanism

The failure this prevents is not a bypass, it is *rot*. An exception is added
for a real reason, the reason expires, the entry stays. Nothing goes red,
because a one-way check only ever asks "is this violation on the list?" — never
"is everything on the list still a thing?" The gate keeps passing, and the
allowlist quietly becomes a standing grant of whatever anyone ever needed.

Two clean implementations of the closed loop, both from
[pi](https://github.com/earendil-works/pi) (MIT), an agent harness whose
supply-chain gates are unusually literal about this:

- **`scripts/generate-coding-agent-shrinkwrap.mjs`.** Packages with install
  scripts are the interesting supply-chain surface, so the generator carries
  `allowedInstallScriptPackages` — a `Map` keyed by `name@version`, valued by a
  sentence saying why that one is tolerable ("preinstall is a no-op in the
  published package"). Validation walks the generated shrinkwrap and errors on
  any `hasInstallScript` entry that is *not* in the Map. Then it walks the Map
  and errors on any key it did not just see: `allowed install-script package
  <id> is no longer present; remove it from the allowlist`. Pinning by
  `name@version` is doing work here too — a version bump re-opens the review
  rather than inheriting the old verdict.
- **`scripts/check-lockfile-commit.mjs`.** A pre-commit gate that reads the
  *semantic* content of the staged lockfile diff instead of matching a path: it
  parses `HEAD:package-lock.json` and `:package-lock.json`, diffs the `packages`
  maps, and lets the commit through only when every changed entry is
  workspace-internal (`packages/…`). Anything touching `node_modules/…` blocks,
  with a summary of what actually changed (added / removed / version-bumped) and
  a review checklist. The single override is an explicit env var,
  `PI_ALLOW_LOCKFILE_CHANGE=1`, named in the failure message — the same shape as
  this repo's `REDLINE_OK=1` and `MASK-OK`: one conscious act, visible in the
  command, not a persistent entry.

That contrast is the design rule, not a detail. A **standing** exception (an
allowlist entry) must be re-validated on every run, because it outlives the
person who understood it. A **one-shot** exception (an env var or a token in the
command) does not need that, because it dies with the command.

## Why this belongs next to the false-green material

[`agent-success-signals.md`](agent-success-signals.md) asks whether a green can
tell *passed* from *never ran*. This is the same question one layer down: a
one-way allowlist is a gate that cannot tell *current* from *stale*. Both are
signals with a collapsed state space — a distinction the reader assumes is being
made, that the mechanism never actually makes. And both fail in the safe-looking
direction, which is why neither gets noticed by running it.

## The check

For each guard chain here that holds an exception list, ask once: what happens
when an entry's subject disappears? If the answer is "nothing", it is a one-way
list. Concretely, that means auditing at least:

- **`scripts/redline-guard.py`** — the `EXEMPT` path set (currently the guard's
  own source), and the untracked `.redlines.local` terms, which are the worst
  case of this failure mode because they are machine-local and unreviewable.
  Nothing today fails when an exempt path is deleted or renamed.
- **`security/credential-guard.py`** — the sensitive-path patterns and the
  carve-outs around them. Same question in the mirror: an entry naming a file
  shape that no longer exists is dead weight that makes the real list harder to
  read.
- **Permission allowlists** generally, per
  [`operating-model.md`](../operating-model.md) — a prefix rule kept for a
  command shape nobody runs anymore is a standing grant with no owner.

Fixing them is not this convention's job, and none of these are urgent. The rule
is that a *new* exception list does not ship one-way, and that an existing one
gets the reason-per-entry the next time it is edited.

The reusable shape: **a list that only fails in the direction you were thinking
about when you wrote it will eventually be enforcing a decision nobody would
make today.** Make it fail toward its own maintenance.

See also [`truncated-producers-taint.md`](truncated-producers-taint.md) and
[`truncation-defers.md`](truncation-defers.md), the other two conventions
distilled from the same read.
