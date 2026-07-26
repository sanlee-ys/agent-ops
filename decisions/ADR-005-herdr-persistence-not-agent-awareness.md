# ADR-005: Herdr is adopted for persistence, not for agent awareness

**Status:** Accepted — 2026-07-26. Records the outcome of a scoped trial of
Herdr 0.7.5 as a persistent agent workspace.
**Scope:** This repo (the Claude operating layer). The trial ran inside the
public `netops-lab` repo, but the decision is about how long agent sessions are
run generally, not about that lab.
**Amended:** 2026-07-26, same day. A parallel session dug further into the same
trial and established that `done` behaves as designed rather than as a defect,
and that `agent prompt` has a working substitute. Both corrections are folded in
below and marked. The original claims are named rather than silently replaced,
because "we called documented behaviour a bug" is the more instructive record.
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

**Detection is accurate in at least one subtle case:** a pane holding
*unsubmitted* text in its prompt box was correctly reported idle rather than
working.

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
2. **`agent prompt` fails silently and logs success.** On Claude Code 2.1.220 it
   delivers keystrokes without submitting them, and the server records
   `outcome="ok"`. A caller that checks the return value learns nothing.
   *(Amended: a working substitute exists — following it with
   `herdr pane send-keys <pane> enter` submits correctly. The call is therefore
   usable by hand; it remains unfit for unattended automation, because the thing
   that is broken is its truthfulness, not its delivery.)*
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
7. **The input path that works is not audited.** Only `agent.prompt` appears in
   the server log. The `pane.send-keys` / `pane.send-text` calls that actually
   succeed leave no trace at all.

With findings 1 and 3 corrected, the honest split is three-way rather than
two-way: **awareness works** — every state reported during the trial was
correct, attached and detached, including a visually busy pane holding
unsubmitted text that was rightly called idle. **Control is broken.**
**Notification was never built for absence.** Only the second of those is a
defect to wait on.

Findings 2 and 7 compose into the sharp edge: the call that lies is logged, and
the call that works is invisible. During the trial a write-intent instruction was
found armed in a pane's prompt box and its provenance could not be established
from the logs. It turned out to be benign — an agent's own drafted recap, left
unsent — but nothing in the record could establish that, and a human had to.

## Decision

**Adopt Herdr for persistence and interactive use. Do not build on its agent
awareness.** Concretely:

- Long-running agent sessions may live in Herdr panes on the always-on host.
- **No automation calls `agent prompt`.** Anything driving a pane from outside
  must send input and then verify the effect by reading the pane back, never by
  trusting a return value.
- **Status is advisory, never a gate.** `working` and `idle` were correct in
  every observed case and are fine to read. Nothing irreversible may branch on
  them, because the failure mode when detection drifts is not an error but a
  confident, wrong `idle`.
- **Don't wait on `done`.** Not because it is broken, but because it is a
  client-side notification and absence is exactly when it cannot fire. If
  "finished while away" is ever wanted, it comes from a Claude Code lifecycle
  hook, which fires detached and fires whether or not Herdr is running.
- **No standing permission to drive agent sessions from outside.** Granting it
  would create an unauditable write path into a session that can modify a repo.

**Revisit when `agent prompt` submits correctly** — that one is a defect in a
fast-moving 0.7.5 and was reported upstream. Do *not* wait on `done`; the
original version of this ADR set that as a revisit condition, and since the
behaviour is designed rather than broken, it would have waited forever. A
revisit condition that can never be met is worse than none, because it reads
like a plan.

## Options considered

**(a) Stay on tmux.** Twenty years of hardening and no false signals, at the
price of losing detached `working`/`idle`, which the trial proved is real.
Rejected: that capability is worth having, and the failures are avoidable by not
depending on the parts that fail.

**(b) Adopt fully, including scripted drive-from-outside. — REJECTED.** This is
the option the findings exist to rule out. It requires trusting the one call
that reports success on failure, over a path with no audit trail.

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

**(e) Adopt persistence only. — CHOSEN.** Takes the part that is proven, depends
on nothing that was found broken, and costs nothing to reverse.

## The rule

> **An interface that reports success for work it did not complete is worse than
> one that errors, and audit coverage that is strongest on the path that fails
> is not an audit trail. Before depending on a status signal, test it under the
> condition it exists for — which is usually the condition where nobody is
> watching.**

Three things generalise beyond this tool.

**Test the signal under absence.** Every failure here was invisible while
attached. `done` looked correct, and `agent prompt` looked correct, precisely
because a person was present to see the outcome directly. A signal that exists
for unattended use has to be tested unattended, or the test confirms only that
it works when it is not needed. This is the same shape as a green check that
means the job ran rather than that the work happened.

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

Sampled on a 2-second interval across attached and fully detached phases,
producing a 6,482-line evidence log, cross-read against the server's own logs
rather than against the client display. Connection loss was tested by killing
the SSH connection that launched the server.

Two limits stated rather than glossed. The drop test ran from an already
detached state, so it proves the server is independent of the launching shell,
not client-teardown recovery while attached. And the evidence log was
session-scoped and is not preserved — the findings above are the artifact.

An earlier draft of this trial's brief asserted the observing session ran inside
a Herdr pane. It did not, and the correction is recorded here because the
conflation is easy to repeat: the integration hook reporting itself as installed
and current was read as evidence that detection had run, which finding 6 shows
it is not.

## Consequences

- Herdr stays installed on the always-on host and is used by hand. Nothing in
  the operating layer depends on it.
- The `done` state and `agent prompt` are on a do-not-depend list. If either is
  fixed upstream, this ADR is the thing to amend.
- A machine seam falls out of this and is recorded where the work happens: the
  host that touches hardware is deliberately not configured to commit, and the
  machine with the git identity and signing key does the committing. Configuring
  an identity on the always-on host would quietly grant an unaudited agent path
  the ability to write history.
