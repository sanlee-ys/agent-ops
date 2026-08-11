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
  the launch-shell caveat documented in its README
  ([`decisions/ADR-009`](../decisions/ADR-009-cursor-ide-lane-in-fleet.md)).
- [`gemini/`](gemini/) — Google Antigravity (AGY), the measured
  Gemini-family research/overflow/third-opinion lane. Gemini CLI remains the
  enterprise/API-key variant, not the consumer surface. Wiring, channel,
  safety boundary, and capabilities are documented in its README.
- [`grok/`](grok/) — Grok Build (xAI). **Guard wiring only, not a routing
  lane.** It is installed and capable on the Windows workstation, which under
  ADR-012 is enough to owe it a guard; admitting it to the fleet would be a
  separate decision. Its README carries the measured hook semantics and the
  runtime checks still outstanding.
- [`pi/`](pi/) — Pi (earendil-works), the open-source overflow harness.
  Admitted 2026-08-11 with a verified `tool_call` deny guard. **Target model
  family is Kimi (K3 when access lands)** per
  [`ADR-014`](../decisions/ADR-014-pi-harness-kimi-model-target.md). Interim
  backend is xAI `grok-4.5` for capacity only — that does **not** make this
  a Grok routing lane and does **not** count as independence from Grok.

The fleet routes on two axes: the **harness** selects tools and working
surface; the **model family** determines whether a second opinion is
independent. The base routing decision is
[`ADR-010`](../decisions/ADR-010-claude-led-four-vendor-orchestration.md);
Pi's harness/model split is
[`ADR-014`](../decisions/ADR-014-pi-harness-kimi-model-target.md).

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

Current implementation truth: Claude, Codex, Antigravity, Cursor, Grok
Build, and Pi all have the fleet suite wired (Pi via its `tool_call`
extension; the others via their native hook adapters). The open rows are no longer *whether* a
harness is wired but *how far each wiring has been observed working* — Cursor's
was verified live on 2026-08-04, Grok's on 2026-08-09, both on the Windows
workstation. Cursor is the row that still leaves a machine open: the macOS
build's hook execution has never been measured, and the Windows
launch-shell bug recorded in [`cursor/README.md`](cursor/README.md) is
exactly why "imported" cannot be read as "working" until someone measures it.

Grok's live verification also produced the first measured **failure** of a
floor claim, and it belongs here rather than only in the vendor file, because
it is not Grok-specific: the hook deny survives `bypassPermissions`, but the
credential guard's documented out-of-scope classes are contained by the
permission layer that a bypass removes — so a decoy credential was read out in
an ordinary session. **A wired row means the hook fires. It does not mean the
redline holds under a permission bypass.** See
[`grok/README.md`](grok/README.md), "The floor does not hold under
`bypassPermissions`".

Both halves of that finding are now settled, and the wiring table is not what
settled them. The measured shape closed in the **canonical** guard (v2.9), so
it closed for every lane at once rather than for Grok: a copy / move / rename
whose source is a credential path and whose destination is not is refused, and
the sensitive-file pattern now covers derived names. The *class* it came from
is still open by design — a pattern guard cannot be complete against an agent
holding a shell — so the conclusion is an operational rule rather than a fix:
**`bypassPermissions` is not a supported configuration on any lane with no
judgment layer above the guard**, and a lane running under one is treated as
unguarded for credential exposure whatever its row here says. The rule and its
named residuals are in [`security/posture.md`](../security/posture.md) (limit
#8 and "What the copy rule does and does not buy");
[`ADR-012`](../decisions/ADR-012-capability-parity-and-the-guard-obligation.md)
decision 2 carries the correction in place, dated, rather than as a separate
ADR.

**A harness nobody routed work to still owes a guard.** Grok Build is the
worked example: it was never assigned a lane, and it was still an unprompted
agent with shell and filesystem reach whose imported guards had never once
fired. Waiting for a routing decision before wiring the control gets the
dependency backwards, which is the same inversion ADR-012 found in ADR-010.

Until 2026-08-04 Cursor and Antigravity compensated with bounded safety
envelopes — read-only defaults and revertible-work-only rules.
[`ADR-012`](../decisions/ADR-012-capability-parity-and-the-guard-obligation.md)
retires that compensation: **capability parity is the fleet default, so guard
wiring is the only remaining control.** An unwired vendor is now an open
obligation, not a vendor kept on a short leash.

Antigravity's half of that obligation is closed. It ships a `PreToolUse` hook
contract with a hard `deny`, and
[`gemini/hooks/agy-guard-adapter.py`](gemini/hooks/agy-guard-adapter.py) now
wires all three guards through it by translating the payload and running the
canonical scripts unmodified — no second copy of any rule. The deny was
measured to hold even under `--dangerously-skip-permissions`. ADR-010's
"until tool-time guard parity exists" did describe a build task, and the
build is done; see [`gemini/README.md`](gemini/README.md) for the measured
hook semantics and the residual gaps that remain.

Rationale for this layout: [`decisions/ADR-008`](../decisions/ADR-008-agent-ops-rename-and-vendor-layer.md).
