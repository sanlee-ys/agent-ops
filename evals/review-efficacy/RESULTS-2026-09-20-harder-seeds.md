# Harder seeds, 2026-09-20

**The headline: the Claude lane caught 6 of 18 seeded defects, and the Codex
lane did not run at all.** The pilot on 2026-09-04 caught 8 of 10. This run
removed the one property every pilot catch shared, which is a contradiction
sitting beside the defect in the same diff, and the catch rate fell to a third.
**This run cannot compare the two lanes.** The Codex condition failed on every
case before it reached a model, so it is UNMEASURED here, and no paired
statistic exists.

**Later the same day the Codex condition ran on all 18 stored prompts, and it
caught 7 of 18 against Claude's 6 of 18 on 5 discordant pairs, which is below
the power floor; see "Codex condition, re-run 2026-09-20 with a pinned model"
at the end of this file.** The paragraph above is the record of the first
attempt and it stays as written.

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
| Cases | 18, from 13 merged pull requests of this repository |
| Defect classes | wrong-constant, missing-branch, narrow-invariant, six each |
| Claude condition | `claude -p --model sonnet`, resolved id `claude-sonnet-5` |
| Codex condition, attempt 1 | `codex exec`, configured model `gpt-6-astra`, **every case failed** |
| Codex condition, attempt 2 | `codex exec -m gpt-5.6-sol`, pinned, **18 of 18 ran** |
| Prompt | version 2: the WHOLE rules file, plus the pull request body |
| Rules text | `vendors/shared/AGENTS.md`, sha256 `697cca69...cce1fa5dbf` |
| Conditions that ran | 36 of 36, after the re-run. Attempt 1 ran 18 of 36 |
| Writer provenance | 13 of 18 cases: every commit in `base..head` carries a Claude `Co-Authored-By` trailer |

The rules file digest is the same value the pilot recorded. The file did not
move between the two runs. What changed is how much of it the prompt carries.

## What a harder seed is

**The pilot's most useful observation was about both lanes at once.** Every
defect it caught had a contradiction beside it in the same diff: a comment, a
docstring, or a test that said the opposite. Both defects it missed did not.
The pilot could not tell whether the reviewers were finding defects or finding
contradictions.

So 17 of the 18 seeds are defects that **nothing in the diff contradicts**. No
comment, no docstring, no error message and no test in those 17 diffs states
the behaviour the seed breaks.

**h18 is the one exception, and the case record names it.** The same diff adds
a `_tokens` docstring that reads "Non-posix mode keeps Windows backslash paths
intact". The h18 seed removes the backslash handling from the basename split in
`_dangerous_target`. That docstring therefore states the behaviour the seed
breaks, which is the property this run set out to remove. The `defect_description`
for h18 in [`cases-harder-seeds.json`](cases-harder-seeds.json) cites that
docstring, so the exception was in the record from the start and the summary
sentence above it was wrong. h18 is graded a miss. **The catch rate is not
inflated by this, and the property claim is.** Read the run as 17
contradiction-free seeds plus one that is not.

The three classes come from `RESULTS.md`:

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
| h01 | #108 | wrong-constant | catch | catch |
| h02 | #87 | wrong-constant | **miss** | **miss** |
| h03 | #26 | wrong-constant | **miss** | **miss** |
| h04 | #18 | wrong-constant | catch | **miss** |
| h05 | #88 | wrong-constant | **miss** | catch |
| h06 | #143 | wrong-constant | catch | catch |
| h07 | #96 | missing-branch | **miss** | **miss** |
| h08 | #96 | missing-branch | **miss** | **miss** |
| h09 | #25 | missing-branch | **miss** | catch |
| h10 | #37 | missing-branch | **miss** | **miss** |
| h11 | #18 | missing-branch | **miss** | **miss** |
| h12 | #100 | missing-branch | catch | **miss** |
| h13 | #49 | narrow-invariant | catch | catch |
| h14 | #27 | narrow-invariant | **miss** | **miss** |
| h15 | #28 | narrow-invariant | catch | catch |
| h16 | #18 | narrow-invariant | **miss** | **miss** |
| h17 | #88 | narrow-invariant | **miss** | **miss** |
| h18 | #100 | narrow-invariant | **miss** | catch |

The Codex column comes from the re-run. The Claude column is the first run,
unchanged: the re-run touched no `claude.*` file.

