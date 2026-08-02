# ADR-009: Cursor as IDE lane in the agent fleet

**Status:** Accepted — 2026-08-02
**Amends:** the fleet division-of-labor contract referenced in
[`ADR-008`](ADR-008-agent-ops-rename-and-vendor-layer.md) (2026-08-02)

## Context

The fleet had a written two-vendor contract (Claude Code primary implementer,
Codex second opinion) plus a reserved third **API-metered** slot for Gemini so
the cross-vendor usage HUD can track three quota windows
([`vendors/gemini/README.md`](../vendors/gemini/README.md)). A fourth runtime
was already in daily use: **Cursor** (Composer), embedded in the IDE — a
different axis from API vendors. It had no adapter, no allocation table row, and
no recorded guard gap.

ADR-008 requires each vendor to have a directory under `vendors/`, a
division-of-labor amendment, and an honest guard-wiring note. Cursor met none
of those.

## Decision

1. **Add `vendors/cursor/`** with the adapter contract in its README — role,
   allocation table, instruction wiring, channel, guard gaps, telltale note.
2. **Cursor is an IDE lane**, not co-primary with Claude for long
   implementation and not a substitute for Codex on consequential independent
   review.
3. **Cross-harness transfers use inspectable state only** — branch, PR, diff,
   optional handoff brief — extending the protocol already documented for
   Codex to Cursor.
4. **Guard gap is recorded, not implied.** The `PreToolUse` hooks in
   `hooks/` and `security/` are not wired in Cursor; fleet policy still
   applies behaviorally. Consequential or credential-adjacent work stays on
   Claude until parity exists or an equivalent is documented.
5. **The Gemini slot is unchanged.** Cursor is runtime #4; Gemini remains the
   planned API vendor #3 for telltale quota tracking. They are not the same
   slot.

## Consequences

- The private usage strategy (loaded via pointer sections in global
  instruction files) gains a Cursor section and a pointer back to
  `vendors/cursor/README.md`.
- Global instruction files need their fleet-division summary updated when
  next edited — hand-mirrored, same drift risk as the Codex file.
- Telltale has a documented gap until a Cursor quota adapter lands.
- The one-month measurement gate may add a Cursor friction axis once telltale
  supports it; until then, Cursor routing is exercised but not metered in the
  HUD.
