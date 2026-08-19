# Pi lane

Pi ([earendil-works/pi](https://github.com/earendil-works/pi)) is the fleet's
open-source overflow harness. Admitted 2026-08-11. Routing contract:
[`ADR-014`](../../decisions/ADR-014-pi-harness-kimi-model-target.md).

| Axis | This seat |
|---|---|
| Harness | Pi (thin core, extension-first) |
| Role | Overflow capacity; custom tools/UI via extensions |
| **Target model family** | **Kimi (Moonshot / Kimi For Coding), default Kimi K3 when access lands** |
| Interim backend | **None.** San declined the xAI ride on 2026-08-16. Seat is parked until Kimi. |
| Not for | Control-plane work, GPT-family review, IDE edit-test, Claude pool rides |

## Why this harness

- Open-source, scriptable, and built to grow through TypeScript extensions
  rather than a fork.
- First-class multi-provider support, including Kimi For Coding subscription
  OAuth and Kimi K3 (deferred tools, thinking levels) in current Pi releases.
- Adds a seat whose *tools and packaging* are not owned by Anthropic, OpenAI,
  Google, or xAI product surfaces.

## Model backend

**Target (ADR-014):** Kimi K3 via Kimi For Coding (or the then-current Kimi
coding default). That is what makes the Pi seat a real additional model
family, not a second chrome on Grok or Claude.

**Interim (now):** none. San declined the xAI `grok-4.5` ride on
2026-08-16. Do not `/login xai` on this seat to keep it warm. Do not put
Claude or GPT behind Pi. The harness and the fleet-guard stay installed.
Route no work here until Kimi cutover.

Grok Build stays guard-only ([`vendors/grok/`](../grok/)). Prefer other
lanes when a model is required (Codex for GPT, Antigravity for Gemini,
Claude for Anthropic).

**Never:** Anthropic Pro/Max (or any Claude pool) behind Pi. Unsupported as a
third-party client ride, and it would duplicate Claude Code with a worse tool
surface. The Cline evaluation was that failure shape.

### Cutover when Kimi access lands

```text
1. pi  →  /login  →  Kimi For Coding (subscription) or API key path
2. Set defaults in ~/.pi/agent/settings.json:
     defaultProvider: kimi-coding   # or the provider id Pi shows at login
     defaultModel:    <kimi-k3 id Pi lists>
3. Set AGENT_OPS_ROOT to the agent-ops checkout
4. Re-copy fleet-guard.ts, fleet-resources.ts, and instructions/AGENTS.md
5. Run: python vendors/pi/scripts/check-park.py
6. Verify:
     pi -p --no-session "Reply with exactly: PI_PROBE_OK"
     pi -p --no-session "Run exactly: git branch -D no-such-branch-guard-test"
7. Update the verification record below
```

## Guard wiring (ADR-012)

Pi has no built-in permission system. The core runs with full user
permissions.

[`extensions/fleet-guard.ts`](extensions/fleet-guard.ts) is a thin
`tool_call` wrapper. It holds no redline patterns. It runs
[`hooks/pi-guard-adapter.py`](hooks/pi-guard-adapter.py). That adapter
translates the Pi event into the Claude Code payload and runs the
canonical guards unmodified:

- `security/credential-guard.py`
- `hooks/git-staging-guard.py`
- `hooks/published-history-guard.py`

A pass returns nothing. A deny returns `{ block: true, reason }`. Missing
Python, a missing checkout, a missing adapter, a crash, or a timeout is
a deny. A check that did not run is not a pass.

`!command` and `!!command` fire Pi's `user_bash` event, not `tool_call`.
The same wrapper sends those as a bash call. A deny returns a finished
command result with exit 2 and does not run the shell line.

Set `AGENT_OPS_ROOT` to the agent-ops checkout. A Windows copy of the
extension cannot walk up into the repo.

## Instructions and skills

- Standing instructions: [`instructions/AGENTS.md`](instructions/AGENTS.md)
  copies to `~/.pi/agent/AGENTS.md`.
- [`extensions/fleet-resources.ts`](extensions/fleet-resources.ts) returns
  `skillPaths` for `vendors/claude/skills`. Do not copy skill bodies.
- Deploy notes: [`skills/README.md`](skills/README.md).

## Park check

[`scripts/check-park.py`](scripts/check-park.py) fails if settings leave
park (xAI, Claude, or GPT) or if any deployed copy differs from its
canonical file: `fleet-guard.ts`, `fleet-resources.ts`, and
`instructions/AGENTS.md`.

```text
python vendors/pi/scripts/check-park.py
```

Then inspect the PASS or FAIL lines.

## Deploy

Windows uses a file copy, not a symlink. Re-run the copy after each
edit. Then run the park check.

```text
$env:AGENT_OPS_ROOT = "<path to the agent-ops clone>"
cp vendors/pi/extensions/fleet-guard.ts ~/.pi/agent/extensions/fleet-guard.ts
cp vendors/pi/extensions/fleet-resources.ts ~/.pi/agent/extensions/fleet-resources.ts
cp vendors/pi/instructions/AGENTS.md ~/.pi/agent/AGENTS.md
python vendors/pi/scripts/check-park.py
```

The Pi start screen lists loaded extensions. Confirm `fleet-guard.ts`
and `fleet-resources.ts` appear under `[Extensions]` before you route
work to the lane.

```text
pi
```

## Channel

```bash
pi                            # interactive
pi -p --no-session "<prompt>" # one-shot print mode
pi -c                         # continue previous session in this cwd
```

Transfers in still follow the fleet rule: frozen brief, file boundary, pushed
branch or PR, revision, verification — never San as clipboard. There is no
`pi exec` equivalent required for admission; print mode is enough for
headless probes.

## Verification record

Measured 2026-08-11 on the Windows PC, Pi v0.84.1 (interim xAI backend):

- Probe: `pi --print` with a brief-shaped prompt that starts with `---`
  returned the expected single-word reply. The leading-`---` argv failure
  that hit the Grok CLI seat does not occur here.
- Probe (recheck): `pi -p --no-session` returned `PI_PROBE_OK`.
- Deny: a `git branch -D <nonexistent>` request through Pi returned the
  guard's block message. The tool call did not execute.
- False positive fixed 2026-08-11: the force-delete pattern used `/i`, so
  `git branch -d` (merged-only) matched `-D` and blocked ordinary cleanup.
  Pattern is now case-sensitive on `-D` and also matches `--delete --force`.
- The deny is verified for `bash`-tool commands and path arguments. Other
  tools pass through unless their input matches the path patterns. Treat the
  guard as a floor, not a policy engine.

Adapter unit tests (2026-08-16): `tests/test_pi_guard_adapter.py` and
`tests/test_pi_park.py` pass under `python -m unittest`. No live `pi -p`
run. Kimi-backend verification is still **not yet** (waitlist). Run the
cutover checklist when access lands.

## Known limits

- The adapter inherits the canonical guards' documented out-of-scope
  classes. A script that wraps a redline command still passes unless
  the inner command is itself spawned through a guarded tool.
- A deployed copy of the TypeScript wrapper can go stale. Run
  `check-park.py` after each edit. Set `AGENT_OPS_ROOT` or the wrapper
  cannot find the checkout and will deny every tool call.
- Skill frontmatter: Pi's YAML parser rejects an unquoted `description:`
  value that contains a colon and a space. Use a `>-` block scalar in every
  SKILL.md description. Of the five canonical skills in
  `vendors/claude/skills/`, two follow this form (`handoff`, `proglog`);
  the other three (`dcb`, `descope-sweep`, `park`) use plain scalars whose
  text contains no colon-and-space today, so they parse — but they are one
  edit away from the failure.
- The xAI subscription path is not in use. If a later session finds
  `defaultProvider: xai` again, that is a contract break, not a restore
  path. Park the seat rather than moving Pi onto Claude or Grok Build.
