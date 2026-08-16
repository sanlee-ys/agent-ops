# Deploy notes

Do not copy skill bodies. `fleet-resources.ts` points Pi at
`vendors/claude/skills`.

## Standing instructions

Copy `vendors/pi/instructions/AGENTS.md` to `~/.pi/agent/AGENTS.md`.
On Windows, use a file copy. Do not use a symlink.

```text
cp vendors/pi/instructions/AGENTS.md ~/.pi/agent/AGENTS.md
```

Then start Pi and confirm the session context includes this file:

```text
pi
```

## Resource extension

Copy `vendors/pi/extensions/fleet-resources.ts` to
`~/.pi/agent/extensions/fleet-resources.ts`.
On Windows, use a file copy. Do not use a symlink.

```text
cp vendors/pi/extensions/fleet-resources.ts ~/.pi/agent/extensions/fleet-resources.ts
```

Then start Pi and confirm the start screen lists `fleet-resources.ts`
under `[Extensions]`:

```text
pi
```

A Windows copy cannot walk up into the repo.
Set `AGENT_OPS_ROOT` to the agent-ops checkout, then start Pi so the
extension can resolve `vendors/claude/skills`:

```text
$env:AGENT_OPS_ROOT = "<path to the agent-ops clone>"
pi
```

## Re-copy after edits

A Windows copy can go stale against the file in this repo.
After you edit a source file, copy it again. Then start Pi and confirm
the new text.

```text
cp vendors/pi/instructions/AGENTS.md ~/.pi/agent/AGENTS.md
cp vendors/pi/extensions/fleet-resources.ts ~/.pi/agent/extensions/fleet-resources.ts
pi
```
