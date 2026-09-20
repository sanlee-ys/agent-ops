# Derive the HANDOFF facts a machine already holds

**A HANDOFF State section restates facts that git and the forge hold exactly.**

The open pull requests, the newest tag, the top CHANGELOG entry, the branch. A
person writes those into prose once, and the merged set moves past the prose the
same day. Nothing turns red when it does, because nothing tests prose. The next
session reads a confident sentence and acts on it.

A refresh chore does not fix this. The classifier's State section went stale
twice in one day in spite of a same-day refresh, which is the case that produced
this page.

## The decision

**Check the claims a machine can derive. Never rewrite the file.**

Two build paths were open. The first generates the State section from `gh` and
the CHANGELOG. The second reads the section and reports what disagrees. This
repo takes the second.

The reason is what a HANDOFF is for. A generated State section carries only the
facts the generator knows, and the judgement around them is the part that helps
the next session: which pull request matters, what a number means, what to do
first. A generator deletes that prose or leaves it beside a machine block that
nobody trusts. A check leaves the writer in charge and refuses to let one class
of claim go quiet.

**The check is advisory about prose and strict about facts.** It never edits
HANDOFF.md, so a wrong report costs a reader one minute. That is what lets it
exit 1 on a disagreement without anybody having to fear it.

## The mechanism

[`scripts/handoff_check.py`](../scripts/handoff_check.py). It reads the repo's
HANDOFF.md, it derives the same facts from `git` and `gh`, and it prints every
claim as MATCH, DRIFT, or UNMEASURED.

```
uv run python scripts/handoff_check.py <repo-path>
```

Read the DRIFT rows and correct HANDOFF.md by hand. The tool names both values,
so the edit is mechanical. `--json` emits the same rows for a comparison to
consume:

```
uv run python scripts/handoff_check.py <repo-path> --json
```

Exit codes are the interface: 0 no drift, 1 one or more DRIFT rows, 2 usage
error. A missing HANDOFF.md is a usage error, and the next section says why.

Six checks run. Five read the HANDOFF against a system of record, and one reads
the clone. The script's module docstring names each one and says what it
compares.

## Three rules the report rests on

**1. Absent is not zero.** A `gh` call that fails reports UNMEASURED with the
reason. It never reports an empty set of open pull requests, because an empty
set is a real answer that the check acts on. A claim the State section does not
make reports UNMEASURED, never MATCH. An unrun check is not a pass, and the
output must never let the two look alike. `agent-trigger-authorization.md`
carries the same rule for the guard layer, and
`allowlists-fail-both-ways.md` carries it for exception lists.

**A missing HANDOFF.md refuses.** It exits 2. A repo whose HANDOFF someone
deleted must not report the same green as a repo whose HANDOFF is correct. That
is the same rule at the file level, and it is the behaviour to expect when this
runs across several repos.

**2. The remote is the authority.** Branches and tags come from `git ls-remote`.
A remote-tracking ref is a local cache. It lists a branch that the remote
deleted an hour ago, and a check built to catch a stale claim must not read from
a cache that can carry one. [`reconcile-claims.md`](reconcile-claims.md) makes
the same choice for the same reason. The `main-vs-origin` row exists for the
same reason: when the clone is behind, the other five rows describe a tree that
the HANDOFF's readers do not have.

**3. A false DRIFT is the expensive error.** A check that reports a drift which
is not there trains the reader to skip the output, and a skipped check is worse
than no check. Every detector is therefore built to under-report rather than to
guess, and the limits below say where.

## Honest limits

Read these before you act on a row.

1. **A claim detector reads a shape, not a sentence.** The open-pull-request
   detector attaches the word "open" to a number only inside a narrow window.
   English attaches it in ways the window misses, as in "both open: #208 and
   #209". That under-report is deliberate and is pinned by a test. It is safe
   only because the check never compares that set to the forge for equality.
   The second direction asks whether a number appears on the page at all, which
   reads no English.
