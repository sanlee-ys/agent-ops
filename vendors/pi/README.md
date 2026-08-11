# Pi lane

Pi ([earendil-works/pi](https://github.com/earendil-works/pi)) is the fleet's
open-source overflow harness. Admitted 2026-08-11. Routing contract:
[`ADR-014`](../../decisions/ADR-014-pi-harness-kimi-model-target.md).

| Axis | This seat |
|---|---|
| Harness | Pi (thin core, extension-first) |
| Role | Overflow capacity; custom tools/UI via extensions |
| **Target model family** | **Kimi (Moonshot / Kimi For Coding), default Kimi K3 when access lands** |
| Interim backend | xAI subscription `grok-4.5` — capacity only, **not** independence from Grok |
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

**Interim (now):** xAI subscription — `/login xai` → "Use a subscription",
model `grok-4.5`. Keeps the seat usable while Kimi K3 access is waitlisted.
While interim Grok is configured:

- Do **not** bill work here as "non-Grok second opinion."
- Do **not** treat this as admitting Grok Build as a routing lane
  ([`vendors/grok/`](../grok/) stays guard-only).
- Prefer other lanes when model-family independence is the reason for the
  handoff (Codex for GPT, Antigravity for Gemini, Claude for Anthropic).

**Never:** Anthropic Pro/Max (or any Claude pool) behind Pi. Unsupported as a
third-party client ride, and it would duplicate Claude Code with a worse tool
surface. The Cline evaluation was that failure shape.

### Cutover when Kimi access lands

```text
1. pi  →  /login  →  Kimi For Coding (subscription) or API key path
2. Set defaults in ~/.pi/agent/settings.json:
     defaultProvider: kimi-coding   # or the provider id Pi shows at login
     defaultModel:    <kimi-k3 id Pi lists>
3. Re-copy fleet-guard if needed; confirm it loads on startup
4. Verify:
     pi -p --no-session "Reply with exactly: PI_PROBE_OK"
     pi -p --no-session "Run exactly: git branch -D no-such-branch-guard-test"
5. Update the verification record below; interim Grok language drops out
```

## Guard wiring (ADR-012)

Pi has no built-in permission system. The core runs with full user
permissions. The guard for this lane is
[`extensions/fleet-guard.ts`](extensions/fleet-guard.ts), a Pi extension on
the `tool_call` hook. The hook fires before tool execution and returns
`{ block: true }` on a redline match.

The extension blocks the three fleet redlines:

1. Credential and secret-store paths (`.ssh`, `.aws/credentials`, `.gnupg`,
   `.netrc`, and similar).
2. Published-history destruction (`git reset` in every form, force-push,
   `branch -D`, `git clean -f`, `filter-branch`/`filter-repo`).
3. Broad destructive mutations (`rm -rf`, `Remove-Item -Recurse -Force`,
   `rmdir /s`, `format`).

## Deploy

Copy the extension to Pi's global extensions directory:

```bash
cp vendors/pi/extensions/fleet-guard.ts ~/.pi/agent/extensions/fleet-guard.ts
```

Windows uses a file copy, not a symlink, per the same convention as the Claude
guards. A copy can go stale against this canonical file. Re-run the copy after
each edit here, and check the deployed copy before you trust it.

The Pi startup screen lists loaded extensions. Confirm `fleet-guard.ts`
appears under `[Extensions]` before you route work to the lane.

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
- The deny is verified for `bash`-tool commands and path arguments. Other
  tools pass through unless their input matches the path patterns. Treat the
  guard as a floor, not a policy engine.

Kimi-backend verification: **not yet** (waitlist). Run the cutover checklist
when access lands.

## Known limits

- The guard is regex-based. It does not resolve indirection (a script that
  contains a redline command passes the hook and fails only if the inner
  command is itself spawned through a guarded tool).
- Skill frontmatter: Pi's YAML parser rejects an unquoted `description:`
  value that contains a colon and a space. Use a `>-` block scalar in every
  SKILL.md description. The canonical skills in `vendors/claude/skills/`
  follow this form.
- Interim Grok rides a third-party subscription path. If xAI withdraws it
  before Kimi cutover, park the seat rather than silently moving Pi onto
  Claude or onto Grok Build.
