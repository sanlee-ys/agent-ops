# ADR citations: anchors, not line numbers (hard rule)

An ADR, a rule file, or a memory often cites a companion file. Many of these
citations name a line number, for example `decisions/README.md:44-45`. A line
number is not stable. An edit anywhere above the cited line shifts it, even
an edit that never touches the cited content. Nothing catches the drift. The
ADR-007 split found ADR provenance notes that pointed at lines that had
already moved.

This is an agent-ops-local convention. The problem spans every repo in the
fleet, but the fleet has no shared-block mechanism for a rule of this shape,
so there is no marker block here to propagate. Apply the rule directly in
each repo.

## The decision

Cite a heading or an explicit anchor. Do not cite a line number. An anchor
drifts only when the heading text itself changes. A line number drifts on
every edit above it, related or not.

When no heading sits near the target, for example inside a list or a table
row, add an explicit anchor (next section) and cite that. A short quoted
phrase from the text is an acceptable fallback when an anchor is not
practical, for example inside a file this convention does not own.

## The citation shape

Use `file.md#heading-slug` for a citation to a specific section.

- GitHub-flavored markdown builds the slug from the heading text: lowercase,
  spaces become hyphens, punctuation drops out, and a repeated heading gets a
  numeric suffix. This is the platform's own rendering behavior, not a rule
  this repo enforces. Check the rendered page when in doubt (verified
  2026-09-20).
- A citation to a whole short file, or to a file's single top heading, needs
  no anchor. Link the file.
- A heading whose wording may still change is not a safe target on its own,
  because the slug changes with it. Add a stable anchor instead, and cite
  that.

### A stable anchor when a heading may change

GitHub markdown does not support a custom ID inside the heading line itself.
Add an explicit anchor immediately above the target, or inside the same list
item, instead:

```
<a id="stable-slug"></a>
```

Then cite `file.md#stable-slug`. The anchor holds even when the heading text,
or the wording of the list item, changes later. Name the slug for the rule it
marks, not for its position (`verify-before-sending`, not `rule-2`), so a
reorder does not break it either.

## Worked example: `conventions/links-verify.md`

The sweep this convention names
(`grep -rn ":[0-9]\+-[0-9]\+\|:L[0-9]\+" decisions conventions`) found no
line-number citation inside agent-ops itself. The drift this convention
fixes was found in kb-agent and classifier, both outside this repo. So the
worked example below adds the mechanism to a real file here, standing in for
a retrofit this repo did not need.

`conventions/links-verify.md` states three rules in one numbered list, with
no heading at rule level. This page adds a stable anchor to each rule in that
file:

```
1. <a id="full-urls-only"></a>**Full URLs only.** ...
2. <a id="verify-before-sending"></a>**Verify before sending.** ...
3. <a id="branch-links-are-perishable"></a>**Branch links are perishable.** ...
```

A citation to rule 2 now reads `conventions/links-verify.md#verify-before-sending`,
in place of a line number such as `conventions/links-verify.md:15`, which was
only ever accurate until the next edit above it.

## Scope

This convention applies prospectively. Retrofitting an ADR that already cites
a line number is optional; that citation was correct on the date it was
written. A repo-wide sweep for existing line-number citations is a later
concern. This page does not attempt one.

## The check

Before adding a citation to a companion file, look for a heading near the
target. If one exists and its wording is settled, cite
`file.md#heading-slug`. If the wording may still change, or the target has no
heading at all, add a stable `<a id="...">` anchor and cite that. Never cite
a line number.
