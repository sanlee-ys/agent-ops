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

## settings-toggle.py — two settings, and no way to reach a third

Turning a skill off or disabling an MCP server is routine and reversible. Doing
it without a permission prompt is not: the only grant that permits it is write
access to `settings.json` as a *file*, and that same grant admits `permissions`,
`env` and `hooks` — including switching `bypassPermissions` back on. Guard
wiring is the whole of the control
([ADR-012](../decisions/ADR-012-capability-parity-and-the-guard-obligation.md)),
the guards are wired *by* `hooks`, and what may run at all is decided *by*
`permissions`. So a convenience grant shaped to allow the toggle also allows
turning the guards off. The gap is path-shaped; the fix is a program narrow
enough to allowlist by name.

It performs exactly two operations, and the harness does not keep them in one
place — so neither does the program:

| Operation | Key it writes | File |
|---|---|---|
| `--skill NAME --off` / `--on` | `skillOverrides` | `~/.claude/settings.json` |
| `--mcp-server NAME --disable` / `--enable` | `projects[P].disabledMcpServers` | `~/.claude.json` |

```
uv run python scripts/settings-toggle.py --settings PATH --skill some-skill --off
uv run python scripts/settings-toggle.py --settings PATH --skill some-skill --on
uv run python scripts/settings-toggle.py --settings PATH --mcp-server some-server --disable --project DIR
uv run python scripts/settings-toggle.py --settings PATH --mcp-server some-server --enable --project DIR
uv run python scripts/settings-toggle.py --settings PATH --show [--project DIR]
```

`--project` defaults to the current directory and must already exist in the
document — the harness creates a project's entry the first time it runs there,
and inventing one produces a key that looks right and disables nothing.
`--dry-run` prints the one-line diff and writes nothing. Exit codes are the
interface: 0 applied (or already in that state), 1 refused, 2 usage error.

Verify it actually refuses — the same decoy discipline the redline guard's
entry demands, because "the code looks right" is not the bar:

```
uv run python scripts/settings-toggle.py --settings PATH --permissions "Bash(rm:*)"
```

Expect exit 2: there is no such flag, and no flag that takes a key name at all.
Then confirm the convenience half still works, which is the "now what?" for the
check above:

```
uv run python scripts/settings-toggle.py --settings PATH --dry-run --skill some-skill --off
```

Expect exit 0 and two lines — `--- would change PATH` and the single key's
before/after. If you get more than that, or anything from `env` or `mcpServers`,
that is a bug worth reporting: see "It never prints the file" below.

### `--settings` is required, and that is the security property

**It had a default, and the default was a way around the credential guard.**
Measured 2026-08-09. The guard protecting the live Claude config is
*path-based on the command string*: it refuses `Read`, `Get-FileHash`, and any
shell command naming `~/.claude/settings.json`. A default applied inside Python
is invisible to it — so `settings-toggle.py show`, with no flag, cleared the
guard and read the live config that every other reader was blocked from. A
`set` would have written it the same way, atomically and unobserved.

That inverted the program's entire justification. It is allowlisted *because*
it is narrow; a narrow tool that is also the one thing able to reach a
guard-protected file is a bypass wearing the allowlist as a costume.

The fix is one line of argparse plus the deletion of `DEFAULT_SETTINGS`: the
path is now always in the command string, where the guard can see it and
decide. Three directions, all verified after the change:

| Invocation | Result |
|---|---|
| no `--settings` | exit 2, nothing opened — the bypass is closed |
| `--settings ~/.claude/settings.json` | blocked by the credential guard, as it should be |
| `--settings <ordinary file>` | works, no prompt |

If the guard refuses a path you genuinely need, that refusal is the operator's
to lift deliberately — not this program's to route around by defaulting.
Regression cover: `TestTargetIsAlwaysExplicit`, which asserts the constant is
*gone* rather than merely unreferenced.

The general lesson generalizes past this script:
[`conventions/allowlists-fail-both-ways.md`](../conventions/allowlists-fail-both-ways.md)
is about stale entries, but this is its mirror — **a path-based control only
sees what the command string says, so any default resolved after the check is
outside the control.** Applies to every guard in `hooks/` and to any future
tool that takes a path.

