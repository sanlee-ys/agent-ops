# Pass 1, 2026-09-04: tainted. Kept as evidence, never scored.

**Do not read a number out of this directory.** It is here because it is the
evidence for two defects in the harness, and for nothing else. The pilot result
is in `runs/2026-09-04/`.

Two defects made this pass unusable.

1. **Every Codex condition failed to start, in 0.0 seconds.** On Windows the
   `codex` CLI installs as a `.CMD` shim, and `CreateProcess` cannot start a
   `.CMD` file. `subprocess.run` with `shell=False` therefore raised
   `FileNotFoundError` for a command that runs in every shell. Ten of ten Codex
   conditions were lost. The design's own rule held: each one is recorded as a
   failure in `manifest.json`, never as a miss.
2. **Eight of ten prompts carried mojibake.** `_git` ran `subprocess` with
   `text=True` and no encoding, so a UTF-8 diff was decoded with the platform's
   locale. On Windows that is cp1252, and an em dash reached the reviewer as
   three wrong characters. The seeded defects are all ASCII and were untouched,
   but the reviewer of case c09 reported the corrupted regex as a defect in the
   code under review. That is a finding the harness manufactured.

The second defect is the reason this pass is not simply re-run for its missing
half. A corrupt input taints everything downstream of it, even where it parses
([`conventions/truncated-producers-taint.md`](../../../conventions/truncated-producers-taint.md)).
So the whole pilot re-ran, both conditions, on the fixed harness.

**The eval found both defects on its first run, and one of them came from a
reviewer inside the eval.** That is worth recording next to the pilot's own
result.
