# ADR-006: Parallel sessions claim the concern before working it, or they collide

**Status:** Accepted — 2026-07-26. Written the same day as the collision that
prompted it.
**Scope:** This repo (the Claude operating layer), applying to every repo worked
by more than one session. Repo-local ADR per the two-tier convention.
**Related:** [`ADR-004-ref-explicit-git-in-shared-clones.md`](ADR-004-ref-explicit-git-in-shared-clones.md)
— the other failure mode of a shared clone, where the hazard is a sibling moving
the checkout rather than a sibling duplicating the work.

## Context

Sessions run in parallel across more than one machine and more than one
interface. They share git remotes and nothing else. There is no live channel
between them: a session cannot see another's conversation, its working tree, or
its intent, and no supported mechanism exists to transfer a session between
machines — transcripts are stored locally, scoped to a project directory, and
each interface keeps its own history.

The standing pre-flight already anticipates this. It says to scan for work
already in flight before claiming anything. That step is sound and it did not
help, because it can only find work that has been made *visible*.

### What happened

On 2026-07-26 two sessions independently wrote the same architecture decision.
One was on a remote host writing a repo-local ADR into a working tree; the other
was on a workstation writing the cross-repo version. Both were correct about
what should be written. Neither could see the other:

- The remote session's work was an **untracked file**. Nothing about it existed
  outside that one filesystem, so no scan on any other machine could find it.
- The workstation session's work was a **local branch**, pushed only at the
  moment it was ready to open a pull request — by which time both documents
  existed.

The scan ran and returned nothing, truthfully. The work was invisible by
construction, not by oversight.

They also disagreed. Within about ninety seconds, one session merged a rule
saying a particular host should not be configured to commit, while the other
configured exactly that on the same host. Both had defensible reasons. Neither
was wrong given what it could see.

### Why a channel is not the fix

The obvious reading is that the sessions needed a way to talk. That is the wrong
diagnosis, and acting on it would buy machinery that does not solve the problem.

Both sessions believed they owned "write the decision record." Two peers holding
the same belief will collide however well they can communicate, because the
collision happened at the moment of *deciding to start*, not during the work.
A channel helps a session that knows to ask. It does nothing for a session with
no reason to think the question exists.

The failure is a claim failure. Ownership was never asserted anywhere both
sessions could see.

## Decision

**1. Claim before you work.** The first action on a concern is to push a branch
naming it — before any content exists. An empty branch is enough; a draft pull
request is better, because it carries a title and a description into
`gh pr list`. Only then start the work.

This inverts the current habit, which is to branch locally, do the work, and
push when opening the pull request. That habit makes the claim visible only
after the window in which it would have mattered has closed.

**2. Name the concern, not the change.** A scan is only useful if a sibling can
tell from the branch name whether it overlaps. `decision/herdr-verdict` is a
claim. `docs/updates` is not.

**3. Untracked files are not work in progress; they are invisible work.** Any
artifact meant to be found by another session lives on a pushed branch. A draft
in a working tree on a host nobody else can reach does not exist for
coordination purposes, however finished it is.

**4. When two sessions must run at once, they get disjoint concerns, and one
owns the decision.** Cutting by file is the existing rule and remains correct
for content. It is not sufficient for *decisions*, which do not live in a
predictable file and tend to be written wherever the session that had the
insight happens to be. Where a decision is in scope, exactly one session holds
it and the others report into it.

## What this does not fix

Stated plainly, because a control that is oversold is worse than none.

The claim window shrinks; it does not close. Two sessions starting within the
same few seconds still collide, and a claim pushed after a sibling has already
started does not undo the sibling's work. This converts a whole-task race into a
few-seconds race, which is a large improvement and not a guarantee.

It also depends on discipline at exactly the moment discipline is weakest — the
start of a task, when the work feels obvious and the ceremony feels pointless.
The mitigation is that the ceremony is one command and produces an artifact
wanted anyway.

## Options considered

**(a) A shared coordination file in the repo.** A list of in-flight claims,
committed. Rejected: it collides on itself, needs a pull to be current, and
duplicates what branches already express natively.

**(b) A live channel between sessions.** Rejected on the diagnosis above — it
addresses communication, and the failure was ownership. It is also the largest
option by far, for the problem least in evidence.

**(c) A coordinator session that dispatches to worker sessions.** This is the
shape of the agent-fleet frameworks already declined elsewhere, and it does
solve the problem: one brain decides, the rest execute. Rejected for now as
disproportionate — it requires standing infrastructure, and the same benefit is
available from decision 4 without any.

**(d) Claim by pushed branch. — CHOSEN.** Costs one command, uses a mechanism
that already exists on every machine, is visible from every machine
simultaneously, and produces the branch the work needed anyway.

**(e) Never run sessions in parallel.** Honest to consider and rejected:
parallelism is the point. The cost of the collision was two documents and an
hour, against a working pattern worth considerably more.

## The rule

> **Between processes that share only a remote, ownership must be asserted in
> the remote or it does not exist. Work that has not been pushed is not
> in progress from any other session's point of view — it is invisible, and a
> scan that misses it is not wrong. Claim first, then work.**

The generalisation worth keeping: **the scan is only as good as what the others
published.** Both sessions here ran the correct check and got a truthful,
useless answer. When a coordination control fails, look at what the control can
*see* before concluding anyone skipped it.

## Consequences

- Branches appear before they have content, so the branch list carries in-flight
  intent as well as finished work. That is the point, and it makes branch
  hygiene matter more: an abandoned claim is a false claim, so delete it.
- A session that finds an existing claim on its concern stops and reports rather
  than proceeding in parallel. That is the intended behaviour even when the
  claim looks stale.
- Decisions specifically get a single owner when sessions overlap. Content can
  still be cut by file.
