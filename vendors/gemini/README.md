# Antigravity adapter (Gemini family)

Google Antigravity (`agy`) is the active consumer Gemini-family harness in the
fleet. Gemini CLI remains relevant only for Gemini Code Assist
Standard/Enterprise or API-key use; it is not the consumer subscription
surface.

Role in the fleet (ADR-010): Antigravity is a **measured experimental and
overflow lane**, not a co-primary implementer. Default uses are parallel
read-only research, broad audits, browser/Google-stack work, and a Gemini
third opinion when Claude and Codex disagree.

An implementation prototype is allowed only in a disposable worktree with
explicit review. Consequential, credential-adjacent, and published-history
writes stay out of this lane until tool-time guard parity or a documented
equivalent exists.

## Operating rule

> Claude owns implementation and integration; Codex owns independent
> consequential challenge/review; Cursor owns bounded IDE/UI work;
> Antigravity supplies measured Gemini research, overflow, and third-opinion
> value; San verifies against live repository state.

### Anti-routing

- Do not route a long refactor to Antigravity merely to exercise the
  subscription.
- Do not use Claude or GPT inside Antigravity when model-family diversity is
  the reason for the handoff.
- Do not let Antigravity and another writer touch the same file or generated
  artifact in parallel.
- Do not use an Antigravity self-report as the verifier for its own prototype.

## Instruction-file wiring

- **Global standing instructions:** `~/AGENTS.md`.
- **Project instructions:** workspace-root `AGENTS.md` and `CLAUDE.md`.
- **Skills:** built-ins plus project `.agents/skills/`.

The global file is hand-mirrored across harnesses. Treat it like a shared
block: verify the compact fleet pointer and worktree instructions rather than
assuming another product's syntax applies here.

## Harness and channel

- **Harness:** Antigravity CLI and IDE (`agy`).
- **Models:** Gemini Flash/Pro for this lane; model identifiers evolve.
- **Subagent primitives:** `invoke_subagent`, `define_subagent`,
  `send_message`, and `manage_subagent`.
- **Inbound, headless:** `agy -p "<prompt>"` (aliases `--print` and
  `--prompt`), with `--output-format text|json|stream-json` when a caller
  needs structured capture.
- **Permissions:** headless reads/writes inside the active workspace may be
  allowed while commands that require confirmation are soft-denied unless
  policy grants them. Never use a permission-bypass flag as fleet wiring.

## Transfer packet

```text
Repo:
Branch or PR (pushed):
Exact revision:
Concern:
Mode: read-only research | third opinion | disposable prototype
Files in scope:
Out of scope:
Frozen brief or question:
Verification already run:
Return findings/artifacts to:
```

The source of truth is the branch, PR, diff, and exact revision. Findings go
to an inspectable file; San is never asked to relay prose between harnesses.

## Guard wiring

| Fleet policy | Antigravity |
|---|---|
| `credential-guard.py` | **Not wired** |
| `git-staging-guard.py` | **Not wired** |
| `published-history-guard.py` | **Not wired** |
| `redline-guard.py` (pre-commit) | Applies when the target repo has the hook |

The current fleet configuration also has a permissive command posture.
Behavioral instructions are not equivalent to the missing controls; this is
why the default lane is read-only and prototypes are disposable.

## Telltale

Antigravity is live in both telltale surfaces:

- the statusline reads vendor-reported model, context, quota buckets, agent
  state, branch, and folder from the documented stdin payload;
- the HUD reads session metadata from the on-disk corpus but does not invent
  quota or cost fields the store does not persist.

Telltale observes this lane. It does not decide when to invoke it.

## Delegation level

- Read-only research/audit: L1 autonomous with an inspectable report.
- Third opinion at a real fork: L0; San rules the decision.
- Disposable prototype against a frozen contract: L1 only when deterministic
  verification exists and a different agent integrates it.
- Broad subagent fan-out: L2 with an explicit scope/cap and one integrator.

Rationale: [`ADR-010`](../../decisions/ADR-010-claude-led-four-vendor-orchestration.md).
Adapter contract: [`../README.md`](../README.md).

