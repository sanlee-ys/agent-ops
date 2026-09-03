# Pi lane

Pi is the open-source overflow harness. The target model family is Kimi.
Use Kimi K3 when access lands. The routing contract is ADR-014.

The fleet-wide contract — division of labor, redlines, the cross-agent
channel, the escalation packet, and the command shapes every vendor
follows — is canonical at `vendors/shared/AGENTS.md` in the agent-ops repo.
This file states only what is true of the Pi lane specifically, so it never
duplicates text that could drift out of sync with the canonical block.

San declined the interim xAI ride on 2026-08-16. This seat is parked until Kimi.
Do not run `/login xai`.
Do not put Claude, GPT, or Grok behind Pi.

Grok Build is not a routing lane.

You are not the control plane. You are not the GPT review lane.
You are not the IDE lane.

A transfer in must carry inspectable state: a frozen brief, a file
boundary, a pushed branch or PR, a revision, and verification. Never ask
San to paste between tools.

Pi's YAML parser rejects an unquoted skill `description` that contains a colon and a space.
Canonical skills already use `>-` block scalars.
