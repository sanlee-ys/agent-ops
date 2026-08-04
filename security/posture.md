# Security posture: running an agentic CLI with real credentials

This describes the layered defenses in place for running Claude Code, an
agentic CLI, on a personal machine with real credentials in reach: GitHub
tokens, API keys, SSH keys, cloud CLI credentials. It's written after four
credential exposures in the space of two days (2026-07-02 to 2026-07-04),
each documented in `incidents/` in this repo, and one proactive audit finding
that closed a fifth gap before it was exploited. The posture below is what
survived that process, not a design done up front.

Scale note: this is a single user on a single machine, not an org. There is
no *organization* — no shared secrets manager, no second reviewer, no
security team. Every control here had to work under that constraint: cheap
enough for one person to actually maintain.

**Scope warning, added 2026-08-04.** Everything below describes **Claude
Code only**. That was a fair simplification when Claude was the only harness
that wrote to disk. It no longer is: under
[`decisions/ADR-012`](../decisions/ADR-012-capability-parity-and-the-guard-obligation.md)
all four vendors read and write, and two of them
(Cursor, Antigravity) have **none** of the guards described here. So this
document's silence about the other three harnesses is now a gap rather than
a scoping choice, and its layers should be read as covering one vendor of
four. Per-vendor wiring truth lives in
[`vendors/`](../vendors/); closing the gap is tracked as the guard
obligation in ADR-012.

## Threat model

Two distinct risks, and they call for different defenses.

**1. Credential values echoed into the session transcript.** This is the
risk that actually materialized, four times. An agentic CLI's tool calls
(shell commands, file reads, its own subcommands) can return content that
includes a live secret, and that content becomes part of the conversation
transcript (visible to the model, logged, and potentially retained wherever
the session history is stored). Nothing exotic has to go wrong here: a
routine diagnostic command, a config file that happens to hold a token, or
a verification step that prints what it just registered are all sufficient.
This is the risk this document is mostly about, because it's the one with a
track record.

**2. Prompt-injection blast radius.** If the model is ever steered by
untrusted content (a file it reads, a web page, a tool result crafted by
someone else) into taking unwanted actions, the damage it can do is bounded
by what the permission allowlist lets it run without asking. This is a
containment argument, not a detection one: the allowlist is deliberately
narrow and deliberately excludes shell control-flow, so an injected
instruction can't silently chain itself into something bigger without
tripping a permission prompt. This risk has not materialized here; the
allowlist design below exists specifically to keep it that way.

Both risks matter, but the first one is the one with real incidents behind
it, so the rest of this document is organized around the four layers that
address it, in the order the failures happened.

## Layer 1: the permission allowlist (what runs unprompted)

Claude Code prompts for permission before running a command unless that
command shape is on an allowlist. The allowlist here includes the full git
verb set (including `git -C <path>` forms) and common interpreters
(`python`, `python3`, `py`) for development work.

That interpreter allowlisting is exactly what enabled one of the gaps this
posture had to close: a credential-guard hook (Layer 2) that matched literal
read commands like `cat`/`type`/`Get-Content` did nothing against
`python3 -c "open(path).read()"`, and because `python3` was already
allowlisted, that one-liner ran with no permission prompt *and* no hook
block: both layers of defense removed at once by the same allowlist entry.
See `incidents/2026-07-03-credential-guard-interpreter-bypass.md` for the
full account. The fix wasn't to de-allowlist interpreters (that would make
normal development unusable); it was to make the hook capability-based
instead of command-based, so it catches what an interpreter *does*
regardless of language. That's covered under Layer 2.

**Deliberate exclusion: shell control-flow.** `for`/`while`/`if` and command
substitution (`$(...)`) are not allowlisted, on purpose, even though they'd
make routine sweeps across many files less naggy. A loop or a substitution
can smuggle a read of a sensitive file inside a command that looks
innocuous at a glance: the risky part isn't in the part a reviewer's eye
goes to first. The standing convention instead is to emit flat, unrolled
command sequences: one command per file, each one individually inspectable
before it runs. This is a real cost (more permission prompts, more verbose
command lists) accepted deliberately in exchange for every command being
legible on its own.

