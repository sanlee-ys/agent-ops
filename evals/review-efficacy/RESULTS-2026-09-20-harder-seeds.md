# Harder seeds, 2026-09-20

**The headline: the Claude lane caught 6 of 18 seeded defects, and the Codex
lane did not run at all.** The pilot on 2026-09-04 caught 8 of 10. This run
removed the one property every pilot catch shared, which is a contradiction
sitting beside the defect in the same diff, and the catch rate fell to a third.
**This run cannot compare the two lanes.** The Codex condition failed on every
case before it reached a model, so it is UNMEASURED here, and no paired
statistic exists.

Everything below comes from
[`runs/2026-09-20-harder-seeds/`](runs/2026-09-20-harder-seeds/). Regenerate the
table:

```
uv run python evals/review-efficacy/run_eval.py report --run evals/review-efficacy/runs/2026-09-20-harder-seeds
```

**This is a NEW experiment, not more cases of the pilot.** The prompt changed,
so the two runs measure different things. `RESULTS.md` names both changes and
says why each one had to wait for a new run. Read the two numbers side by side
only with the section "What this cannot say" in hand.

## The run

| | |
| --- | --- |
| Date | 2026-09-20 |
| Cases | 18, from 12 merged pull requests of this repository |
| Defect classes | wrong-constant, missing-branch, narrow-invariant, six each |
| Claude condition | `claude -p --model sonnet`, resolved id `claude-sonnet-5` |
| Codex condition | `codex exec`, configured model `gpt-6-astra`, **every case failed** |
| Prompt | version 2: the WHOLE rules file, plus the pull request body |
| Rules text | `vendors/shared/AGENTS.md`, sha256 `697cca69...cce1fa5dbf` |
| Conditions that ran | 18 of 36. All 18 Codex conditions `UNRUN` |
| Writer provenance | 13 of 18 cases: every commit in `base..head` carries a Claude `Co-Authored-By` trailer |

The rules file digest is the same value the pilot recorded. The file did not
move between the two runs. What changed is how much of it the prompt carries.

## What a harder seed is

**The pilot's most useful observation was about both lanes at once.** Every
defect it caught had a contradiction beside it in the same diff: a comment, a
docstring, or a test that said the opposite. Both defects it missed did not.
The pilot could not tell whether the reviewers were finding defects or finding
contradictions.

So every seed in this run is a defect that **nothing in the diff contradicts**.
No comment, no docstring, no error message and no test in the same diff states
the behaviour the seed breaks. The three classes come from `RESULTS.md`:

- **wrong-constant.** A value whose correctness is fixed by other code in the
  diff, and which no prose names. An exit code, an index, a loop step, a slice.
- **missing-branch.** One entry removed from a table of inputs, so a real input
  class stops being handled, and no test in the diff covers it.
- **narrow-invariant.** A rule that still holds for every example the diff
  shows, and not in general. A path with one separator, a name with one
  wildcard, a build command with no quoting.

The seeds are in [`cases-harder-seeds.json`](cases-harder-seeds.json), one per
case, with the location and the wrong behaviour each one causes.

## The table

| case | PR | defect class | Claude | Codex |
| --- | --- | --- | --- | --- |
| h01 | #108 | wrong-constant | catch | UNRUN |
| h02 | #87 | wrong-constant | **miss** | UNRUN |
| h03 | #26 | wrong-constant | **miss** | UNRUN |
| h04 | #18 | wrong-constant | catch | UNRUN |
| h05 | #88 | wrong-constant | **miss** | UNRUN |
| h06 | #143 | wrong-constant | catch | UNRUN |
| h07 | #96 | missing-branch | **miss** | UNRUN |
| h08 | #96 | missing-branch | **miss** | UNRUN |
| h09 | #25 | missing-branch | **miss** | UNRUN |
| h10 | #37 | missing-branch | **miss** | UNRUN |
| h11 | #18 | missing-branch | **miss** | UNRUN |
| h12 | #100 | missing-branch | catch | UNRUN |
| h13 | #49 | narrow-invariant | catch | UNRUN |
| h14 | #27 | narrow-invariant | **miss** | UNRUN |
| h15 | #28 | narrow-invariant | catch | UNRUN |
| h16 | #18 | narrow-invariant | **miss** | UNRUN |
| h17 | #88 | narrow-invariant | **miss** | UNRUN |
| h18 | #100 | narrow-invariant | **miss** | UNRUN |

