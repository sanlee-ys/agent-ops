#!/usr/bin/env python3
# tool-version: 2.0 (2026-08-09)
"""Narrow-privilege editor for two harmless Claude Code settings.

WHY. Turning a skill off and disabling an MCP server are routine, reversible,
boring changes. But the only way to make them without a permission prompt is to
hold write access to ``settings.json`` as a *file* — and that same grant admits
edits to ``permissions``, ``env`` and ``hooks``. That is the whole safety
posture: guard wiring is the control (``decisions/ADR-012``), the guards are
wired *by* ``hooks``, and which tools may run at all is decided *by*
``permissions``. A convenience grant shaped to permit a skill toggle also
permits switching the guards off. The gap is path-shaped, so the fix has to be
too: a program narrow enough to be allowlisted by name, whose narrowness is a
property of the code rather than of how it is invoked.

TWO OPERATIONS, TWO FILES, TWO SHAPES. The harness does not keep these settings
in one place, so neither does this program::

    --skill NAME --off/--on          skillOverrides       ~/.claude/settings.json
    --mcp-server NAME --disable/--enable
                                     projects[P].disabledMcpServers  ~/.claude.json

The second one is nested, and that is not a detail: the harness records a
disabled server **per project**, under that project's own entry. Version 1.0 of
this program wrote a flat top-level ``disabledMcpServers`` into
``settings.json``, which validates, reports success, and disables nothing —
the silent-no-op failure shape ``conventions/agent-success-signals.md`` is
about. Fixing it required moving the owned key, which is the security boundary,
so it was held for a reviewed decision rather than taken as a doc fix.

THE CONSTRAINT, AND WHY IT HOLDS. Which top-level keys are writable is decided
by the *operation*, not by the caller: ``--skill`` owns ``skillOverrides`` and
nothing else, ``--mcp-server`` owns ``projects`` and nothing else. There is no
verb that takes a key name, a key path, or a blob of JSON, so there is no input
that can name ``permissions``. The single mutation primitive is
:func:`_replace_owned`, which shallow-copies the parsed document and assigns
*one* key, checked against the operation's owned set first. Every other key's
value is carried across by reference and never traversed, so an unowned key
cannot change even in principle.

For the nested case the same discipline runs one level deeper: the ``projects``
map is shallow-copied, then the *one* addressed project entry is shallow-copied,
then ``disabledMcpServers`` is assigned on that copy. Sibling projects, and the
addressed project's own ``mcpServers``, ``history`` and ``allowedTools``, are
carried across by reference.

Belt and braces, because "the code looks right" is not the bar in this repo:
:func:`_assert_only_owned_changed` and :func:`_assert_only_project_entry_changed`
re-derive the diff between the document as parsed and the document about to be
serialized, and refuse the write if anything outside the owned path differs.
Those checks are what make the guarantee observable rather than argued.

NAMES ARE UNTRUSTED. A skill or server name arrives from whoever composed the
command line, which in an agent session is not necessarily a person. JSON is
never built by concatenation here — the document is parsed, an object is
mutated, and ``json.dump`` re-serializes it — so a crafted name cannot break
out of its string. It is still validated against ``_NAME_RE`` before use: a
name is a name, and one containing a quote, a backslash, a brace, a bracket, a
newline or a control character is a sign of something other than a skill being
named. Refusing it costs nothing and removes a whole class of argument.

OUTPUT NEVER SHOWS THE FILE. ``~/.claude.json`` holds ``mcpServers`` blocks
with API keys in their ``headers``, OAuth account details, and the full prompt
history of every project. ``settings.json`` holds ``env``. So this program
prints only the specific key it is changing, and for the nested case only the
delta — never the document, not even under ``--dry-run``. A helper that dumps
the file to stdout would defeat the guard it exists to work alongside, since
stdout is read by the agent that invoked it.

ATOMICITY AND THE BACKUP. Writes go to a temp file beside the destination and
are moved into place with ``os.replace``, which is atomic on Windows and POSIX
alike. A live session reading the file sees either the old one or the new one,
never a truncated one. Before the write, the untouched original bytes are
copied to ``<name>.bak-<UTC timestamp>``. That suffix shape is deliberate: the
credential guard's sensitive-file pattern is suffix-tolerant and already
recognises ``settings.json.bak-20260806``, so the backup inherits the same
protection as its original instead of becoming an unguarded plaintext copy
beside it — the laundering shape closed in the guard by PR #74.

A UTF-8 BOM, CRLF line endings, and the file's existing indentation (including
a single-line compact document, which is how a large ``~/.claude.json`` tends
to be written) are detected on read and reproduced on write, so a routine
toggle does not come back as a whole-file diff.

USAGE. ``--settings PATH`` is REQUIRED and has no default — see the note above
``_MISSING`` for why that is a security property, not a UX choice::

    uv run python scripts/settings-toggle.py --settings PATH --skill some-skill --off
    uv run python scripts/settings-toggle.py --settings PATH --skill some-skill --on
    uv run python scripts/settings-toggle.py --settings PATH --mcp-server some-server --disable --project DIR
    uv run python scripts/settings-toggle.py --settings PATH --mcp-server some-server --enable --project DIR
    uv run python scripts/settings-toggle.py --settings PATH --show [--project DIR]

``--dry-run`` prints the one-line diff it would apply and writes nothing.

EXIT CODES ARE THE INTERFACE. 0 applied (or already in the requested state), 1
refused — a bad name, a bad target, an unknown project, an unreadable or
non-object document, a duplicate key — 2 usage error from the argument parser.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# The security boundary.
#
# Ownership is per-operation, not global. `--skill` can reach `skillOverrides`
# and `--mcp-server` can reach `projects`; neither can reach the other's key,
# and nothing can reach a third. Widening either tuple is a reviewed change,
# not a convenience: `permissions`, `env`, `hooks`, `disableAllHooks`,
# `apiKeyHelper`, `awsAuthRefresh` and `otelHeadersHelper` are the keys this
# program exists to stay away from.
# ---------------------------------------------------------------------------
SKILL_OWNED_KEYS = ("skillOverrides",)
MCP_OWNED_KEYS = ("projects",)

# Inside the addressed project entry, this is the only key that may differ.
PROJECT_OWNED_KEY = "disabledMcpServers"

# Every key this program can write anywhere, for documentation and for the test
# that fails if the boundary is widened without one.
OWNED_KEYS = tuple(sorted(SKILL_OWNED_KEYS + MCP_OWNED_KEYS + (PROJECT_OWNED_KEY,)))

# `off` hides a skill from the model and from `/`. The harness also accepts
# `user-invocable-only` and `name-only`, which are visibility *tuning* rather
# than the off switch this program exists to provide; a two-state flag surface
# (`--off` / `--on`) cannot express them, and adding them would mean adding a
# free-form value argument. Off, or absent. That is the whole vocabulary.
SKILL_OFF = "off"

# Basenames this program will edit, per operation. A settings file is a known
# artefact with a known name; a path that is not one of these is a typo or a
# mistake, and either way not something to rewrite. This is defence in depth
# rather than the main control — the main control is that only the owned keys
# can be written into whatever file is named.
SKILL_TARGET_BASENAMES = ("settings.json", "settings.local.json")
MCP_TARGET_BASENAMES = (".claude.json",)

# Names arrive from the command line and are used as JSON object keys and list
# elements. Letters, digits, space, underscore, dot and hyphen cover every
# skill and MCP server name the harness ships. Anything else - a quote, a
# backslash, a brace, a bracket, a newline, a control character - is refused.
# NOTE: this deliberately excludes `:` and `/`, so a plugin-scoped skill name
# (`plugin:skill`) or a directory-scoped one (`apps/web:deploy`) cannot be
# named. Widening the charset is a security decision and is left to the
# operator rather than taken here.
_NAME_MAX = 128
_NAME_RE = re.compile(r"\A[A-Za-z0-9 _.-]{1,%d}\Z" % _NAME_MAX)

# A project key is a filesystem path, so it cannot share the name charset -
# it legitimately contains `\`, `/` and `:`. It gets its own, weaker rule:
# non-empty, length-capped, and free of control characters. It is never used
# to open anything; it is only ever looked up among the keys already present
# in the document, and an unknown one is refused rather than created.
_PROJECT_MAX = 4096

# There is deliberately NO default target. `--settings` is required, and that
# is a security property rather than a UX preference.
#
# The credential guard that protects the live Claude config is *path-based on
# the command string* - it refuses `Read`, `Get-FileHash`, and any shell
# command naming `~/.claude/settings.json`. A default applied inside Python is
# invisible to it: the guard clears a command with no path in it, and this
# program then opens the very file the guard exists to protect. Measured
# 2026-08-09 - `settings-toggle.py show` with no flag read the live config
# while every other reader of that path was blocked. That made an
# allowlisted-by-name helper into a way around the guard, which is the exact
# inverse of the reason it was allowlisted.
#
# Requiring the path puts it back in the command string, where the guard can
# see it and decide. If the guard then refuses, that refusal is correct and is
# the operator's to lift - not this program's to route around by defaulting.
_MISSING = object()


class Refused(Exception):
    """A requested edit was refused. The message is shown to the operator."""


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _require_owned(key: str, owned: tuple[str, ...]) -> None:
    """Refuse any key the current operation does not own.

    The argument parser offers no way to name a key at all. This is the check
    underneath it: it holds for every caller, including a future one that does
    not go through the CLI.
    """
    if key not in owned:
        raise Refused(
            f"REFUSED: `{key}` is not a key this operation owns.\n"
            f"It can write only: {', '.join(owned)}.\n"
            "Keys such as `permissions`, `env`, `hooks` and `apiKeyHelper` are "
            "out of reach on purpose - that narrowness is the reason this "
            "program can be allowlisted at all. Edit those by hand, "
            "deliberately."
        )


def _require_valid_name(name: str, kind: str) -> str:
    """Refuse a skill or server name that is not plainly a name."""
    if not _NAME_RE.match(name):
        # The rejected name is echoed back only as a repr and only up to a
        # bounded length: an operator needs to see what was refused, and a
        # control character must not reach the terminal raw.
        shown = repr(name[: _NAME_MAX + 1])
        raise Refused(
            f"REFUSED: {shown} is not an acceptable {kind} name.\n"
            f"Allowed: letters, digits, space, underscore, dot and hyphen, "
            f"1-{_NAME_MAX} characters. Quotes, backslashes, braces, brackets, "
            "newlines and control characters are refused - a name containing "
            "one is a sign of something other than a skill or server being "
            "named."
        )
    return name


def _require_valid_project(project: str) -> str:
    """Refuse a project path that could not be a path."""
    if not project or len(project) > _PROJECT_MAX:
        raise Refused(
            "REFUSED: --project must be a non-empty path of at most "
            f"{_PROJECT_MAX} characters."
        )
    if any(ch < " " or ch == "\x7f" for ch in project):
        raise Refused(
            "REFUSED: --project contains a control character. A project key is "
            "a filesystem path; this is not one."
        )
    return project


def _require_target(path: Path, basenames: tuple[str, ...], why: str) -> Path:
    """Refuse a target whose filename is not one this operation edits."""
    if path.name not in basenames:
        raise Refused(
            f"REFUSED: {path.name} is not a file this operation edits.\n"
            f"{why} lives in: {', '.join(basenames)}.\n"
            "The path is still required in full, so a path-based guard can see "
            "it; this check only stops a typo from rewriting the wrong file."
        )
    return path


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def _parse_no_duplicates(text: str) -> Any:
    """Parse JSON, refusing a document with a duplicate key at any level.

    ``json.loads`` keeps the last of a duplicated pair and discards the rest.
    That would let this program "pass through" a key by silently deleting it,
    which is exactly the outcome the whole design is meant to rule out.
    """

    def hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        seen: set[str] = set()
        for name, _ in pairs:
            if name in seen:
                raise Refused(
                    f"REFUSED: the document contains a duplicate key `{name}`.\n"
                    "Rewriting it would silently drop one of the two. Fix the "
                    "file by hand first."
                )
            seen.add(name)
        return dict(pairs)

    return json.loads(text, object_pairs_hook=hook)


def _detect_indent(text: str) -> int | str | None:
    """Return the document's indentation, or None if it is written compact.

    A large ``~/.claude.json`` is often a single line. Re-indenting it would
    turn a one-key toggle into a whole-file diff, so the existing style wins.
    """
    for line in text.splitlines()[1:]:
        stripped = line.lstrip(" \t")
        if not stripped or stripped.startswith("}") or stripped.startswith("]"):
            continue
        lead = line[: len(line) - len(stripped)]
        if not lead:
            return None
        return "\t" if lead[0] == "\t" else len(lead)
    return None


class Document:
    """A parsed settings file, plus everything needed to write it back as-is."""

    def __init__(
        self,
        data: dict[str, Any],
        raw: bytes | None,
        had_bom: bool,
        newline: str,
        indent: int | str | None,
        trailing_newline: bool,
    ) -> None:
        self.data = data
        self.raw = raw  # original bytes, for the backup; None if no file yet
        self.had_bom = had_bom
        self.newline = newline
        self.indent = indent
        self.trailing_newline = trailing_newline


def _read(path: Path) -> Document:
    """Parse a settings file, or return an empty document if it is not there.

    A missing file reads as an empty document, so a first toggle works on a
    machine that has no settings file yet.
    """
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return Document({}, None, False, "\n", 2, True)
    except OSError as exc:
        raise Refused(f"REFUSED: cannot read {path}: {exc}") from exc

    had_bom = raw.startswith(b"\xef\xbb\xbf")
    # PowerShell 5.1 writes UTF-8 with a BOM by default, and json.loads chokes
    # on it. Read it off, and put it back on write.
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise Refused(f"REFUSED: {path} is not valid UTF-8: {exc}") from exc

    newline = "\r\n" if "\r\n" in text else "\n"

    if not text.strip():
        return Document({}, raw, had_bom, newline, 2, True)

    try:
        data = _parse_no_duplicates(text)
    except json.JSONDecodeError as exc:
        raise Refused(f"REFUSED: {path} is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise Refused(
            f"REFUSED: {path} holds a {type(data).__name__}, not a JSON "
            "object. Refusing to guess what to do with it."
        )
    return Document(
        data,
        raw,
        had_bom,
        newline,
        _detect_indent(text.replace("\r\n", "\n")),
        text.endswith("\n"),
    )


# ---------------------------------------------------------------------------
# Mutation - the only place the document changes
# ---------------------------------------------------------------------------


def _replace_owned(
    document: dict[str, Any], key: str, value: Any | None, owned: tuple[str, ...]
) -> dict[str, Any]:
    """Return a copy of `document` with exactly one owned key set or removed.

    This is the only mutation in the program. It shallow-copies, so every key
    other than `key` is carried across as the same object it came in as - there
    is no traversal that could reach one, and nothing is mutated in place.
    Passing ``None`` removes the key entirely.
    """
    _require_owned(key, owned)
    updated = dict(document)
    if value is None:
        updated.pop(key, None)
    else:
        updated[key] = value
    return updated


def _assert_only_owned_changed(
    before: dict[str, Any], after: dict[str, Any], owned: tuple[str, ...]
) -> None:
    """Refuse the write unless the top-level diff is confined to owned keys.

    :func:`_replace_owned` already makes this true by construction. Asserting
    it again turns "the code looks right" into something a test can observe
    fail, which is the standard the guards in this repo are held to.
    """
    changed = {
        name
        for name in set(before) | set(after)
        if before.get(name, _MISSING) != after.get(name, _MISSING)
    }
    trespass = sorted(changed - set(owned))
    if trespass:
        raise Refused(
            "REFUSED: the pending write would change keys this program does "
            f"not own: {', '.join(trespass)}.\n"
            "Nothing was written. This is a bug in the program, not in the "
            "settings file - please report it rather than working around it."
        )


def _assert_only_project_entry_changed(
    before: dict[str, Any], after: dict[str, Any], project_key: str
) -> None:
    """Refuse the write unless the diff inside `projects` is one entry's one key.

    The top-level check above can only say "`projects` changed", which for
    ``~/.claude.json`` is nearly the whole file - every project's MCP servers,
    allowed tools and prompt history live under it. This is the check that
    makes the nested write as narrow as the flat one.
    """
    before_projects = before.get("projects", {})
    after_projects = after.get("projects", {})
    if not isinstance(before_projects, dict) or not isinstance(after_projects, dict):
        raise Refused("REFUSED: `projects` is not an object. Nothing was written.")

    changed = {
        name
        for name in set(before_projects) | set(after_projects)
        if before_projects.get(name, _MISSING) != after_projects.get(name, _MISSING)
    }
    # Project keys are absolute paths. Report how many strayed, never which -
    # this program does not print the contents of the file.
    trespass = changed - {project_key}
    if trespass:
        raise Refused(
            f"REFUSED: the pending write would change {len(trespass)} project "
            "entr(y/ies) other than the one addressed.\n"
            "Nothing was written. This is a bug in the program, not in the "
            "settings file - please report it rather than working around it."
        )

    before_entry = before_projects.get(project_key, {})
    after_entry = after_projects.get(project_key, {})
    if not isinstance(before_entry, dict) or not isinstance(after_entry, dict):
        raise Refused("REFUSED: the project entry is not an object. Nothing written.")
    inner_changed = {
        name
        for name in set(before_entry) | set(after_entry)
        if before_entry.get(name, _MISSING) != after_entry.get(name, _MISSING)
    }
    inner_trespass = sorted(inner_changed - {PROJECT_OWNED_KEY})
    if inner_trespass:
        raise Refused(
            "REFUSED: the pending write would change keys inside the project "
            f"entry that this program does not own: {', '.join(inner_trespass)}.\n"
            "Nothing was written. This is a bug in the program, not in the "
            "settings file - please report it rather than working around it."
        )


def _next_skill_overrides(
    document: dict[str, Any], skill: str, off: bool
) -> Any:
    """Compute the new `skillOverrides` object (or None to remove the key)."""
    current = document.get("skillOverrides", {})
    if not isinstance(current, dict):
        raise Refused(
            "REFUSED: the existing `skillOverrides` is a "
            f"{type(current).__name__}, not an object. Fix it by hand first."
        )
    overrides = dict(current)
    if off:
        overrides[skill] = SKILL_OFF
    else:
        overrides.pop(skill, None)
    return overrides or None


def _resolve_project_key(projects: dict[str, Any], project: str) -> str:
    """Find the existing `projects` key that names `project`.

    An unknown project is refused rather than created. The harness writes these
    entries itself; inventing one produces a key that looks right and disables
    nothing, which is the same silent no-op this version exists to remove. The
    refusal reports a count, never the other project paths - see the note about
    output in the module docstring.
    """
    if project in projects:
        return project
    want = os.path.normcase(os.path.normpath(project))
    matches = [
        key
        for key in projects
        if isinstance(key, str)
        and os.path.normcase(os.path.normpath(key)) == want
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise Refused(
            f"REFUSED: {project} matches {len(matches)} project entries that "
            "differ only in spelling. Fix the file by hand rather than letting "
            "this program pick one."
        )
    raise Refused(
        f"REFUSED: no project entry for {project}.\n"
        f"The document has {len(projects)} project entr(y/ies), none of them "
        "this one. The harness creates the entry the first time it runs in a "
        "directory - open a session there first, or pass the exact path it "
        "recorded via --project."
    )


def _next_projects(
    document: dict[str, Any], project_key: str, server: str, disable: bool
) -> Any:
    """Compute the new `projects` map with one entry's server list changed."""
    projects = document.get("projects", {})
    if not isinstance(projects, dict):
        raise Refused(
            f"REFUSED: the existing `projects` is a {type(projects).__name__}, "
            "not an object. Fix it by hand first."
        )
    entry = projects.get(project_key, {})
    if not isinstance(entry, dict):
        raise Refused(
            f"REFUSED: the project entry is a {type(entry).__name__}, not an "
            "object. Fix it by hand first."
        )
    current = entry.get(PROJECT_OWNED_KEY, [])
    if not isinstance(current, list):
        raise Refused(
            f"REFUSED: the existing `{PROJECT_OWNED_KEY}` is a "
            f"{type(current).__name__}, not a list. Fix it by hand first."
        )
    if not all(isinstance(item, str) for item in current):
        raise Refused(
            f"REFUSED: the existing `{PROJECT_OWNED_KEY}` holds a non-string "
            "entry. Fix it by hand first."
        )

    # Rebuild from the filtered list so a pre-existing duplicate collapses to
    # one entry rather than being appended to.
    servers = [name for name in current if name != server]
    if disable:
        servers.append(server)

    updated_entry = dict(entry)
    if servers:
        updated_entry[PROJECT_OWNED_KEY] = servers
    else:
        updated_entry.pop(PROJECT_OWNED_KEY, None)

    updated_projects = dict(projects)
    updated_projects[project_key] = updated_entry
    return updated_projects


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def _serialize(document: dict[str, Any], style: Document) -> bytes:
    """Render the document back to bytes, preserving BOM, endings and indent."""
    # ensure_ascii=False so a non-ASCII value survives as itself rather than
    # coming back as an escape sequence, which would be a spurious diff.
    if style.indent is None:
        text = json.dumps(document, separators=(",", ":"), ensure_ascii=False)
    else:
        text = json.dumps(document, indent=style.indent, ensure_ascii=False)
    if style.trailing_newline:
        text += "\n"
    if style.newline != "\n":
        text = text.replace("\n", style.newline)
    return (b"\xef\xbb\xbf" if style.had_bom else b"") + text.encode("utf-8")


