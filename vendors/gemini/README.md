# Gemini adapter — Google Antigravity (AGY)

Google Antigravity (`agy` / Google DeepMind) is installed and active as the Gemini-family agent adapter and contributor in the fleet.

Role in the fleet: Antigravity acts as an active contributor for autonomous software engineering, deep codebase research, complex refactoring, and multi-agent coordination across the workspace.

## Instruction-file wiring

- **Global standing instructions:** Reads `AGENTS.md` and `CLAUDE.md` in workspace root and user home directory (`~/AGENTS.md`).
- **Skills:** Loaded from `~/.gemini/antigravity-cli/builtin/skills/` and project skill directories (`.agents/skills/`).
- **Rules & Posture:** Obey global rules defined in `AGENTS.md`.

## Harness & Channel

- **Harness:** Antigravity CLI and IDE (`agy`).
- **Models:** Gemini 3.6 Flash (High) / Gemini 3.6 Pro.
- **Subagent primitives:** `invoke_subagent`, `define_subagent`, `send_message`, `manage_subagent`.

## Guard Wiring

- **Redline guard:** Pre-commit hook (`scripts/redline-guard.py`) applies on `git commit`.
- **Tool permission gating:** Enforced via CLI permission prompts and allowlists.

Adapter contract: [`../README.md`](../README.md).

