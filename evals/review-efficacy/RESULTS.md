# Pilot, 2026-09-04

**The headline: no difference, and this run could not have measured one.** Both
reviewers caught the same 8 of 10 seeded defects and missed the same 2. There
were **zero discordant pairs**, so the exact McNemar test has nothing to weigh
and returns undefined, not a p value. The design's own floor is six discordant
pairs. This run has zero. **It cannot reach significance at any split, and it
cannot be read as evidence that the two reviewers are equal.** It is evidence
that ten cases of this kind do not separate them.

Everything below comes from [`runs/2026-09-04/`](runs/2026-09-04/). Regenerate
it:

```
uv run python evals/review-efficacy/run_eval.py report --run evals/review-efficacy/runs/2026-09-04
```

## The run

| | |
| --- | --- |
| Date | 2026-09-04 |
| Cases | 10, from merged pull requests of this repository |
| Claude condition | `claude -p --model sonnet`, resolved id `claude-sonnet-5` |
| Codex condition | `codex exec`, model `gpt-5.6-sol` |
| Rules text | `vendors/shared/AGENTS.md`, sha256 `697cca69...cce1fa5dbf` |
| Repository head at run time | `c992fa3` |
| Conditions that ran | 20 of 20. None `UNRUN` |
| Writer provenance | 10 of 10 cases: every commit in `base..head` carries a Claude `Co-Authored-By` trailer |

## The table

| case | PR | defect class | Claude | Codex |
| --- | --- | --- | --- | --- |
| c01 | #111 | logic-inversion | catch | catch |
| c02 | #125 | off-by-one | catch | catch |
| c03 | #102 | weakened-test | catch | catch |
| c04 | #114 | regression | catch | catch |
| c05 | #119 | unchecked-none | catch | catch |
| c06 | #113 | weakened-test | **miss** | **miss** |
| c07 | #121 | scope-creep | catch | catch |
| c08 | #99 | weakened-guard | **miss** | **miss** |
| c09 | #120 | off-by-one | catch | catch |
| c10 | #112 | logic-inversion | catch | catch |

| metric | Claude | Codex |
| --- | --- | --- |
| Catch rate | 8/10 | 8/10 |
| False findings | 0 | 0 |
| Total wall time | 921 s | 206 s |

Discordant pairs: 0 either way. Exact McNemar two-sided p: **undefined**.

## The power statement, stated plainly

**The pilot is below the floor by the widest possible margin.** Six discordant
pairs are the fewest that can reach p < 0.05, and this run produced none. The
binding constraint is discordance, not the case count: at a discordance rate
near one third, six discordant pairs need roughly 18 cases. At the rate this
pilot measured, zero out of ten, no achievable case count would get there.

**So the honest reading is narrow.** On seeded defects of these classes, in
this repository, at this difficulty, the two reviewers agree. That is not a
finding about review value, and it does not answer whether Codex reviewing
Claude pays. It answers a smaller question: this particular measurement, at
this size, does not separate them.

## What the two shared misses have in common

Both misses are the same shape, and the shape is worth more than the counts.

- **c06** weakened `assertTrue(blocked(out), ...)` to `assertIsNotNone(out, ...)`
  inside a new test. Both reviewers said "no findings in scope."
- **c08** deleted the `^` anchor from `_REMOTE_URL = re.compile(r"^https?://")`.
  Both reviewers missed it. Claude's own finding then described the pattern as
  matching a value that *starts with* `http`, which is the behaviour **before**
  the seed. It read the anchor that was no longer there.

**Both misses are single-character or single-token weakenings that leave the
code reading correctly.** The seven catches are all defects with a visible
contradiction nearby: a comment, a docstring, or a test in the same diff that
says the opposite. Neither reviewer caught a defect that had no contradiction
beside it. **That is the pilot's most useful observation, and it is about both
lanes at once, not about the difference between them.**

Note that c03 was also a weakened assertion and both reviewers caught it. The
difference from c06 is that c03's sibling assertions on the following lines use
`assertEqual(..., BLOCK)`, so the odd one out is visible in the same hunk.

## Where the reviewers were not the same

The catch counts are identical. Two differences are visible in the transcripts,
and neither is measured by this design.

- **Codex found two real defects Claude did not, on c05.** `parse_porcelain`
  strips the two-character status, so `" M"` and `"M "` both become `"M"` and
  the promised staged-versus-unstaged distinction is erased. And both `gh`
  queries cap at 100 results, so a busy repository gets a silently incomplete
  snapshot. Neither is the seeded defect, so neither moves a number in the
  table.
- **Codex is about four and a half times faster** (206 s against 921 s over the
  same ten diffs) and much terser. Claude's reviews average five findings; Codex
  averages two.

**A design that scores only the seeded defect cannot see either difference.**
That is a real limit of the unit of measurement, not an incidental one.

## What the grader was

**The grader was the Claude Code lane that built this eval.** Not a human, and
not an independent third model. The grading rules are written into
[`runs/2026-09-04/grades.json`](runs/2026-09-04/grades.json) and the raw reviews
are next to them, so any reader can re-grade without a re-run.

That is a real weakness and it points one way. The lane wrote the seeds, so it
knows exactly what a catch looks like, and a lane grading a condition that
shares its model family is not disinterested. **Before this eval is used to
decide anything, a second grader should re-grade the same transcripts.**

## The first run, and what it caught

