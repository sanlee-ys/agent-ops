# ADR-008: Rename to agent-ops; add a per-vendor adapter layer

**Status:** Accepted — 2026-08-02
**Supersedes:** the *name* in ADR-001 (its scope contract stands unchanged)

## Context

This repo was founded as the operating layer for one agent harness, and was
named for it. The fleet no longer looks like that: a second vendor is in
daily use as design challenger and independent reviewer under a written
division-of-labor contract (2026-08-02), and a third is planned so the
cross-vendor usage HUD can track three quota windows. The founding name was
now wrong in both directions — it under-claimed the repo's scope, and it
implied a per-vendor split ("codex-ops") that was considered and rejected:
the concerns here (credential exposure, staging hygiene, published-history
protection, session protocol, incident discipline) are fleet concerns, and
splitting them per vendor would recreate the hand-mirrored-copy drift
problem this repo exists to kill.

## Decision

1. **Rename the repo to `agent-ops`.** The operated unit is agents, so the
   name says agents. "llm-ops" was rejected because *LLMOps* is an
   established industry term for model deployment/serving pipelines, which
   this repo is not, and borrowing the term would mislead exactly the
   skeptical reader it is written for.
2. **Root stays vendor-neutral canon.** Incidents, decisions, conventions,
   security posture and guards, operating model — none of it names a vendor
   as a structural assumption.
3. **Vendor-specific material moves to `vendors/<name>/`** — skills in a
   harness's native format, instruction-file wiring, inter-agent channel
   notes, quirks. The adapter contract is `vendors/README.md`. Initial
   layout: `claude/` (skills), `codex/` (wiring + channel), `gemini/`
   (reserved landing pad with a definition of done).
4. **Historical records keep the name they were written under.** ADR-001's
   filename, incident texts, and prose inside earlier ADRs are records of
   what was true when written; rewriting them would falsify the record.
   GitHub redirects the old repository URLs, so inbound links keep
   resolving.

## Consequences

- One repo carries the operating layer for every vendor; adding a vendor is
  a directory plus a contract amendment, not a new repository.
- The guards remain implemented against one harness's hook contract while
  enforcing fleet policy — each vendor README must say how the policy is
  wired for that vendor, or that it is not. An unwired vendor is a recorded
  gap, not silence.

## Downstream surfaces (per the de-scope sweep discipline)

- Machine provisioning that fetches guards by raw URL or sibling-clone path.
- The shared-block canonical text in `scripts/sync-shared-blocks.py` and
  every consumer repo's stamped `CLAUDE.md` blocks (restamp, don't
  hand-edit).
- The architecture repo's system index row and portal launchpad for this
  repo (its SYS record keeps its historical filename, same as ADR-001 here).
- Published site pages that link or name this repo.
- The profile-map generator and its committed SVGs.
- Agent memory files and IDE VCS mappings naming the old clone path.