Five design points worth keeping:

- **The narrowness is structural, not configured.** Which key is writable is
  decided by the *operation*, not by the caller: `--skill` owns
  `skillOverrides` and `--mcp-server` owns `projects`, and neither can reach
  the other's. One mutation primitive (`_replace_owned`) shallow-copies the
  parsed document and assigns a single key, checked against the operation's
  owned tuple first. Every other key is carried across by reference and never
  traversed, so an unowned key cannot change even in principle. There is no
  verb that takes a key name, a key path, or a blob of JSON — so there is no
  input at all that can name `permissions`, and loosening the CLI alone does
  not widen the hole.
- **The nested write is as narrow as the flat one.** `projects` is nearly all
  of `~/.claude.json` — every project's MCP servers, allowed tools and prompt
  history. So the program shallow-copies the `projects` map, then the *one*
  addressed entry, then assigns `disabledMcpServers` on that copy, and asserts
  afterwards that no sibling project and no other key inside the entry moved.
- **The guarantee is asserted, not just argued.** Before writing, the program
  re-derives the diff between the document as parsed and the document about to
  be serialized, and refuses if anything outside the owned path differs. That
  is what the test suite can watch fail; a design argument is not.
- **Names are untrusted, and JSON is never built by concatenation.** A skill or
  server name comes from whoever composed the command line, which in an agent
  session is not necessarily a person. The document is parsed, an object is
  mutated, and `json.dump` re-serializes it, so a crafted name cannot break out
  of its string — and it is *still* refused unless it matches
  `[A-Za-z0-9 _.-]{1,128}`. **Known gap:** that charset excludes `:` and `/`,
  so a plugin-scoped skill (`plugin:skill`) cannot be named. Widening a
  security-relevant validation is an operator decision, left open deliberately.
- **It refuses rather than guesses, and keeps the original.** Invalid JSON, a
  non-object document, a duplicate key (which `json.loads` would silently
  resolve by dropping one), a wrongly-typed owned key, a non-string in the
  server list, or an unknown project all abort with nothing written. Writes are
  atomic — temp file beside the destination, then `os.replace` — and preceded
  by a copy of the untouched original to `<name>.bak-<UTC timestamp>`. A UTF-8
  BOM, CRLF endings and the existing indentation (including a compact
  single-line `~/.claude.json`) are detected and reproduced, so a routine
  toggle does not come back as a whole-file diff.

### It never prints the file

`~/.claude.json` holds `mcpServers` blocks with API keys in their `headers`,
OAuth account details, and the full prompt history of every project;
`settings.json` holds `env`. And stdout here is read by the *agent* that ran the
command. So the program prints only the specific key it is changing — a
one-line before/after for a skill, a `+ "name"` delta for a server — and never
the document, not even under `--dry-run`, and not even in a refusal (an unknown
`--project` reports a count of known entries, never their paths). A helper that
dumps the file to stdout would defeat the guard it exists to work alongside.
`TestNothingLeaks` is the regression cover.

The backup's name is load-bearing for the same reason. The credential guard's
sensitive-file pattern is suffix-tolerant and already recognises
`settings.json.bak-20260806`, so `<name>.bak-<stamp>` inherits the same
protection as its original. A differently-named copy would be an unguarded
plaintext duplicate of a credential-bearing file sitting right beside it — the
laundering shape closed in the guard by PR #74.

Test suite: `tests/test_settings_toggle.py`, organised around the claim about
what the program *cannot* do rather than around its features.

### The `disabledMcpServers` half used to be inert; 2.0 moved it to where the harness looks

