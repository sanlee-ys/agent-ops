# Truncation defers, it never destroys (hard rule)

Any tool that cuts output down before handing it to a model or a log has made a
decision on the reader's behalf. The decision is only legitimate if the rest is
still reachable. Truncation that drops bytes on the floor is data loss with a
polite message attached.

This is a agent-ops-local convention — no consumer repo mirrors it, so there is
no shared block to propagate.

Three rules, all of which [pi](https://github.com/earendil-works/pi) (MIT)
implements in a form worth copying:

## 1. Two limits, and count real bytes

Cap **lines** and **bytes** independently, whichever hits first. One limit alone
fails on the other axis: a 2,000-line cap passes a single 40 MB minified line,
and a 50 KB cap on a log of short lines silently costs you the line *count* the
reader was using to orient.

Bytes means encoded bytes. `str.length` is UTF-16 code units, so a CJK log or a
stack trace full of box-drawing characters blows past a "50 KB" budget by 2-3x
without the counter noticing. pi's
`packages/agent/src/harness/utils/truncate.ts` computes UTF-8 length properly
(`Buffer.byteLength` where available, an explicit 1/2/3/4-byte fallback where
not), defaults to 2000 lines / 50 KB, reports *which* limit fired
(`truncatedBy: "lines" | "bytes"`), and never emits a partial line except in the
one documented edge case where a single line exceeds the whole byte budget. It
also handles the boundary the naive version gets wrong: cutting mid-surrogate,
which yields a string that is not valid UTF-8. Pairs are kept whole; orphans are
replaced.

## 2. Cut the end the reader does not need — and that direction is not universal

Truncation direction is a semantic choice about where the information lives:

- **Command output keeps the TAIL.** Exit status, the error, the final result —
  all at the end. A head-truncated build log is the part you already knew.
- **File reads keep the HEAD.** A file is read to be continued, and continuation
  is what `offset`/`limit` are for. pi's `read` tool truncates head and then
  tells the model the exact next offset: `[Showing lines X-Y of Z. Use
  offset=N to continue.]` — a truncation message that is also the resumption
  instruction.

Both live in the same module (`truncateTail`, `truncateHead`), which is the
point: the asymmetry is a property of the *caller*, so it has to be a choice at
the call site rather than a default baked into one function.

## 3. Spill to a file, and say so precisely

On truncation, write the full output somewhere and hand back the path. pi does
this in `packages/agent/src/harness/utils/shell-output.ts`: the moment a running
command crosses either limit, it opens a temp file, seeds it with what has been
captured so far, and keeps appending every subsequent chunk — so the spill is
complete, not a snapshot of the moment the limit tripped. The in-memory tail is
separately trimmed to a bounded window, so a runaway process cannot exhaust
memory while the file keeps the record.

Then the message has to be *specific*. From
`packages/agent/src/harness/tools/bash.ts` (~lines 136-140), which branches on
how the cut happened:

```
[Showing lines 1841-2000 of 44017. Full output: /tmp/bash-xxxx.log]
[Showing lines 1841-2000 of 44017 (50.0KB limit). Full output: /tmp/bash-xxxx.log]
[Showing last 50.0KB of line 44017 (line is 3.2MB). Full output: /tmp/bash-xxxx.log]
```

Each one answers what a reader actually needs: *what did I get*, *what is the
whole*, *why did it stop*, and *where is the rest*. Compare the usual
`... [output truncated]`, which answers none of them and cannot be acted on.

## The check

Before shipping any tool, hook or wrapper that emits model-facing or log-facing
output, answer three questions. If any answer is missing, it is not truncation,
it is loss:

1. What are the two limits, and are the bytes real encoded bytes?
2. Which end is kept, and why is that the end with the information?
3. Where did the rest go, and is that path in the message?

The reusable shape, beyond output: **a control that discards to protect a budget
must leave a pointer to what it discarded.** Otherwise the budget is enforced
and the work is gone, and the only evidence is a sentence saying so.

Related: [`truncated-producers-taint.md`](truncated-producers-taint.md) is the
consumer-side half of this — what to do when it was someone *else's* output that
got cut off.
