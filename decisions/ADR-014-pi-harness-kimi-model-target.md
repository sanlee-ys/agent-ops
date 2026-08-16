# ADR-014: Pi harness seat; Kimi is the model target

**Status:** Accepted — 2026-08-11
**Amends:** [`ADR-010`](ADR-010-claude-led-four-vendor-orchestration.md)
(harness roster and model-family axis); pairs with the Pi admission in
[`vendors/pi/`](../vendors/pi/)

## Context

Pi ([earendil-works/pi](https://github.com/earendil-works/pi)) was admitted
2026-08-11 as an open-source coding harness with a verified `tool_call`
deny guard (`vendors/pi/extensions/fleet-guard.ts`). The first live seat
used the xAI subscription ride (`grok-4.5`) because it was a documented
first-party Pi login and drew on a pool no other routing lane drained.

That interim choice collides with a fleet rule ADR-010 already stated:
**harness and model family are separate axes.** Grok Build is installed and
guard-wired but deliberately **not** a routing lane
([`vendors/grok/`](../vendors/grok/)). Cursor may also surface Grok. Putting
Grok behind Pi as the *standing* backend would create a second (or third)
Grok surface and call it "independence" — the Cline failure shape, only
with xAI instead of Anthropic.

Pi itself is still worth the seat: thin core, extension-first, first-class
provider plugins, and native support for Kimi For Coding / Kimi K3
(including subscription OAuth and deferred-tool loading). The missing piece
is naming which **model family** the Pi harness is for, so overflow capacity
and family independence stop being confused.

Access to Kimi K3 is waitlisted at acceptance time. The decision cannot wait
on the waitlist; the interim backend must be labeled interim.

## Decision

1. **Pi is a fleet routing harness.** Role: open-source overflow and
   extension-first seat. It is not the control plane, not the GPT review
   lane, not the IDE lane, and not a substitute for Antigravity's
   Gemini-family research role.
2. **The Pi seat's target model family is Kimi (Moonshot / Kimi For
   Coding), with Kimi K3 as the intended default when access lands.** That
   is the independence claim. Until then the seat is admitted but its
   model-family value is provisional.
3. **xAI `grok-4.5` on Pi is interim capacity only.** It may keep the seat
   warm and drain an otherwise unused subscription, but it does **not**
   count as model-family independence from Grok, and it does **not** admit
   Grok Build as a routing lane by the back door.
   **Amendment, 2026-08-16:** San declined that interim ride. The Pi seat
   is parked until Kimi access lands. Do not put Grok, Claude, or GPT
   behind Pi to keep the chair warm.
4. **Do not put Anthropic Pro/Max (or any Claude pool) behind Pi.**
   Unsupported third-party ride; duplicates Claude Code with a worse tool
   surface. Same prohibition shape as the Cline evaluation.
5. **Cutover is a settings + verify step, not a re-admission.** When Kimi
   access arrives: authenticate the Kimi provider in Pi, set
   `defaultProvider` / `defaultModel` to the Kimi K3 (or then-current Kimi
   coding) default, re-run the print probe and a fleet-guard deny, and
   update `vendors/pi/README.md` verification. No second ADR unless the
   family target itself changes.
6. **Grok Build remains guard-wired, not routed.** Unchanged from
   [`vendors/grok/`](../vendors/grok/) and ADR-012's "installed ⇒ owes a
   guard" rule.

## Consequences

- Top-level fleet prose (`vendors/README.md`, profile/operating docs that
  mirror ADR-010) lists Pi as a harness seat and states the Kimi target
  explicitly, rather than describing Pi as "the xAI lane."
- Agents must not treat "I am in Pi" as "I am a non-Grok second opinion"
  while the interim backend is still Grok.
- **2026-08-16:** the interim Grok backend is off. Pi has no model until
  Kimi cutover. A launch that needs a model is not a reason to restore
  xAI, Claude, or GPT on this seat.
- Subscription economics for Kimi land in the private strategy when the
  waitlist converts; this ADR only locks the routing intent.
- If the Kimi waitlist never converts, revisit the target family — do not
  silently promote interim Grok into the permanent Pi backend.
