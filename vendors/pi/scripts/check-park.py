#!/usr/bin/env python3
"""Park and drift checker for the Pi seat.

Pi is parked until Kimi. The ADR-014 amendment of 2026-08-16 declined the
interim xAI ride. A later session that puts xAI, Claude, or GPT back is a
contract break.

This script is the CI and local checker. It fails in both directions:
a forbidden backend is a fail, and a missing required file is a fail.
It must not pass because it asserted nothing.

It does not implement redline policy. It does not call the fleet guards.

Usage:
    python vendors/pi/scripts/check-park.py
    python vendors/pi/scripts/check-park.py --settings PATH --deployed PATH
    python vendors/pi/scripts/check-park.py --deployed-resources PATH --deployed-agents PATH
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

OK = 0
FAIL = 1

_MARKER = Path("security") / "credential-guard.py"
_CANONICAL_GUARD = Path("vendors") / "pi" / "extensions" / "fleet-guard.ts"
_CANONICAL_RESOURCES = Path("vendors") / "pi" / "extensions" / "fleet-resources.ts"
_CANONICAL_AGENTS = Path("vendors") / "pi" / "instructions" / "AGENTS.md"
_DEFAULT_SETTINGS = Path.home() / ".pi" / "agent" / "settings.json"
_DEFAULT_DEPLOYED_GUARD = (
    Path.home() / ".pi" / "agent" / "extensions" / "fleet-guard.ts"
)
_DEFAULT_DEPLOYED_RESOURCES = (
    Path.home() / ".pi" / "agent" / "extensions" / "fleet-resources.ts"
)
_DEFAULT_DEPLOYED_AGENTS = Path.home() / ".pi" / "agent" / "AGENTS.md"

# Forbidden defaultProvider prefixes. Each entry carries its reason.
_FORBIDDEN_PROVIDER_PREFIXES = (
    ("xai", "xAI ride is declined; Pi is parked until Kimi"),
    ("anthropic", "Claude pool behind Pi is forbidden"),
    ("openai", "GPT ride behind Pi is forbidden"),
    ("openai-codex", "Codex ride behind Pi is forbidden"),
)

# Forbidden defaultModel tokens. Each entry carries its reason.
_FORBIDDEN_MODEL_NEEDLES = (
    ("grok", "Grok model behind Pi is forbidden"),
    ("claude", "Claude model behind Pi is forbidden"),
    ("gpt-", "GPT model behind Pi is forbidden"),
    ("o1", "OpenAI o1 model behind Pi is forbidden"),
    ("o3", "OpenAI o3 model behind Pi is forbidden"),
    ("o4", "OpenAI o4 model behind Pi is forbidden"),
)

# Family match, not an exact-string allowlist. The README cutover says
# "kimi-coding or the provider id Pi shows at login" and "the kimi-k3 id
# Pi lists", so the exact ids are not known before cutover. An exact
# match would call the runbook's own end state a FAIL and train the
# operator to ignore a red park check. The forbidden needles above stay
# the hard fail.
_ALLOWED_PROVIDER_PREFIX = "kimi"
_ALLOWED_MODEL_NEEDLE = "kimi"

_SETTINGS_NAME = "SETTINGS PARK"
_GUARD_NAME = "GUARD COPY DRIFT"
_RESOURCES_NAME = "RESOURCES COPY DRIFT"
_AGENTS_NAME = "AGENTS COPY DRIFT"


def resolve_repo_root() -> Path | None:
    """Return the agent-ops root, or None when the marker file is absent."""
    env = os.environ.get("AGENT_OPS_ROOT")
    if env:
        candidate = Path(env).expanduser()
        if (candidate / _MARKER).is_file():
            return candidate.resolve()
    here = Path(__file__).resolve().parent
    for folder in (here, *here.parents):
        if (folder / _MARKER).is_file():
            return folder
    return None


def resolve_settings_path(cli_path: Path | None) -> Path | None:
    """Return the settings path the operator named, or the default file."""
    if cli_path is not None:
        return cli_path.expanduser()
    env = os.environ.get("PI_SETTINGS")
    if env:
        return Path(env).expanduser()
    if _DEFAULT_SETTINGS.is_file():
        return _DEFAULT_SETTINGS
    return None


def _sha256_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_field(document: dict, key: str) -> tuple[str | None, str | None]:
    """Return (value, error). None value means the key is absent or empty."""
    if key not in document:
        return None, None
    value = document[key]
    if value is None:
        return None, None
    if not isinstance(value, str):
        return None, f"{key} must be a string"
    stripped = value.strip()
    if not stripped:
        return None, None
    return stripped, None


def _provider_reason(provider: str) -> str | None:
    folded = provider.casefold()
    for prefix, why in _FORBIDDEN_PROVIDER_PREFIXES:
        if folded.startswith(prefix):
            return (
                f"defaultProvider {provider!r} is a forbidden backend ({why})"
            )
    if not folded.startswith(_ALLOWED_PROVIDER_PREFIX):
        return f"defaultProvider {provider!r} is not a parked backend"
    return None


def _model_reason(model: str) -> str | None:
    folded = model.casefold()
    for needle, why in _FORBIDDEN_MODEL_NEEDLES:
        if needle in folded:
            return (
                f"defaultModel {model!r} contains forbidden token "
                f"{needle!r} ({why})"
            )
    if _ALLOWED_MODEL_NEEDLE not in folded:
        return f"defaultModel {model!r} is not a parked model"
    return None


class Reporter:
    """Print one PASS or FAIL line per check. Track whether any check ran."""

    def __init__(self) -> None:
        self.failed = False
        self.ran = 0

    def report(self, name: str, ok: bool, reason: str) -> None:
        self.ran += 1
        if not ok:
            self.failed = True
        status = "PASS" if ok else "FAIL"
        print(f"{name}: {status} {reason}")


def check_settings(path: Path | None, allow_missing: bool, reporter: Reporter) -> None:
    if path is None or not path.is_file():
        if allow_missing:
            return
        if path is None:
            reporter.report(
                _SETTINGS_NAME,
                False,
                "settings file is missing",
            )
            return
        reporter.report(
            _SETTINGS_NAME,
            False,
            f"settings file is missing: {path}",
        )
        return

    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        reporter.report(
            _SETTINGS_NAME,
            False,
            f"settings file is not valid JSON: {exc}",
        )
        return

    if not isinstance(document, dict):
        reporter.report(
            _SETTINGS_NAME,
            False,
            "settings file must be a JSON object",
        )
        return

    provider, err = _text_field(document, "defaultProvider")
    if err:
        reporter.report(_SETTINGS_NAME, False, err)
        return
    model, err = _text_field(document, "defaultModel")
    if err:
        reporter.report(_SETTINGS_NAME, False, err)
        return

    if provider is not None:
        why = _provider_reason(provider)
        if why:
            reporter.report(_SETTINGS_NAME, False, why)
            return
    if model is not None:
        why = _model_reason(model)
        if why:
            reporter.report(_SETTINGS_NAME, False, why)
            return

    if provider is None and model is None:
        reporter.report(
            _SETTINGS_NAME,
            True,
            "defaultProvider and defaultModel are absent",
        )
        return
    if provider is None:
        reporter.report(
            _SETTINGS_NAME,
            True,
            f"defaultProvider is absent and defaultModel is {model!r}",
        )
        return
    if model is None:
        reporter.report(
            _SETTINGS_NAME,
            True,
            f"defaultProvider is {provider!r} and defaultModel is absent",
        )
        return
    reporter.report(
        _SETTINGS_NAME,
        True,
        f"parked provider {provider!r} and model {model!r}",
    )


def check_copy(
    name: str, canonical_rel: Path, deployed: Path, reporter: Reporter
) -> None:
    """Fail if either side of a deployed pair is missing or the hashes differ."""
    root = resolve_repo_root()
    if root is None:
        reporter.report(
            name,
            False,
            "repo root is missing",
        )
        return

    canonical = root / canonical_rel
    if not canonical.is_file():
        reporter.report(
            name,
            False,
            f"canonical file is missing: {canonical}",
        )
        return
    if not deployed.is_file():
        reporter.report(
            name,
            False,
            f"deployed copy is missing: {deployed}",
        )
        return

    if _sha256_bytes(canonical) != _sha256_bytes(deployed):
        reporter.report(
            name,
            False,
            "deployed copy bytes differ from canonical",
        )
        return
    reporter.report(name, True, "SHA-256 matches")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail if the Pi seat left park or a deployed Pi copy drifted."
        )
    )
    parser.add_argument(
        "--settings",
        type=Path,
        default=None,
        help="Pi settings.json path (default: PI_SETTINGS or ~/.pi/agent/settings.json)",
    )
    parser.add_argument(
        "--deployed",
        type=Path,
        default=None,
        help="Deployed fleet-guard.ts path (default: ~/.pi/agent/extensions/fleet-guard.ts)",
    )
    parser.add_argument(
        "--deployed-resources",
        type=Path,
        default=None,
        help=(
            "Deployed fleet-resources.ts path "
            "(default: ~/.pi/agent/extensions/fleet-resources.ts)"
        ),
    )
    parser.add_argument(
        "--deployed-agents",
        type=Path,
        default=None,
        help="Deployed AGENTS.md path (default: ~/.pi/agent/AGENTS.md)",
    )
    parser.add_argument(
        "--allow-missing-settings",
        action="store_true",
        help="Skip the settings check when the settings file is absent.",
    )
    args = parser.parse_args(argv)

    reporter = Reporter()
    settings_path = resolve_settings_path(args.settings)
    check_settings(settings_path, args.allow_missing_settings, reporter)

    deployed_guard = (
        args.deployed.expanduser()
        if args.deployed is not None
        else _DEFAULT_DEPLOYED_GUARD
    )
    deployed_resources = (
        args.deployed_resources.expanduser()
        if args.deployed_resources is not None
        else _DEFAULT_DEPLOYED_RESOURCES
    )
    deployed_agents = (
        args.deployed_agents.expanduser()
        if args.deployed_agents is not None
        else _DEFAULT_DEPLOYED_AGENTS
    )
    check_copy(_GUARD_NAME, _CANONICAL_GUARD, deployed_guard, reporter)
    check_copy(
        _RESOURCES_NAME, _CANONICAL_RESOURCES, deployed_resources, reporter
    )
    check_copy(_AGENTS_NAME, _CANONICAL_AGENTS, deployed_agents, reporter)

    if reporter.ran == 0:
        reporter.report(
            "PARK CHECK",
            False,
            "no checks ran",
        )
    return FAIL if reporter.failed else OK


if __name__ == "__main__":
    sys.exit(main())
