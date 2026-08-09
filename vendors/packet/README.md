# `packet/` — the cross-vendor transfer packet

A typed envelope for the one thing every vendor adapter in this directory
describes and none of them agree on: what crosses a harness boundary when work
moves from one agent to another.

[`ADR-010`](../../decisions/ADR-010-claude-led-four-vendor-orchestration.md)
decision 7 states the rule — *"A frozen brief, explicit file boundary, pushed
branch or PR, exact revision, and verification results cross the harness
boundary. San is never the clipboard between agents."* Today that rule is
instantiated as prose templates in the vendor READMEs, and
[`SYS-022`](https://github.com/sanlee-ys/architecture/blob/main/decisions/SYS-022-org-graph-and-the-mechanization-split.md)
says exactly what that costs: *"the edge contracts are prose, and prose is the
mechanism… enforced by an agent reading it, which means its failure rate is not
zero."*

This directory promotes that one edge to something checkable. It does nothing
else, and the section [What this is not](#what-this-is-not) is not boilerplate.

---

## 1. The problem, re-derived from source

Not "the templates are informal" — **the templates disagree with each other**,
and the disagreements land on the fields ADR-010 decision 7 names.

Re-derived 2026-08-09 against `main` at `e5509fa`, by reading the four vendor
files rather than a summary of them:

| ADR-010 dec. 7 requires | `codex/README.md` "Escalation packet" | `gemini/README.md` "Transfer packet" | `cursor/README.md` "Transfer in" | `grok/README.md` |
|---|---|---|---|---|
| repo | **absent** | `Repo:` | `Repo: <path>` — a **local path** | **no template at all** |
| pushed branch or PR | `Relevant branch/PR/diff and exact revision:` — one line, pushed-ness never stated | `Branch or PR (pushed):` | `Branch: <name> (pushed)` + `PR:` | — |
| exact revision | folded into that same line | `Exact revision:` — its own field | **absent** | — |
| explicit file boundary (in) | `Relevant files:` | `Files in scope:` | `Files in scope: <explicit list>` | — |
| explicit file boundary (out) | **absent** | `Out of scope:` | `Out of scope: <explicit list>` | — |
| verification results | **absent** | `Verification already run:` | `Verification run:` | — |
| frozen brief | **absent** (the prose fields are the brief) | `Frozen brief or question:` | `Handoff: <path to HANDOFF.md or paste…>` | — |
| return destination | absent from the template; prose routes findings to `outputs/` | `Return findings/artifacts to:` | **absent** | — |
| role / mode | implicit, in a prose sentence | `Mode: research/audit \| third opinion \| implementation` | **absent** | — |
| failed hypotheses | `What we tried (hypothesis, test, result for each attempt):` | **absent** | **absent** | — |
| write authority | one prose sentence: *"Please diagnose only; don't modify files."* | **absent** | **absent** | — |
| **model family** | **absent** | **absent** | **absent** | **absent** |
| **author of the revision under review** | **absent** | **absent** | **absent** | **absent** |

Four readings of that table, and each one is a field in the schema:

1. **The Codex template — the one behind the sharpest trigger predicate in the
   fleet — is the only one with no file boundary and no verification field.**
2. **Two rules that ADR-010 and ADR-012 both treat as load-bearing are in no
   template at all.** ADR-010 decision 5 (*"Selecting Claude or GPT inside
   Cursor or Antigravity does not satisfy"* model-family independence) cannot be
   checked against a packet that carries no family. ADR-012 decision 5 keeps the
   author/reviewer boundary explicitly out of the capability-parity sweep — and
   no template records who authored the revision under review.
3. **`cursor/README.md` contradicts itself inside one file.** Its template line
   reads `Handoff: <path to HANDOFF.md or paste from /handoff skill>`; nine
   lines later the same file says *"never ask San to paste between tools.
   Inspectable state only."* A prose contract cannot notice that.
4. **`cursor/README.md`'s `Repo: <path>` invites the exact string this repo's
   own pre-commit guard rejects.** `scripts/redline-guard.py` refuses a "local
   user path" anywhere in a commit. The packet's `repo` field is `owner/name`.

A fifth copy of the Codex template lives in a private strategy document. The
scoping brief for this work claimed it had drifted in transcription; **it has
not** — the two are byte-identical today.

This is [`SYS-018`](https://github.com/sanlee-ys/architecture/blob/main/decisions/SYS-018-provider-owned-contract-artifacts.md)'s
finding one layer up. *"Two unit tests that happen to agree are not a contract
test."* Four hand-mirrored templates that partially overlap are not a contract
either.

---

## 2. Wired is not allocated

Five harnesses on this fleet have tool-time guards wired. **Four have a lane in
ADR-010's division of labor.** The fifth, Grok Build, has guards, a telltale
seat, and — per `grok/README.md` — *"Nothing here admits Grok Build to the fleet
as a routing lane, and nothing here assigns it work."*

So `target_seat` enumerates five and `LANES` maps four, with `grok` mapped to
the empty set. A packet whose `(target_seat, role)` pair is outside that seat's
lane is not forbidden — `codex/README.md` carries a standing exception letting
Codex implement directly in this repo — it is forbidden **silently**. It must
carry `off_lane_justification` naming the role being invoked and the authority
for it. One rule covers both cases: a seat with no lane, and a seat asked for a
role outside its lane.

---

## 3. Files

| File | What it is |
|---|---|
| `packet.py` | Source of truth: rosters, the lane table, the field spec, the validator, the digest. |
| `packet.schema.json` | **Generated** from `packet.py`, closed (`additionalProperties: false`), never hand-edited. Published for consumers per `SYS-018` decision 1. |
| `compile.py` | The CLI: `new`, `check`, `dispatch`, `report`, `schema`. |
| `../../tests/test_packet_schema.py` | The schema, the refusals both directions, and the `SYS-018` staleness gate. |
| `../../tests/test_packet_dispatch.py` | Real throwaway git repos with a real bare remote; the dispatch path against a fake vendor. |

Stdlib only, matching the rest of this repo. The staleness gate lives in the
test suite rather than as a new step in `.github/workflows/ci.yml`: CI already
runs `python -m unittest discover -s tests`, so it fails in the same place, and
it avoids a second edit to a workflow file two open dependabot PRs are touching.

---

## 4. Using it

```bash
python vendors/packet/compile.py new --role review --to codex \
    --repo sanlee-ys/telltale --branch council/needs-you \
    --concern 'the ACP seat drops a late chunk as an empty column' \
    --scope 'internal/council/**' --out-of-scope 'docs/**' \
    --authored-by claude --route-reason independence \
    --repo-dir ../telltale --out packet.json

python vendors/packet/compile.py check packet.json --repo-dir ../telltale
python vendors/packet/compile.py dispatch packet.json --repo-dir ../telltale --dry-run
python vendors/packet/compile.py dispatch packet.json --repo-dir ../telltale
python vendors/packet/compile.py report
```

`check` and `dispatch` are separate verbs so `check` can run over a corpus in CI
without spawning anything, and so nothing that spends money is one typo away
from a validation run. Exit codes: `0` clean, `1` refused, `2` operator error.

### Refusals

Refusing, not warning. `SYS-017`'s corollary is blunt — *a gate that cannot
fail is theater* — and a warn-only compiler emits well-formed packets that
violate ADR-010 and reports green.

| Code | Fires when |
|---|---|
| `E-ATTEMPTS-TOO-FEW` | a `diagnose` packet carries fewer than two attempts |
| `E-SELF-REVIEW` | `authored_by == target_seat` on a review or challenge |
| `E-INDEPENDENCE-SAME-FAMILY` | `route_reason: independence` with issuer and target in the same model family |
| `E-OFF-LANE` | the `(seat, role)` pair is outside ADR-010's lane and nothing says why |
| `E-FAMILY-MISMATCH` | the declared family contradicts the harness (four of five seats settle it) |
| `E-REVIEW-WRITE` | a review or challenge packet carries write authority |
| `E-WRITE-PATHS` | `write_authority: paths` with no paths, or paths with no authority |
| `E-BRANCH-NOT-PUSHED` | `git ls-remote` does not find the branch on the remote |
| `E-REVISION-UNRESOLVABLE` | `base_revision` does not resolve to a commit |
| `E-PROMPT-TOO-LARGE` | the rendered packet exceeds the target's channel budget |
| `E-CODEX-RESUME-FLAGS` | `sandbox` or `cd` on a `codex exec resume` path |
| `E-CURSOR-GIT-BASH` | `launch_parent: git-bash` |
| `E-NO-DISPATCH-PATH` | dispatch to a seat outside phase 1 |
| `E-DIGEST` | the packet body no longer matches its own digest |
| plus the structural set | `E-MISSING-FIELD`, `E-UNKNOWN-FIELD`, `E-BAD-TYPE`, `E-BAD-ENUM`, `E-BAD-FORMAT`, `E-CONCERN-TOO-LONG`, `E-EMPTY-SCOPE` |

`--allow <CODE>` overrides a refusal, in the house style of `MASK-OK` /
`STAGE-ALL-OK` — *"the guard's job is to make that a decision rather than a
default"* — and the override is recorded **in the packet** (`overrides`) rather
than lost in a shell invocation, so it rides the digest.

**The first three are not overridable.** They are the ADR predicates this whole
exercise exists to mechanize; an override token on them would put them back
where they started, in the operator's memory.

### `branch_pushed` is a live query, never the tracking ref

`refs/remotes/origin/<branch>` — and therefore `git branch -r` — is a local
cache written by the last fetch. It will claim a branch exists on the remote
after someone deleted it. `compile.py` uses `git ls-remote`, and
`tests/test_packet_dispatch.py::test_a_stale_tracking_ref_lies` proves the
distinction by making the cache lie.

---

## 5. Measured vendor facts encoded here

Everything in this table was measured on the Windows workstation on
2026-08-09, or read from a pinned source. None of it was copied from a design
document.

| Fact | Basis |
|---|---|
| `codex exec` takes `-s/--sandbox {read-only,workspace-write,danger-full-access}`, `-C/--cd`, `--skip-git-repo-check`, `--json` | `codex exec --help`, codex-cli 0.147.0 |
| **`codex exec resume` takes neither `-s/--sandbox` nor `-C/--cd`** | `codex exec resume --help`, same build. Passing them dies at argument parsing with empty stdout — indistinguishable from a vendor that answered nothing. |
| `agy`'s `-p` is a value-taking flag, so **the prompt must be its immediate value and `-p` must be last** | `agy --help`, agy 1.1.11 (`-p` = "Short alias for --print"). The failure mode is measured in telltale's seat: `agy -p --output-format stream-json "<prompt>"` swallows the literal `--output-format` as the prompt and exits 0 with a paragraph about CLI output formats. |
| agy's prompt has **no stdin channel at all** | `echo x \| agy --output-format stream-json -p` → "flag needs an argument: -p", exit 2. |
| argv budget 24 KiB | A Windows command line caps near 32,767 UTF-16 units; telltale settled on 24 KiB for anything travelling in argv. The compiler **fails closed** on overflow and never truncates. |
| `launch_parent: git-bash` kills the Cursor lane | `cursor/README.md`, measured 2026-08-04: cursor-agent selects its bash executor but builds the hook command as a PowerShell pipeline; bash dies on the syntax and every tool call is denied. |

---

## 6. What the return carries, and where it comes from

Three sources, ranked, and the ranking is the design.

1. **Git for what happened.** `HEAD` plus a `git status --porcelain` snapshot is
   taken immediately before the spawn and again after; `files_changed` and
   `boundary_violations` come from that diff and from nowhere else. This is
   telltale's `VerifyReceipt` doctrine generalized, including its bound: a
   receipt proves change-after-start, **not authorship**. The field is therefore
   named `files_changed`, not `files_the_seat_changed` — a human or a parallel
   session editing the tree mid-dispatch lands in the same bucket.
2. **The vendor's exit code and structured stream for transport.** A stream line
   that does not parse is counted and reported once, never fatal.
3. **Free text for nothing.** Stored verbatim; never parsed into a claim.

`boundary_violations` = `files_changed` minus what the packet **licensed**, and
the licensing set is `write_paths` and only `write_paths`. `files_in_scope` is a
*reading* boundary: it says where to look, not where to write. So a change to an
in-scope file under `write_authority: none` is a violation, loudly. (The scoping
brief proposed `files_changed − (write_paths ∪ files_in_scope)`; that union
quietly hands a review packet a write licence it never asked for, and write
authority is declared, never inferred.)

`write_authority: workspace` licenses the whole tree and therefore produces no
violations *by construction* — reported as such rather than as a zero that
looks like a clean run.

Returns land in `~/.agent-ops/packets/<packet_id>/`, mode `0700`, outside any
git tree — the same containment telltale's artifact store uses, and for the
same reason: a returned finding must not be one `git add -A` away from being
published.

---

## 7. What this is not

**It does not close `SYS-022`'s `state consistency` row, and the write-up must
not say it does.** A JSON schema plus a subprocess is not a work-graph runtime.
After this change the council room is still last-save-wins, the seat roster is
still fixed at four lanes, dynamic node spawning is still "No" at the graph
layer, and `/arena` still has no edges. This hardens **one edge** and reports a
number about how often that edge held. `SYS-022` exists specifically to stop
this system overclaiming a runtime on the strength of a policy document, and
claiming otherwise here would reproduce that failure in code.

**It is instrumentation, not a verdict.** `compile.py report` prints the
boundary-violation rate as a number with its `n`, and gates on nothing. A floor
over a few dozen non-independent dispatches would be an aspirational floor
wearing a measured number's clothes. The honest prediction is that the rate
comes back at or near zero — the seats mostly behave, and the one recorded
catastrophe (a codex racer opening and merging a PR) happened in an unusually
permissive arena worktree, not on a normal transfer. **A measured zero honestly
reported is the finding either way.**

**It publishes less than it validates.** `packet.schema.json` carries the
structural rules. The cross-field refusals — independence, the author/reviewer
boundary, off-lane routing, the codex resume flags — are implemented in
`packet.py` and are not expressible in JSON Schema. A consumer validating with
the artifact alone gets strictly less, and the artifact says so in its own
`description`.

**It cannot verify guard wiring on the receiving machine, and does not
pretend to.** `gemini/README.md` records the bound: *"nothing in this repo can
prove a given machine deployed it."* A write-authority packet therefore carries
a fixed, honest statement instead of a probe result — that a wired hook's deny
has been measured surviving a permission bypass while the redlines have not
([`ADR-012`](../../decisions/ADR-012-capability-parity-and-the-guard-obligation.md)
decision 2 as corrected 2026-08-09), and that the packet must not be run under
a permission-bypass flag. A `guard_posture` field was designed and **dropped**
for this reason: a green cell there would invite exactly the reading ADR-012's
correction exists to forbid.

---

## 8. Phase 1 boundary

Dispatches to **codex and agy only**. Everything else compiles, validates, and
is emitted as a file — saying so is better than shipping a path that cannot
work. Cursor in particular has no batch invocation left; its seat is
conversational over ACP.

Deliberately untouched in phase 1: the four vendor READMEs still carry their
prose templates, and `telltale` is not modified. Retiring the templates in
favour of a pointer here is one commit by one session, done last, because every
vendor-facing change wants those same four files. A `telltale dispatch --packet`
mode — telltale reading this schema as a consumer and supplying argv it already
measures — is `SYS-018`'s consumer half and is the shape that removes the
duplication rather than managing it. Neither is in this change.