**Known limit.** An allowlist bounds *what runs without asking*, not what a
command does once it's allowed to run. `python3` being allowlisted for
legitimate development work is exactly why it was available as a bypass
vector: the allowlist can't distinguish "read a source file" from "read a
credential file" by command shape alone. That distinction has to be made
downstream, by the hook.

### Layer 1 update (2026-07-12): auto mode, and an explicit deny/ask floor beneath it

Permission evaluation now runs in Claude Code's native auto mode
(`defaultMode: "auto"` with `classifyAllShell`): a classifier model reviews
each shell command and prompts only on escalation or destructive shapes.
This natively supersedes the interim fail-closed "safe command auto-allow"
PreToolUse hook built during the permission-friction investigation; that
hook is retired. The allowlist itself stays, deliberately: explicit allow
rules are a deterministic fast path evaluated before any classifier call,
and they still govern entirely in non-auto modes.

Auto mode changed one assumption this document previously relied on:
"absent from the allowlist" no longer guarantees a prompt — the classifier
decides. So the gates that used to be enforced by *omission* are now
enforced by *explicit rules*, restoring the hard guarantee (rules evaluate
deny → ask → allow, and per the documented precedence a deny survives every
permission mode, including bypass):

- **`ask` rules** pin the destructive git verbs (`reset`, `clean`,
  `branch -D`, force-push) and `rm -rf` behind a prompt in every shape
  (bare and `-C`, both shells) — a hard floor the classifier's soft
  judgment cannot loosen.
- **`deny` rules** natively mirror the credential files the guard (Layer 2)
  already blocks (`.env`, the MCP config file, SSH private keys, cloud CLI
  credentials) for the Read tool. This is a floor *beneath* the hook, not a
  replacement: documented deny rules do not reach a subprocess that
  `open()`s a file or a PowerShell reader, which is exactly why the
  interpreter-agnostic guard remains the load-bearing backstop.
- **`disableBypassPermissionsMode`** closes the one-keystroke switch into
  bypass mode. Set at user scope, this guards against an *accidental*
  toggle, not a hostile override — only managed settings would be
  un-overridable, a rigidity deliberately not adopted on a single-user
  machine (yet; recorded as an open decision).

Also evaluated and recorded: Claude Code's OS-enforced sandbox (credential
isolation, filesystem and network egress control) does not run on native
Windows — macOS/Linux/WSL2 only, per the official sandboxing docs. The
layered stack in this document is the deliberate substitute on this
platform, and network egress control is the one capability class it still
lacks; closing that gap would require a WSL2 migration, which is parked.

## Layer 2: the mechanical guard (what is blocked outright)

