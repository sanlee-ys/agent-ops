# Review-efficacy eval

**The question.** Does a Codex review of a Claude-authored diff catch a defect
that a Claude review of the same diff does not? The fleet runs Codex as the
reviewer of Claude's work ([`vendors/codex/README.md`](../../vendors/codex/README.md)).
That order costs tokens and time on every consequential diff. Nothing in this
repository measures whether it pays.

**Why the question is open.** Two pieces of evidence point in opposite
directions.

- arXiv 2607.21656 (2026-07-22) ran 116 LiveCodeBench tasks through six
  writer-reviewer conditions. A Claude review raised Codex drafts from 71.6% to
  89.7% (p_BH = .001). The reverse order dropped Claude drafts from 91.4% to
  82.8% (p_BH = .046). The paper concludes that the useful pairing is
  asymmetric, and that this fleet runs the order that did not pay.
- On 2026-09-04 the CI review lane caught three real defects in a new workflow,
  across pull requests #130, #131 and #132. Each finding was correct and each
  produced a follow-up pull request. That is evidence the other way, and it is
  anecdotal.

The paper does not settle the fleet's case. It measures whether the writer's
REVISED solution passes a test suite. It therefore scores detection and repair
together, and a bad repair can cancel a good detection. The fleet uses a review
differently: the reviewer only writes findings, and the applying session decides
what to do with each one. So this eval measures detection alone.

## The unit of measurement, and why

**One case is a real merged diff from this repository, with one defect seeded
into it.** The alternative was a diff with a known post-merge defect or a known
reviewer-caught defect. This design rejects that alternative for two reasons.

1. **The sample would be too small and it could not grow.** A known defect
   exists only where somebody already found one. This repository holds a few
   such diffs, and the count is fixed by history. A seeded defect lets the case
   count grow to whatever power the test needs.
2. **A known defect has contaminated ground truth.** The defect is known because
   a reviewer, an incident, or a follow-up commit named it. That text is in the
   repository, and a reviewer can reach it. A seeded defect exists only in the
   run directory.

The cost of the choice is real and this eval does not hide it. **A seeded defect
is not a random sample of real defects.** The results measure detection of the
defect classes in [`cases.json`](cases.json), not review value in general. A
reviewer that is strong on a seeded off-by-one may still be weak on the defects
this eval never seeds.

Three rules keep a seeded case honest, and
[`run_eval.py`](run_eval.py) enforces all three at build time:

- The seed anchor must match the diff exactly once. The ground truth is a
  location, so an ambiguous location is not a case.
- The seed must land inside an added line. A change to a context line rewrites
  code the pull request never touched.
- The seed must preserve the line count. A hunk header that disagrees with its
  body is a malformed diff, and a reviewer that reports the malformation has not
  found the seeded defect.

A fourth rule follows from the same reasoning. **A diff over the character cap
is a build error, not a truncated prompt.** Truncation can cut the seeded defect
out of the prompt, and the reviewer would then be graded a miss for a defect it
never received. That is a false result, which is worse than a missing one.
Narrow the case's `paths` instead.

## The two conditions

**Paired design: both conditions review the same seeded diff.** The pairing
removes diff difficulty as a source of variance. That matters most at a small
case count, which is where this eval starts.

| | Condition A | Condition B |
| --- | --- | --- |
| Reviewer | `claude -p` | `codex exec` |
| Model | Sonnet, the tier the fleet uses for review | the id the harness reads from the Codex config at run time |
| Rules | the `## Code Review Rules` section of [`vendors/shared/AGENTS.md`](../../vendors/shared/AGENTS.md) | the same text, read from the same file |
| Isolation | file and shell tools refused | an empty working directory, read-only sandbox |

**Both conditions read the same rules text from the same file.** The runner does
not restate the rules. A restatement is a second copy, and a second copy drifts.

**The two isolations are not equally strong, and the eval says so rather than
claim otherwise.** The Claude condition refuses its file and shell tools, so it
cannot read anything. The Codex condition runs in an empty working directory
under a read-only sandbox, so it cannot write and has no repository at hand, but
a read outside that directory is not blocked. Both prompts say to review only
the diff. Both transcripts reach a file, so a read would be visible to the
grader. **Treat a Codex catch that cites a file the diff does not contain as
suspect, and check its transcript.**

**Both models resolve at run time and reach `manifest.json`.** A model id
written into this file would go stale the moment a lane changes model, and the
result would then name the wrong model.

