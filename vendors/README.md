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

- [`claude/`](claude/) — the control plane, primary implementation vendor,
  and final integrator; carries the skills published as patterns.
- [`codex/`](codex/) — the second-opinion vendor: design challenge,
  consequential-diff review, stuck-diagnosis. Wiring and channel documented
  in its README.
- [`cursor/`](cursor/) — the IDE lane: bounded edit-test loops, UI
  verification, parallel work on non-colliding files. Wiring, channel, and
  guard gaps documented in its README
  ([`decisions/ADR-009`](../decisions/ADR-009-cursor-ide-lane-in-fleet.md)).
- [`gemini/`](gemini/) — Google Antigravity (AGY), the measured
  Gemini-family research/overflow/third-opinion lane. Gemini CLI remains the
  enterprise/API-key variant, not the consumer surface. Wiring, channel,
  safety boundary, and capabilities are documented in its README.

The fleet routes on two axes: the **harness** selects tools and working
surface; the **model family** determines whether a second opinion is
independent. The complete routing decision is
[`ADR-010`](../decisions/ADR-010-claude-led-four-vendor-orchestration.md).

## Commit attribution — Co-authored-by trailers

Vendor-attributed commits carry a `Co-authored-by:` trailer so each vendor
shows up on the repo's contributors graph. GitHub resolves the trailer's
*email* — the name is cosmetic — to whatever account has that email
attached, official or not. The canonical trailer lines, verbatim:

```
Co-authored-by: Claude <noreply@anthropic.com>
Co-authored-by: chatgpt-codex-connector[bot] <199175422+chatgpt-codex-connector[bot]@users.noreply.github.com>
Co-authored-by: gemini-code-assist[bot] <176961590+gemini-code-assist[bot]@users.noreply.github.com>
Co-authored-by: Cursor <cursoragent@cursor.com>
```

The Claude line may carry a model-specific name (same email — it resolves
to the official `claude` account). The Gemini line covers Antigravity too:
no Antigravity-specific bot account exists on GitHub, so
`gemini-code-assist[bot]` is the closest official Google identity.

**Rule: only use an email verified to resolve to an official vendor
account** — check with `gh api users/<login>` before adding a new one. This
fails both ways: an email no account owns yields no contributor tile at
all, and an email a third party has claimed puts a stranger on the graph.
Both happened here — `codex@openai.com` resolved to nothing, and
`antigravity@google.com` resolved to an unrelated personal account; both
trailers were rewritten out of `main` on 2026-08-02.

## Guards note

The guards in `hooks/` and `security/` were written against Claude Code's
hook contract, but the policy they enforce (credential
non-exposure, staging hygiene, published-history protection) is fleet
policy. Other harnesses reuse the policy with their own wiring; each vendor
README records how, or that it is not wired yet. A policy enforced for only
one vendor is a gap, not a default — see
[`conventions/allowlists-fail-both-ways.md`](../conventions/allowlists-fail-both-ways.md)
for the general principle.

Current implementation truth: Claude and Codex have the fleet suite wired
locally; Cursor and Antigravity do not.

Until 2026-08-04 the latter two compensated with bounded safety envelopes —
read-only defaults and revertible-work-only rules.
[`ADR-012`](../decisions/ADR-012-capability-parity-and-the-guard-obligation.md)
retires that compensation: **capability parity is the fleet default, so guard
wiring is the only remaining control.** An unwired vendor is now an open
obligation, not a vendor kept on a short leash.

The mechanism is available where it matters most: Antigravity ships a
`PreToolUse` hook contract with a hard `deny`, confirmed in the shipped
binary. It was never wired, which means ADR-010's "until tool-time guard
parity exists" described a build task, not a blocker.

Rationale for this layout: [`decisions/ADR-008`](../decisions/ADR-008-agent-ops-rename-and-vendor-layer.md).