A `PreToolUse` hook (`credential-guard.py`, the canonical copy of which lives
in this repo) inspects tool calls before they run and blocks the ones that
would expose a credential, regardless of whether the underlying command was
otherwise allowlisted. As of the v2 rewrite (ADR-003 Phase 1) it matches
**all** tools, not a named few: coverage is keyed on whether a call's
path-bearing field targets a sensitive file, so Read, content-mode Grep, and
any not-yet-existing tool that reaches a credential path are all in scope by
construction rather than by enumeration — the structural fix for limits #1–#3
below. The exact blocked patterns, the sensitive-file list, and the
escape-hatch mechanics live in
[`security/README.md`](README.md#what-it-blocks); what belongs here is why
each category is in scope.

The guard targets whatever class of action can put a live secret's bytes on
stdout, regardless of the command used to get there: bulk environment
dumps (any credential-shaped variable currently set, printed wholesale),
full reads of known credential-store files (by any read construct in any
interpreter, not a fixed command list, since the risk is the read capability
and not the specific syntax that invokes it), `claude mcp get` (a
verification command that prints secret values by design, not by mistake),
and content-mode Grep against a sensitive file (a narrow search pattern
doesn't help if the matched line itself is the secret). A masked read for a
legitimate purpose, like a length-and-prefix check, still needs a path
through — that's the `MASK-OK` escape hatch documented in the README.

**Why this layer exists at all.** The guard was built after the first
plaintext exposure produced only a behavioral rule ("never print a
credential-shaped value unmasked") and that rule failed again within a
week, in a different command. A rule with no enforcement between two
occurrences of the same failure isn't a control, it's a hope — see the
honest lesson below.

**Known limits, found the hard way, in order:**

1. **Command-shape coverage.** The guard was first built to block specific
   command patterns from the incidents that motivated it. A verification
   step (`claude mcp get`) that nobody had enumerated yet sailed through
   the same day it was written, because the guard only recognized shapes
   it had already seen fail.
2. **Tool-shape coverage.** The guard originally only inspected
   Bash/PowerShell tool calls. Claude's own Read and Grep tools read the
   same sensitive files through a completely different code path and
   weren't in scope at all: a fourth exposure, via a tool category nobody
   had thought to add.
3. **Interpreter/capability coverage.** Even after Bash/PowerShell were
   covered, the check matched a fixed list of read commands
   (`cat`/`type`/`Get-Content`/`gc`). Any interpreter one-liner
   (`python3 -c "open(...).read()"`, equivalent forms in `node` or `perl`,
   PowerShell's `[System.IO.File]::ReadAllText(...)`) did the same thing
   under a different name and went unmatched. Found by a proactive audit
   before it was exploited, not by a fifth leak — see
   `incidents/2026-07-03-credential-guard-interpreter-bypass.md`.
4. **A path-matching boundary bug**, found while fixing #3: the sensitive-
   file pattern only matched a filename immediately preceded by a path
   separator or the start of a string, so `cat .env` or `'.npmrc'` (preceded
   by a space or a quote) went unmatched even with a real read construct
   present.
5. **An overcorrection that would have traded one failure mode for
   another.** A first draft of the interpreter fix tried "block any mention
   of a sensitive filename unless it matches a narrow existence-check
   allowlist." That's more thorough in principle, and it immediately
   blocked its own commit message for quoting the vulnerable example
   command in prose. False positives on documentation defeat a guard as
   surely as a missed bypass does — a guard nobody can use gets routed
   around. Reverted in favor of requiring an actual read construct in the
   same segment, not just a filename appearing anywhere.
6. **Duplicated logic drifting out of sync.** A separate bootstrap path
   (for provisioning a fresh machine without an existing clone to read the
   canonical hook from) embeds its own copy of the same logic. A fix to the
   canonical hook did not automatically propagate there, so a fresh machine
   could be provisioned with a guard that still had an already-fixed gap.
   The fix needed an explicit "and the other copy" step, not an assumption
   that "the hook" means one file.

Every one of these was closed by widening the guard, and every widening was
verified against a decoy credentials file holding a fake value — confirming
the new case is blocked and the previously-passing cases (existence checks,
plain non-sensitive files, prose mentions) still pass — before being
declared done. "The code looks right" was explicitly not treated as
sufficient after the first few rounds of this; see the verification
discipline note below.

## Layer 3: human-runs-credential-commands protocol

Some operations can't be made safe by better pattern-matching, because the
whole point of the operation is to place a live secret somewhere. Token
rotation and registering an MCP server with a new token both fall in this
category. For these, the rule is procedural rather than mechanical: the
human runs the command directly in his own terminal, never through the
agent's Bash/PowerShell tool. The new token then never enters a tool call,
never enters the transcript, and never has a chance to be echoed back by a
verification step afterward.

This protocol is what's left after acknowledging that a mechanical guard
can only block *reads* of secrets already at rest; it can't prevent a
secret from being typed into a command in the first place without also
blocking the legitimate registration commands that need to carry one. Some
things are safer kept off the agent's plate entirely rather than trusted to
a pattern match.

**Known limit.** This layer depends entirely on the human actually doing it.
There's no mechanical enforcement that a credential-bearing command was
run outside the agent's tools. It's a discipline, not a guard, and it only
covers the narrow set of operations recognized in advance as
credential-bearing. A registration flow that doesn't look like one at first
glance is a gap this layer doesn't catch by itself.

## Layer 4: rotation (when the layers fail anyway)

Every exposure that did happen was followed by rotating the credential,
regardless of whether misuse was confirmed. None of the four incidents
found evidence of downstream misuse, but "probably fine" was never treated
as a substitute for rotation: a token that touched a transcript is treated
as compromised, full stop. This is the layer that assumes the first three
will eventually fail again in some new shape, and makes sure that failure
is bounded to "rotate one credential," not "trust a possibly-burned one
indefinitely."

**Why rotation and not cleanup.** A secret that reached a transcript cannot be
un-leaked by fixing the file it came from. The exposure and its source are two
different artifacts: moving a token into a keystore and scrubbing the plaintext
config leaves every *prior* session's transcript on disk untouched, each one
still holding the value exactly as the command printed it. Those transcripts
are append-only history, and on a machine that syncs or backs up session
history they may exist in more than one place. So "I cleaned up the config" is
never "the secret is safe" — the config is now clean and the leaked bytes are
still sitting in the logs. The only action that actually bounds the exposure is
rotating the credential so those bytes stop being valid. This is the whole
reason Layer 4 is rotation and not redaction: you can reliably invalidate a
secret, you cannot reliably erase every copy of one. (Deleting the offending
transcript is fine hygiene, but it's cleanup *after* rotation, never instead of
it — you can't prove you got every copy.)

## Account-level guardrails (verified in the Console, 2026-07-13)

The layers above are all machine-local. The API account itself is the layer
beneath them, and its state was verified in the Console rather than assumed:
a monthly spend limit is set with an email notification below it (bounding
what a runaway loop or a leaked key can spend before a human notices), the
consumer-plan model-training toggle is confirmed off, and API keys are
scoped per consumer with expiries — one consumer still lacks its own key,
recorded here as the open item rather than rounded up to done.

One measurement surprise, kept for honesty: the classifier project's
per-call `cache_control` marker is currently inert — its cacheable prefix
sits well under the model's documented minimum cacheable-prefix floor,
confirmed live with the cache-diagnosis beta rather than inferred from
docs. "Caching enabled in code" and "caching active in production" are
different claims; only a measurement distinguishes them.

## The honest core lesson

Two things, stated plainly because dressing them up would undersell them:

**A behavioral rule that has already failed once is not a control, it's a
hope.** The first exposure produced the rule "never print a
credential-shaped value unmasked." The second exposure, six days later,
broke that exact rule in a different command. A rule with no enforcement
between two occurrences of the same failure mode has no mechanism to catch
the second occurrence; it just waits to fail again. The fix had to be
mechanical (a hook that blocks, not a reminder to be careful) precisely
because the behavioral version had already been tried and had already
failed.

**A mechanical guard is only as complete as the surface someone enumerated.**
This recurred three more times after the guard existed: a command shape
nobody had listed yet (`claude mcp get`), a whole tool category nobody had
listed yet (Read and Grep operate outside Bash/PowerShell entirely), and an
interpreter-language capability nobody had listed yet (any language's file-
read API is functionally `cat` for this purpose). Each fix closed the
specific gap found and each fix left the same category of question open:
not "what command did the last leak use" but "what are all the ways this
file's bytes could reach stdout." A command or tool enumeration is always
finite and will always trail the next new way to do the same thing. The
guard in this repo is not claimed to be complete: it's claimed to be
better than a behavioral rule, and open to the next gap being found by a
reader of this repo rather than by a fifth leak.

## Why publish this at all

Publishing a security guard's internals looks, at first glance, like
handing an attacker the map. It isn't, for the reason stated in
`decisions/ADR-001-public-claude-ops-repo.md`: the guard's value is
defense-in-depth on a single user's machine, not secrecy of its rules. Its
regex patterns describe exactly which files and read constructs it covers,
which is also, implicitly, an honest description of what it doesn't cover
yet. Anyone with local code execution on this machine has already won;
the guard was never meant to withstand that. What it's meant to do is
catch an agent's own routine, non-adversarial mistakes: the kind that
produced all four real incidents here, none of which involved an attacker.
Keeping the rules secret would mean the next uncovered gap gets found by
a fifth leak instead of by a reader. This repo bets on the reader.