**The pilot's first pass is kept, unscored, in
[`runs/2026-09-04-tainted-pass/`](runs/2026-09-04-tainted-pass/).** It found two
defects in the harness, and one of them was found by a reviewer inside the eval.

1. **All ten Codex conditions failed to start, in 0.0 seconds each.** On Windows
   the `codex` CLI is a `.CMD` shim and `CreateProcess` cannot start one. The
   design's rule held: every one was recorded as a failure, never as a miss.
2. **Eight of ten prompts carried mojibake.** `_git` decoded with the platform
   locale instead of UTF-8, so an em dash reached the reviewer as three wrong
   characters. Case c09's reviewer reported the corrupted regex as a defect in
   the code under review. **That is a finding the harness manufactured**, and it
   is why the whole pilot re-ran rather than only its missing half.

## What the review lane found in this pull request

The `codex-review` lane reviewed this work seven times as it was built. It
raised **eleven distinct real findings**, and this session fixed all of them:
a truncated prompt could be graded a miss; the Codex model id was a hard-coded
string; a timed-out condition discarded its partial output; the README claimed
an isolation guarantee the mechanism does not provide; the harness shipped with
no tests; a split re-run could pair two different prompts; provenance checked
only the head commit; per-condition metrics vanished when the other lane failed;
`--validate-only` wrote and overwrote run evidence; and the report attributed
every case to one model id.

It also reported the same **false** scope finding in five consecutive rounds:
that the diff deleted `delegation-policy.md` and `ADR-014` material. The cause
was mechanical. The workflow diffs against `main`'s current tip, so a branch
behind `main` reads as deleting the commits it does not yet carry. A rebase
cleared it. **A reviewer that reads a stale base reports a deletion that never
happened, and it will repeat that report on every push until the branch moves.**

Findings arriving after the five-round cap in
[`delegation-policy.md`](../../delegation-policy.md) were ruled on by this
session rather than sent back for another round, which is what that rule
prescribes. Two of those are recorded here rather than fixed.

**Open finding 1, `ask-user`: the prompt carries the review rules without the
label definitions.** `read_review_rules` takes the text from `## Code Review
Rules` onward. That section ends by telling the reviewer to label every finding
per "Review finding disposition", which sits **earlier** in the same file and is
therefore not in the prompt. Both reviewers received the label names and not the
rule for when each applies. The production CI workflow passes the whole file, so
the harness is less faithful to production than the workflow it imitates.

It is not fixed here because fixing it changes the prompt, and a changed prompt
is a different experiment. **This pilot's numbers belong to the prompt in
`runs/2026-09-04/*/prompt.txt` and to no other.** The fix belongs in the next
run, together with the harder seeds named at the end of this file.

**Open finding 2, ruled and partly closed: a `.cmd` shim launched through the
command interpreter.** The interpreter re-parses its own command line, so a
path or argument holding a space, `&`, `|`, `<`, `>`, `^`, `"`, `%`, or a
parenthesis could run something other than what the harness intended. No path in
this pilot holds one. Rather than add a quoting scheme nothing here can test,
`resolve_executable` now **refuses** such a launch with a named reason, and the
refusal is recorded as a condition failure, never as a miss. A wrong command
that runs is worse than a run that stops.

## Limits, named

1. **Zero discordant pairs. No statistical claim is available from this run.**
2. **The grader was the lane that built the eval.** See above.
3. **Seeded defects are not a sample of real defects.** The result covers the
   classes in `cases.json` and nothing wider.
4. **Only the seeded defect scores.** A reviewer that finds two real unseeded
   defects, as Codex did on c05, gets no credit for them.
5. **Ten cases from one repository, one author lane, one day.** Every diff is a
   guard, a hook, or a script from the same codebase.
6. **The isolations differ.** Claude's tools are denied by a denylist that does
   not cover a configured MCP server. Codex gets an empty working directory and
   a read-only sandbox, which does not block a read elsewhere. Neither is a
   guarantee.
7. **Each lane loads its own standing instructions.** This measures the lanes as
   the fleet runs them, not the bare models.
8. **The manifest's `generated_at` has two entries** — a validation pass at
   20:52:23 and the review run at 20:52:32. Both conditions of every case ran in
   the single review invocation. The report's note about a missing prompt hash
   reflects that this run predates the per-condition hash, which landed later
   the same day.
9. **The harness's tests do not run in this repository's CI.** The CI job
   discovers `tests/` only, and this lane does not edit `.github/`. 39 tests
   pass when run by hand.

## What this does not say

**It does not say the fleet should stop using Codex to review Claude.** It says
this measurement did not separate the two on defect detection, and that arXiv
2607.21656's asymmetry did not reproduce here. The paper measures a different
thing: whether the writer's *revised* solution passes tests, which scores
detection and repair together. The fleet uses a review for detection only. On
detection alone, at this size, the two lanes look the same.

**The next measurement that would move this** is not more cases of the same
kind. It is harder seeds. Every catch in this pilot had a contradiction sitting
beside it in the same diff. A defect class with no such contradiction is where
the two lanes might diverge, and it is where a review is worth paying for.

Two changes belong to that next run, and both change the prompt, so neither was
made here:

1. **Send the whole rules file, as the CI workflow does.** Open finding 1 above.
2. **Seed defects with no contradiction in the diff.** A wrong constant that no
   comment names, a missing branch no test covers, an invariant that holds only
   in the cases the diff happens to show.

The verification that this pilot's evidence is intact is one command:
`run --validate-only` rebuilds every case and reports `matches the stored
prompt` for all ten.
