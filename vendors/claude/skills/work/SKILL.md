---
name: work
description: Route a task to one of six fixed playbooks (investigation, bug-fix, feature, refactor, land, pickup), copy the playbook steps into the todo list verbatim, then run them with Direction stated at step 0, the resident rules as the Contracts, and the playbook's verify step as the Bar. Invoke via /work <task>, or when the user says "work this", "run the playbook", or starts a task that matches a playbook. Do NOT use for a casual question, a one-line edit, or a task the user has already specified step by step; the playbook is overhead there.
---

# Work: one router, six playbooks

<!-- Published version: this is a reusable pattern, not a working install.
     Three things differ from the source skill.
     1. The source skill names its operator; this copy says "the user".
     2. The Contracts are the operator's own rule files under `~/.claude/rules/`.
        A playbook cites one by its bare file name, in parentheses. Two of those
        rules are published in this repo: `parallel-sessions`
        ([conventions/parallel-sessions.md](../../../../conventions/parallel-sessions.md))
        and `branch-hygiene`
        ([conventions/branch-hygiene.md](../../../../conventions/branch-hygiene.md)).
        The rest live in the operator's private rules directory. Supply your own
        rule set; the playbooks do not restate one.
     3. The playbooks call `/scope`, `/gates` and `/ship`, which this repo does not
        publish. `/handoff` and `/descope-sweep` are published as sibling skills.
        Substitute your own procedure for the three that are absent. -->

This skill replaces `/dcb` (retired 2026-09-03). The DCB framework stays. Direction,
Contracts, and Bar now have a fixed slot in every playbook, so no separate pre-flight
runs. The router and the verbatim-copy rule come from pstack's `poteto-mode`
(cursor/plugins, MIT, Lauren Tan); the playbooks are our own.

## The three fixed slots

Every playbook has the same three slots. They do not move.

- **Step 0 is Direction.** Restate the scope in one sentence and say what "done"
  means. Assume and state; do not ask. Ask only when two readings of the task would
  produce materially different work. The user ruled "assume and state" on 2026-09-03.
- **The Contracts are the resident rules.** The files under `~/.claude/rules/` bind
  every playbook. No playbook restates a rule. A playbook step names a rule only
  when that step is where the rule bites.
- **The Bar is the playbook's verify step.** It is specific to the task type. "Tests
  pass" is not a bar. A gate that did not run is not green.

## Procedure

1. **Match the task to a playbook.** Use the table below. When two match, take the
   narrower one. When none matches, say so and work without a playbook; do not
   invent one mid-task.
2. **Open the playbook file and copy its steps into the todo list verbatim.** Do this
   before any task-specific todo and before you reason about the task. A bespoke
   plan that drops a named step is the failure this rule exists to stop.
3. **Run the steps in order.** A step you decide to not do stays in the list as
   `skip: <reason>`. Never drop a step silently (working-style, plan-step
   accounting).
4. **End with the playbook's reply.** Each playbook names what its reply carries.
   The reply is the record the user reads instead of the transcript.

## Routing table

| Task shape | Playbook |
|---|---|
| A question with a cited answer and no build. "How does X work", "why was Y built this way", "is Z still true". | `playbooks/investigation.md` |
| A reported defect to reproduce, root-cause, and fix with runtime evidence. | `playbooks/bug-fix.md` |
| New behavior that ends in a PR. | `playbooks/feature.md` |
| A change that keeps behavior and reduces code, layers, or duplication. Includes a cross-repo sweep. | `playbooks/refactor.md` |
| A PR exists and the ask is to get it merged. "Check on PR X", "get it green", "land it". | `playbooks/land.md` |
| Resume work from a handoff, a PARITY entry, or a prior session. | `playbooks/pickup.md` |

## What a playbook is not

A playbook names steps and gates. It never describes an implementation, a tool
version, or a file layout. That keeps it from going stale (documentation-rules:
record the decision, not the current behavior). When a step needs a procedure that
another skill owns (`/scope`, `/gates`, `/ship`, `/handoff`, `/descope-sweep`), the
playbook calls that skill and does not restate it.
