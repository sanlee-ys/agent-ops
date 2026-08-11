# Pi lane

Pi ([earendil-works/pi](https://github.com/earendil-works/pi)) is the fleet's
open-source overflow harness. It was admitted 2026-08-11. The seat runs on the
xAI subscription (`/login xai` → "Use a subscription", model `grok-4.5`), so it
adds capacity from a pool no other lane drains, and it keeps model-family
independence real.

## Why this backend

- The xAI subscription ride is a documented, first-party Pi login flow.
- An Anthropic Pro/Max ride from a third-party client is not supported by
  Anthropic. Do not configure it. The Claude pool is served by Claude Code.
- A Pi-on-Claude seat would duplicate the Claude lane with worse tools. The
  Cline evaluation showed this failure shape: same model, same limits, new
  chrome.

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

## Verification record

Measured 2026-08-11 on the Windows PC, Pi v0.84.1:

- Probe: `pi --print` with a brief-shaped prompt that starts with `---`
  returned the expected single-word reply. The leading-`---` argv failure
  that hit the Grok CLI seat does not occur here.
- Deny: a `git branch -D <nonexistent>` request through Pi returned the
  guard's block message. The tool call did not execute.
- The deny is verified for `bash`-tool commands and path arguments. Other
  tools pass through unless their input matches the path patterns. Treat the
  guard as a floor, not a policy engine.

## Known limits

- The guard is regex-based. It does not resolve indirection (a script that
  contains a redline command passes the hook and fails only if the inner
  command is itself spawned through a guarded tool).
- Skill frontmatter: Pi's YAML parser rejects an unquoted `description:`
  value that contains a colon and a space. Use a `>-` block scalar in every
  SKILL.md description. The canonical skills in `vendors/claude/skills/`
  follow this form.
- Subscription rides from third-party harnesses are upstream-hostile
  territory in general. If xAI withdraws the ride, the lane falls back to a
  metered key decision, which goes through the normal fleet-routing process.
