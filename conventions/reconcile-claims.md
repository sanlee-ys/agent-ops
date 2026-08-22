# An agent's self-report is a claim, not a record

**Reconcile it against `gh` and `git` before you report it.**

A session that says "opened PR #51" wrote a sentence. The sentence is identical
whether the `gh` call succeeded, returned an error nobody read, or never ran at
all. Nothing downstream can tell those apart, and the reader least able to tell
is the person the report was written for.

[`agent-success-signals.md`](agent-success-signals.md) records the same shape
from the tool side: a green check means the step exited 0, not that the work
happened. This convention is its other half. **A green check is not evidence the
work happened, and a confident sentence is not evidence a record exists.**

## The decision

**Rule adherence is measured against a system of record, never asserted.** At
the end of a cycle a session or an agentic loop compares its own claims against
a snapshot taken from `gh` and `git`. A claim with no matching record is one of
two things, and both are the same problem for the reader: a fabrication, or a
silent failure. Which one it is matters for the fix and not for the report.

Three reasons this is mechanical rather than a habit:

- **A habit is what fails under load.** The reports most likely to carry a false
  claim are the long ones at the end of a hard session, which is exactly when a
  self-check gets skipped.
- **A model cannot audit its own transcript.** The claim and the audit come from
  the same place. Only an outside record breaks that loop.
- **The failure is silent by construction.** Nothing turns red. The work simply
  is not there, and it is found later by a person looking for a pull request
  that was never opened.

## The mechanism

[`scripts/reconcile.py`](../scripts/reconcile.py). It reads only, it writes
nothing, and it sends nothing anywhere. JSON goes to stdout for a comparison to
consume; a compact table goes to stderr for a person to read.

```
uv run python scripts/reconcile.py --repo . --since 6h
```

Repeat `--repo` for more than one clone. `--since` takes a duration (`6h`,
`90m`, `2d`, `3w`) or an ISO datetime.

Exit codes are the interface: 0 snapshot complete, 1 one or more repos failed
(the JSON still carries the ones that worked, each failure named in its entry),
2 usage error.

## One detail that is a decision, not an implementation

**The branch list comes from `git ls-remote`, never from `git branch -r`.**
`git branch -r` prints a local cache of remote-tracking refs. It goes stale the
moment another machine or another session moves the remote, and it will happily
list a branch that was deleted an hour ago. A snapshot built to catch a false
claim must not be built from a cache that can carry one.

The same reasoning bars two other tempting shortcuts. A repo that could not be
read is reported as an ERROR, never as a repo with nothing in it — an empty
result and an unread result must not look alike. And a pull request whose merge
time cannot be parsed is dropped rather than assumed to be inside the window,
because a record that cannot be dated cannot corroborate a claim about when
something happened.

## What it does not do

It does not read the transcript, and it does not decide whether a claim is true.
It produces the ground truth. The comparison is the caller's, and so is the
judgement about which mismatch is a fabrication and which is a silent failure.
