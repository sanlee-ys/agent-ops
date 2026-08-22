# Rule adherence is measured, not assumed

**A rule nobody follows looks exactly like a rule everybody follows.**

Nothing tests prose. A rule file is written once, and after that the only
evidence it works is that it is still in the file. Code that describes stale
behaviour fails a test; a rule that every session quietly ignores produces no
signal at all. That is a **dead rule**, and it is worse than a missing one: it
occupies the slot where a working control would go, and it is cited in reviews
as though it were load-bearing.

## The decision

**Count the violations you can detect, and say plainly what you cannot.**

The measurement is deliberately small. A handful of rules leave a mechanical
trace in a session transcript — a command shape, a character in prose — and
those can be counted exactly. Most rules cannot, because they are about
judgement, and judgement leaves no regular expression behind.

That asymmetry is not a defect to be engineered away. It is the reason the
limits below are part of the convention rather than a footnote: **a partial
measurement reported as a full one is worse than no measurement**, because it
converts "we do not know" into a number, and a number gets quoted.

## The mechanism

[`scripts/dead_rules_audit.py`](../scripts/dead_rules_audit.py). It reads local
session transcripts and counts four rule signatures per rule per day.

```
uv run python scripts/dead_rules_audit.py --days 7
```

`--json` emits the same data as JSON. `--root DIR` points it at another
transcript store. Exit codes are the interface: 0 audit complete, 2 usage error.

The script **never writes anything and never sends anything anywhere.** It
opens transcripts read-only and prints to stdout.

## Honest limits

Read these before quoting a number from this script.

1. **It measures the DETECTABLE subset only.** Four signatures is not the rule
   corpus. Everything about scope discipline, routing a finding, cadence,
   verification honesty, and how a decision gets recorded is invisible here.
2. **Absence of hits is not proof of compliance.** A rule with zero hits may be
   perfectly observed, or it may have no detector, or its detector may be
   narrower than the rule. All three look identical in the output.
3. **The count is a floor on violations, never a compliance score.** Do not
   divide it by anything. There is no denominator: the script cannot count the
   occasions on which a rule *could* have been broken.
4. **A detector is a shape, not a rule.** Each one is named for the command
   shape it finds, not for the rule it belongs to. The shapes are generic and
   public; the rule corpus that motivates them stays private, and nothing in
   this repo needs to name it.
5. **The window is the transcript store on ONE machine.** Work done on another
   machine is not in it, and a transcript can be pruned. A drop to zero may be
   a fixed habit or a deleted file.
6. **It reports what a transcript recorded, not what happened.** A command
   blocked by a guard and a command that ran look the same in the record.

## What never leaves the transcript

A transcript holds the whole session. An audit of one must not become a second
copy of it, so the script prints:

- **counts, always;**
- **up to three truncated COMMAND strings per rule**, and nothing else;
- **no examples at all for the prose detector.** Its evidence is prose, and
  printing prose to make a point about prose would put the session in the
  report.

Assistant prose, user prose, and file contents never reach a count or an
example. `tests/test_dead_rules_audit.py::TestNothingLeaks` asserts each of
those from the failing side, so the claim is pinned rather than argued.