| metric | Claude | Codex |
| --- | --- | --- |
| Catch rate | 6/18 | 7/18 |
| False findings | 0 over 18 graded cases | 0 over 18 graded cases |
| Total wall time | 873 s | 614 s. Attempt 1 spent 153 s on failures |

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

**A removal is harder to see than a wrong value.** All six missing-branch seeds
remove one entry from a table, and five of the six were missed. The one catch,
h12, is also a removal, so this run does not pair the two properties. It shows
one rate on six removals and nothing else. A reader checks the entries that are
present. Nothing in a diff points at an entry that is not.

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
request bodies name a private repository. The harness scans a title and a body
against `scripts/redline-guard.py`'s own term tables before it builds the
prompt, and it writes a visible placeholder. `manifest.json` records the count
per case.

**Six cases carry one redaction each: h04, h05, h10, h11, h16, h17.** Their
prompts therefore differ by one token from what the production review lane
would send. Four of the six are misses and two are catches, and no redaction
touches a seeded line.

**Who wrote those six placeholders matters, so read it here.** All six are
hand-written into [`cases-harder-seeds.json`](cases-harder-seeds.json): each of
the six case bodies already holds the literal placeholder, and each already
carries `body_redactions: 1`. `run_cases` adds the runtime count to that
stored number, and the two numbers are equal for all 18 cases, so **the
runtime redactor replaced nothing on this run**. It is covered by the harness
tests against a synthetic guard module, and this run did not exercise it
against real private text. A later run records the two halves apart, under
`redactions_from_cases_file` and `redactions_at_runtime`.

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
6. **Four pull requests each supply more than one case, so 18 cases come from
   13 pull requests.** h04, h11 and h16 are one diff with three seeds; h05 and
   h17 are one diff; h07 and h08 are one diff; h12 and h18 are one diff. The
   reviews are independent invocations, and the diffs are not independent
   samples.
7. **"No contradiction in the diff" is a hand judgement, and it was wrong
   once.** This lane read each diff and decided. No mechanical check enforces
   it. A reviewer of this pull request named h18, and the section "What a
   harder seed is" now carries that exception. A reader who disagrees about
   another case should say which one.
8. **Six prompts carry a redaction, and a hand wrote all six.** The runtime
   redactor replaced nothing on this run. See the section above.
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

# Codex condition, re-run 2026-09-20 with a pinned model

**The Codex lane caught 7 of 18 and the Claude lane caught 6 of 18, on the same
18 prompts.** The two lanes disagree on five cases. Five discordant pairs are
below the power floor of six, so this run cannot separate the lanes at any
split. The exact McNemar two-sided p is 1.0000.

The section above asked for this measurement. It said the run needed a working
Codex CLI and nothing else. The run needed a working INVOCATION, which is a
different thing: the harness supplied one, and the machine did not change.

## What changed in the invocation, and why

Two properties of the Codex invocation are now fixed by the harness. Nothing
else about the run changed.

1. **The model is pinned with `-m`.** Attempt 1 let the CLI read the model from
   the machine's Codex config. That config named `gpt-6-astra`, and
   `codex-cli 0.151.0` answered every request with an HTTP 400. Attempt 2
   passes `-m gpt-5.6-sol`, which is the id `second_grader.py` already used for
   20 grading calls on this machine on this day.
2. **The prompt travels on stdin through `-`.** This was already true of
   attempt 1, and a test now holds it there. A Windows command line stops at
   32767 characters, and case h06 builds a 47934-byte prompt. That prompt ran
   in 31.7 s.

**A pinned model contradicts an earlier finding, and the contradiction is
deliberate.** The pilot's review lane raised "the Codex model id was a
hard-coded string" as a defect, and `RESULTS.md` lists it as finding 3. The
reasoning then was sound: an id written into the harness goes stale when the
lane changes model, and the result names the wrong model. The re-run reverses
that decision for a stronger reason. **A model that a machine is configured to
use is a machine setting, and an experiment cannot depend on one.** The old
rule cost this run its whole Codex condition; the new rule costs one flag when
an id is wrong. `manifest.json` still records the config id under
`conditions.codex.config_model`, so the stale-id risk is answered by evidence
rather than by inheritance. `gpt-6-astra` sits there now, beside the
`gpt-5.6-sol` that ran.

## What did NOT change

**The Codex CLI was not upgraded and its config file was not edited.** A
machine change belongs to the owner, and another session may share the same
binary. The config still names a model this CLI refuses.