| metric | Claude | Codex |
| --- | --- | --- |
| Catch rate | 6/18 | UNMEASURED |
| False findings | 0 over 18 graded cases | UNMEASURED |
| Total wall time | 873 s | 153 s, all of it failures |

## Catch rate per class, with an interval sized for n

The interval is a 95% Wilson score interval. It is wide because n is 6 per
class, and the width is the point: **a per-class rate from six cases orders the
classes at best, and it measures none of them.**

| class | catches | rate | 95% Wilson |
| --- | --- | --- | --- |
| wrong-constant | 3/6 | 0.50 | 0.188 to 0.812 |
| missing-branch | 1/6 | 0.17 | 0.030 to 0.564 |
| narrow-invariant | 2/6 | 0.33 | 0.097 to 0.700 |
| **all classes** | **6/18** | **0.33** | **0.163 to 0.563** |

**The three intervals overlap almost completely.** This run does not separate
the classes. It says only that the pooled rate on seeds of this difficulty is
near one third, with a floor around one sixth and a ceiling around one half.

## The difference against the pilot, and why it is not a measurement

| run | prompt | catch rate | 95% Wilson |
| --- | --- | --- | --- |
| 2026-09-04 pilot | version 1 | 8/10 | 0.490 to 0.943 |
| 2026-09-20 harder seeds | version 2 | 6/18 | 0.163 to 0.563 |

The difference in proportions is **0.33 minus 0.80, which is -0.47**. A Fisher
exact test over the two-by-two table returns a two-sided **p = 0.0461**.

**Do not read that p value as a measured effect of seed difficulty.** Three
things changed at once between the two runs, and this design cannot separate
them:

1. **The seeds changed**, which is the intended change.
2. **The prompt changed.** Version 2 sends the whole rules file and the pull
   request body. A larger prompt is a different task, and it could move the
   rate in either direction.
3. **The cases changed.** Different pull requests, different files, different
   diff sizes.

The two Wilson intervals also overlap between 0.490 and 0.563, so the
difference is not clean even before the confounds. **The honest statement is
that the observed rate fell by about half, and that this run cannot attribute
the fall to any one of the three changes.**

## The Codex lane, verbatim

Every Codex condition failed in about eight seconds. The harness recorded each
one as a condition failure and never as a miss, which is honesty rule 4. The
raw transcripts are in each case directory. The error, copied exactly from
`h01/codex.stderr.txt`:

```
ERROR: {"type":"error","status":400,"error":{"type":"invalid_request_error","message":"The 'gpt-6-astra' model requires a newer version of Codex. Please upgrade to the latest app or CLI and try again."}}
```

The installed CLI is `OpenAI Codex v0.151.0`. The model id in the Codex config
is `gpt-6-astra`. The CLI reached the API, and the API refused the model.

**This lane did not upgrade the Codex CLI.** The upgrade is a machine change
outside this repository, and another session may be running against the same
binary. **Report the Codex lane as UNMEASURED.** No review text was written for
it, and none was invented.

## What the misses have in common

Twelve misses is the useful half of this run, because the transcripts show the
reviewer reading the seeded line and drawing a different conclusion.

- **h07 quotes the shortened table back.** The seed drops `"cmd"` from
  `_COMMAND_KEYS`. The review writes "a shell tool has no `command`,
  `commandline`, or `script` key", which is the table after the seed. It treats
  the table as the design and reports the pass-through as a general fail-open.
- **h11 and h16 are the same diff with different seeds.** h11 removes
  `--no-ignore-removal` from the whole-tree table. The review lists eight
  findings about that file and never misses the flag. The h16 review, on the
  unseeded table, names `--no-ignore-removal` as an unrequested addition. **One
  review saw the entry because it was there. The other did not notice that it
  was gone.**
- **h09 reads the seeded line and argues about something else.** It quotes the
  seeded `CRED_VAR_READ` alternative and asks for an optional quote in front of
  `Env:`. It does not notice that one alias is missing from the alternation
  while the sibling pattern still lists it.
- **h02 repeats the pilot's c08 shape.** The seed changes a loop step from two
  to one. The review describes the function as counting every **unescaped**
  quote, which is the behaviour before the seed. It read the escape handling
  that was no longer there.

**A removal is harder to see than a wrong value.** Five of the six
missing-branch seeds are removals from a table, and five of the six were
missed. A reader checks the entries that are present. Nothing in a diff points
at an entry that is not.

