# Codex attempt 1, 2026-09-20, model `gpt-6-astra`

**This directory holds a failure, and it is kept on purpose.** The first Codex
pass of this run produced no review. All 18 conditions failed in about eight
seconds each, before the request reached a model. `RESULTS-2026-09-20-harder-seeds.md`
quotes the error verbatim in the section "The Codex lane, verbatim".

The harness recorded each case as a condition failure and never as a miss,
which is honesty rule 4 in [`../../README.md`](../../README.md). No review text
was written, and none was invented.

## What is here

| Path | What it holds |
| --- | --- |
| `<case>/codex.stdout.txt` | Attempt 1 stdout. Every one of the 18 is empty |
| `<case>/codex.stderr.txt` | Attempt 1 stderr, with the HTTP 400 at the end |
| `records.json` | The 18 `conditions.codex` manifest records of attempt 1, and the run-level record |

## Why the transcripts moved here

The second attempt writes `<case>/codex.stdout.txt` and
`<case>/codex.stderr.txt` in the case directories, and those files are now the
condition's transcripts. A copy of attempt 1 was taken first, because a failed
condition is the evidence for the change that followed it. `manifest.json`
describes attempt 2 only; `records.json` here is the attempt 1 half.

## What changed between the two attempts

The harness now pins the Codex model with `-m` instead of inheriting the id in
the machine's Codex config. `run_eval.py` states the reason at
`DEFAULT_CODEX_MODEL`. Nothing about the machine changed: the Codex CLI was not
upgraded, and its config file was not edited. The prompts are byte-identical
across the two attempts, and `manifest.json` records the sha256 of each one.