def _backup(path: Path, raw: bytes) -> Path:
    """Copy the untouched original beside itself, before anything is written.

    The `.bak-<timestamp>` suffix is not cosmetic. The credential guard's
    sensitive-file pattern is suffix-tolerant and already recognises
    `settings.json.bak-20260806`, so a backup named this way is protected by
    the same guard as its original. A differently-named copy would be an
    unguarded plaintext duplicate of a file full of API keys sitting next to
    it - the laundering shape the guard closed in PR #74.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.name}.bak-{stamp}")
    # An exclusive create, so two runs in the same second cannot have one
    # silently overwrite the other's backup.
    suffix = 0
    while True:
        try:
            handle = os.open(
                str(backup), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            break
        except FileExistsError:
            suffix += 1
            backup = path.with_name(f"{path.name}.bak-{stamp}.{suffix}")
    with os.fdopen(handle, "wb") as fh:
        fh.write(raw)
        fh.flush()
        os.fsync(fh.fileno())
    return backup


def _write_atomic(path: Path, payload: bytes) -> None:
    """Write via a temp file beside the destination, then os.replace.

    Beside, not in the system temp dir, so the final move is same-volume and
    therefore atomic. An in-place rewrite could be observed truncated by a live
    session reading the file at the wrong moment.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    try:
        os.chmod(tmp_name, 0o600)
    except OSError:  # best effort; a no-op on Windows
        pass
    try:
        with os.fdopen(handle, "wb") as tmp:
            tmp.write(payload)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        # Never leave a stray temp file next to a settings file.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _describe(value: Any) -> str:
    """Render one owned value for the operator, or say it is absent."""
    if value is _MISSING:
        return "(absent)"
    return json.dumps(value, ensure_ascii=False)