**The Claude condition is byte-identical.** `claude_command` did not move, and
a test now writes its whole argument list out so that a later change is a red
build. The 18 stored Claude transcripts were not re-run. Directly after the
re-run, `git status` reported a modification to the 18 Codex transcripts and to
`manifest.json`, and to no other file. `prompt.txt` and `seeded.diff` were
rewritten with identical bytes, which is why they do not appear. The grading
pass changed `grades.json` after that.

**Every pair is a pair.** `run --validate-only` rebuilt all 18 prompts before
the re-run and reported `matches the stored prompt` for each one. `report`
reads the per-condition sha256 and excludes no case, so the two lanes reviewed
the same text in all 18 cases.

## Catch rate per class, both lanes

The interval is a 95% Wilson score interval, the same method the Claude table
above uses. Six cases per class is what produces these widths.

| class | Claude | 95% Wilson | Codex | 95% Wilson |
| --- | --- | --- | --- | --- |
| wrong-constant | 3/6 | 0.188 to 0.812 | 3/6 | 0.188 to 0.812 |
| missing-branch | 1/6 | 0.030 to 0.564 | 1/6 | 0.030 to 0.564 |
| narrow-invariant | 2/6 | 0.097 to 0.700 | 3/6 | 0.188 to 0.812 |
| **all classes** | **6/18** | **0.163 to 0.563** | **7/18** | **0.203 to 0.614** |

**The two lanes rank the classes the same way, and neither separates them.**
Both lanes are weakest on missing-branch at 1 of 6. The whole ordering rests on
six cases per class, so read it as a direction and not as a measurement.

## The paired difference

The 2x2 table over the 18 paired cases:

| | Claude catch | Claude miss |
| --- | --- | --- |
| **Codex catch** | 4 | 3 |
| **Codex miss** | 2 | 9 |

- **Codex minus Claude is +0.0556**, which is 7/18 against 6/18.
- **95% interval: -0.1741 to +0.2764.** The method is Newcombe's
  score-interval method for the difference between paired proportions
  (Newcombe 1998, method 10). It combines the two Wilson intervals and a
  correlation term, which here is 0.403. A Wald interval is wrong on this data,
  because both rates come from the same 18 diffs.
- **Exact McNemar two-sided p = 1.0000**, over the 5 discordant pairs.
- **The floor is 6 discordant pairs.** This run has 5, so it cannot reach
  p < 0.05 at any split.

**The interval contains zero and spans both directions.** It allows a Claude
advantage of 17 points and a Codex advantage of 28 points. **This run does not
show that either lane is better.**

## The five cases where the lanes disagree

These five are the whole of the difference, and they are worth more than the
counts.

**Codex caught three that Claude missed.**

- **h05**, wrong-constant. Codex names `_rule_is_unrestricted_shell`, the
  closing parenthesis left on the body, and the three rules that then return
  `False`. The Claude review never reached that function's body comparison. It
  raised two other real findings in the same file, and one of them, the
  substring guard-name match, is a finding both lanes made.
- **h09**, missing-branch. Codex names the missing `gci` alias in
  `CRED_VAR_READ` and writes the exact bypass, `gci Env:GITHUB_TOKEN`. Claude
  quoted the same line and argued about an optional quote in front of `Env:`.
- **h18**, narrow-invariant. Codex names the basename split on forward slashes
  alone, the Windows path it fails on, and the weaker verdict that follows.
  **h18 is the one case whose own diff contradicts its seed**, through the
  `_tokens` docstring. The section "What a harder seed is" records that
  exception, and the Codex lane is the one that read it.

**Claude caught two that Codex missed.**

- **h04**, wrong-constant. Claude names the seeded `sys.exit(1)` and the
  consequence: only exit 2 blocks a `PreToolUse` call. Codex wrote six findings
  about the same file, including lines one hunk from the seed, and never read
  the exit code.
- **h12**, missing-branch. Claude names the missing bare `~`, the score it
  falls back to, and the recursive delete the guard then allows. Codex came
  near it: it reports that `rm.recursive` gives only a warning to absolute
  paths. That statement is true of the code before the seed as well, so it is
  not the seeded defect.

**Both lanes produced 0 false findings under the stored grading rules.** That
figure means "no finding was shown to be false", not "every finding was proved
true". Grading rule 5 states that scope, and this lane applied it to the Codex
column exactly as the first grader applied it to the Claude column.

## Wall time

| lane | wall time, 18 cases | mean per case |
| --- | --- | --- |
| Claude | 872.7 s | 48.5 s |
| Codex, attempt 2 | 614.3 s | 34.1 s |
| Codex, attempt 1 | 153 s | all of it failures |

