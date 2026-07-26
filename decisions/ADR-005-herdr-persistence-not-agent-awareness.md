# ADR-005: Herdr is adopted for persistence, not for agent awareness

**Status:** Accepted — 2026-07-26. Records the outcome of a scoped trial of
Herdr 0.7.5 as a persistent agent workspace.
**Scope:** This repo (the Claude operating layer). The trial ran inside the
public `netops-lab` repo, but the decision is about how long agent sessions are
run generally, not about that lab.
**Related:** [`ADR-004-ref-explicit-git-in-shared-clones.md`](ADR-004-ref-explicit-git-in-shared-clones.md)
— a sibling case of automation that does exactly what it was written to do, on
the wrong object.

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

## What the trial found broken

1. **`done` is inverted.** The state whose entire purpose is "this finished
   while you were away" appeared only while attached, was cleared at the instant
   of detach, and never appeared at all across a detached run. The one signal
   worth having when absent is the one that requires presence.
2. **`agent prompt` fails silently and logs success.** On Claude Code 2.1.220 it
   delivers keystrokes without submitting them, and the server records
   `outcome="ok"`. A caller that checks the return value learns nothing.
3. **Detection is entirely screen-scrape.** The winning rule regexes a braille
   spinner out of the terminal title; others grep literal interface strings such
   as `esc to interrupt`. It is coupled to the agent's cosmetics, so a UI change
   degrades it silently.
4. **The detection manifest is fetched unpinned at server start**, over the
   network, unverified. Milder than executable code — it is TOML regexes — but
   inconsistent with the care taken elsewhere in the same install.
5. **The integration hook contributes no status.** It only reports a
   pane-to-session mapping. The hook being installed and current says nothing
   about whether detection ever ran.
6. **The input path that works is not audited.** Only `agent.prompt` appears in
   the server log. The `pane.send-keys` / `pane.send-text` calls that actually
   succeed leave no trace at all.

Findings 2 and 6 compose into the sharp edge: the call that lies is logged, and
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
- **Status is not authoritative when unattended.** `working` and `idle` are
  usable; `done` is not, and must not be the signal a person or script waits on.
- **No standing permission to drive agent sessions from outside.** Granting it
  would create an unauditable write path into a session that can modify a repo.

Revisit when `agent prompt` submits correctly and `done` survives detach. Both
look like defects rather than architecture in a fast-moving 0.7.5, and both were
reported upstream.

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
that survives detach. Finding 5 means this does not conflict with Herdr's hook,
which is not doing that job.

**(e) Adopt persistence only. — CHOSEN.** Takes the part that is proven, depends
on nothing that was found broken, and costs nothing to reverse.

## The rule

> **An interface that reports success for work it did not complete is worse than
> one that errors, and audit coverage that is strongest on the path that fails
> is not an audit trail. Before depending on a status signal, test it under the
> condition it exists for — which is usually the condition where nobody is
> watching.**

Two things generalise beyond this tool.

**Test the signal under absence.** Every failure here was invisible while
attached. `done` looked correct, and `agent prompt` looked correct, precisely
because a person was present to see the outcome directly. A signal that exists
for unattended use has to be tested unattended, or the test confirms only that
it works when it is not needed. This is the same shape as a green check that
means the job ran rather than that the work happened.

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
and current was read as evidence that detection had run, which finding 5 shows
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
