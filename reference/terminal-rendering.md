# Reference: terminal rendering primitives

**Shelf note, not a convention.** Nothing here needs doing. Filed for the day
something in this fleet draws a live, multi-line terminal UI — a statusline that
outgrows one line, a progress view, a local TUI over a long-running agent run.

Source: [pi](https://github.com/earendil-works/pi) (MIT), `packages/tui/` —
`tui-main-screen.ts`, `tui-alt-screen.ts`.

## 1. Synchronized output: two lines that delete tearing

Wrap **any** multi-line repaint in:

```
\x1b[?2026h   // begin synchronized output
…all the cursor moves, clears and writes…
\x1b[?2026l   // end synchronized output
```

The terminal holds its presentation until the closing sequence, then swaps the
whole region at once. Without it, the terminal is free to paint mid-update, and
the user sees the intermediate frame — cleared rows, a half-moved cursor, text
flashing at the wrong column. That is the entire cause of the "flickering TUI"
that gets misattributed to render speed and then chased with throttling and
debouncing, none of which fix it, because the problem is atomicity and not
frequency.

Terminals that do not implement the mode ignore the sequences, so there is no
capability detection and no fallback path to maintain. pi emits them around
every repaint site: the incremental line update, the deleted-lines clear, the
full render. **The rule is per-repaint, not per-frame** — if a single logical
update writes more than one line, it is inside the pair.

Cost: two constants and a `try`-shaped discipline about where the buffer starts
and ends. This is the highest value-per-line item in the whole read.

## 2. Render to a string list, diff by string equality

pi's main-screen renderer produces the entire screen as an array of strings
(each already containing its ANSI attributes), keeps the previous array, and
compares them element-wise with `!==` to find `firstChanged` and `lastChanged`.
Only that range is repainted; everything outside it is left alone.

```
for (let i = 0; i < maxLines; i++) {
    const oldLine = i < this.previousLines.length ? this.previousLines[i] : "";
    const newLine = i < newLines.length ? newLines[i] : "";
    if (oldLine !== newLine) {
        if (firstChanged === -1) firstChanged = i;
        lastChanged = i;
    }
}
```

That is the whole diff algorithm. No virtual DOM, no cell-level damage
tracking, no curses. It works because a rendered terminal line **is** its own
identity — style is in the string, so string equality is exactly the right
comparison, with no need for a separate model of what a cell contains.

The design lesson is the one worth shelving: the reason terminal UIs get
reached-for-a-framework is an assumed need for fine-grained reconciliation, and
at terminal dimensions that need is imaginary. A few thousand string
comparisons per frame is nothing. **Reconciliation machinery earns its keep when
computing the diff is cheaper than redrawing; at this scale it never is, so the
cheapest correct diff wins.**

Appends are special-cased rather than diffed (if the new list is longer and
nothing before the old end changed, `firstChanged` is the old length) — which is
the streaming-output case, i.e. the common one.

## 3. Explicit full-redraw fallbacks, each with a stated reason

Incremental rendering is an optimization with preconditions, and pi enumerates
every point where they stop holding and falls back to a full render — each one
logged with the reason that triggered it:

- first render
- terminal **width** changed
- terminal **height** changed
- content **shrank** below the previously-rendered maximum and no overlays are
  active (leftover rows would otherwise stay on screen)
- deleted lines moved the target row **above the viewport top**
- lines to clear **exceed the terminal height**
- `firstChanged` is **above the viewport top** — the changed line has scrolled
  out of the addressable region, so relative cursor motion cannot reach it

The shape to copy is not the specific list, it is the discipline: **the
incremental path is allowed to handle only the cases it provably can, and every
other case has a named, logged escape to the slow-but-correct path.** A renderer
that tries to be incremental everywhere accumulates rare visual corruption that
is unreproducible by definition, because reproducing it requires the resize, the
scrollback state and the content length that produced it.

The shrink-clear fallback is even made configurable (an env var and a setter),
which is the honest admission that one of these heuristics interacts with the
host terminal in ways the author could not fully enumerate. That is the right
move for a heuristic in a compatibility layer: make it a switch, not a bet.
