---
name: dcb
description: Scaffold a task into the user's DCB framework (Direction, Contracts, Bar) before starting ambiguous, consequential, or hard-to-reverse work with Claude, and for consequential work also produce a short plan document that is reviewed before any implementation starts. Invoke via /dcb <task description>, or /dcb alone to be asked what task is being scoped. Use this when the user explicitly types /dcb, or says things like "let's DCB this", "set direction/contracts/bar for X", or asks to scope out a risky/ambiguous piece of work before diving in. Do NOT use for quick mechanical edits, renames, or bounded tasks the user has already fully specified — DCB is overhead there, not help.
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

6. **Decide whether the work is consequential.** If it is, continue to the Questions step
   and the plan document below, and do not start implementing. If it is not, the scaffold
   above is the whole output — stop here and get to work.

## The plan document (consequential work only)

Added 2026-08-11. Design source: **RPI / QRSPI** (Dex Horthy) — Questions, Research,
Sketch/Plan, Implement. The DCB scaffold above is unchanged: Direction, Contracts and Bar
keep their names, their order, and their meaning. The plan document is an **addition after
them**, not a rename of any of them.

DCB says what the work is bound to. It does not say what the work *is*. For a bounded task
that gap does not matter, because the task fits in the prompt. For consequential work it is
the whole risk: the session and the user agree on the contract and then discover, an hour
in, that they never agreed on the change.

**Consequential** means at least one of: it is hard to reverse; it changes a contract other
work depends on; it spans several files or repos; or it encodes a design decision with a
real fork in it. Bounded, already-decided work is not consequential however important it is.

### Step 1 — Questions, before the plan

Ask the open questions **first**, and wait for the answers. This step is ahead of the plan
on purpose. A plan written over an unasked question buries the question: it becomes an
assumption inside a document that now reads as settled, and the review that follows reviews
the assumption without ever seeing it as a choice.

Ask only what changes the plan. Three or four real questions beat a questionnaire. If a
question has an obvious default, state the default in the question so the user can agree in
one word.

### Step 2 — The plan document

Write it short. Four headings, and it should fit on a screen:

```
## Current state
What is true in the repo now. Verified, not remembered - name the files read.

## Desired end state
What is true when this is done. Observable, so the Bar can check it.

## Constraints
What the work must not do or must not break. Blast radius: the files this
expects to touch.

## Open questions
What is still undecided, and what happens by default if it stays undecided.
```

Keep "Open questions" even after Step 1. Step 1 clears the questions that block the plan;
this heading holds the ones the plan can proceed without, and it is where an honest plan
admits what it guessed.

### Step 3 — Stop for review

**Present the plan and stop. Do not start implementing.** This is a hard stop, not a
checkpoint the session may pass on its own judgement. The plan is the artifact the user
reviews, and a plan reviewed after the code is written is a description, not a plan.

The user may approve it, edit it, or reject the framing. All three are cheap here and
expensive later, which is the entire reason the step exists.

### The plan doubles as the frozen brief

A consequential change is also the class that goes to the **Codex challenge lane**. That
lane needs a *frozen brief*: inspectable state, an explicit file boundary, and an exact
revision — not a prose retelling of a conversation Codex cannot see.

The plan document is already that brief. "Current state" names the revision and the files
read, "Constraints" carries the file boundary, and "Open questions" tells the challenger
where to push hardest. So write it to be handed over as-is, and hand over the reviewed
version rather than re-summarising it. A retelling is a second artifact that can drift from
the first, and the challenger has no way to detect the drift.
