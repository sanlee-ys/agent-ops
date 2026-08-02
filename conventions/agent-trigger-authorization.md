# Authorizing a CI-triggered agent: four independent checks (hard rule)

Any workflow where **external input can reach an agent that has capabilities** —
a repo checkout, a model budget, write scope on issues, a runner — must
authorize the *sender*, through checks that are independent of each other and
independent of the text that triggered them. Four of them, all of which must
pass:

1. **Event and trigger shape.** The event type is one this workflow accepts, and
   for a label event, the label is the specific trigger label.
2. **An explicit trigger phrase.** Matched by regex against the comment body.
   Mentioning the agent in passing is not a trigger.
3. **Org/team membership, verified live through a separately-scoped token** —
   not the workflow's default `GITHUB_TOKEN`.
4. **Repo permission level.** The sender holds `admin` or `write`. Read access
   to a public repo is not authority over it.

And the rule that makes those four mean anything: **untrusted text never counts
as authorization, and unknown or conflicting control tags are rejected, not
defaulted.**

This is a agent-ops-local convention — no consumer repo mirrors it, so there is
no shared block to propagate.

The reference implementation is
`.github/workflows/issue-analysis.yml` in
[pi](https://github.com/earendil-works/pi) (MIT), where the entire gate lives in
a dedicated `authorize` job whose only output is a boolean the real job is
conditioned on.

## Why four, and why independent

Each check answers a question the others cannot.

**The trigger phrase is not authorization.** It is in the issue body or a
comment, which means anyone with a GitHub account wrote it. It establishes
*intent* — that someone meant to invoke the agent rather than mentioning it —
and nothing else. Treating a phrase in user-supplied text as permission is the
prompt-injection surface in its purest form: the payload and the credential are
the same string.

**Membership is not permission.** An org member without write access on this
repo is not authorized to spend this repo's runner on this repo's checkout.

**Permission is not membership.** An outside collaborator granted write on one
repo has not joined the org.

**The token used to check membership must not be the one the workflow already
holds.** pi passes a separate `secrets.*_ORG_READ_TOKEN` and calls the org-team
membership endpoint with it directly. The default `GITHUB_TOKEN` is repo-scoped
and cannot answer an org question — so a gate written against it would either
silently degrade to a weaker check or quietly fail open. And the workflow
*refuses to run at all* when that token is absent:

> `EARENDIL_ORG_READ_TOKEN is not configured; refusing to run issue analysis.`

That line is the convention's spine. A missing credential makes the check
*unrunnable*, and an unrunnable check is a failure, never a pass. This is the
same rule as [`agent-success-signals.md`](agent-success-signals.md) — a green
that cannot distinguish *passed* from *never ran* is not a signal — applied to
authorization, where the safe-looking direction is the expensive one.

Every failure path also **removes the trigger label** before failing, so the
rejected state does not sit there looking armed, and re-labelling is a fresh
deliberate act rather than a retry of something already half-authorized.

## Unknown input is rejected, not defaulted

pi's comment trigger accepts optional `#run-on-<platform>` tags that steer which
runner executes the agent. The handling is the transferable part:

- An unrecognized tag → `core.setFailed("Unknown issue analysis runner tag(s): …")`.
- Two conflicting tags → `core.setFailed("Conflicting issue analysis runner tags: …")`.

Neither falls back to the default platform. The tempting version — "unknown tag,
just use linux" — turns a typo into a silent, wrong execution, and turns a
conflict into a coin flip. **When untrusted text carries a control parameter, the
parser's unknown-input branch is part of the security boundary.**

Note also what is done with the rest of the comment: everything that is not the
trigger phrase or a control tag is passed to the agent as
`extra_instructions` — that is, as *content*, downstream of a gate that has
already decided the sender may direct this agent. That is the correct shape.
Untrusted text can be input to an authorized run; it can never be the thing that
authorizes the run.

## Structure: authorize as its own job

The gate is a separate job with `permissions: contents: read, issues: write`,
whose outputs the capable job is gated on:

```yaml
analyze:
  needs: authorize
  if: needs.authorize.outputs.should_run == 'true'
  environment: pi-analyze
```

Three things fall out of that split, all worth copying:

- The authorizing job never checks out untrusted code, so nothing it evaluates
  can influence its own verdict.
- The capable job runs under a named **GitHub environment**, which is where
  approvals and scoped secrets attach — a second, platform-level gate that does
  not depend on the script being correct.
- `should_run` is initialized to `'false'` and every early return leaves it
  there. The default is refusal; only the bottom of the script sets it true.

## Where this applies here

The local instance is the on-demand `@claude` review CI on the portfolio repo:
a comment written by a human causes an agent with a checkout and a model budget
to run. Same shape, same exposure. **This document is the canonical rule; it is
deliberately written independent of any one workflow's current state**, and a
separate audit of what the live workflows actually implement is being run on its
own. Where the two disagree, the workflows are what needs changing.

The generalization beyond CI: this is the standard for *any* path by which input
someone else wrote reaches an agent that can act. A webhook, a watched inbox, a
scheduled job that reads a shared file. The four checks specialize to whatever
identity system is available, but the two invariants do not move — **the
triggering text is never the authorization, and a check that could not run is
not a check that passed.**

See also [`allowlists-fail-both-ways.md`](allowlists-fail-both-ways.md), from
the same read: this gate's `admin`/`write` set and its runner-alias table are
allowlists, and the same maintenance question applies to them.
