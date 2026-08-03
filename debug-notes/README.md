# Debug notes

Write-ups that were worth keeping but did not clear the incident bar.

**The bar** (2026-08-01): an entry goes in `incidents/` only if there was real
exposure (a credential or private data reached somewhere it shouldn't), real
spend (money or a usage window burned), or a live control failing in
production use. Everything else — however instructive the debugging was — is
a debug note.

The distinction is the point. A log where every annoying bug becomes an
"incident" is a log where severity stops meaning anything, and the next
reader (including a future session of the agent this repo operates) can no
longer tell the credential leak from the console flash. The first two entries
below were originally filed as incidents and demoted when the log was held
to the bar above; the write-ups are unchanged apart from the
reclassification note, because what they record is still true and still
useful — it just isn't an incident. Everything filed since is classified
against that bar at writing time.

- [`2026-07-04-graphify-console-flash-three-surfaces.md`](2026-07-04-graphify-console-flash-three-surfaces.md)
  — a console window flashing at unpredictable moments turned out to be
  three unrelated processes with three different fixes, plus one wrong
  diagnosis along the way. UX annoyance; no exposure, no spend.
- [`2026-07-25-memory-sync-orphaned-index-lock.md`](2026-07-25-memory-sync-orphaned-index-lock.md)
  — a `SessionEnd` hook killed mid-git-sequence wedged cross-machine memory
  sync silently for an hour, twice, in two different windows of the same
  sequence. No data lost; the reusable part is that two plausible fixes
  were both wrong and a ten-minute empirical probe killed both.
- [`2026-08-02-sweep-relitigated-a-settled-ruling.md`](2026-08-02-sweep-relitigated-a-settled-ruling.md)
  — a weekly hygiene sweep re-raised a question that had been ruled closed
  in writing, and the chip it filed framed the settled call as an open
  tradeoff, so a session with no history decided it. No exposure, no spend;
  the cost was the same decision made a third time. Filed here rather than
  as an incident because nothing failed except a process loop.
- [`2026-08-03-rename-dangled-live-hook-symlinks.md`](2026-08-03-rename-dangled-live-hook-symlinks.md)
  — renaming the clone that hosts the guard hooks dangled all three of them
  mid-session, and since a missing `PreToolUse` script is a hard error, every
  `Bash`, `Read` and `Write` was refused from that call onward. The session
  could not repair the damage it had just caused: the fix needs exactly the
  tools the breakage removed. No exposure and no spend — but the guards were
  unenforced for the whole window, and the recovery had to come from outside
  the session.