def _cmd_skill(args: argparse.Namespace) -> int:
    """Set `skillOverrides[name] = "off"`, or remove the key."""
    skill = _require_valid_name(args.skill, "skill")
    path = _require_target(
        Path(args.settings).expanduser(),
        SKILL_TARGET_BASENAMES,
        "`skillOverrides`",
    )
    document = _read(path)
    before = document.data

    after = _replace_owned(
        before,
        "skillOverrides",
        _next_skill_overrides(before, skill, off=args.off),
        SKILL_OWNED_KEYS,
    )
    _assert_only_owned_changed(before, after, SKILL_OWNED_KEYS)

    old = before.get("skillOverrides", {}).get(skill, _MISSING)
    new = after.get("skillOverrides", {}).get(skill, _MISSING)
    change = f'skillOverrides["{skill}"]: {_describe(old)} -> {_describe(new)}'
    return _finish(path, document, before, after, change, args.dry_run)


def _cmd_mcp(args: argparse.Namespace) -> int:
    """Add or remove a server in one project's `disabledMcpServers`."""
    server = _require_valid_name(args.mcp_server, "MCP server")
    project = _require_valid_project(args.project)
    path = _require_target(
        Path(args.settings).expanduser(),
        MCP_TARGET_BASENAMES,
        f"`{PROJECT_OWNED_KEY}`",
    )
    document = _read(path)
    before = document.data

    projects = before.get("projects", {})
    if not isinstance(projects, dict):
        raise Refused(
            f"REFUSED: the existing `projects` is a {type(projects).__name__}, "
            "not an object. Fix it by hand first."
        )
    project_key = _resolve_project_key(projects, project)

    after = _replace_owned(
        before,
        "projects",
        _next_projects(before, project_key, server, disable=args.disable),
        MCP_OWNED_KEYS,
    )
    _assert_only_owned_changed(before, after, MCP_OWNED_KEYS)
    _assert_only_project_entry_changed(before, after, project_key)

    # The delta only - never the list, which names every server the operator
    # has disabled in that project.
    verb = "+" if args.disable else "-"
    count = len(
        after["projects"][project_key].get(PROJECT_OWNED_KEY, [])
    )
    change = (
        f"projects[<project>].{PROJECT_OWNED_KEY}: "
        f'{verb} "{server}"  ({count} disabled after)'
    )
    return _finish(path, document, before, after, change, args.dry_run)