Kept as a record, because the failure shape is more instructive than the fix.
Version 1.0 owned `disabledMcpServers` as a **flat top-level key of
`settings.json`**. Measured against the published docs on 2026-08-09: the key is
real, but the harness reads it only from `~/.claude.json`, and the
[settings reference](https://code.claude.com/docs/en/settings) does not list it
as a `settings.json` key at all. So the toggle applied cleanly, the file
validated, the command reported success — and nothing was disabled. A silent
no-op, which is exactly the failure shape
[`conventions/agent-success-signals.md`](../conventions/agent-success-signals.md)
is about.

Pointing `--settings` at `~/.claude.json` did not rescue it either. Per the
[MCP reference](https://code.claude.com/docs/en/mcp#managing-your-servers), the
harness records that choice **per project**, nested under the project's own
entry, whereas 1.0 wrote a flat top-level array. So the fix was never a flag: it
was moving the owned key, one level down and into a different file — and the
owned key *is* the security boundary, so it waited for a reviewed decision
rather than being taken as a doc fix.

2.0 takes that decision. `--mcp-server` now owns `projects` in `~/.claude.json`
and writes `projects[P].disabledMcpServers`, with the nested trespass assertion
described above standing in for the narrowness that a flat single-key write got
for free. Two things did **not** change: `disabledMcpjsonServers` /
`enabledMcpjsonServers` — the unrelated `settings.json` keys that approve or
reject servers declared in a project's `.mcp.json` — are still **not** owned;
and `--skill` still cannot touch `projects`, nor `--mcp-server` touch
`skillOverrides`.

The generalizable bit, and the reason this section survives its own fix: **a
config write that lands in a valid-but-unread location fails green.** The file
parses, the diff looks right, the exit code is 0, and the setting does nothing.
Neither a test asserting the file was written nor a reviewer reading the diff
would catch it — only checking where the *consumer* reads from does.

## reconcile.py — the claims, against the system of record

An agent's self-report is a claim, not a record. "Opened PR #51" is the same
sentence whether the `gh` call worked, failed unread, or never ran. The decision
and its reasoning are in
[`conventions/reconcile-claims.md`](../conventions/reconcile-claims.md); this
entry is how to run it.

```
uv run python scripts/reconcile.py --repo . --since 6h
```

Repeat `--repo` for more than one clone. `--since` takes a duration (`6h`,
`90m`, `2d`, `3w`) or an ISO datetime. JSON goes to **stdout** for a comparison
to consume, a compact table to **stderr** for a person to read — so redirect
one and keep the other:

```
uv run python scripts/reconcile.py --repo . --since 6h > snapshot.json
```

Exit codes are the interface: 0 snapshot complete, 1 one or more repos failed
(the JSON still carries the ones that worked, each failure named in its entry),
2 usage error.

It reads only. It runs no command that writes, and it sends nothing anywhere.

Two design points worth keeping:

- **Branches come from `git ls-remote`, never `git branch -r`.** The second is a
  local cache of remote-tracking refs and will list a branch the remote deleted
  an hour ago. A snapshot built to catch a false claim must not be built from a
  cache that can carry one.
- **An unread repo is an ERROR, not an empty one.** A repo whose `gh` or `git`
  call failed reports the failure in its entry rather than returning no records.
  An empty result and an unread result must not look alike — that is the shape
  that would let a false claim through the very check meant to catch it.

Test suite: `tests/test_reconcile.py`. It covers the parsers and the formatter
with recorded `gh` and `git` output, so it needs no network and no repo.

## dead_rules_audit.py — is anyone following the rules?

A rule nobody follows looks exactly like a rule everybody follows, because
nothing tests prose. The decision and its limits are in
[`conventions/dead-rules-audit.md`](../conventions/dead-rules-audit.md); this
entry is how to run it.

```
uv run python scripts/dead_rules_audit.py --days 7
```

`--json` emits the same data as JSON. `--root DIR` points it at another
transcript store. Exit codes are the interface: 0 audit complete, 2 usage error.

It reads only. It writes nothing and it sends nothing anywhere.

Two design points worth keeping:

- **The number is a floor on violations, never a compliance score.** There is no
  denominator: the script cannot count the occasions on which a rule *could*
  have been broken. Absence of hits is not proof of compliance — a rule with
  zero hits may be observed, may have no detector, or may have a detector
  narrower than the rule, and all three look identical.
- **A transcript holds the whole session, so the audit never becomes a second
  copy of it.** Examples are COMMAND strings only, truncated, capped at three
  per rule; the prose detector reports counts with no examples at all, because
  its evidence is prose. `TestNothingLeaks` pins each of those from the failing
  side.

Test suite: `tests/test_dead_rules_audit.py`. Fixtures are synthetic
transcripts in a temporary directory, so the suite never reads the real session
store.

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
