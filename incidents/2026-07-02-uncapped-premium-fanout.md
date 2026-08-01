# Postmortem: Uncapped premium-model fan-out burned a 5-hour window

**Date:** 2026-07-02 | **Duration:** ~45 min | **Severity:** Cost (one full 5-hour usage window burned with no warning; nothing exposed, nothing broken — expensive and avoidable, not an outage)
**Status:** Resolved (guard written; deployment gap found + closed on Windows)

The full cost model, cost tables, and pre-flight protocol live in a private
working copy; this file is the incident record, not a duplicate of that
analysis.

## Summary

A scoped, single-topic research question triggered a full deep-research multi-agent
fan-out (30-50+ agents, multi-round adversarial verify) on a premium model
tier, launched uncapped with no cost warning. It ran ~45 minutes and consumed
an entire 5-hour usage window. The question needed a handful of inline
searches, not a fan-out.

## Impact

- Full 5-hour usage window exhausted (~4.5M weighted tokens, ~95% of window) on one run.
- No other work possible on this account until the window reset.

## Root cause (5 whys)

1. Why did one run eat the whole window? -> It fanned out 30-50+ agents on the most expensive model tier with no cap.
2. Why no cap? -> Nothing forced one — the tool allowed an open-ended fan-out call.
3. Why did the model default to premium for a fan-out? -> No standing rule to default fan-out fleets to a mid-tier model and reserve premium for inline/hard-verify work.
4. Why wasn't the scale of the ask questioned before firing? -> No pre-flight step requiring tier + estimate + explicit go-ahead before anything above inline work.
5. Root cause: no hard backstop existed — spend was authorized blind, by default, with no gate.

## Second-order finding (discovered 2026-07-02, this session)

The fix — a `PreToolUse` hook that blocks any uncapped fan-out call and any
uncapped premium-model call — was written and committed to a private config
repo the same day. But it's only *installed* on a machine that has run the
provisioning setup script through the step that deploys hooks. **This Windows
machine never ran that step** — confirmed the same day: no `PreToolUse` hook
in `~/.claude/settings.json`, no guard script on disk. The guard existing in
principle in the config repo did nothing for sessions run from an
un-provisioned machine. This is a config-drift / incomplete-rollout problem,
not a flaw in the guard's logic. (See also
debug-notes/2026-07-04-graphify-console-flash-three-surfaces.md, which turned
up the same class of "wrote the fix" vs. "the fix is deployed everywhere"
gap.)

## What went well

- The incident was measured mid-flight and killed rather than run to full completion.
- Produced a real, reusable artifact same-day: the cost model, the pre-flight protocol, and the hook itself — not just a one-off apology.
- The fix was written to be portable (committed to the private config repo, meant to sync across machines) rather than patched into one session.

## What went poorly

- "Wrote the fix" and "the fix is protecting you" turned out to be two different claims — the gap wasn't caught until a second, unrelated incident on this machine prompted a memory-vs-reality check.

## Action items

| Action | Priority | Status |
|---|---|---|
| Write the fan-out guard `PreToolUse` hook + pre-flight protocol doc | P0 | Done (2026-07-02) |
| Deploy guard to this Windows machine (provisioning script's hook-deployment step, or manual copy of the settings + hook script) | P0 | Done |
| Standing rule (corrected 2026-07-03): a mid-tier model and a higher second tier are both fine defaults for fan-outs — restrict the top-of-line "nuclear option" model to genuinely-stuck, complicated problems, not routine fan-out fleets. The guard's premium-model gate had treated the second tier and the nuclear-option tier identically in one repo's local copy (a second copy had already been narrowed). Fixed 2026-07-03: the gate now matches only the nuclear-option tier. | P1 | Done (2026-07-03) |
| After any future fan-out, log the weighted actual cost into the cost table in the private cost-control doc | P2 | Ongoing |
| When provisioning a new machine, verify hook deployment immediately (don't assume the config repo existing = hook installed) | P1 | Adopted going forward |

## Lessons learned

A safety mechanism that lives in a repo but isn't verified as *installed* on
every machine you actually work from isn't a safety mechanism yet — it's a
draft. "I wrote the guard" and "the guard is active here" need to be checked
as two separate facts, especially across a multi-machine setup.
