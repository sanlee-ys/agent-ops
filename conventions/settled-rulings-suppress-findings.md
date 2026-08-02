# Settled rulings suppress findings (hard rule)

A recurring sweep, audit or status pass rediscovers the estate from first
principles on every run. That is what makes it useful, and it is also what makes
it dangerous: unless something tells it otherwise, a **deliberate exception**
looks exactly like a **gap**. So the same gap gets reported every week, and the
owner pays for the same decision again, forever.

This is a claude-ops-local convention — no consumer repo mirrors it, so there is
no shared block to propagate.

The rule: **a question the owner has already closed is not a finding.** Any
automated sweep must check its candidate findings against a registry of settled
rulings *before* reporting, and drop the matches — silently.

## Why silently

The instinct is to compromise: keep reporting it, but softly. "Still open,
noted as intentional." That is not a compromise, it is the whole cost. The
expensive part of a re-raised finding was never the workflow file or the config
change — it is the owner reading it, recognising it, and deciding it again.
A soft mention costs exactly that, and a settled ruling can be re-raised
politely just as often as bluntly.

So a matched finding gets no footnote, no "also still open", no line in the
summary, and no recommendation. The single permitted acknowledgement is an
aggregate count — `Suppressed under settled rulings: N` — carrying no subject
and no finding text. That count exists because *invisible* suppression is the
false-green shape from [`agent-success-signals.md`](agent-success-signals.md):
a report that cannot distinguish "nothing to say" from "the filter ate
everything" is a report you cannot audit.

## The chip is the actual failure mode

Suppression at report time is the easy half. The half that bites is the
**handoff**: a sweep that spawns a background task for a finding it cannot fix
itself.

A chip is written to be self-contained, and a self-contained restatement of a
settled question is indistinguishable from an open one. The receiving session
starts with no history, reads a crisply framed tradeoff, reasons about it
correctly, and decides it — against a ruling it had no way to see. Every step is
locally right and the outcome is a reversal by accident.

The 2026-08-02 case (see
[`../debug-notes/2026-08-02-sweep-relitigated-a-settled-ruling.md`](../debug-notes/2026-08-02-sweep-relitigated-a-settled-ruling.md))
turned on one sentence of chip prose: the settled question was written up as
*"add a gate, or turn the dependency bot off"*. Framing it as a live tradeoff
is what invited a decision. It got one.

So:

- A **suppressed** finding never becomes a chip. Not in any framing.
- A chip for anything **adjacent** to a ruling must quote the ruling, name where
  the ruling is recorded, and instruct the receiving session to **confirm with
  the owner rather than decide**.
- Every chip a sweep files says, in its own text, to check the registry first
  and close as a false positive if it is already covered. A chip's prompt is the
  only context its session gets; if the constraint isn't in the prompt, it does
  not exist.

## The registry

Where it lives depends on the estate — the rulings themselves are usually
private, and this repo is public, so no registry ships here. What the mechanism
requires is the same wherever it lives:

- **Keyed on (subject, finding class)**, not on a repo name alone. "This repo is
  exempt from everything" is too blunt to survive; "this repo does not get a
  test gate" is a rule a sweep can apply and a reader can check.
- **One reason per entry, in the entry**, per
  [`allowlists-fail-both-ways.md`](allowlists-fail-both-ways.md) — the person
  deciding whether an entry can go is looking at the list.
- **Read fresh on every run.** An index line or a summary of the registry is not
  the registry; the failure mode is precisely a plausible new framing that a
  half-remembered rule does not catch.
- **General from the first entry.** The reflex is to special-case the repo that
  just caused the argument. The next deliberate exception is already out there,
  and hardcoding one subject buys nothing for it.
- **Its absence announces itself.** A registry that cannot be read fails *open*
  — every suppressed question returns at once, in a report that looks entirely
  normal. That is the worst-shaped failure available here, because the run it
  breaks is indistinguishable from a run with nothing to suppress. So an
  unreadable registry is reported at the top of the output, before the findings,
  and the consumer says plainly that the filter did not run. This is the same
  distinction the aggregate count draws, one layer down: the count separates
  "nothing matched" from "matches were dropped", and this separates both from
  "the filter was never applied."

## It fails both ways, and only one way is real

Per [`allowlists-fail-both-ways.md`](allowlists-fail-both-ways.md), an exception
list must also fail when an entry loses its subject. Here that is concrete: an
entry names a repo, the repo is deleted, the entry becomes a standing
suppression nobody is choosing to keep. Report that as maintenance.

The tempting second check is a review date — "re-examine this ruling quarterly."
Don't. A scheduled re-review of a live ruling is the relitigation this
convention exists to stop, with a calendar attached to make it feel like
process. Likewise, an entry that matched nothing this run is not stale; it is an
exception whose trigger did not fire. Entries change when the owner changes
them.

## The check

For any recurring automated report, ask: **if the owner has already decided this
question, what in the pipeline knows that?** If the answer is "the agent might
remember", the answer is nothing — a fresh run has no memory and a fresh chip
session has less. The reusable shape: **an automation that rediscovers state
without also discovering the decisions made about that state will keep
presenting settled questions as open ones, and each round spends the attention
the automation was supposed to save.**
