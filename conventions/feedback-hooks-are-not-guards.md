# Feedback hooks are not guards (hard rule)

The hook layer has two tiers, and they must not mix. A **gate** stands in
front of an irreversible action and refuses it. A **feedback** hook stands
behind a reversible action and comments on it. The two look identical in
`settings.json` — a script wired to an event — and they are opposite kinds of
control: one is security code, the other is quality tooling. Treating them as
one category is how a lint reminder ends up in a security inventory, or worse,
how a redline guard picks up a fail-open habit from the tier next to it.

This is an agent-ops-local convention — no consumer repo mirrors it, so there
is no shared block to propagate.

## The two tiers

**Gates** are the `PreToolUse` redline guards: `credential-guard.py`,
`git-staging-guard.py`, `published-history-guard.py`, `config-change-guard.py`.
They protect actions that cannot be taken back — a credential in a commit, a
force-push over published history, a config change nobody approved. Per
[ADR-013](../decisions/ADR-013-guard-canonicality-line.md) they are canonical
**here**, in the public repo, with adversarial tests, and the sync script's
registry `--check` fails if a wired guard has no canonical home. A gate
**fails closed**: if the script is missing or errors, the action does not
proceed. That is not a bug to soften — a missing gate that waves things
through is a control that has silently stopped controlling.

**Feedback hooks** are everything else: `PostToolUse` format-and-lint passes,
generated-file "you edited the output, not the source" reminders,
`SessionStart` context injection. They protect quality outcomes that are
reversible — a misformatted file is fixed by the next formatter run; a missed
reminder costs one round of rework. Per the same ADR-013 line they are
canonical in the **private machine-config repo**, like `fanout-guard.py`: they
encode local preference and cost control, not fleet redlines. A feedback hook
**fails open by design**: if it is missing or errors, work proceeds and
nothing irreversible happened. Failing closed here would let a broken linter
wedge every session — a availability cost with no safety purchased.

The dividing question is not "how important is this hook" — it is **"what
happens if the action goes through and the hook was wrong or absent?"** If the
answer is "we clean it up," it is feedback. If the answer is "we cannot," it
is a gate.

## Consequences

- **A feedback hook never earns a place in the guard registry.** The registry
  in `sync-claude-hooks` is a security inventory: its `--check` is the claim
  that every wired redline has a tested canonical source. Adding a formatter
  to it dilutes that claim to "every wired *script* has *some* home," which is
  a different and much weaker statement. Keep the registry a security
  inventory, not a grab bag.
- **A guard never fails open.** No `try/except: allow`, no "skip if the
  helper is missing," no environment flag that downgrades a refusal to a
  warning. The failure mode of a gate is a blocked action and a loud message;
  anything softer is a posture change, and posture changes are ADRs.
- **Promoting a hook across the line is an ADR-013 decision, not a wiring
  change.** Moving a script from the private repo into `hooks/` here (or
  back) changes who canonically owns it, what tests it must carry, what its
  failure mode must be, and what the registry vouches for. That is exactly
  the question ADR-013 exists to settle — amend it or write the successor;
  do not just move the file and update a path.

## The check

For any hook you are about to wire, answer one question in the commit
message: **which tier, and why.** If the action it watches is irreversible,
it is a gate — canonical here, adversarially tested, registered, fail-closed.
If not, it is feedback — canonical in machine-config, fail-open, and kept
out of the registry. A hook you cannot place is a hook you do not understand
well enough to deploy.
