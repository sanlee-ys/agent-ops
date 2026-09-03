# Refactor

A change that keeps behavior and removes code, layers, duplication, or stale
references. Subtract before you add. The bar is that nothing observable changed.

0. **Direction.** Restate the refactor in one sentence: what goes, what replaces
   it, and what must stay identical. If the change also adds behavior, that is a
   feature; split it.
1. **Record the baseline.** Run the repo's gates and any surface check before you
   touch a file. Save the output. This is the "before" half of the bar.
2. **Delete first.** Remove dead weight before you restructure what remains. A
   one-caller wrapper, an unused branch, a compatibility shim with no caller.
3. **Make the smallest structural change** that reaches the target shape. Do not
   preserve an intermediate compatibility state that no one will ship. Migrate every
   caller and delete the legacy path in the same change.
4. **For a cross-repo removal, invoke `/descope-sweep`** with the old term and the
   new one. It owns the long-tail sweep (ADRs, `.env.example`, KB stubs, generated
   doc sources).
5. **Bar: the step-1 gates and surface checks produce the same result after the
   change.** Diff the two outputs. Any difference is either explained in the reply
   or it is a regression, and a regression stops the chain.
6. **Run `playbooks/feature.md` from its step 6** (PR, land).

**Reply:** what was removed and what replaced it, line counts before and after on
their own line, the before-and-after gate comparison, and the PR link.
