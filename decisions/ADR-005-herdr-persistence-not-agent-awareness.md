# ADR-005: Herdr is adopted for persistence, not for agent awareness

**Status:** Accepted — 2026-07-26. Records the outcome of a scoped trial of
Herdr 0.7.5 as a persistent agent workspace.
**Scope:** This repo (the Claude operating layer). The trial ran inside the
public `netops-lab` repo, but the decision is about how long agent sessions are
run generally, not about that lab.
**Corrected:** 2026-07-26, twice, both on the day of writing. The second round
retracts a central finding. **`agent prompt` is not broken** — it was
re-tested directly and submitted correctly, with and without `--wait`. And the
"unattributable instruction found armed in a composer" that this ADR used as
its sharp edge **did not happen**: the text was the agent's own dim placeholder
suggestion, confirmed by reading the pane's raw output and finding the ANSI
faint attribute (`ESC[2m`) on it. Nobody could establish its provenance because
nothing had been sent.

What survives is thinner than the original document and is marked in place
rather than rewritten, because the retraction is the useful record. The first
round's correction — that `done` behaves as designed rather than as a defect —
also stands. See [The rule](#the-rule); the lesson moved from "the tool lies" to
"we misread the tool twice and wrote decisions on top of it."
**Related:** [`ADR-004-ref-explicit-git-in-shared-clones.md`](ADR-004-ref-explicit-git-in-shared-clones.md)
— a sibling case of automation that does exactly what it was written to do, on
the wrong object. The lab-side application of this decision lives in the public
`netops-lab` repo as its ADR-007, which records what the trial means for that
lab's hardware cycles; this ADR holds the general rule.

## Context

Work spans more than one machine, and sessions do not survive switching between
them: uncommitted work is invisible across devices, and a closed terminal ends
whatever was running in it. The wanted property is a workspace that keeps agents
alive when nobody is attached, reachable over SSH from any of the machines.

[Herdr](https://github.com/ogulcancelik/herdr) (Rust, Apache 2.0) advertises
exactly that, plus something tmux does not have: per-pane detection of whether
an agent is idle, working, blocked, or done. Persistence alone is a solved
problem, so the agent-awareness layer is the entire reason to prefer it over
tmux, and the trial was designed to test that layer specifically.

Trial shape: Herdr 0.7.5 (stable `linux-aarch64`) on an always-on ARM64 Linux
host, driving Claude Code against one public repo on read-only documentation
tasks. A second Claude Code outside the pane polled the socket API on a 2-second
interval and read Herdr's own server logs.

## What the trial proved

**Persistence is solid.** The server daemonises to PPID 1 with no controlling
tty and the agent runs on the server's own pty. Killing the SSH connection that
launched it left both alive, the session reported `running`, and scrollback was
readable straight out of the server's buffer after the connection was gone.

**Detached tracking is real, and tmux cannot do it.** With zero clients
connected, Herdr tracked a full `working` → `idle` cycle. This is the
differentiator, and it works.

**Driving a pane from outside works.** *(Added on correction. The original
document claimed the opposite.)* `herdr agent prompt <target> <text>` submitted
and the agent answered, both with `--wait` and without it, issued from a
one-shot SSH command with no client attached. Verified by reading the pane back
rather than by trusting the return value.

~~**Detection is accurate in at least one subtle case:** a pane holding
*unsubmitted* text in its prompt box was correctly reported idle rather than
working.~~ *(Retracted. That text was dim placeholder suggestion, not entered
text, and Herdr documents ghost/placeholder recognition via ANSI de-emphasis.
Reporting idle was therefore trivially correct, not subtly correct. Detection
was still right in every observed case — this just was not evidence for it.)*

## What the trial found broken, and what it found merely misunderstood

1. **`done` requires presence — by design, not by defect.** *(Amended. The first
   version of this ADR called it "inverted" and treated it as a fixable bug.
   That was wrong.)* `done` means "the agent finished while you weren't
   looking," and it appears only while a client is attached, clearing at the
   instant of detach. The reason is that it feeds `[ui.toast]`, a client-side
   concept: with nobody attached there is nobody to notify. It was built for
   "attached, looking at another pane," not "away from the machine." Compounding
   it, `[ui.toast] delivery` defaults to `"off"` and the trial host had no
   config file, so `done` was firing into the void even while attached.

   The correction matters more than the fact. A capability can be absent because
   it is broken or because it was never the tool's job, and only the first is
   worth waiting on. Calling this a defect set up a revisit condition that would
   never have been met.
2. ~~**`agent prompt` fails silently and logs success.**~~ **RETRACTED.** The
   original claim was that it delivers keystrokes without submitting them while
   recording `outcome="ok"`. Re-tested directly on the same host and the same
   Claude Code build, in a scratch pane, from a one-shot SSH command with no
   client attached: it submitted and the agent answered, both with `--wait` and
   without. Two for two.

   The original observation was a single `outcome="ok"` log line correlated with
   text believed to be sitting unsubmitted in a composer. That text was
   placeholder (see the retraction below), so there was never an unsubmitted
   prompt to explain. The log line was recording a call that worked.

   An upstream report of this bug does exist —
   [ogulcancelik/herdr#1878](https://github.com/ogulcancelik/herdr/issues/1878),
   filed independently by another user hours before this trial began — so the
   defect is real for someone. It does not reproduce here, and this ADR should
   never have asserted it from correlation.
3. **Agent state cannot be made event-driven.** `pane.report_agent` accepts an
   explicit state, but pushing one — using the official `herdr:claude` source
   string and a fresh sequence number — was ignored. The screen manifest is the
   sole authority for Claude Code, and nothing the agent reports can override
   it. This closes the obvious repair: you cannot fix the heuristic by feeding
   the tool ground truth.
4. **Detection is entirely screen-scrape.** The winning rule regexes a braille
   spinner out of the terminal title; others grep literal interface strings such
   as `esc to interrupt`. It is coupled to the agent's cosmetics, so a UI change
   degrades it silently.
5. **The detection manifest is fetched unpinned at server start**, over the
   network, unverified. Milder than executable code — it is TOML regexes — but
   inconsistent with the care taken elsewhere in the same install.
6. **The integration hook contributes no status.** It only reports a
   pane-to-session mapping. The hook being installed and current says nothing
   about whether detection ever ran.
7. **`pane.send-keys` / `pane.send-text` are not logged.** Only `agent.prompt`
   appears in the server log. This one is unchanged and verified: a grep of the
   server log during the correction pass showed `agent.prompt` and nothing else.
   It is a genuine gap in what a herdr server can tell you after the fact.

   *(Its original framing is retracted. This was written as "the input path
   that works is not audited" — the sharp half of a pair with finding 2, where
   the audited call lied and the unaudited one worked. With finding 2 gone,
   what remains is an ordinary logging gap, not an inversion. It is worth
   fixing upstream and it is not a reason to withhold anything.)*

**Where this leaves the verdict.** With findings 2 and the composer incident
retracted: **awareness works** — every state reported was correct, attached and
detached. **Control works** — panes can be driven from outside, verified
directly. **Notification was never built for absence**, by design. The only
standing reservation is durability: detection is screen-scrape against another
program's chrome (finding 4), unrepairable by feeding it ground truth
(finding 3), and it fails by reporting a confident wrong `idle` rather than by
erroring.

That reservation is real and is the whole basis for what follows. The rest of
the original case against this tool did not survive re-testing.

### The retracted incident

The original document built its case on this paragraph, which is now withdrawn
in full:

> Findings 2 and 7 compose into the sharp edge: the call that lies is logged,
> and the call that works is invisible. During the trial a write-intent
> instruction was found armed in a pane's prompt box and its provenance could
> not be established from the logs.

No instruction was ever armed. The text was the agent's own **dim placeholder
suggestion** — the next prompt Claude Code offers, rendered faint. Confirmed by
reading the pane's raw terminal output and finding the ANSI faint attribute
(`ESC[2m`) wrapping it. Herdr's own documentation describes ghost/placeholder
recognition via ANSI de-emphasis, so this is furniture the tool already knows
about.

The provenance could not be established because there was no provenance. Two
sessions and a human spent real time attributing a message nobody sent, and a
security posture was written on top of it.

## Decision

**Adopt Herdr for persistence, interactive use, and driving panes from outside.
Treat its status signal as advisory.** Concretely:

- Long-running agent sessions may live in Herdr panes on the always-on host.
- **Driving a pane from outside is supported.** `agent prompt` works. Still
  verify the effect by reading the pane back when the result matters — not
  because the call lies, but because reading the artifact rather than the
  return value is the standing discipline, and it is one command.
- **Status is advisory, never a gate.** `working` and `idle` were correct in
  every observed case and are fine to read. Nothing irreversible may branch on
  them, because the failure mode when detection drifts is not an error but a
  confident, wrong `idle`. **This is the one reservation that survived
  re-testing**, and it rests on the mechanism (finding 4), not on any observed
  failure.
- **Don't wait on `done`.** Not because it is broken, but because it is a
  client-side notification and absence is exactly when it cannot fire. If
  "finished while away" is ever wanted, it comes from a Claude Code lifecycle
  hook, which fires detached and fires whether or not Herdr is running.

**Revisit conditions, corrected.** The original said "revisit when `agent
prompt` submits correctly." It already does. There is no open defect this
decision is waiting on. If detection drift is ever observed in practice, that is
the trigger to reconsider, and the drift check in `scripts/herdr-awareness-check`
exists to surface it.

## Options considered

**(a) Stay on tmux.** Twenty years of hardening and no false signals, at the
price of losing detached `working`/`idle`, which the trial proved is real.
Rejected: that capability is worth having, and the failures are avoidable by not
depending on the parts that fail.

**(b) Adopt fully, including scripted drive-from-outside.** ~~REJECTED.~~
*(Correction: this was rejected on findings that did not survive re-testing.
`agent prompt` works. It is no longer ruled out, and the only thing standing
between here and it is that nothing yet needs it — which is a reason not to
build, not a reason it cannot be built.)*

**(c) Switch the agent harness.** Herdr treats some harnesses as lifecycle
authorities and gets real events rather than screen-scrape; Claude Code is
documented as *not* one. Rejected: a second harness and a second authentication
is a large commitment to buy one status signal.

**(d) Adopt persistence, own the status signal separately.** Not chosen now, but
the natural next step if the signal is ever needed unattended. Claude Code's own
hook system fires on session lifecycle events, so a hook can write durable state
that survives detach. Finding 6 means this does not conflict with Herdr's hook,
which is not doing that job, and finding 3 means it is the *only* route: state
cannot be pushed into Herdr, so a parallel signal is the sole way to get an
event-driven one.

**(e) Adopt persistence and interactive use, treat status as advisory. —
CHOSEN.** Takes what re-testing actually supports. The single standing
reservation is detection durability, which is a property of the mechanism rather
than an observed failure.

## The rule

> **A defect claimed from a single correlated observation is a hypothesis, not a
> finding. Reproduce it deliberately before writing a decision on top of it —
> especially when the claim is that a tool is lying, because that explanation is
> unfalsifiable from the outside and flattering to the observer.**

*(The original rule here asserted that an interface reporting false success is
worse than one that errors. True in general, and not what happened. It is
replaced rather than kept, because keeping it would preserve the frame that
produced the error.)*

Four things generalise beyond this tool.

**Correlation is not a finding.** The central claim — that `agent prompt`
submits nothing and reports success — came from one `outcome="ok"` log line
observed alongside text believed to be sitting unsubmitted in a composer. Both
halves were wrong: the text was placeholder, so there was nothing unsubmitted,
and the log line was recording a call that had worked. Neither half was checked
independently. Two ADRs, a machine-seam rule and a security posture were written
before anyone ran the command a second time.

**Test the signal under absence.** Still holds, and it is what eventually
settled this: the re-test was issued from a one-shot SSH command with no client
attached, which is the condition the capability exists for. The original trial
had this instinct right and its execution was sound — the polling, the server
logs, the detached window. What it lacked was repetition.

**Separate "broken" from "not its job" before writing a revisit condition.**
This ADR originally filed `done` as a defect and promised to revisit when it was
fixed. It is documented, intended behaviour, so that revisit would never have
arrived — and the plan would have looked healthy the whole time it wasn't
happening. Absence of a capability has at least two causes and only one of them
is worth waiting on. Reading the tool's own design docs, rather than only its
behaviour, is what distinguishes them, and it is cheap relative to waiting on a
fix nobody is writing.

**Verifying the front door is not verifying the software.** This install checked
the binary's SHA-256 against the publisher's digest and the package repository's
GPG fingerprint before trusting either — and then the program fetched its
detection rules over the network at startup, unpinned and unverified. Supply
chain review that stops at installation misses everything a program pulls in at
runtime.

## Verification

**Original trial.** Sampled on a 2-second interval across attached and fully
detached phases, producing a 6,482-line evidence log, cross-read against the
server's own logs rather than against the client display. Connection loss was
tested by killing the SSH connection that launched the server. The drop test ran
from an already detached state, so it proves the server is independent of the
launching shell, not client-teardown recovery while attached. The evidence log
was session-scoped and is not preserved.

**Correction pass.** In a scratch pane on the same host, same Claude Code build,
issued from one-shot SSH commands with no client attached:

- `herdr agent prompt <target> "Reply with exactly: DONE" --wait --timeout 6000`
  — submitted, agent answered `DONE`, turn completed in 4s.
- `herdr agent prompt <target> "Reply with exactly: SECOND"` (no `--wait`) —
  submitted, agent answered `SECOND`.
- Both confirmed by reading the pane back, not by the return value.
- `grep agent.prompt` on the server log across the whole day: three calls, all
  accounted for. No unexplained input.
- The composer's remaining text was read with `pane read --ansi` and carries the
  ANSI faint attribute `ESC[2m`, identifying it as placeholder.

The scratch pane was created with `pane split`, the agent with `agent start`,
and the pane closed afterwards.

An earlier draft of this trial's brief also asserted the observing session ran
inside a Herdr pane. It did not, and the conflation is recorded because it is
easy to repeat: the integration hook reporting itself as installed and current
was read as evidence that detection had run, which finding 6 shows it is not.
That is the same error as the retracted finding 2, in miniature — a status
string read as evidence of an event.

## Consequences

- Herdr stays installed on the always-on host, is used by hand, and may be
  driven from outside when something needs it. Nothing in the operating layer
  depends on it today.
- `done` is on a do-not-depend list, permanently — it is not a defect awaiting
  a fix.
- The one live risk is detection drift, which fails silently. That is what
  `scripts/herdr-awareness-check` watches, and the reason status stays advisory.
- **The machine-seam rule this ADR originally justified is weakened.** It
  withheld push credentials from the always-on host because an instruction could
  reach an agent there unattributably. That incident did not happen. The
  logging gap is real, so the seam may still be worth keeping, but it now rests
  on a general argument rather than a specific one and should be re-decided on
  that basis rather than inherited from here.
