---
name: proglog
description: Append a dated entry to the user's private pairing-journal file — concepts relearned (with an analogy to a prior stack when one genuinely fits) and what got built this session. Invoke via /proglog, or proactively offer it at the end of a substantive hands-on pairing/relearning session. Also proactively check at the START of a session that looks like a continuation of pairing work: if the latest prog-log entry looks like it predates work that's evidently happened since, remind the user before diving back in. Do NOT use for quick one-off questions, mechanical edits, or sessions with no relearning/building content worth journaling — and don't nag if the user declines the reminder once.
---

# Prog-log entry

<!-- Published version: the source skill targets a specific file in the user's private
     strategy repo. The mechanism (dated first-person journal, concept-recall section,
     session-start staleness check) is the pattern worth reusing; the destination path is
     genericized below — swap in your own private journal location. -->

`<your-private-notes-repo>/prog-log.md` is a private, dated pair-programming journal —
what the user relearned each session (moving from one stack to another, strong on
fundamentals, rusty on syntax — this is the relearning bridge toward a target role) and
what he was building. It's written in **his** voice, first person, assisted-by Claude — not
a third-person summary of him. He's said outright he won't reliably remember to trigger this
himself, so this skill carries both ends: offering to log at session end, and catching a
missed log at the next session's start.

## Entry format (match the existing file, don't improvise a new shape)

Read `<your-private-notes-repo>/prog-log.md` before drafting — it already has real entries
to pattern-match against. The established shape:

- Header line: `## YYYY-MM-DD — <short title>`
- Body as short paragraphs, each led by an inline bold label (not a markdown subheading):
  `**Working on:**`, `**What I built (hands-on pairing):**`, `**Process notes:**` /
  `**Process lessons:**`, `**Up next:**` — used flexibly, skip ones with nothing to say.
- `**Concepts that came back to me:**` as its own bold line, followed by a bullet list —
  bolded concept name first, then the explanation, then an analogy to a prior stack *only
  if one genuinely clicked*. Don't force an analogy in. This section is the one that matters
  most; give it the most care.
- Entries are newest-first, separated by `---`.
- Not every entry has to be a relearning session — an operational/handoff-flavored entry
  is fine when that's genuinely what the session was, but default to the shape above for
  ordinary hands-on pairing.

## How to run it — offering at session end

1. Check there's actually something worth logging: a concept genuinely relearned, or
   something hands-on built. If the session was a quick fix or Q&A, say so and skip —
   don't manufacture a "concepts" section from nothing.
2. Draft the entry from what actually happened this session, in the user's first-person
   voice.
3. Show the user the draft before writing anything. This is his personal journal — the
   phrasing and the "aha" have to be *his* understanding, not Claude's gloss on it. Let him
   edit.
4. Once approved, open `<your-private-notes-repo>/prog-log.md` and insert the new entry as
   the new first entry — right after the intro paragraph's trailing `---`, pushing the
   current top entry down, with a fresh `---` after the new entry's body to separate it from
   what follows.
5. Offer to commit + push (private repo — standing OK to just do it once the user has
   approved the content; no need to re-ask about the push separately).

## How to run it — reminder at session start

When a new session opens and looks like a continuation of hands-on pairing work (not every
session — skip this for one-off questions), do a cheap check before diving in:

1. Read the top entry of `<your-private-notes-repo>/prog-log.md` — its date and title.
2. Look for evidence of a substantive session since that date that isn't reflected in the
   log (recent commits/PRs in the repo being picked back up, or the user's own description
   of what he did last time).
3. If there's a real gap, say one line: *"Last prog-log entry was `<date>` (`<title>`) —
   looks like there's been a session since that isn't logged. Want me to draft that entry
   before we continue?"* If he says no, drop it — don't re-ask later in the same session.
4. If nothing looks missing, don't mention prog-log at all — silence is the correct output
   most of the time.
