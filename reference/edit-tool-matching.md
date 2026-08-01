# Reference: the matching algorithm for a file-edit tool

**Shelf note, not a convention.** Nothing here needs doing. This is the spec to
reach for if a custom file-edit tool ever gets built in this fleet — a harness,
an eval rig, a repo-surgery script that takes `{oldText, newText}` pairs from a
model.

Source: [pi](https://github.com/earendil-works/pi) (MIT),
`packages/agent/src/harness/tools/edit-diff.ts`.

## Why this is worth having on a shelf

A string-replacement edit tool looks like `content.replace(old, new)` and is
not. The gap between those two is where a model's edits fail for reasons that
have nothing to do with the model being wrong: it reproduced a line correctly as
*text* and incorrectly as *bytes*, because the file contains a smart quote, an
en dash, a non-breaking space, or trailing whitespace the model's own rendering
of the file dropped.

Every one of those failures costs a retry — a full model turn re-reading the
file and re-emitting the edit. On an eval harness that is a direct, measurable
token cost multiplied by the run count, which is the practical reason to care
about this rather than an aesthetic one. **The design goal is not "match more
generously"; it is "when the edit does fail, fail in a way the model can fix in
one move."**

## The algorithm

### 1. Exact first, always

`fuzzyFindText` tries `content.indexOf(oldText)` and returns immediately on a
hit, flagged `usedFuzzyMatch: false`. Only on a miss does normalization happen
at all. Fuzzy matching is a fallback, never the primary path — so the common
case cannot be perturbed by the tolerance added for the uncommon one.

### 2. The normalization is a specific, closed list

`normalizeForFuzzyMatch` applies, in order:

- `.normalize("NFKC")` — Unicode compatibility composition, first, so
  everything after it works on one canonical form.
- Trailing whitespace stripped **per line** (split on `\n`, `trimEnd`, rejoin).
- Smart single quotes `U+2018 U+2019 U+201A U+201B` → `'`.
- Smart double quotes `U+201C U+201D U+201E U+201F` → `"`.
- Dashes `U+2010`–`U+2015` and `U+2212` (minus) → `-`.
- Spaces `U+00A0` (NBSP), `U+2002`–`U+200A`, `U+202F`, `U+205F`, `U+3000` → `" "`.

That is the whole tolerance. It is *typographic* — it forgives the
transformations a model or a copy-paste applies to text while preserving what a
human reads. It does not forgive indentation changes, case, or reordering,
because those change the meaning of the code. A fuzzy matcher with a similarity
score would forgive them, which is why this is a normalization table and not a
score.

Line endings are handled separately and earlier: `normalizeToLF` before
matching, `detectLineEnding` / `restoreLineEndings` around it, and `stripBom`
splits off a leading `U+FEFF` so it can be re-attached. The file's CRLF-ness and
BOM survive an edit untouched.

### 3. Uniqueness is enforced *after* a fuzzy hit, in fuzzy space

This is the subtle one and the easiest to get wrong. `countOccurrences`
normalizes both sides and counts in the **normalized** space, and `> 1` throws.

The reason: two passages that are distinct in the original file can become
identical after normalization — one uses a smart quote, the other an ASCII
quote. A tool that checked uniqueness against the raw content, then matched
fuzzily, would find one match, believe it unique, and edit the wrong one. So the
uniqueness check has to run in whatever space the match ran in. **A tolerance
added to matching must be added to the ambiguity check at the same time, or it
converts "no match" into "wrong match" — a strictly worse failure.**

Overlap between separate edits is checked too: matches are sorted by index and
any pair where `previous.matchIndex + previous.matchLength > current.matchIndex`
throws, naming both edit indices and telling the caller to merge them or target
disjoint regions.

### 4. Normalization never reaches disk

If any edit needed fuzzy matching, the replacements are computed in normalized
space — but writing that back would rewrite every smart quote in the file as a
side effect of one edit.

`applyReplacementsPreservingUnchangedLines` prevents it. It splits both the
original and the normalized base into lines, widens each replacement to the
lines it actually touches, groups overlapping ranges, then rebuilds the output:
touched line ranges come from the normalized base, **every other line is copied
back byte-for-byte from the original**. It asserts equal line counts between the
two views up front, and refuses if they differ.

Two details do real work. Splicing at **line boundaries** means the blast radius
of normalization is the lines you edited, which is exactly the set the user is
already reviewing in the diff. And the grouping is driven by the actual
replacement ranges rather than by matching normalized lines to original lines —
so duplicate normalized lines cannot be aligned to the wrong occurrence. The
docstring calls that out explicitly; it is the failure a naive line-alignment
implementation walks into.

### 5. Byte-identical output is an error, not a silent success

```
if (baseContent === newContent) throw getNoChangeError(path, …);
```

A replacement that produced identical content means the tool did *something*
other than what was asked — most likely `oldText` and `newText` differ only in
characters the normalizer collapsed. Returning success there tells the model its
edit landed, and the model moves on. Since the message is what the model reads
next, it names the likely cause: *the replacement produced identical content,
this might indicate an issue with special characters or the text not existing as
expected.*

This is the same rule as [`../conventions/agent-success-signals.md`](../conventions/agent-success-signals.md)
at the tool-call level: a success value has to mean the work happened, not that
the code path completed.

### 6. Every error names the edit index

There are dedicated constructors for not-found, duplicate, empty-`oldText`, and
no-change, and each has two forms:

- Single edit: `Could not find the exact text in <path>. …`
- Multiple edits: `Could not find edits[2] in <path>. …`

Both forms carry the corrective action, not just the diagnosis — *the oldText
must match exactly including all whitespace and newlines*, *provide more context
to make it unique*.

This is the cheapest item on the list and the one with the clearest return.
Given `edits[2] is not unique`, the model re-emits one edit with more context.
Given `edit failed`, it re-reads the file and re-emits all of them, and may loop.
**The retry loop's length is a function of error-message precision**, and on an
eval harness that shows up as spend. When the batch is a list, the error must
index into the list.

## If it gets built here

The parts to copy, in order of value: per-index error messages with the fix
stated; exact-before-fuzzy; the closed normalization table; uniqueness checked
in match space; line-boundary splicing so normalization never leaks. The parts
to skip until needed: the Kitty-image range expansion and the unified-patch
generation, both of which are pi's display layer rather than its matching layer.
