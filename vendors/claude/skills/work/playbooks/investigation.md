# Investigation

A read-only question with a cited answer. The deliverable is the answer, not a
change. Do not build, do not edit, do not open a branch.

0. **Direction.** Restate the question in one sentence. Say what a complete answer
   contains: a claim, the evidence, and the file or commit that carries it.
1. **Read the authoritative source first.** The code, the ADR, the commit, the
   vendor doc. Not a memory file, not a summary, not a prior chat. A memory is a
   pointer to a source, and it can be stale (verify-current-state-before-asserting).
2. **Pull before the first claim about a repo.** A stale clone gives a stale answer.
3. **Separate what you verified from what you infer.** Mark each inference as an
   inference. If a fact is observable by running something, run it; do not ask the user
   for a fact the machine can give.
4. **Check the settled non-findings registry** before you report a problem. A match
   drops silently.
5. **Bar: every claim in the reply points at a file, a line, a commit, or a command
   output.** A claim with no pointer is an inference, and the reply says so.

**Reply:** the answer first, in one paragraph. Then the evidence as a list, one
pointer per line. Then open inferences, if any. No recommendation unless the user asked
for one.
