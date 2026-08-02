---
name: descope-sweep
description: Sweep every one of the user's repos for stale references to something that was cut, renamed, ported, or scrapped (a dropped dependency, a superseded metric, a language/framework port, a rejected experiment, a renamed contract) — covering not just the obvious docs but the long tail (ADRs, .env.example, KB stubs an agent might index and speak, the sources of generated docs, stale metric cells, SYS-NNN/ADR-NNN ranges). Invoke via /descope-sweep <old-term> <what-it-changed-to>, or when the user mentions something was cut/replaced/ported and wants references cleaned up. Do NOT use for a single-file rename inside one PR — just fix that inline. This is for changes that cross, or could plausibly cross, repo boundaries.
---

# De-scope sweep

Codified as an architecture decision record (documentation-cascade). The pattern that keeps
recurring: a de-scope correction lands cleanly on the primary surface (a top README, a repo
description) and quietly survives everywhere else — ADRs, `.env.example`, KB stubs that get
indexed and spoken by an agent, the source files that generate docs (portal source,
docs-site bodies, diagram data), stale metric cells, and numbered ranges that don't
grow. A full cross-repo audit found exactly this months after a dependency cut and a
language port. The fix is a sweep that treats the long tail as the point, not
an afterthought.

## How to run it

1. **Confirm the reconciliation target, not just the old term.** Get both sides from the
   user if they aren't already obvious: what's being searched for (e.g. "Kafka"), and what
   the *current truth* is to reconcile each hit against (e.g. "dropped, replaced by an
   in-process background task"). Don't guess the architecture decision.

2. **Sync before you grep.** Local clones can be stale — `git fetch`/`git pull` every repo
   before trusting what's on disk. For a repo with no local clone, search the remote
   directly rather than skipping it.

3. **Cast wide.** Grep every repo, but deliberately check these categories, not just
   READMEs — this is where past sweeps missed:
   - Top-level docs (README, CLAUDE.md)
   - ADRs / decision records (each repo's `decisions/`, the architecture repo's numbered
     decision docs)
   - `.env.example` and config templates
   - KB stubs — anything an agent indexes and might speak as current fact
   - **Sources** of generated docs — portal source pages, docs-site bodies, diagram/data
     files — not just the rendered output
   - Metric cells / comparison tables (v1 vs v2 numbers, before/after)
   - Numbered ranges that enumerate things (decision-record IDs) that may need a new entry
     or a relabel

   If this spans more than 2-3 repos, fan out one read-only search per repo (an Explore
   agent each, in parallel) rather than working through them serially. If a code-graph tool
   has the term indexed as a node, a quick graph query/neighbor check can surface non-obvious
   structural references a text grep would miss — worth a look, not a substitute for the grep.

4. **Checkpoint before editing.** Show the user the full list of hits, grouped by repo and
   surface, before touching anything. This is where genuine judgment calls surface (labeled
   history vs. needs updating vs. leave alone) — don't silently resolve them yourself.

5. **Reconcile each hit** one of two ways: update it to current truth, or explicitly label
   it as history (a clearly-marked "v1" / "earlier approach" mention is fine and often worth
   keeping — it shows evolution. An unlabeled present-tense claim is not.)

6. **No partial sweeps.** Don't stop after the obvious surface. A fixed banner sitting over
   a still-stale ADR reads as "done" while the substance keeps rotting — that's the exact
   failure mode this skill exists to prevent. Work through every category from step 3 before
   calling it finished.

7. **One branch/PR per repo touched**, per the standing pre-flight rule. Each PR description
   names the surfaces it swept — including categories checked and found already-clean, so
   "checked, nothing there" reads as distinct from "not checked."

## Not a substitute for

The periodic full cross-repo consistency audit (one read-only agent per public repo:
docs-vs-code, claimed-facts extraction, staleness, secrets) is the backstop that catches
whatever a targeted sweep misses. Run this skill right after a specific de-scope event; rely
on the periodic audit to catch anything that still slips through.
