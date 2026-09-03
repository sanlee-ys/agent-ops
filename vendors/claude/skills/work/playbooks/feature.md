# Feature

New behavior that ends in a merged PR. This playbook is the `/ship` chain with
Direction in front and `land` behind. It does not restate a step another skill owns.

0. **Direction.** Restate the change in one sentence and say what "done" means for
   the user of the feature, not for the code. If the sentence needs an "and" that
   joins unrelated work, it is two concerns; scope one now and defer the other
   (parallel-sessions).
1. **Scope: invoke `/scope`.** It emits the SCOPE / FILES / DEFERRED block. That
   block is the spec for every later step.
2. **Branch.** Session pre-flight first (session-preflight): sync `main`, check CI,
   scan open PRs and `PARITY.md`. Then cut the branch from fresh `main`.
3. **Implement the smallest diff that meets the SCOPE sentence.** Regenerate any
   generated output whose source you touched, in the same change. Compare the real
   diff against the FILES list and explain any difference.
4. **Bar: invoke `/gates`.** Every declared gate runs and reports PASS, FAIL, or
   UNRUN with real output. UNRUN is not green. Zero gates discovered is a FAIL. A
   red gate stops the chain; fix it inside this step or stop and report.
5. **Verify the feature on its real surface**, not only through the gates. Run the
   command, load the page, or call the endpoint, and read the result. Say what you
   ran and what you saw. Where no surface exists, say that the gates are the whole
   bar.
6. **Open the PR.** The body carries the SCOPE sentence, the GATES summary, and the
   DEFERRED list. Commit and PR prose in STE (working-style).
7. **Run `playbooks/land.md`.** Green and revertible means merged and the branch
   deleted (merge-authorization).

**Reply:** what changed for the user, the PR link as a full URL, the gates result,
what was verified on the surface, and the DEFERRED list.
