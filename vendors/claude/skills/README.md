# Skills

Claude Code custom skills are `SKILL.md` files under `~/.claude/skills/<name>/`. Each
one is a markdown file with a YAML frontmatter block (`name`, `description`) followed
by instructions Claude follows when the skill runs. Claude Code surfaces them as slash
commands (`/<name>`) and also matches the `description` against conversational
triggers, so a skill can fire from a typed command or from the shape of what the user
says. A skill may also carry supporting files beside its `SKILL.md`; `work` keeps its
six playbooks in a `playbooks/` subdirectory and reads one per task. The five below are
published here as reusable patterns, not as a working install — some reference a private
notes file, a private rule set, or a sibling skill this repo does not publish, each by a
genericized placeholder; see each `SKILL.md` for the note on that.

| Skill | Purpose |
|---|---|
| [`work`](work/SKILL.md) | Route a task to one of six fixed playbooks (investigation, bug-fix, feature, refactor, land, pickup), copy that playbook's steps into the todo list **verbatim**, then run them. Direction, Contracts and Bar get a fixed slot in every playbook: step 0 states the scope, the resident rules are the contracts, and the playbook's own verify step is the bar. A step the session declines stays in the list as `skip: <reason>`. |
| [`descope-sweep`](descope-sweep/SKILL.md) | Sweep every repo for stale references to something cut, renamed, ported, or scrapped — including the long tail (ADRs, config templates, KB stubs, doc sources, metric tables), not just the obvious README. |
| [`park`](park/SKILL.md) | Append a stray, not-yet-ready idea to a private parking-lot file in a fixed entry format, so it's captured without derailing current work. |
| [`proglog`](proglog/SKILL.md) | Append a dated, first-person pairing-journal entry (concepts relearned, what got built) and check at session start for a missed entry from last time. |
| [`handoff`](handoff/SKILL.md) | Write a paste-ready, live-state-verified brief so another Claude Code window or a future session can resume work without reading this session's transcript. |

## What makes these worth publishing as patterns

- **`work`** replaces an earlier `dcb` skill that ran Direction / Contracts / Bar as a
  separate pre-flight (the framework itself is described in this repo's
  `operating-model.md`). A pre-flight the session may judge unnecessary gets skipped on
  exactly the tasks that needed it, so the three now occupy fixed slots inside each
  playbook instead of a step in front of them. The reusable ideas are the **verbatim
  copy** of the playbook steps into the todo list before any task-specific reasoning —
  a bespoke plan silently drops the step it finds inconvenient — and the **visible
  skip**, which turns a dropped step into a reviewable record. The router and both of
  those rules come from `poteto-mode` in
  [cursor/plugins](https://github.com/cursor/plugins) (MIT, Lauren Tan); the six
  playbooks are our own. It also has an explicit off-switch — it names the casual or
  already-specified task where the playbook is overhead, not help.

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

- **`handoff`** bookends a session: it is explicitly a post-flight snapshot, state
  captured after work happened, and `work`'s `pickup` playbook is what consumes it.
  Its core discipline is refusing to write from memory of
  the conversation — it re-derives git state, PRs, and commits from the real repo
  each time, on the premise that a handoff which misstates the branch is worse than
  no handoff at all.
