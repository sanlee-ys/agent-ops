# An agent in CI is a proposer, not a committer (hard rule)

Running a coding agent as a CI or pipeline step is not "an interactive session
that happens to be headless." A session has an operator watching, approving,
and able to interrupt; a CI job has none of that, runs on a trigger the agent
never sees, and inherits whatever credentials the job carries. The controls
that make an interactive agent safe do not travel automatically — each one has
to be re-attached, explicitly, or the job runs without it.

This is an agent-ops-local convention — no consumer repo mirrors it, so there
is no shared block to propagate. The fleet already has every piece this doc
names — the redline guards ([`hooks/`](../hooks/)), the generated-drift gate
([`scripts/check-generated-drift.py`](../scripts/check-generated-drift.py)),
the SYS-017 eval tiers in the architecture repo. This is the **assembly
rule**: which pieces an agentic job must carry, and in what posture.

## The four rules

1. **The agent runs sandboxed, and the sandbox is written down.** No ambient
   credentials beyond the job's own scoped token — no long-lived PATs in env,
   no deploy keys the task does not need, nothing inherited from a runner that
   also does releases. Network policy is explicit: which hosts the job may
   reach is a line in the workflow, not a property discovered later. An agent
   that can read a secret can be prompt-injected into exfiltrating it, and in
   CI the injection surface is everything the job checks out or fetches.

2. **Output is a proposal, never a push to a protected branch.** The agent's
   deliverable is a branch, a PR, or a report — an artifact a human or a
   deterministic gate reviews before it becomes `main`. A job token that *can*
   push to a protected branch is the sandbox rule already violated; the
   proposal shape is what keeps a bad run cheap. This is the delegation-policy
   stance restated for CI: autonomy is granted per task class, and the
   verifier — not the agent — holds the merge.

3. **Every agentic job is followed by a deterministic verifier.** Tests,
   linters, the drift check — something whose green means what it says.
   [`agent-success-signals.md`](agent-success-signals.md) is the reason:
   agent green is not build green. An agentic step exits 0 whether the work
   landed, was denied, crashed, or was never attempted, so a pipeline that
   ends on the agent's own exit code ends on a claim. The verifier must run
   *after* the agent, *in the pipeline* — a check that exists in the repo but
   is only run if the agent's prompt tells it to is a suggestion, not a gate.

4. **The guards travel with the job.** The redline guards are wired per
   machine; a fresh CI container has none of them unless the job installs
   them before the agent's first tool call. A headless run without
   `credential-guard.py` and its siblings is running **unguarded** — a
   security-posture change relative to every provisioned machine in the
   fleet, made implicitly by whoever wrote the workflow, approved by nobody.
   If a job genuinely must run without a guard, that is a decision to record,
   not a default to inherit.

## The check

Before merging any workflow that puts an agent in the pipeline, point at four
lines in the YAML: the token scope and network policy (rule 1), the step that
opens a PR rather than pushing (rule 2), the deterministic verifier step after
the agent (rule 3), and the guard-install step before it (rule 4). A rule you
cannot point at is a rule the job does not follow — and the job will still go
green, which is the whole problem.
