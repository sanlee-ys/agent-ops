# ADR-010: Claude-led orchestration across four vendor surfaces

**Status:** Accepted — 2026-08-02; decision 4 and the guard-posture table's
"Routing consequence" column superseded by
[`ADR-012`](ADR-012-capability-parity-and-the-guard-obligation.md) (2026-08-04);
harness roster extended by
[`ADR-014`](ADR-014-pi-harness-kimi-model-target.md) (2026-08-11) for the Pi
seat and its Kimi model target
**Amends:** ADR-009 decision 5 and its telemetry consequences

## Context

The vendor registry had reached four active surfaces—Claude Code, Codex,
Cursor, and Google Antigravity—but the division-of-labor contract still
described three. The mismatch was substantive:

- ADR-009 called Gemini a planned API slot, while the Antigravity adapter
  called it a broad active implementation vendor.
- Cursor was already live in telltale, although the private strategy still
  described its HUD adapter as future work.
- Codex had gained local parity with Claude's fleet guard hooks, while the
  public adapter recorded no guard posture; Cursor and Antigravity still had
  no equivalent tool-time suite.
- A harness and a model family were being treated as the same routing axis.
  Opening Claude or GPT in a different product changes tools and workflow,
  but does not create an independent opinion.

Equal work distribution would spend coordination on duplicated capability.
The useful shape is one control plane with specialist lanes whose boundaries
are explicit and whose value can be measured.

## Decision

1. **San owns Direction, Contracts, and Bar. Claude Code is the control
   plane, default implementer, and final integrator.** Its working context,
   native skills, and deliberately larger capacity make internal
   subagents/worktrees the first production-parallelism tool.
2. **Codex is the independent GPT-family challenge lane.** It challenges
   consequential designs, reviews consequential diffs read-only, and
   diagnoses after two failed hypothesis-driven attempts or visible looping.
   Mechanical green-CI work does not receive a ceremonial second pass.
3. **Cursor is the IDE lane.** It owns bounded edit-test loops and browser/UI
   verification when the editor surface is the advantage. It is not the
   default for long refactors and its own subagent review does not satisfy the
   independent-review contract.
4. ~~**Antigravity is a measured Gemini-family experiment and overflow lane.**
   Default uses are read-only research, broad audits, browser/Google-stack
   work, and a third opinion when Claude and Codex disagree. An implementation
   prototype is allowed only in a disposable worktree with explicit review.
   Consequential, credential-adjacent, and published-history writes stay out
   until tool-time guard parity or an equivalent is documented.~~
   **Superseded by [`ADR-012`](ADR-012-capability-parity-and-the-guard-obligation.md).**
   The lane's role (research, audits, browser/Google-stack work, third
   opinion) stands; the capability restriction does not. The trailing
   condition proved to be a build task rather than a blocker — the
   `PreToolUse` deny mechanism was there all along.
5. **Harness and model family are separate routing axes.** Model-family
   independence is required when independence is the reason for the handoff.
   Selecting Claude or GPT inside Cursor or Antigravity does not satisfy that
   requirement.
6. **Parallelism keeps one integrator.** Partition by independent file or
   repository, freeze shared contracts before fan-out, and update generated
   or aggregate artifacts once, last.
7. **Transfers use inspectable state.** A frozen brief, explicit file
   boundary, pushed branch or PR, exact revision, and verification results
   cross the harness boundary. San is never the clipboard between agents.
8. **Telltale remains an observer, not a router.** Direct headless calls such
   as `codex exec` and `agy -p` are deliberate case-by-case dispatches. No
   quota-based or automatic dispatcher is built until repeated manual routing
   proves a need.

**Amendment, 2026-08-11 ([`ADR-014`](ADR-014-pi-harness-kimi-model-target.md)):**
Pi is an additional routing harness (open-source overflow / extension-first).
Its **target** model family is Kimi (K3 when access lands). An interim xAI
`grok-4.5` backend may keep the seat warm but does not satisfy decision 5's
independence test against Grok, and does not admit Grok Build as a routing
lane. Anthropic pools stay on Claude Code, not behind Pi.

## Guard posture at this decision

| Harness | Tool-time fleet guards | Routing consequence |
|---|---|---|
| Claude Code | Wired | Full primary lane |
| Codex | Locally mirrored and wired | Review/diagnosis lane remains read-only by contract |
| Cursor | Not wired | ~~Bounded, revertible work only~~ |
| Antigravity | Not wired; permissive command posture observed | ~~Read-only by default; disposable-worktree prototypes only~~ |

The table records implementation truth, not a promise that behavioral
instructions substitute for controls.

**Amendment, 2026-08-04 ([`ADR-012`](ADR-012-capability-parity-and-the-guard-obligation.md)):**
the "Routing consequence" column is retired. Capability parity is the fleet
default, so a routing consequence no longer follows from a guard gap — the
gap is simply an open obligation. The "Tool-time fleet guards" column stays
accurate and becomes the entire argument. The caveat above it survives
intact and is now the spine of the posture rather than a footnote to it.

## Consequences

- ADR-009's statement that Gemini remains a planned slot is superseded.
  Antigravity is active, but deliberately bounded rather than co-primary.
- ADR-009's Cursor telemetry gap is resolved for session/context visibility:
  Cursor is in telltale's HUD. Cursor still persists no local consumption
  reading, so subscription burn remains absent rather than estimated.
- Public vendor adapters carry the role, channel, and guard truth for each
  harness. Subscription economics and the dated measurement gate remain in
  the private strategy.
- The fleet gains no new orchestrator service or shared mutable state. Git and
  deterministic verifiers remain the coordination and acceptance surfaces.
