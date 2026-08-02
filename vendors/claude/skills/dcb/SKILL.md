---
name: dcb
description: Scaffold a task into the user's DCB framework (Direction, Contracts, Bar) before starting ambiguous, consequential, or hard-to-reverse work with Claude. Invoke via /dcb <task description>, or /dcb alone to be asked what task is being scoped. Use this when the user explicitly types /dcb, or says things like "let's DCB this", "set direction/contracts/bar for X", or asks to scope out a risky/ambiguous piece of work before diving in. Do NOT use for quick mechanical edits, renames, or bounded tasks the user has already fully specified — DCB is overhead there, not help.
---

# DCB scaffolding

DCB is the user's standing operating model for directing AI tools, drawn from his own
words: "I set the direction, the contracts, and the bar; an AI did most of the typing;
and I verified the output against the real repos before it shipped." The point of this
skill is to make those three things explicit *before* work starts, not to narrate them
after the fact.

Use it only where it earns its keep: ambiguous scope, real tradeoffs, anything
consequential or hard to reverse. If the task in front of you is a bounded, already-decided
edit, say so and suggest skipping the ceremony — scaffolding a one-line fix into D/C/B
wastes the user's time and defeats the purpose.

## The three pieces

**Direction** — his, not delegable. What's actually in scope for this task, what "done"
looks like, and which seat/framing he's operating from if that matters (e.g. operator vs.
product-owner on a given workstream). Don't guess this on his behalf; if the task
description leaves it open, ask.

**Contracts** — the rules he binds the work to, stated up front. Two common shapes:
what may be asserted as fact vs. must be flagged as unverified (this matters most for
domain- or employer-specific claims — policy, internal process, anything Claude can't
independently confirm), and any fixed output format for recurring work. Propose sensible
defaults based on the task, but let him override.

**Bar** — the verification standard before this counts as shipped or resolved. Not "the
model sounded confident" but checked against the real source: the actual doc, the actual
repo state, the actual person's word. Propose a concrete bar specific to this task rather
than a generic "tests pass."

## How to run it

1. **Get the task.** If this skill was invoked with a task description attached, use that.
   If not, ask what's being scoped — don't invent a task.

2. **Draft Direction first, as a question, not an assertion.** Read the task and identify
   what's genuinely ambiguous about scope or "done." Ask the user directly rather than
   assuming — this is the one piece that's structurally his to decide, so guessing at it
   defeats the point.

3. **Propose Contracts.** Based on the task, suggest what should be flagged as unverified
   vs. assertable, and any output format worth locking in. Keep it short — one or two
   concrete rules beat a long list of hedges. Let the user edit or add to it.

4. **State the Bar.** Propose a specific, checkable verification standard for this task
   (e.g. "checked against the actual PR diff," "confirmed against the source document text,"
   "run and the output inspected, not just assumed to pass"). Ask if that's the right bar or
   if he wants something stricter/looser.

5. **Output the final scaffold** as a compact block:

   ```
   Direction: <what's in scope, what done means>
   Contracts: <what to assert vs. flag, any format rules>
   Bar: <verification standard before this ships>
   ```

   This block is meant to be dropped at the top of the real working prompt (or just kept
   as the operating contract for the rest of the session) — not filed away as a document.
   Don't create a separate file for it unless the user asks.