## The pull request body is a confound, and it is counted

Prompt version 2 sends the pull request body, which is a production-fidelity
gain and a new source of contradiction. A body often states the behaviour the
diff is meant to have. `cases-harder-seeds.json` records per case whether the
body states the behaviour the seed breaks.

| the body states the intent | catches | 95% Wilson |
| --- | --- | --- |
| yes, 4 cases | 3/4 | 0.301 to 0.954 |
| no, 14 cases | 3/14 | 0.076 to 0.476 |

**Four cases cannot settle anything, and the intervals overlap.** The number is
here because the confound is real and because the next run can grow it, not
because it measures anything now. The direction is the one the pilot's
observation predicts: a contradiction beside the defect makes the defect
visible, wherever the contradiction sits.

## What the grader was

**The grader was the Claude Code lane that built this run.** Not a human, and
not an independent third model. The grading rules are copied without change
from [`runs/2026-09-04/grades.json`](runs/2026-09-04/grades.json) into
[`runs/2026-09-20-harder-seeds/grades.json`](runs/2026-09-20-harder-seeds/grades.json),
so the two runs are graded by one standard. The raw reviews sit next to the
grades, so any reader can re-grade without a re-run.

The weakness points the same way the pilot's did, and harder. **The lane wrote
the seeds, and it graded a condition that shares its model family.** A second
grader should re-grade these transcripts before anything is decided on them.

## The publication boundary changed six prompts

This repository is public, and a run directory is committed whole. Three pull
request bodies name a private repository. The harness redacts a body against
`scripts/redline-guard.py`'s own term tables before it builds the prompt, and
it writes a visible placeholder. `manifest.json` records the count per case.

**Six cases carry one redaction each: h04, h05, h10, h11, h16, h17.** Their
prompts therefore differ by one token from what the production review lane
would send. Four of the six are misses and two are catches, and no redaction
touches a seeded line.

## Limits, named

1. **The Codex lane is UNMEASURED. There is no paired statistic and no lane
   comparison in this run.** The eval's own question stays open.
2. **The grader was the lane that built the run.** See above.
3. **Six cases per class.** Every per-class interval spans more than half the
   range. The classes are not separated by this run.
4. **The prompt changed with the seeds.** The fall against the pilot cannot be
   attributed to seed difficulty alone.
5. **Five of 18 cases have no Claude trailer on every commit in `base..head`:
   h01, h05, h07, h08 and h17.** For those five the population is merged diffs
   of this repository, not Claude-authored diffs. `report` prints the warning.
6. **Three cases reuse one pull request and three others reuse two more.** h04,
   h11 and h16 are one diff with three seeds; h05 and h17 are one diff; h07 and
   h08 are one diff; h12 and h18 are one diff. The reviews are independent
   invocations, and the diffs are not independent samples.
7. **"No contradiction in the diff" is a hand judgement.** This lane read each
   diff and decided. No mechanical check enforces it, and a reader who
   disagrees about one case should say which one.
8. **Six prompts carry a redaction.** See the section above.
9. **`manifest.repo_head` names the head at the LAST run invocation, and
   `generated_at` holds six entries.** The reviews ran in six invocations, and
   the outputs were committed between them. No prompt depends on the repository
   head: every case pins its own base and head revision, and the rules file
   digest is the same in every record. `run --validate-only` against this
   directory rebuilds all 18 prompts and reports that each matches the stored
   one.
10. **Only the seeded defect scores.** Several reviews raised real defects in
    untouched code. None of them moves a number here.
11. **False findings are reported as 0, and that means "none was shown to be
    false".** The grader checked every finding against the seeded diff for the
    seeded defect. It did not independently re-derive every claim a review made
    about code the seed never touched.

## What this does not say

**It does not say a review is worth less than the pilot suggested.** It says
that on this kind of defect, at this size, one lane named the seeded defect in
a third of the cases, and that the other lane could not be measured on the same
day.

**It does not say the pilot was wrong.** The pilot's own closing paragraph
predicted this: every catch it recorded had a contradiction beside it, and it
named harder seeds as the next thing to measure. This run is that measurement,
and the direction matches the prediction.

**The next measurement that would move this** is the Codex lane on these same
18 prompts. The prompts are stored, the seeds are stored, and the grading rules
are stored, so that run needs a working Codex CLI and nothing else. A second
grader on these transcripts is worth more than more cases.
