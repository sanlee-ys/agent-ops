#!/usr/bin/env python3
# tool-version: 1.0 (2026-08-09)
"""Narrow-privilege editor for two harmless Claude Code settings keys.

WHY. Toggling a skill's visibility or disabling an MCP server are routine,
reversible, boring changes. But the only way to make them without a permission
prompt is to hold write access to ``settings.json`` as a *file* — and that same
grant admits edits to ``permissions``, ``env`` and ``hooks``. That is the whole
safety posture: guard wiring is the control (``decisions/ADR-012``), the guards
are wired *by* ``hooks``, and which tools may run at all is decided *by*
``permissions``. A convenience grant shaped to permit a skill toggle also
permits switching the guards off. The gap is path-shaped, so the fix has to be
too: a program narrow enough to be allowlisted by name, whose narrowness is a
property of the code rather than of how it is invoked.

THE CONSTRAINT, AND WHY IT HOLDS. This program owns exactly the two keys in
``OWNED_KEYS`` and has no code path that can write any other. The single
mutation primitive is :func:`_replace_owned`, which shallow-copies the parsed
document and assigns *one* key — checked against ``OWNED_KEYS`` first. Every
other key's value is carried across by reference and never mutated, so an
unowned key cannot change even in principle. There is deliberately no
``set <any-key> <value>`` verb: the argument parser restricts the key to the
two literals, and :func:`_replace_owned` refuses again underneath it, so
neither a new caller nor a future edit to the CLI can widen the hole alone.

Belt and braces, because "the code looks right" is not the bar in this repo:
:func:`_assert_only_owned_changed` re-derives the diff between the document as
parsed and the document about to be serialized, and refuses the write if any
key outside ``OWNED_KEYS`` differs. That check is what makes the guarantee
observable rather than argued.

WHAT IT WILL NOT DO. Reformat the file beyond re-indenting, reorder keys, drop
unicode, resolve a duplicate key silently (it refuses — see
:func:`_parse_no_duplicates`), or write anything if the document does not parse
or is not a JSON object. It is not a hook and blocks nothing; it is a writer
that cannot reach past its own two keys.

ATOMICITY. Writes go to a temp file beside the destination and are moved into
place with ``os.replace``, which is atomic on Windows and POSIX alike. A live
session reading ``settings.json`` sees either the old file or the new one,
never a truncated one. A UTF-8 BOM and CRLF line endings are detected on read
and reproduced on write, so a file last touched by PowerShell 5.1 does not come
back as a whole-file diff.

USAGE. ``--settings PATH`` is REQUIRED and has no default — see the note above
``_MISSING`` for why that is a security property, not a UX choice::

    uv run python scripts/settings-toggle.py --settings PATH show
    uv run python scripts/settings-toggle.py --settings PATH set skillOverrides some-skill off
    uv run python scripts/settings-toggle.py --settings PATH unset skillOverrides some-skill

``--dry-run`` prints the resulting document instead of writing it.

EXIT CODES ARE THE INTERFACE. 0 applied (or already in the requested state), 1
refused — an unowned key, a bad value, an unreadable or non-object document, a
duplicate key — 2 usage error from the argument parser.

A NOTE ON ``disabledMcpServers`` — IT DOES NOT WORK, AND CANNOT BE MADE TO.
Measured against the published docs on 2026-08-09. The harness reads that key
only from ``~/.claude.json``; it is not a ``settings.json`` key, so writing it
into one disables nothing while reporting success. Nor does ``--settings
~/.claude.json`` rescue it: the harness records the choice *per project*, under
that project's own entry, and this program writes a flat top-level array. The
``settings.json`` keys that do this job are ``disabledMcpjsonServers`` /
``enabledMcpjsonServers``, scoped to servers declared in a ``.mcp.json``; they
are *not* owned here, because widening a security boundary is not a thing to do
in passing. Only ``skillOverrides`` actually takes effect. These verbs stay
because removing them means changing ``OWNED_KEYS`` — the boundary itself, and
a reviewed decision rather than a doc fix. Disable a server via the ``/mcp``
panel instead. Full record: ``scripts/README.md``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

# The entire security boundary. Adding a name here widens what an allowlisted
# invocation of this program can reach, so it is a reviewed change, not a
# convenience: `permissions`, `env`, `hooks`, `autoMode` and `statusLine` are
# the keys this exists to stay away from.
OWNED_KEYS = ("disabledMcpServers", "skillOverrides")

# `off` hides a skill from the model and from `/`; `user-invocable-only` hides
# it from the model only; `name-only` collapses its description. Sourced from
# the harness changelog (the key is not in the published settings table). If
# the harness gains a value, this tuple is the one place to update - refusing
# an unrecognised value beats writing a typo the harness silently ignores.
SKILL_OVERRIDE_VALUES = ("off", "user-invocable-only", "name-only")

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


def _require_owned(key: str) -> None:
    """Refuse any key this program does not own.

    The argument parser already restricts `key` to the owned literals. This is
    the check underneath it: it holds for every caller, including a future one
    that does not go through the CLI.
    """
    if key not in OWNED_KEYS:
        raise Refused(
            f"REFUSED: `{key}` is not a key this program owns.\n"
            f"It can read and write only: {', '.join(OWNED_KEYS)}.\n"
            "Keys such as `permissions`, `env` and `hooks` are out of reach on "
            "purpose - that narrowness is the reason this program can be "
            "allowlisted at all. Edit those by hand, deliberately."
        )


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


def _read(path: Path) -> tuple[dict[str, Any], bool, str]:
    """Return (document, had_bom, newline) for a settings file.

    A missing file reads as an empty document, so a first toggle works on a
    machine that has no settings file yet.
    """
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {}, False, os.linesep if os.name == "nt" else "\n"
    except OSError as exc:
        raise Refused(f"REFUSED: cannot read {path}: {exc}") from exc

    had_bom = raw.startswith(b"\xef\xbb\xbf")
    # PowerShell 5.1 writes UTF-8 with a BOM by default, and json.loads chokes
    # on it. Read it off, and put it back on write.
    text = raw.decode("utf-8-sig")
    newline = "\r\n" if "\r\n" in text else "\n"

    if not text.strip():
        return {}, had_bom, newline

    try:
        document = _parse_no_duplicates(text)
    except json.JSONDecodeError as exc:
        raise Refused(f"REFUSED: {path} is not valid JSON: {exc}") from exc

    if not isinstance(document, dict):
        raise Refused(
            f"REFUSED: {path} holds a {type(document).__name__}, not a JSON "
            "object. Refusing to guess what to do with it."
        )
    return document, had_bom, newline


def _replace_owned(
    document: dict[str, Any], key: str, value: Any | None
) -> dict[str, Any]:
    """Return a copy of `document` with exactly one owned key set or removed.

    This is the only mutation in the program. It shallow-copies, so every key
    other than `key` is carried across as the same object it came in as - there
    is no traversal that could reach one, and nothing is mutated in place.
    Passing ``None`` removes the key entirely.
    """
    _require_owned(key)
    updated = dict(document)
    if value is None:
        updated.pop(key, None)
    else:
        updated[key] = value
    return updated


def _assert_only_owned_changed(
    before: dict[str, Any], after: dict[str, Any]
) -> None:
    """Refuse the write unless the diff is confined to owned keys.

    :func:`_replace_owned` already makes this true by construction. Asserting
    it again turns "the code looks right" into something a test can observe
    fail, which is the standard the guards in this repo are held to.
    """
    changed = {
        name
        for name in set(before) | set(after)
        if before.get(name, _MISSING) != after.get(name, _MISSING)
    }
    trespass = sorted(changed - set(OWNED_KEYS))
    if trespass:
        raise Refused(
            "REFUSED: the pending write would change keys this program does "
            f"not own: {', '.join(trespass)}.\n"
            "Nothing was written. This is a bug in the program, not in the "
            "settings file - please report it rather than working around it."
        )


def _serialize(document: dict[str, Any], had_bom: bool, newline: str) -> bytes:
    """Render the document back to bytes, preserving BOM and line endings."""
    # ensure_ascii=False so a non-ASCII value survives as itself rather than
    # coming back as an escape sequence, which would be a spurious diff.
    text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    if newline != "\n":
        text = text.replace("\n", newline)
    return (b"\xef\xbb\xbf" if had_bom else b"") + text.encode("utf-8")


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


def _next_skill_overrides(
    document: dict[str, Any], skill: str, value: str | None
) -> Any:
    """Compute the new `skillOverrides` object (or None to remove the key)."""
    current = document.get("skillOverrides", {})
    if not isinstance(current, dict):
        raise Refused(
            "REFUSED: the existing `skillOverrides` is a "
            f"{type(current).__name__}, not an object. Fix it by hand first."
        )
    overrides = dict(current)
    if value is None:
        overrides.pop(skill, None)
    else:
        if value not in SKILL_OVERRIDE_VALUES:
            raise Refused(
                f"REFUSED: `{value}` is not a recognised skill override.\n"
                f"Accepted values: {', '.join(SKILL_OVERRIDE_VALUES)}."
            )
        overrides[skill] = value
    return overrides or None


def _next_disabled_servers(
    document: dict[str, Any], server: str, disable: bool
) -> Any:
    """Compute the new `disabledMcpServers` list (or None to remove the key)."""
    current = document.get("disabledMcpServers", [])
    if not isinstance(current, list):
        raise Refused(
            "REFUSED: the existing `disabledMcpServers` is a "
            f"{type(current).__name__}, not a list. Fix it by hand first."
        )
    servers = [name for name in current if name != server]
    if disable:
        # Rebuild from the filtered list so a pre-existing duplicate collapses
        # to one entry rather than being appended to.
        servers.append(server)
    return servers or None


def _apply(
    document: dict[str, Any], key: str, name: str, value: str | None, remove: bool
) -> dict[str, Any]:
    """Dispatch to the per-key shape and return the updated document."""
    _require_owned(key)
    if key == "skillOverrides":
        updated_value = _next_skill_overrides(document, name, None if remove else value)
    else:
        updated_value = _next_disabled_servers(document, name, disable=not remove)
    return _replace_owned(document, key, updated_value)


def _cmd_show(path: Path) -> int:
    """Print the owned keys' current state, and nothing else from the file."""
    document, _, _ = _read(path)
    visible = {key: document[key] for key in OWNED_KEYS if key in document}
    print(f"# {path}")
    print(json.dumps(visible, indent=2, ensure_ascii=False))
    return 0


