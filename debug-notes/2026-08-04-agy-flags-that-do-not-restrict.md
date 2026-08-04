# Two Antigravity flags that read as containment and are not

**Date:** 2026-08-04
**Classification:** debug note, not an incident. No credential was exposed,
no spend occurred, and no *live* control failed — the guards were never
wired on this harness, so nothing that had been claimed to hold gave way.
Filed against the bar in `CLAUDE.md`.

## What happened

While building telltale's council mode, a probe of the Antigravity CLI
(`agy`) tested whether its `--mode plan` and `--sandbox` flags restrict what
the agent can do. Under both flags the agent was asked to write a file, and
the file landed on disk. The reported `permission_mode` and tool list were
byte-identical to a run without the flags.

The probe artifact was written under the CLI's own scratch directory and
deleted; the directory was confirmed empty afterward.

## What it actually means — the two flags are not the same finding

**`--sandbox` behaved as documented.** Its help text reads: *"Run in a
sandbox with **terminal** restrictions enabled."* The documented scope is
commands, not the filesystem. A file write succeeding under `--sandbox` is
the flag working correctly within a narrower scope than the probe assumed.
The error was reading "sandbox" as a general containment word.

**`--mode plan` is a genuine discrepancy.** It is documented as an execution
mode (`accept-edits, plan`), and a plan mode that permits a write is not
doing what the name and the mode list imply. Measured once. **Not
re-verified**, because re-running it is a state modification rather than an
observation, and the conclusion below does not depend on the second data
point.

## Why it was worth writing down anyway

The conclusion is the same for both flags and does not depend on which one
is a bug: **neither is a mitigation for a permissive permission store.**
Both were reached for as if they were, which is the actual lesson. A flag
named `--sandbox` or `plan` invites the assumption that it bounds the blast
radius, and neither one bounds writes.

A third, sharper finding came out of the same investigation: **in print
mode, settings allow-rules do not apply at all.** The binary's own message
says tools requiring approval are auto-denied in headless mode and points at
`--dangerously-skip-permissions`. So reasoning about `agy -p` from the
contents of `settings.json` is reasoning about the wrong file.

## The general shape

This is the same failure mode as `conventions/agent-success-signals.md` —
ask what a green signal is actually measuring — applied to a safety flag
rather than a test result. A flag's name is a claim about intent; only its
documented scope, and then a measurement, tells you what it bounds. Two of
the three assumptions here were wrong in the same direction: the tooling
looked more restrictive than it was.

Related: `decisions/ADR-012-capability-parity-and-the-guard-obligation.md`,
which records the permission posture this probe surfaced and the guard
obligation that replaces it.