2. **The tag check is one-directional.** It fires only when the remote is
   tagged PAST the newest version the prose names. A HANDOFF that discusses an
   older tag is a correct record of an older day. A check that called that a
   drift would fire on every honest file.
3. **A version in prose needs the leading `v`.** A HANDOFF writes its own
   release as `v3.2.0` and a dependency bump as `4.37.3`. Without that rule the
   Dependabot number reads as the newest release, and it is usually the highest
   number on the page. The failure is SILENT: the tag check reports MATCH and
   the drift stays. This one was found by a run against a real file, not by
   review.
4. **The job cross-check needs two distinctive words.** It finds work that the
   "Next jobs" section marks DONE and the "Owner-only" section still describes
   as pending. It keys on the job's own words, never on the job number, because
   a finished job legitimately hands one remaining step to the owner and that
   step cites the job it came from. A job whose title holds fewer than two
   distinctive words can never be matched.
5. **MATCH covers the derived facts only.** Everything a HANDOFF is actually
   for stays invisible here: what the work means, which risk matters, what to do
   first. A file can pass every row and still mislead a reader.
6. **It reports the repo, not the work.** A pull request that is open and
   irrelevant looks exactly like a pull request that is open and urgent.

## Measured, 2026-09-20

Two runs, on the day the tool landed. Local paths are shown `~`-style, per this
repo's publication boundary.

**The motivating case.** `defense-news-classifier`, whose HANDOFF dates from
2026-08-02:

```
handoff check  ~/code/defense-news-classifier/HANDOFF.md

DRIFT      open-prs         (handoff)
    claimed  open per State: 123, 147
    derived  open per gh: 206, 207, 208, 209
    The State calls 123, 147 open. The forge does not. The forge lists 206, 207, 208, 209 open. The State never names them

UNMEASURED branch           (handoff)
    why      the State section names no branch
    derived  main

DRIFT      main-vs-origin   (clone)
    claimed  local main aa8e6d54e
    derived  remote main 46611b866
    the other checks read a tree that the remote does not carry

DRIFT      latest-tag       (handoff)
    claimed  v3.2.0
    derived  v3.2.1
    the remote is tagged past the newest version the State section names

DRIFT      changelog-top    (handoff)
    claimed  not mentioned
    derived  3.2.1
    the State section never names the top released CHANGELOG version

DRIFT      job-consistency  (handoff)
    claimed  Owner-only pending: Running the higher-power re-run (job 3)
    derived  job 3 DONE in Next jobs: The higher-power re-run
    one piece of work carries two answers in one file. Shared words: higher, power

5 DRIFT, 1 UNMEASURED, 0 MATCH.
An UNMEASURED row is not a pass. It is a check that could not run.
This tool never edits HANDOFF.md. See conventions/handoff-check.md.
```

Exit code 1. The last row is the failure that produced this page: job 3 is
struck out and marked DONE under "Next jobs", and the "Owner-only actions
pending" list still asks the owner to run it. The `branch` row is the honest
shape of a claim that the file never makes. Nothing in this lane edited that
HANDOFF, and the classifier repo stays read-only here.

**This repo.** `agent-ops` keeps no HANDOFF.md:

```
handoff_check: ~/code/agent-ops has no HANDOFF.md. Nothing was checked, and that is not a pass.
```

Exit code 2. That is the intended answer, and it is worth reading twice. The
easy alternative is to exit 0 and print nothing, which would make a repo with no
HANDOFF indistinguishable from a repo whose HANDOFF is correct. A sweep across
several repos would then report green for the one file that went missing.

## What it never does

It never writes HANDOFF.md, and it never writes any other file. It runs no
command that mutates, and it sends nothing anywhere.
`tests/test_handoff_check.py::TestNeverWrites` compares the HANDOFF bytes before
and after a full run, so the claim is pinned rather than argued.
