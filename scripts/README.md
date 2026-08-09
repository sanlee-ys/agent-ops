# scripts

## herdr-awareness-check — does herdr still understand Claude Code?

Herdr decides whether an agent is working or idle by regex-matching Claude
Code's *cosmetics* — a braille spinner in the terminal title, literal strings
like `esc to interrupt`. Nothing Claude Code reports is authoritative
([ADR-005](../decisions/ADR-005-herdr-persistence-not-agent-awareness.md)), so
the two sides can drift apart. When they do, herdr does not error. It reports a
confident, wrong `idle`.

This compares Claude Code's version against the cached detection manifest and
the fetch's own health, and says so when they diverge. Install and login-hook
instructions are in the script header:

```
install -m 755 scripts/herdr-awareness-check ~/.local/bin/
```

Two design points worth keeping:

- **On drift it deliberately does not update its baseline**, so the warning
  persists until the pairing has been verified by hand and explicitly acked with
  `--ack`. A check that silently accepts the new state on first sight is a check
  that fires once and then lies.
- **Exit 3 means "not applicable"**, distinct from exit 2 "fault", so the login
  hook stays quiet on a host where herdr was never installed rather than
  training you to ignore it.

It compares the *inputs* to detection and cannot prove detection is correct.
Ground truth needs a functional probe driving a pane through a known
working→idle cycle. Not built.

## check-generated-drift.py — stale build output, caught in CI

For any repo that commits build output next to its source (a static site's
`index.html`, a generated SVG): rebuild from source, fail if the committed
output drifted. Generalizes learning-notes' repo-local `generated-files` job
per the [ADR-003 backlog disposition](../decisions/ADR-003-delegation-maturity.md).
The per-repo variables — build commands + watched paths — live in the consumer
repo's `.generated-drift.toml`:

```toml
[check.site]
build = ["python build_site.py", "python build_graph.py"]
watch = ["index.html", "concept-map.html", "assets/category-map.svg"]
```

Run locally from the consumer's root
(`python path/to/check-generated-drift.py`), or wire CI with one job via the
reusable workflow:

```yaml
jobs:
  generated-drift:
    uses: sanlee-ys/agent-ops/.github/workflows/generated-drift.yml@main
    # with:
    #   setup: pip install -r requirements.txt   # only if the build needs deps
```

Exit codes are the interface: 0 clean, 1 drift (rebuild and commit), 2
operator/config error (dirty watched path before the build, broken build
command, missing config). Test suite: `tests/test_generated_drift.py`.

## settings-toggle.py — two settings keys, and no way to reach a third

Flipping a skill's visibility or disabling an MCP server is routine and
reversible. Doing it without a permission prompt is not: the only grant that
permits it is write access to `settings.json` as a *file*, and that same grant
admits `permissions`, `env` and `hooks` — including switching
`bypassPermissions` back on. Guard wiring is the whole of the control
([ADR-012](../decisions/ADR-012-capability-parity-and-the-guard-obligation.md)),
the guards are wired *by* `hooks`, and what may run at all is decided *by*
`permissions`. So a convenience grant shaped to allow the toggle also allows
turning the guards off. The gap is path-shaped; the fix is a program narrow
enough to allowlist by name.

It owns exactly two keys — `skillOverrides` and `disabledMcpServers` — and
passes everything else through untouched:

```
uv run python scripts/settings-toggle.py show
uv run python scripts/settings-toggle.py set skillOverrides some-skill off
uv run python scripts/settings-toggle.py unset skillOverrides some-skill
uv run python scripts/settings-toggle.py set disabledMcpServers some-server
uv run python scripts/settings-toggle.py unset disabledMcpServers some-server
```

`--settings PATH` targets a file other than `~/.claude/settings.json`;
`--dry-run` prints the result instead of writing it. Exit codes are the
interface: 0 applied (or already in that state), 1 refused, 2 usage error.

Verify it actually refuses — the same decoy discipline the redline guard's
entry demands, because "the code looks right" is not the bar:

```
uv run python scripts/settings-toggle.py set permissions allow "Bash(rm:*)"
```

Expect exit 2 and `invalid choice`, with the two owned keys named. Then confirm
the convenience half still works with a `--dry-run set skillOverrides`.

Three design points worth keeping:

- **The narrowness is structural, not configured.** One mutation primitive
  (`_replace_owned`) shallow-copies the parsed document and assigns a single
  key, checked against `OWNED_KEYS` first. Every other key is carried across by
  reference and never traversed, so an unowned key cannot change even in
  principle. There is deliberately no `set <any-key> <value>` verb — the
  argument parser restricts the key to two literals and the primitive refuses
  again underneath it, so loosening the CLI alone does not widen the hole.
- **The guarantee is asserted, not just argued.** Before writing, the program
  re-derives the diff between the document as parsed and the document about to
  be serialized, and refuses if any key outside `OWNED_KEYS` differs. That is
  what the test suite can watch fail; a design argument is not.
- **It refuses rather than guesses.** Invalid JSON, a non-object document, a
  duplicate key (which `json.loads` would silently resolve by dropping one), a
  wrongly-typed owned key, or an unrecognised override value all abort with
  nothing written. Writes are atomic — temp file beside the destination, then
  `os.replace` — and a UTF-8 BOM or CRLF endings are detected and reproduced,
  so a file last touched by PowerShell 5.1 does not come back as a whole-file
  diff.

Test suite: `tests/test_settings_toggle.py`, organised around the claim about
what the program *cannot* do rather than around its features.

### The `disabledMcpServers` half does not work, and cannot be pointed at a file where it would

Measured against the published docs on 2026-08-09, closing the caveat this
section used to leave open. **Writing `disabledMcpServers` into a
`settings.json` has no effect on any MCP server.** The key is real, but the
harness reads it only from `~/.claude.json`, and the
[settings reference](https://code.claude.com/docs/en/settings) does not list it
as a `settings.json` key at all. So the toggle applies cleanly, the file
validates, and nothing is disabled — a silent no-op, which is the failure shape
[`conventions/agent-success-signals.md`](../conventions/agent-success-signals.md)
is about.

Pointing `--settings` at `~/.claude.json` does **not** rescue it. Per the
[MCP reference](https://code.claude.com/docs/en/mcp#managing-your-servers), the
harness records that choice **per project** — nested under the project's own
entry — whereas this program writes a flat top-level array. A top-level
`disabledMcpServers` is not where the harness looks for any project, so the
"whichever JSON object it is pointed at" escape hatch has no target that works.
The same page states the key is unrelated to `disabledMcpjsonServers` /
`enabledMcpjsonServers`, the `settings.json` keys that approve or reject
servers declared in a project's `.mcp.json`; those two are **not** owned here,
and widening a security boundary is not something to do in passing.

Net: of the two owned keys, only `skillOverrides` actually takes effect against
`settings.json`. The `disabledMcpServers` verbs are left in place rather than
removed — removing them is a change to `OWNED_KEYS`, which is the security
boundary and a reviewed decision, not a doc fix. Until that decision is taken,
**disable an MCP server with the `/mcp` panel**, which writes the per-project
list the harness actually reads.

## redline-guard.py — the publication boundary, enforced

This repo is public **and canonical** ([ADR-002](../decisions/ADR-002-public-first-canonicality.md)):
material is written here first, so redaction happens at write time — which is
exactly where redaction mistakes happen. The guard scans every commit's staged
content for the [ADR-001](../decisions/ADR-001-public-claude-ops-repo.md)
boundary violations: credential-shaped strings, private repo names, employer
terms, private memory links, local user paths.

Install once per clone:

```
git config core.hooksPath scripts/githooks
```

Verify it actually blocks (the same decoy-file discipline the credential
guard's history demands — "the code looks right" is not the bar):

```
python -c "print('token: ghp_' + 'x'*24)" > decoy.md
git add decoy.md
git commit -m "should be blocked"   # expect: REDLINE GUARD refusal
git reset decoy.md && rm decoy.md
```

(The decoy is generated rather than written literally so this README itself
stays committable — a quoted example token would trip the very guard it
documents, which is how the credential guard's first over-broad draft died.)

Design notes, short version (long version in the script docstring and
ADR-002):

- **Identifying terms ship as SHA-256 hashes**, not literals — a guard that
  blocks private repo names can't have those names in its own public source.
- **Common-word collisions are context-gated.** Terms that are also ordinary
  English words only fire near "repo"/"repository"/"github"/"git" or inside
  an owner slug. A guard that blocks prose gets routed around.
- **Matches are echoed masked.** Printing the full matched string would be
  incident 1 all over again.
- **Override:** `REDLINE_OK=1` for one commit, consciously, with the reason
  in the commit message. **Local extensions:** an untracked `.redlines.local`
  (one term per line) adds terms without publishing them.