def _finish(
    path: Path,
    document: Document,
    before: dict[str, Any],
    after: dict[str, Any],
    change: str,
    dry_run: bool,
) -> int:
    """Report, then write - or report what a write would have done."""
    if before == after:
        print(f"No change: {path} is already in the requested state.")
        return 0

    if dry_run:
        print(f"--- would change {path}")
        print(change)
        return 0

    payload = _serialize(after, document)
    if document.raw is not None:
        backup = _backup(path, document.raw)
        print(f"Backed up to {backup.name}")
    _write_atomic(path, payload)
    print(f"--- changed {path}")
    print(change)
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    """Print the owned keys' current state, and nothing else from the file."""
    path = Path(args.settings).expanduser()
    document = _read(path)
    print(f"# {path}")

    if path.name in MCP_TARGET_BASENAMES:
        projects = document.data.get("projects", {})
        if not isinstance(projects, dict):
            raise Refused("REFUSED: `projects` is not an object.")
        project_key = _resolve_project_key(
            projects, _require_valid_project(args.project)
        )
        entry = projects.get(project_key, {})
        if not isinstance(entry, dict):
            raise Refused("REFUSED: the project entry is not an object.")
        servers = entry.get(PROJECT_OWNED_KEY, [])
        print(f"{PROJECT_OWNED_KEY}: {json.dumps(servers, ensure_ascii=False)}")
        return 0

    _require_target(path, SKILL_TARGET_BASENAMES, "`skillOverrides`")
    overrides = document.data.get("skillOverrides", {})
    print(f"skillOverrides: {json.dumps(overrides, ensure_ascii=False)}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Turn a skill off, or disable an MCP server for one project. "
            "Cannot write any other setting."
        )
    )
    parser.add_argument(
        "--settings",
        required=True,
        help=(
            "settings file to edit. Required, with no default, so the path is "
            "always present in the command string where a path-based guard can "
            "see it - see the note above _MISSING."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the change that would be made, and write nothing",
    )
    parser.add_argument(
        "--project",
        default=None,
        help=(
            "project directory whose MCP server list to edit; defaults to the "
            "current directory. Must already exist in the document."
        ),
    )

    # Exactly one operation. There is no verb that names a key, so there is no
    # input at all that can reach `permissions`.
    what = parser.add_mutually_exclusive_group(required=True)
    what.add_argument("--skill", metavar="NAME", help="skill to turn off or on")
    what.add_argument(
        "--mcp-server", metavar="NAME", help="MCP server to disable or enable"
    )
    what.add_argument(
        "--show",
        action="store_true",
        help="print the owned setting's current state, and nothing else",
    )

    state = parser.add_mutually_exclusive_group()
    state.add_argument(
        "--off", action="store_true", help="--skill: turn the skill off"
    )
    state.add_argument(
        "--on",
        dest="on",
        action="store_true",
        help="--skill: remove the override, restoring the default",
    )
    state.add_argument(
        "--disable",
        action="store_true",
        help="--mcp-server: disable it for the project",
    )
    state.add_argument(
        "--enable",
        action="store_true",
        help="--mcp-server: re-enable it for the project",
    )
    return parser


def _validate_combination(parser: argparse.ArgumentParser, args) -> None:
    """Reject flag combinations argparse cannot express on its own.

    Every test here is `is not None`, never truthiness: `--skill ""` is a
    *supplied* name that happens to be empty, and it must reach
    :func:`_require_valid_name` to be refused as a bad name. Treating it as
    "no skill given" sent it down the MCP branch instead, which then tripped
    over `--mcp-server` being None. Found by the empty-name case in
    `TestNamesAreValidated`.
    """
    if args.skill is not None and not (args.off or args.on):
        parser.error("--skill needs exactly one of --off or --on")
    if args.mcp_server is not None and not (args.disable or args.enable):
        parser.error("--mcp-server needs exactly one of --disable or --enable")
    if args.skill is not None and (args.disable or args.enable):
        parser.error("--skill takes --off/--on, not --disable/--enable")
    if args.mcp_server is not None and (args.off or args.on):
        parser.error("--mcp-server takes --disable/--enable, not --off/--on")
    if args.show and (args.off or args.on or args.disable or args.enable):
        parser.error("--show takes no state flag")


def main(argv: list[str] | None = None) -> int:
    # A Windows console defaults to cp1252, which raises UnicodeEncodeError on
    # any non-ASCII settings value. Nothing here is worth crashing a write for.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # already detached, or not a TTY
            pass

    parser = _parser()
    args = parser.parse_args(argv)
    _validate_combination(parser, args)
    if args.project is None:
        args.project = os.getcwd()

    try:
        if args.show:
            return _cmd_show(args)
        if args.skill is not None:
            return _cmd_skill(args)
        return _cmd_mcp(args)
    except Refused as refusal:
        sys.stderr.write(f"{refusal}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
