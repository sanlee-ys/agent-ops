# Skills

Claude Code custom skills are `SKILL.md` files under `~/.claude/skills/<name>/`. Each
one is a markdown file with a YAML frontmatter block (`name`, `description`) followed
by instructions Claude follows when the skill runs. Claude Code surfaces them as slash
commands (`/<name>`) and also matches the `description` against conversational
triggers, so a skill can fire from a typed command or from the shape of what the user
says. The five below are published here as reusable patterns, not as a working
install — a couple reference a private notes file by a genericized placeholder path;
see each `SKILL.md` for the note on that.

| Skill | Purpose |
|---|---|
| [`dcb`](dcb/SKILL.md) | Scaffold ambiguous or consequential work into Direction / Contracts / Bar before starting, so the three get set explicitly instead of assumed. |
| [`descope-sweep`](descope-sweep/SKILL.md) | Sweep every repo for stale references to something cut, renamed, ported, or scrapped — including the long tail (ADRs, config templates, KB stubs, doc sources, metric tables), not just the obvious README. |
| [`park`](park/SKILL.md) | Append a stray, not-yet-ready idea to a private parking-lot file in a fixed entry format, so it's captured without derailing current work. |
| [`proglog`](proglog/SKILL.md) | Append a dated, first-person pairing-journal entry (concepts relearned, what got built) and check at session start for a missed entry from last time. |
| [`handoff`](handoff/SKILL.md) | Write a paste-ready, live-state-verified brief so another Claude Code window or a future session can resume work without reading this session's transcript. |

## What makes these worth publishing as patterns

- **`dcb`** scaffolds a framework the user already operates by outside of Claude
  (Direction / Contracts / Bar — described further in this repo's
  `operating-model.md`): the skill's job is to force those three decisions into the
  open *before* work starts, not to invent them. It also has an explicit off-switch —
  it names the bounded-task case where invoking it would be overhead, not help.

- **`descope-sweep`** exists because cutting, renaming, or porting something never
  stays contained to the file where the decision was made. Real audits kept finding
  survivors in ADRs, config templates, generated-doc sources, and numbered ranges
  months after the "obvious" surface was fixed. The skill encodes the long-tail
  checklist as the point of running it, not an afterthought, and treats a partial
  sweep as equivalent to no sweep.

- **`park`** and **`proglog`** are both append-to-a-known-file skills with a fixed,
  pattern-matched entry format — the reusable idea is low-ceremony capture with a
  human confirmation step before anything is written, so a private journal or idea
  list stays in the owner's actual voice instead of becoming a Claude-authored
  summary of them.

- **`handoff`** bookends a session: it is explicitly a post-flight snapshot (state
  captured after work happened) as opposed to `dcb`'s pre-flight scaffold (decisions
  set before work starts). Its core discipline is refusing to write from memory of
  the conversation — it re-derives git state, PRs, and commits from the real repo
  each time, on the premise that a handoff which misstates the branch is worse than
  no handoff at all.