**One asymmetry stays, and it is deliberate.** Each vendor still loads its own
standing instruction file. This eval measures the lanes as the fleet runs them,
not the bare models. A result here is a statement about `claude -p` and
`codex exec` in this configuration.

## Metrics

- **Catch rate per condition.** The count of cases where the reviewer named the
  seeded defect, over the count of scored cases.
- **False findings per condition.** The count of findings that are neither the
  seeded defect nor a true property of the diff. This is the cost side. A
  reviewer that reports every line as a risk catches every seeded defect and is
  worthless.
- **The paired difference.** An exact McNemar test over the discordant pairs.
  A concordant pair carries no information about a difference, so only the
  discordant pairs count.

**The power floor: six discordant pairs.** The exact McNemar test reads the
discordant pairs as a binomial with p = 0.5. Six pairs that split 6-0 give a
two-sided p of 0.031. Five pairs that split 5-0 give 0.0625. **So a run with
fewer than six discordant pairs cannot reach p < 0.05 at any split, however
lopsided the result looks.** `run_eval.py report` prints this floor and states
when a run is below it.

Discordance is the binding constraint, not the case count. At a discordance rate
near one third, six discordant pairs need about 18 cases. **The pilot runs 10
cases. The pilot is below the floor, and its p value is descriptive only.**

## Honesty rules

These come from telltale's honest-gauge rule and from
[`conventions/reconcile-claims.md`](../../conventions/reconcile-claims.md).

1. **No metric that this eval did not generate.** A number in a result file
   comes from a run in `runs/`, or it does not appear.
2. **The runner writes every raw output to a file.** `runs/<date>/<case>/` holds
   the prompt, the seeded diff, and both reviewers' unedited stdout and stderr.
   A reader can re-grade the run without a re-run.
3. **The runner grades nothing.** A separate `grades.json` carries the catch
   and miss judgement, and `report` reads it. The runner must not be able to
   score its own run.
4. **An unrun condition is UNRUN, never a miss.** A failed subprocess, a
   timeout, and a missing tool are recorded as failures in `manifest.json`.
   `report` excludes the case from the PAIRED statistic only. A condition that
   ran and was graded still counts toward its own catch rate, because one
   reviewer's failure is not evidence about the other reviewer.
5. **Every result states its revisions, models, and dates.** `manifest.json`
   records the base and head commit of each case, the sha256 of the rules file,
   both resolved model ids, and the run time. When a model id does not resolve,
   `report` prints the numbers with a warning beside them that says the result
   cannot name the model it measured. It does not drop the numbers, and it does
   not print them silently.
6. **A prompt that could not carry the seeded defect never runs.** An over-cap
   diff fails at build time. A truncated producer taints everything downstream
   of it ([`conventions/truncated-producers-taint.md`](../../conventions/truncated-producers-taint.md)).

## The harness has its own tests, and this repository's CI does not run them

`test_run_eval.py` covers the four places that produce a wrong measurement: the
seed validation, the line numbering, the exact McNemar statistic, and the
exclusion of a case that did not run or was not graded.

```
uv run python -m unittest discover -s evals/review-efficacy -p "test_*.py" -v
```

**CI does not run them.** `.github/workflows/ci.yml` discovers `tests/` only,
and the lane that built this eval does not edit that file. Per the gate rule in
[`delegation-policy.md`](../../delegation-policy.md), a check that cannot run is
not a pass, so run the command above by hand until the CI job discovers this
directory too.

## Run it

Fetch the pull request head refs once. A squash merge leaves the head commit
unreachable from `main`.

```
git -C <repo> fetch origin "+refs/pull/*/head:refs/remotes/origin/pr/*"
```

Check that every case still builds against live history:

```
uv run python evals/review-efficacy/run_eval.py run --validate-only
```

Run both conditions:

```
uv run python evals/review-efficacy/run_eval.py run
```

Grade the run. Copy `runs/<date>/grades.template.json` to
`runs/<date>/grades.json`, then fill in `catch` and `false_findings` for each
case and condition. Name the grader in the file.

Print the table and the paired statistics:

```
uv run python evals/review-efficacy/run_eval.py report --run evals/review-efficacy/runs/<date>
```

## Files

| Path | What it holds |
| --- | --- |
| `cases.json` | The cases: pull request, revisions, paths, defect class, seed |
| `run_eval.py` | The harness. Read it for the mechanics |
| `test_run_eval.py` | The harness's own tests. Not in CI. Run them by hand |
| `RESULTS.md` | The pilot result, with its power statement |
| `runs/<date>/` | Raw outputs, `manifest.json`, and `grades.json` |
