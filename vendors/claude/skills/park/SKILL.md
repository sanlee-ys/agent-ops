---
name: park
description: Append a stray project/portfolio idea to the user's private ideas parking-lot file, so it's captured without derailing current work or building it prematurely. Invoke via /park <idea>, or when the user says "park this" or floats an idea he doesn't want to build right now. Do NOT use for ideas that already have an obvious home (an existing repo's own backlog/issue tracker) or for fully-scoped work ready to start now — park is only for not-yet-ready stray ideas.
---

# Park an idea

<!-- Published version: the source skill targets a specific file in the user's private
     strategy repo. The mechanism (append-only parking lot, fixed entry format) is the
     pattern worth reusing; the destination path is genericized below — swap in your own
     private notes location. -->

`<your-private-notes-repo>/ideas.md` is a low-ceremony catch-all in a private repo for
ideas that don't fit other, more structured notes yet — mid-conversation portfolio/project
ideas the user doesn't want to decide on or build right now. Private because half-formed
ideas shouldn't leak into public repos before they've been chosen to build.

## Entry format (match the existing file)

- Header: `## <Title>` — no date in the header itself.
- A short description of what the idea actually is.
- A few bullets if there are obvious considerations or build paths worth capturing while
  they're fresh (e.g. "two build paths depending on X").
- Last line: `- Not started. Parked <date>.`
- Entries separated by `---`.

## How to run it

1. Pull the idea from the invocation or the surrounding conversation — don't invent detail
   that wasn't actually said.
2. Draft title + description + bullets in the format above. Keep it short: this is a
   placeholder, not a spec.
3. Show the user the draft — a one-line "park this as-is?" is enough; this doesn't need the
   review weight of a personal journal entry.
4. Append it to the end of `<your-private-notes-repo>/ideas.md`, preceded by a `---`
   separator.
5. Offer to commit + push (private repo, standing OK).

## Un-parking

When an idea from this file actually gets built, the convention is to remove it or replace
the body with a link to where it landed. If the user references a parked idea and then
starts building it, flag that so a stale duplicate doesn't sit in `ideas.md` afterward.
