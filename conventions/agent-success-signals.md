# Agent success signals — interrogate the green (hard rule)

A deterministic tool fails loudly when it does nothing. An **agentic** tool
succeeds quietly: the same green appears whether the work happened, was denied,
crashed, or was never attempted. A green from an agent tool is therefore a
claim, not evidence, until you know what produced it.

This is a claude-ops-local convention — no consumer repo mirrors it, so there is
no shared block to propagate.

Started 2026-07-24 as a single-incident note: an agentic review lane in CI went
green in 36 seconds having posted nothing, because every attempt to comment was
a tool denial and a denial is not a job failure. That instance is standardised
as SYS-021 in the architecture repo, scoped to agentic CI. It became a
*convention* on 2026-07-26, when the same shape turned up three more times in
one evening across two unrelated third-party tools — which makes it a property
of agent tools generally, not of one GitHub Action.

## Ask these four before trusting a green

1. **What exactly is this success signal measuring?** Name the thing that
   flipped it. "The process exited 0" and "the work landed" are different
   claims, and usually only the first one is actually checked.
2. **Can it distinguish "passed" from "never ran"?** A signal that cannot tell
   silence from success will score every crash, timeout, denial and auth failure
   as a pass. If a skipped run and a clean run look identical, the signal is
   measuring nothing.
3. **Is the gate in the repo, or in the prompt?** A check the tool itself runs
   is a gate. A check that runs only if the objective prompt happens to tell the
   agent to run it is a suggestion — a repo can carry a full test suite that
   gates nothing.
4. **Are the self-reported numbers echoing tool output, or narrating?** Numbers
   an agent read back off a tool are usually right. Numbers it counted from its
   own memory of what it just did are usually *close* — and close is wrong.

## The evidence

- **The gate lived in the prompt.** [`gnhf`](https://github.com/kunchenguid/gnhf),
  a harness for overnight agent runs, decides commit-vs-rollback on the agent's
  own JSON self-report — not on any check gnhf runs. The target repo's test
  suite is not in that path unless the objective prompt explicitly instructs the
  agent to run it.
- **Measured and narrated, in one report.** In a gnhf run against the public
  `notes-api` repo, the agent was exactly right about everything it *measured* —
  four coverage percentages, verified to the point — and wrong about what it
  *counted*: it claimed 19 new tests where `git diff` showed 17. Same report,
  same run. The only variable was whether a tool produced the number.
- **A catch block that erased the distinction.**
  [`superpowers-bench`](https://github.com/kunchenguid/superpowers-bench) runs
  agents under a 5-minute `AGENT_TIMEOUT_MS`, and the catch block in its
  `execAgent` returns `execErr.stdout ?? ""` — so timeout, crash, non-zero exit
  and auth failure all return partial stdout with no downstream signal. Question
  2 falls straight out of it twice: the three negative-control tasks
  (`expected_skills: []`) grade a *crashed* run as a **pass**, and any
  multi-skill task truncated at the timeout scores as a skill-*selection*
  failure rather than as a run that never finished.

## The check

Before adopting an agent tool — and before quoting any number one produced —
verify against the artifact, not the signal: the file written, the comment
posted, the commit landed, the count in `git diff`. If you cannot describe the
failing case this signal would catch, assume it catches nothing and report the
result as unverified.
