# Gemini adapter — reserved

Nothing is installed yet. This directory exists so the session that adds
the third vendor has a defined landing pad and a definition of done.

Minimum deliverables for that session:

1. **Instruction-file wiring** — where Gemini reads standing instructions
   on a machine, and how that file stays in sync with fleet canon (see the
   drift warning in [`../codex/README.md`](../codex/README.md); do not
   invent a third hand-maintained mirror without a check).
2. **Channel probe** — how the other agents reach Gemini non-interactively
   (CLI command, flags, auth state), verified with an actual round trip
   before it is documented as working.
3. **Division-of-labor amendment** — what work routes to Gemini and why,
   recorded in the fleet contract with the other vendors, not only here.
   The default assumption is a specialist/second-opinion role; expanding it
   is a design decision, not a default.
4. **Telltale entry** — the cross-vendor usage HUD
   ([telltale](https://github.com/sanlee-ys/telltale)) tracks this vendor's
   quota window alongside the other two.
5. **Guard wiring or an explicit gap note** — per the guards note in
   [`../README.md`](../README.md): if the fleet's guard policy is not
   enforceable in Gemini's harness, record that as a known gap rather than
   leaving it implicit.

Adapter contract: [`../README.md`](../README.md).