def _cmd_edit(args: argparse.Namespace) -> int:
    """Apply one owned-key edit, verify the diff, then write atomically."""
    path = Path(args.settings).expanduser()
    remove = args.command == "unset"

    if args.key == "skillOverrides" and not remove and args.value is None:
        raise Refused(
            "REFUSED: `set skillOverrides <skill>` needs a value.\n"
            f"Accepted values: {', '.join(SKILL_OVERRIDE_VALUES)}."
        )
    if args.key == "disabledMcpServers" and args.value is not None:
        raise Refused(
            "REFUSED: `disabledMcpServers` is a list of server names and takes "
            "no value. Use `set disabledMcpServers <server>` to disable one and "
            "`unset disabledMcpServers <server>` to re-enable it."
        )

    before, had_bom, newline = _read(path)
    after = _apply(before, args.key, args.name, args.value, remove)
    _assert_only_owned_changed(before, after)

    if before == after:
        print(f"No change: {path} is already in the requested state.")
        return 0

    payload = _serialize(after, had_bom, newline)
    if args.dry_run:
        # Bytes, not text: the preview is the exact payload, and a Windows
        # console defaulting to cp1252 cannot encode a non-ASCII value.
        sys.stdout.flush()
        sys.stdout.buffer.write(payload)
        return 0

    _write_atomic(path, payload)
    print(f"Updated `{args.key}` in {path}.")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read and write only the skillOverrides and disabledMcpServers "
            "keys of a Claude Code settings file."
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
        help="print the resulting document instead of writing it",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("show", help="print the owned keys' current state")

    for name, blurb in (
        ("set", "set a skill override, or disable an MCP server"),
        ("unset", "clear a skill override, or re-enable an MCP server"),
    ):
        edit = sub.add_parser(name, help=blurb)
        # `choices` is the CLI half of the boundary: there is no verb that
        # accepts an arbitrary key, so `set permissions ...` fails at parse
        # time with the owned set named in the error.
        edit.add_argument("key", choices=sorted(OWNED_KEYS))
        edit.add_argument("name", help="skill name, or MCP server name")
        edit.add_argument(
            "value",
            nargs="?",
            default=None,
            help=(
                "for skillOverrides only: "
                + ", ".join(SKILL_OVERRIDE_VALUES)
            ),
        )
    return parser


def main(argv: list[str] | None = None) -> int:
    # A Windows console defaults to cp1252, which raises UnicodeEncodeError on
    # any non-ASCII settings value. Nothing here is worth crashing a write for.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # already detached, or not a TTY
            pass

    args = _parser().parse_args(argv)
    try:
        if args.command == "show":
            return _cmd_show(Path(args.settings).expanduser())
        return _cmd_edit(args)
    except Refused as refusal:
        sys.stderr.write(f"{refusal}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
