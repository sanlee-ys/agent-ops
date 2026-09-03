# Pickup

Resume work that another session, another machine, or a prior day left behind. The
transcript that produced it is gone. The filed record is the record.

0. **Direction.** Restate, in one sentence, what the resumed work is and what "done"
   looked like when it was filed. If the handoff and the live repo disagree, the
   live repo wins, and the reply says where they differed.
1. **Read the filed record.** The handoff brief, the `PARITY.md` entry, the chip
   prompt, or the PR description. Note its origin line: the date, the repo, and the
   revision the finding rested on.
2. **Session pre-flight on every repo the record names** (session-preflight): sync
   `main`, check CI, scan open PRs and `PARITY.md`. Report a red `main` at the top.
3. **Re-verify the finding against live state.** The record can be stale. Diff what
   it claims against what the repo shows now. If the work already landed, say so
   and stop.
4. **Route to the matching playbook** and continue from there. A pickup is a
   starting point, not a task type of its own.
5. **Bar: the reply names the exact revision you resumed from and what changed
   since the record was filed.**
6. **On pause, invoke `/handoff`** so the next session gets a live-state brief. On
   a cross-machine requirement, file a dated `PARITY.md` entry instead
   (deferred-scope-routing).

**Reply:** what was resumed, from which record and revision, what had changed since
it was filed, and which playbook the work continued under.
