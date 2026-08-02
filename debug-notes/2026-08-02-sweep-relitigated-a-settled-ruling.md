# A weekly sweep re-raised a settled ruling, and a chip carried it far enough to overturn it

**Date:** 2026-08-02 | **Severity:** Low — no exposure, no spend, nothing lost; the cost was a decision made for the third time, plus a revert
**Classification:** debug note, not an incident, per [README.md](README.md) — no credential or private data moved, no usage window burned, and no security control failed. What broke was a process loop.

## Summary

A weekly read-only repo-hygiene sweep flagged a private personal-utility repo
for having no CI and several dependency-bot PRs merging without checks. That
question was not open. It had been ruled closed nine days earlier, in writing,
in the notes layer the sweep runs on top of, with the instruction that missing
CI there is intentional and is not to be listed as a finding, a recommendation
or an "also still open" item in any sweep, hygiene report or status map.

The sweep reported it anyway, and then filed a background-task chip. The chip
framed the settled question as a live tradeoff — *add a gate, or turn the
dependency bot off* — and a receiving session with no history read that, reasoned
about it correctly, and **decided it**: it added a CI workflow. The owner had to
rule on it a third time. The workflow, its README section and the bot's
`github-actions` block were reverted in one commit.

The defect is not in that repo, and that repo needed no changes. The defect is
that the sweep rediscovers every "gap" from first principles each run, with no
memory of deliberate exceptions, and then launders the result into a chip that
reads as a fresh open question.

## What actually went wrong

**The sweep had no notion of a settled question.** Its prompt described how to
find things and how to classify them for safety. Nothing in it asked whether a
thing it found had already been decided. Every run therefore re-derived the same
gap, correctly, from a clean slate — which is exactly what a sweep is for, and
exactly why it needs the second input.

**The chip was the amplifier, not the messenger.** A report the owner reads is
recoverable: he recognises the item, skips it, and loses a few seconds. A chip is
not read by him at all. It is written to be self-contained, handed to a session
with no history, and that session's whole world is the prompt text. When the
prompt says "add a gate, or turn the bot off", it has described an open
decision, and a competent session will make it. Nothing in the loop was
malfunctioning; the framing did all the damage.

**Every argument for the change was locally true.** The gate was cheap, it went
green, and it caught a real major-version bump on a dependency. That is what
makes this worth writing down: correctness of the finding is not the test. The
question had been answered, and answering it again is the cost regardless of
which answer is better. "But this instance is different, smaller,
self-verifying" is the shape all three rounds took.

## Fixes applied

- **A registry of settled non-findings**, in the private notes layer (the
  rulings name specific repos, so nothing about it ships to this public repo).
  Entries are keyed on **(subject, finding class)** rather than on a repo name,
  carry their reason and their ruling date inline, and point at the full record.
- **The sweep reads it before reporting.** A matched candidate is dropped
  outright — no softened mention, no summary line, no cleanup recommendation, no
  chip. The one acknowledgement is an aggregate `Suppressed: N` count carrying no
  subject and no finding text, so the filter is visible without re-surfacing what
  it filtered.
- **Chip discipline in the sweep's own prompt.** A suppressed finding never
  becomes a chip. A chip for anything merely adjacent to a ruling must quote the
  ruling, name where it is recorded, and tell the receiving session to confirm
  with the owner rather than decide. And every chip the sweep files instructs its
  session to read the registry first and close as a false positive if covered —
  because the prompt is the only context that session gets.
- **The registry fails both ways**, per
  [`../conventions/allowlists-fail-both-ways.md`](../conventions/allowlists-fail-both-ways.md):
  each entry names a subject repo, and a subject that no longer exists is
  reported as maintenance rather than enforced forever.
- The general rule is written up as
  [`../conventions/settled-rulings-suppress-findings.md`](../conventions/settled-rulings-suppress-findings.md).

## Design calls worth keeping

**No "review by" dates on entries.** The obvious second staleness check is a
scheduled re-examination of each ruling. It is the relitigation this whole fix
exists to prevent, with a calendar attached to make it look like hygiene. The
only automatic staleness signal is a subject that has disappeared. An entry that
matched nothing this week is not stale — it is an exception whose trigger did
not fire.

**A count, not silence.** Dropping findings with no trace would make the report
unauditable in the way [`../conventions/agent-success-signals.md`](../conventions/agent-success-signals.md)
describes: no way to tell "nothing to report" from "the filter ate everything".
A bare integer costs nothing and cannot restate a ruling.

**Keyed on the finding class, not the repo.** "Exempt from everything" would have
been simpler and would have gone stale immediately — ordinary git hygiene in that
repo is still worth reporting; only the CI-gap class is settled.

**General from the first entry.** Hardcoding the one repo that caused the
argument would have solved this instance and nothing else. Any repo with a
deliberate exception has the same failure waiting.

## Lessons

1. **A sweep that rediscovers state must also discover the decisions made about
   that state.** Otherwise a deliberate exception is indistinguishable from a
   gap, and the report is a machine for re-asking answered questions.
2. **Handoffs strip the context that made a finding harmless.** A chip, a ticket,
   an issue — anything self-contained — turns "the owner will recognise this and
   skip it" into "a stranger will read this as a decision to make." Suppress
   before the handoff, never after.
3. **A settled question re-raised politely costs the same as one re-raised
   bluntly.** The expensive resource is the owner's attention, and a soft mention
   spends all of it. There is no gentle version of asking again.
4. **The correctness of a finding is not a licence to raise it.** Every argument
   for the change here was true, and the change was still wrong, because the
   decision had already been made by the person entitled to make it.