**Codex is about 1.4 times faster here.** The pilot measured about 4.5 times.
The two runs use different prompts and different diffs, so the two ratios are
not comparable.

## Writer provenance, unchanged by the re-run

**13 of 18 cases carry a Claude `Co-Authored-By` trailer on every commit in
`base..head`.** The five that do not are h01, h05, h07, h08 and h17. For those
five, the population is merged diffs of this repository and not
Claude-authored diffs. `report` prints the warning.

**This matters more now than it did before the re-run**, because the eval's
question is about a Codex review of a CLAUDE diff. Two of the five unproven
cases are Codex catches: h01, which both lanes caught, and h05, which only
Codex caught. The net difference between the lanes is one case. **One of the
three Codex-only catches sits on a diff this eval cannot prove was
Claude-written**, so the small margin above is not clean on the population the
question names.

## What the grader was

**The grader was a Claude Code lane again, and this time it was the lane that
re-ran the condition.** It is a different session from the one that graded the
Claude column, and it did not write the seeds. It applied the stored
`grading_rules` without change to the 18 new transcripts, and it did not touch
the Claude column: the diff to `grades.json` is 18 lines, one per case.
`grades.json` records this under `codex_column_grader`.

**The weakness is the pilot's weakness with one half removed.** The grader no
longer wrote the seeds, so it does not know what a catch looks like from having
built it. It is still a Claude Code lane scoring a Codex condition against a
Claude one. **A second, independent grader should re-grade all 36 units before
anything is decided on them.** `second_grader.py` does exactly this for the
pilot, and the same command shape runs against this directory.

## What this cannot say

**It cannot say that either lane is better at this.** The interval on the
paired difference spans zero in both directions, and the run holds 5 discordant
pairs against a floor of 6. The eval's question stays open, and it is now open
with a measurement rather than with a missing condition.

**It cannot say that the two lanes are the same.** An interval that contains
zero is not evidence of no difference. It is evidence that 18 cases cannot
resolve one this size.

**It cannot compare either lane to the pilot.** The prompt changed, the seeds
changed and the cases changed between the two runs. The section "The difference
against the pilot, and why it is not a measurement" applies to both lanes.

**It cannot say the pin changed a result.** Attempt 1 produced no review text
at all, so there is no attempt-1 number for attempt 2 to move. The comparison
is between a condition that ran and a condition that did not.

**It cannot say the two lanes read the diffs the same way.** The design scores
only the seeded defect. Both lanes raised real findings outside the seed in
almost every case, and none of those moves a number here.

## What this section supersedes, and what it leaves alone

This section does not rewrite the first-run record above. It names what the
re-run changed, in the same way `RESULTS.md` names the pilot's stale claims.

1. **The headline and limit 1 are superseded on the Codex lane.** They say the
   lane is UNMEASURED and that no paired statistic exists. Both were true of
   attempt 1. The headline now carries a dated pointer to this section, and the
   original sentence stays under it.
2. **The run table and the two result tables are updated in place.** A table is
   a derived record, not dated prose: `run_eval.py report` regenerates the
   per-case table from `manifest.json` and `grades.json`, so a stale copy of it
   would simply be wrong. The per-class table above the tables is the Claude
   lane only, and this section carries both lanes.
3. **Limit 9 is stale on one number.** It says `generated_at` holds six
   entries. It holds seven now, because the re-run is a seventh invocation. The
   reasoning under limit 9 is unaffected: no prompt depends on the repository
   head, every case pins its own revisions, and `run --validate-only` still
   reports that all 18 stored prompts match.
4. **The attempt-1 failure stays on the record.** The section "The Codex lane,
   verbatim" is unchanged, and the 18 failed transcripts sit in
   [`runs/2026-09-20-harder-seeds/codex-attempt-1-gpt-6-astra/`](runs/2026-09-20-harder-seeds/codex-attempt-1-gpt-6-astra/)
   with the attempt-1 manifest records beside them.

Regenerate this section's table and paired statistics:

```
uv run python evals/review-efficacy/run_eval.py report --run evals/review-efficacy/runs/2026-09-20-harder-seeds
```

Check the stored evidence without running a reviewer:

```
uv run python evals/review-efficacy/run_eval.py run --cases evals/review-efficacy/cases-harder-seeds.json --out evals/review-efficacy/runs/2026-09-20-harder-seeds --validate-only
```
