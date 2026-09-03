# Bug fix

A reported defect. Every shipped line traces to runtime evidence. A change that
"might help" is a hypothesis, not a fix, and it does not ship. When evidence refutes
a hypothesis, revert what that hypothesis motivated. The smallest change the
evidence justifies ships, and nothing more.

0. **Direction.** Restate the defect in one sentence: the surface, the trigger, the
   wrong result, the expected result. "Done" means the original reproduction passes
   on the same surface.
1. **Reproduce it yourself, on the same surface the report names.** A CLI bug runs
   in the terminal. A page bug runs in the browser pane. Do not hand the repro to
   the user. If it will not reproduce, force it: tighten the conditions, synthesize the
   trigger, or add instrumentation until it fires. A bug you cannot reproduce, you
   cannot prove fixed.
2. **Find the mechanism with evidence, not by reading.** List the candidate causes.
   Take the split that removes the most candidates, get runtime evidence, and
   eliminate. Read logs and state as the code runs. Confirm the surviving mechanism
   with evidence before you design a fix (diagnose-mechanism-before-patching). Two
   failed hypothesis-driven attempts, or visible looping, is the escalation trigger
   for a Codex diagnosis (fleet-division-of-labor).
3. **Write the failing test first, when a cheap local test path exists.** The test
   fails for the mechanism found in step 2, not for the symptom. Skip this step
   with `skip: <reason>` when the test would be integration-heavy or unclear.
4. **Make the smallest fix the evidence justifies.** No belt-and-braces. No
   adjacent cleanup; that goes to DEFERRED (deferred-scope-routing).
5. **Bar: the step-1 reproduction now passes on the same surface, and the step-3
   test passes.** "Inconclusive" or a different surface is not a pass; say so. A
   unit test shows branch behavior, not the absence of the bug.
6. **Stage the commits so the failing test lands before the fix in history.** The
   diff tells the story. Then run `playbooks/feature.md` from its step 4 (gates,
   PR, land).

**Reply:** what was broken, the root cause, the fix, and how it was verified. Paste
the failing-then-passing reproduction output verbatim.
