# A truncated producer taints everything it produced (hard rule)

When a producer was cut off by a limit — an LLM hitting its output token cap, a
buffer filling, a process killed at a timeout — every structured artifact from
that run is suspect. Including the parts that parse. Including the parts that
validate. The consumer's only safe moves are to fail or to re-request; executing
is not on the list.

This is a claude-ops-local convention — no consumer repo mirrors it, so there is
no shared block to propagate.

## The mechanism

The intuition that makes this a trap is "if it parsed, it survived". That holds
for a strict parser reading a complete stream. It does not hold anywhere a
**salvage parser** sits between the wire and the structure, and streamed output
is exactly that place: arguments arrive as fragments, something has to render a
usable object from a partial buffer at every step, and that something is
best-effort by construction. Feed it a stream that stopped mid-object and it
returns a well-formed object — just a shorter one. Closed brackets it supplied
itself. Fields it never saw are simply absent, which is indistinguishable from
fields that were legitimately optional.

So the corruption is not a broken payload. It is a *complete-looking* payload
with the tail missing, and no downstream schema check can recover the
difference, because validity was never the property that was lost.

[pi](https://github.com/earendil-works/pi) (MIT) handles this at the loop level
in `packages/agent/src/agent-loop.ts`. When an assistant message comes back with
`stopReason === "length"`, the loop does not inspect the tool calls, score them,
or salvage the ones that look fine (~lines 207-216):

```
const executedToolBatch =
    message.stopReason === "length"
        ? await failToolCallsFromTruncatedMessage(toolCalls, emit)
        : await executeToolCalls(...);
```

`failToolCallsFromTruncatedMessage` (~lines 381-406) then fails **every** call in
the message with an error saying why and what to do: the response hit the output
token limit, arguments may be truncated, re-issue with complete arguments. Its
docstring names the reason outright — streamed tool-call arguments are finalized
by a best-effort JSON salvage parser, so a truncated message can yield calls
"whose arguments parse and validate but are silently incomplete."

Two design choices in there are the transferable part:

- **The taint is per-message, not per-item.** The first tool call in a truncated
  message is almost certainly intact. It fails anyway, because "which calls
  finished" is not knowable from the parsed result, and a rule that guesses is a
  rule that guesses wrong on the interesting day. Blast radius is the producer's
  output, whole.
- **The error is addressed to the thing that can fix it.** It goes back as a
  tool result the model reads, phrased as an instruction to re-issue — not a
  crash, not a silent drop. A taint rule that only refuses leaves the caller
  stuck; this one refuses and hands back the move.

Worth noting what is *not* the fix: raising the token limit, retrying blind, or
adding schema validation. The first two change the odds, the third checks a
property that was never violated.

## Where it applies here

Anywhere a limit and a structured artifact meet, which is more places than it
first looks:

- A subagent's report when its run hit a cap — the summary reads finished
  because summaries always read finished.
- A command whose output was truncated (see
  [`truncation-defers.md`](truncation-defers.md)) and then parsed for a count, a
  list, or a diff. The count off a truncated log is a real number and a wrong
  one.
- Any generated file — an index, a manifest, a report — written by a run that
  was killed. It exists, it is syntactically fine, and it is short.

The precondition in all three is the same: **you have to know the producer was
truncated.** That is the debt this convention leaves with the previous one — a
producer that cuts output without saying so makes this rule unenforceable, which
is the real reason the truncation message matters.

## The kinship

This is [`agent-success-signals.md`](agent-success-signals.md) in a different
costume. That convention's rule is to verify against the artifact rather than
the signal: a green means "the process exited 0", not "the work landed". Here
the artifact *is* present, and it still is not evidence, because the property
that failed — completeness — is not one the artifact carries on its face.

So the check generalizes rather than repeats. It is not enough to look at the
artifact instead of the status; you also have to know whether the run that
produced it terminated **because it finished** or **because it hit a wall**.
Same distinction the false-green material keeps landing on: a state space where
two very different outcomes are being represented by one indistinguishable
value.

## The check

When consuming any structured output, ask whether the producer's termination
reason is available to you. If it is, branch on it before you branch on the
content, and treat a limit-hit as fatal for the whole payload. If it is not
available, that is the bug to fix first — everything downstream is unverifiable
until it is.

See also [`allowlists-fail-both-ways.md`](allowlists-fail-both-ways.md), from the
same read.
