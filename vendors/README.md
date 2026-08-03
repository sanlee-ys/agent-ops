# vendors/ — the per-vendor adapter layer

The root of this repo is vendor-neutral canon: incidents, decisions,
conventions, the security posture and its guards, the operating model. None
of that cares which agent harness is running. What *does* care lives here —
one directory per vendor, holding only the material that exists in that
harness's own format or dialect.

## What belongs in a vendor directory

- **Skills / commands** in that harness's native format.
- **Instruction-file wiring** — where that vendor reads its standing
  instructions on a machine, and how those stay in sync with the canon here
  (hand-mirroring drifts; treat it like the shared-block problem).
- **Channel notes** — how the other agents in the fleet reach this one
  without a human relaying: CLI invocation, flags, auth expectations, and
  the file protocol for handing work across.
- **Quirks** that are true of this harness only.

## What does not belong

- Anything true of every vendor — that is root material (a convention, a
  guard, a decision).
- Anything the redline guard would reject anywhere else in the repo. The
  publication boundary does not relax inside a vendor directory.

## Current adapters

- [`claude/`](claude/) — the primary implementation vendor; carries the
  skills published as patterns.
- [`codex/`](codex/) — the second-opinion vendor: design challenge,
  consequential-diff review, stuck-diagnosis. Wiring and channel documented
  in its README.
- [`cursor/`](cursor/) — the IDE lane: bounded edit-test loops, UI
  verification, parallel work on non-colliding files. Wiring, channel, and
  guard gaps documented in its README
  ([`decisions/ADR-009`](../decisions/ADR-009-cursor-ide-lane-in-fleet.md)).
- [`gemini/`](gemini/) — Google Antigravity (AGY) adapter layer for Gemini
  3.6 (Flash/Pro) CLI & IDE harness. Wiring and capabilities documented in
  its README.

## Guards note

The `PreToolUse` guards in `hooks/` and `security/` are written against
Claude Code's hook contract, but the policy they enforce (credential
non-exposure, staging hygiene, published-history protection) is fleet
policy. Other harnesses reuse the policy with their own wiring; each vendor
README records how, or that it is not wired yet. A policy enforced for only
one vendor is a gap, not a default — see
[`conventions/allowlists-fail-both-ways.md`](../conventions/allowlists-fail-both-ways.md)
for the general principle.

Rationale for this layout: [`decisions/ADR-008`](../decisions/ADR-008-agent-ops-rename-and-vendor-layer.md).
