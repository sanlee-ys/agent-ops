#!/usr/bin/env python3
"""The cross-vendor transfer packet: model, validator, and schema generator.

This module is the single source of truth for what a transfer packet *is*.
``packet.schema.json`` beside it is **generated from here** and never hand
edited, per [`SYS-018`] decision 1 and 3 -- the provider owns the artifact, and
a stale artifact turns the provider's own build red
(`tests/test_packet_schema.py`).

Why this exists, in one paragraph
---------------------------------
[`ADR-010`] decision 7 says transfers cross the harness boundary as inspectable
state: "a frozen brief, explicit file boundary, pushed branch or PR, exact
revision, and verification results". That rule is instantiated as three prose
templates in three vendor READMEs, and they do not agree with each other about
which of those five things is a field (see `README.md` in this directory for
the re-derived table). Two unit tests that happen to agree are not a contract
test ([`SYS-018`]); three prose templates that happen to overlap are not a
contract either.

What this module does and does not do
-------------------------------------
It types the packet and refuses malformed ones. It is **not** a work-graph
runtime, and nothing here changes the `state consistency` row of
[`SYS-022`]'s mechanization table. See `README.md`, "What this is not".

Structural rules live here and are expressible in the published JSON Schema.
Cross-field rules also live here (``validate``) because a consumer that only
runs the JSON Schema gets less; that bound is stated rather than hidden.
Environmental rules -- is the branch actually on the remote, does the revision
resolve -- need git and live in ``compile.py``.

Stdlib only, like every other script in this repo.

[`ADR-010`]: ../../decisions/ADR-010-claude-led-four-vendor-orchestration.md
[`ADR-012`]: ../../decisions/ADR-012-capability-parity-and-the-guard-obligation.md
[`SYS-018`]: https://github.com/sanlee-ys/architecture/blob/main/decisions/SYS-018-provider-owned-contract-artifacts.md
[`SYS-022`]: https://github.com/sanlee-ys/architecture/blob/main/decisions/SYS-022-org-graph-and-the-mechanization-split.md
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass

PACKET_VERSION = "1.0.0"

# --------------------------------------------------------------------------
# Rosters
# --------------------------------------------------------------------------

# Every harness on this fleet with tool-time guards wired. FIVE, not four.
#
# This is deliberately NOT the same set as ADR-010's division of labor, and
# keeping the two apart is the point of `LANES` below. `vendors/README.md`
# says it plainly for Grok Build: "Guard wiring only, not a routing lane...
# admitting it to the fleet would be a separate decision." A seat can be
# dispatchable without having a lane role. Wired is not allocated.
SEATS = ("claude", "codex", "cursor", "agy", "grok")

# The routing axis that is NOT the harness (ADR-010 decision 5). Selecting
# Claude or GPT inside Cursor or Antigravity changes tools, not judgment.
MODEL_FAMILIES = ("anthropic", "openai", "google", "xai", "composer")

# Which family a harness is, when the harness settles it. Cursor is absent on
# purpose: its first-party pool is Composer/Grok and its third-party pool is
# Claude/GPT (`vendors/cursor/README.md`, "Prefer Cursor's first-party
# Composer/Grok pool"), so the harness does not determine the family and the
# packet must declare it. That gap IS ADR-010 decision 5's failure mode, so
# the compiler refuses to guess rather than filling in a plausible value.
SEAT_FAMILY = {
    "claude": "anthropic",
    "codex": "openai",
    "agy": "google",
    "grok": "xai",
}

ROLES = ("implement", "review", "challenge", "diagnose", "research", "verify")

ROUTE_REASONS = ("independence", "capacity", "surface-fit", "third-opinion")

WRITE_AUTHORITY = ("none", "paths", "workspace")

# ADR-010's division of labor, read as a role table.
#
# This table is a *reading* of a prose ADR and it is the one thing in this
# module a reviewer should push back on first. Each entry cites the sentence
# it came from; nothing was inferred from vibes:
#
#   claude  -- decision 1: "control plane, default implementer, and final
#             integrator". Review is included because the integrator reviews
#             what lands; when independence is the reason for the handoff,
#             `route_reason: independence` bites instead.
#   codex   -- decision 2, verbatim: "challenges consequential designs,
#             reviews consequential diffs read-only, and diagnoses after two
#             failed hypothesis-driven attempts or visible looping".
#   cursor  -- decision 3: "bounded edit-test loops and browser/UI
#             verification".
#   agy     -- decision 4 as amended by ADR-012, plus
#             `vendors/gemini/README.md`: research, broad audits (review),
#             third opinion (challenge), and "implementation against a frozen
#             contract: L1 when a deterministic verifier covers it".
#   grok    -- EMPTY, and that is the whole point. `vendors/grok/README.md`:
#             "Nothing here admits Grok Build to the fleet as a routing lane,
#             and nothing here assigns it work."
#
# An off-lane pair is not forbidden -- `vendors/codex/README.md` carries a
# standing repo exception letting Codex implement directly in agent-ops. It
# is forbidden *silently*: the packet has to say what role it is invoking and
# on whose authority (`off_lane_justification`).
LANES = {
    "claude": frozenset({"implement", "research", "verify", "review"}),
    "codex": frozenset({"challenge", "review", "diagnose"}),
    "cursor": frozenset({"implement", "verify"}),
    "agy": frozenset({"research", "review", "verify", "challenge", "implement"}),
    "grok": frozenset(),
}

# --------------------------------------------------------------------------
# Per-vendor invocation facts
# --------------------------------------------------------------------------

# Measured on this workstation 2026-08-09, not read off a design brief.
#
#   codex-cli 0.147.0  -- `codex exec --help` lists `-s, --sandbox
#     <read-only|workspace-write|danger-full-access>`, `-C, --cd <DIR>`,
#     `--skip-git-repo-check` and `--json`. `codex exec resume --help` lists
#     `--skip-git-repo-check` and `--json` but carries NEITHER `-s/--sandbox`
#     NOR `-C/--cd`. A packet that puts those on a resume path dies at
#     argument parsing with empty stdout, which reads like a silent vendor
#     failure rather than an operator error.
#   agy 1.1.11 -- `agy --help` shows `-p` as "Short alias for --print" and
#     `--print` as a value-taking flag, so the prompt is the value that
#     immediately follows `-p` and `-p` must be LAST. telltale measured the
#     failure mode directly (`internal/council/vendors/agy.go`): `agy -p
#     --output-format stream-json "<prompt>"` swallows the literal string
#     "--output-format" as the prompt, returns a paragraph about CLI output
#     formats, and exits 0. It fails silently, which is why it is encoded
#     rather than remembered.
CODEX_SANDBOXES = ("read-only", "workspace-write", "danger-full-access")
AGY_OUTPUT_FORMATS = ("text", "json", "stream-json")

# Cursor is not dispatched in phase 1 (it is Conversational over ACP; there is
# no batch invocation left). The enum is still carried because the measured
# Windows failure is a *launch environment* fact worth being legible in a
# packet rather than invisible: `vendors/cursor/README.md` records that a
# Git-Bash-parented cursor-agent "selects its bash executor but builds the
# hook command as a PowerShell pipeline -- bash dies on the syntax, exit 2,
# and every tool call is denied. Fail-closed: safe, but the lane is dead."
CURSOR_LAUNCH_PARENTS = ("powershell", "cmd", "git-bash", "posix-shell")

# How the rendered packet reaches the seat, and what that channel costs.
#
# The cap is a WINDOWS property, not a vendor property: a command line caps
# near 32,767 UTF-16 code units, so telltale settled on a 24 KiB ceiling for
# anything that has to travel in argv (`internal/council/brief.go`: "agy...
# does not accept a prompt on stdin, so its brief travels in argv, and Windows
# caps a command line at roughly 32K"). Fail closed on overflow, never
# truncate -- a packet clipped in half is worse than none, because the seat
# acts on a partial boundary while the log records it as briefed.
#
#   agy   -- argv is the ONLY channel offered. `echo x | agy --output-format
#           stream-json -p` fails with "flag needs an argument: -p" (exit 2);
#           agy never reads stdin for the prompt. No workaround exists short
#           of upstream adding stdin support.
#   codex -- argv here because that is the sanctioned phase-1 dispatch shape.
#           `codex exec --help` documents a positional `[PROMPT]` where "If
#           `-` is used, read from stdin", and telltale's seat uses the stdin
#           form. That escape hatch removes the cap for this seat entirely and
#           is the obvious phase-2 change; it is not taken here because the
#           dispatch shape was specified, and quietly swapping the channel
#           would make the compiler disagree with the contract it publishes.
#
# These are compiler constants rather than packet fields on purpose. A
# declared channel can disagree with the binary; a constant beside a citation
# cannot.
ARGV_BUDGET = 24 << 10

PROMPT_CHANNEL = {
    "codex": ("argv", ARGV_BUDGET),
    "agy": ("argv", ARGV_BUDGET),
    "claude": ("stdin", None),
    "cursor": ("acp", None),
    "grok": ("stdin", None),
}

# Phase 1 dispatches to these and no others. Everything else compiles,
# validates, and is emitted as a file.
DISPATCHABLE = ("codex", "agy")

# --------------------------------------------------------------------------
# Refusals
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Refusal:
    code: str
    message: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.code}: {self.message}"


# The three predicates this whole exercise exists to mechanize. ADR-010 and
# ADR-012 state them as prose thresholds enforced by an agent remembering
# them; here they are exit codes. They are deliberately NOT overridable --
# an override token on these would reintroduce exactly the memory-enforcement
# the packet replaces. Every other refusal takes `--allow <CODE>`, in the
# house style of MASK-OK / STAGE-ALL-OK (ADR-007): the guard's job is to make
# it a decision rather than a default.
NON_OVERRIDABLE = frozenset({
    "E-ATTEMPTS-TOO-FEW",       # ADR-010 decision 2: two failed attempts
    "E-SELF-REVIEW",            # ADR-012 decision 5: author/reviewer boundary
    "E-INDEPENDENCE-SAME-FAMILY",  # ADR-010 decision 5: the two routing axes
})

# --------------------------------------------------------------------------
# Field specification
# --------------------------------------------------------------------------

RE_ULID = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
RE_SHA1 = re.compile(r"^[0-9a-f]{40}$")
RE_SHA256 = re.compile(r"^[0-9a-f]{64}$")
RE_REPO = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
RE_RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)

CONCERN_MAX = 160

_STR = {"type": "string"}
_STRLIST = {"type": "array", "items": {"type": "string"}}


def _enum(values):
    return {"type": "string", "enum": list(values)}


# (name, json-schema fragment, required?) for the mandatory core.
CORE = [
    ("packet_version", {"type": "string", "const": PACKET_VERSION}, True),
    ("packet_id", {"type": "string", "pattern": RE_ULID.pattern}, True),
    ("issued_at", {"type": "string", "pattern": RE_RFC3339.pattern}, True),
    ("issuer_seat", _enum(SEATS), True),
    ("target_seat", _enum(SEATS), True),
    ("target_model_family", _enum(MODEL_FAMILIES), True),
    ("role", _enum(ROLES), True),
    ("route_reason", _enum(ROUTE_REASONS), True),
    ("off_lane_justification", {"type": ["string", "null"]}, False),
    ("repo", {"type": "string", "pattern": RE_REPO.pattern}, True),
    ("branch", {"type": "string", "minLength": 1}, True),
    ("branch_pushed", {"type": "boolean"}, True),
    ("base_revision", {"type": "string", "pattern": RE_SHA1.pattern}, True),
    ("concern", {"type": "string", "minLength": 1, "maxLength": CONCERN_MAX}, True),
    ("files_in_scope", {"type": "array", "items": _STR, "minItems": 1}, True),
    ("files_out_of_scope", _STRLIST, True),
    ("write_authority", _enum(WRITE_AUTHORITY), True),
    ("write_paths", _STRLIST, True),
    (
        "verification_already_run",
        {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "command": _STR,
                    # null is a LEGAL, VISIBLE value meaning "this could not
                    # run". Absent is a compile error. ADR-012 via
                    # `vendors/gemini/README.md`: "A check that could not run
                    # is not a pass" -- so the packet has to be able to say so
                    # out loud instead of omitting the row.
                    "exit_code": {"type": ["integer", "null"]},
                },
                "required": ["command", "exit_code"],
                "additionalProperties": False,
            },
        },
        True,
    ),
    ("vendor_options", {"type": "object"}, True),
    ("overrides", {"type": "array", "items": _STR}, True),
    ("packet_digest", {"type": "string", "pattern": RE_SHA256.pattern}, True),
]

ROLE_EXTRA = {
    # ADR-010 decision 2 licenses a Codex diagnosis only after "two failed
    # hypothesis-driven attempts, or visible looping. First friction is not an
    # escalation." `minItems: 2` turns that sentence into a schema violation.
    # The Codex README's escalation packet already has a "What we tried" line;
    # nothing has ever counted the entries, so an escalation with zero
    # attempts is well-formed prose.
    "diagnose": [
        (
            "attempts",
            {
                "type": "array",
                "minItems": 2,
                "items": {
                    "type": "object",
                    "properties": {
                        "hypothesis": _STR,
                        "test": _STR,
                        "result": _STR,
                    },
                    "required": ["hypothesis", "test", "result"],
                    "additionalProperties": False,
                },
            },
            True,
        ),
        ("expected", {"type": "string", "minLength": 1}, True),
        ("observed", {"type": "string", "minLength": 1}, True),
        ("exact_error", {"type": ["string", "null"]}, True),
    ],
    # ADR-012 decision 5 keeps the author/reviewer boundary explicitly out of
    # the capability-parity sweep: "Codex stays read-only on review. That
    # constraint protects author/reviewer independence, not the filesystem.
    # Do not sweep it away by keyword match." `vendors/gemini/README.md`
    # generalizes it past Codex: "Do not use an Antigravity self-report as the
    # verifier for its own work... it is an author/reviewer independence rule,
    # not a capability limit."
    "review": [("authored_by", _enum(SEATS), True)],
    "challenge": [("authored_by", _enum(SEATS), True)],
    # Without an acceptance command the return cannot be typed pass/fail and
    # the packet degrades into the prose it replaced. `delegation-policy.md`
    # gates autonomy on verifier strength, so naming the verifier is the
    # cheapest thing an implement packet can carry.
    "implement": [("acceptance", {"type": "array", "items": _STR, "minItems": 1}, True)],
    "research": [("question", {"type": "string", "minLength": 1}, True)],
    "verify": [("question", {"type": "string", "minLength": 1}, True)],
}


def fields_for(role):
    """(properties, required) for a role's closed object."""
    props = {name: frag for name, frag, _ in CORE}
    required = [name for name, _, req in CORE if req]
    for name, frag, req in ROLE_EXTRA.get(role, []):
        props[name] = frag
        if req:
            required.append(name)
    props["role"] = {"type": "string", "const": role}
    return props, required


# --------------------------------------------------------------------------
# Identity and digest
# --------------------------------------------------------------------------

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_ulid(now_ms=None, entropy=None):
    """A 26-char Crockford-base32 ULID. Stdlib only; no dependency for an id.

    Time-sortable on purpose: the packet store is one directory per id, and a
    lexical sort of that directory should be chronological.
    """
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    entropy = os.urandom(10) if entropy is None else entropy
    value = (now_ms << 80) | int.from_bytes(entropy, "big")
    out = []
    for shift in range(125, -1, -5):
        out.append(_CROCKFORD[(value >> shift) & 0x1F])
    return "".join(out)


def canonical_json(packet):
    """Deterministic bytes for a packet, excluding its own digest."""
    body = {k: v for k, v in packet.items() if k != "packet_digest"}
    return json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def digest(packet):
    """sha256 over the canonicalized packet minus `packet_digest`.

    The return echoes it, which is the only thing that binds a return to the
    dispatch that produced it. In-house precedent: telltale's artifact store
    stamps a `PromptSHA256-8` header for the same reason -- and its lesson
    rides along, that the header must be stripped before the body reaches a
    downstream model, because a live chain measured codex quoting the
    fingerprint back as if it were content.
    """
    return hashlib.sha256(canonical_json(packet)).hexdigest()


def sealed(packet):
    """Return a copy with `packet_digest` recomputed."""
    out = dict(packet)
    out["packet_digest"] = digest(out)
    return out


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def _type_ok(value, frag):
    kinds = frag.get("type")
    if kinds is None:
        return True
    if isinstance(kinds, str):
        kinds = [kinds]
    for kind in kinds:
        if kind == "string" and isinstance(value, str):
            return True
        if kind == "boolean" and isinstance(value, bool):
            return True
        if kind == "integer" and isinstance(value, int) and not isinstance(value, bool):
            return True
        if kind == "array" and isinstance(value, list):
            return True
        if kind == "object" and isinstance(value, dict):
            return True
        if kind == "null" and value is None:
            return True
    return False


def _check_frag(name, value, frag, out):
    if not _type_ok(value, frag):
        out.append(Refusal("E-BAD-TYPE", f"{name}: expected {frag.get('type')}"))
        return
    if "const" in frag and value != frag["const"]:
        out.append(Refusal("E-BAD-ENUM", f"{name}: must be {frag['const']!r}"))
    if "enum" in frag and value not in frag["enum"]:
        out.append(
            Refusal("E-BAD-ENUM", f"{name}: {value!r} not one of {frag['enum']}")
        )
    if isinstance(value, str):
        pattern = frag.get("pattern")
        if pattern and not re.match(pattern, value):
            out.append(Refusal("E-BAD-FORMAT", f"{name}: {value!r} is malformed"))
        if "minLength" in frag and len(value) < frag["minLength"]:
            out.append(Refusal("E-BAD-FORMAT", f"{name}: must not be empty"))
        if "maxLength" in frag and len(value) > frag["maxLength"]:
            out.append(
                Refusal(
                    "E-CONCERN-TOO-LONG" if name == "concern" else "E-BAD-FORMAT",
                    f"{name}: {len(value)} chars exceeds {frag['maxLength']}. "
                    "One concern -> one branch -> one PR; a concern that will "
                    "not fit is two packets.",
                )
            )
    if isinstance(value, list):
        if "minItems" in frag and len(value) < frag["minItems"]:
            code = "E-ATTEMPTS-TOO-FEW" if name == "attempts" else "E-EMPTY-SCOPE"
            out.append(
                Refusal(
                    code,
                    f"{name}: {len(value)} entries, minimum {frag['minItems']}."
                    + (
                        " ADR-010 decision 2: Codex diagnoses after two failed "
                        "hypothesis-driven attempts or visible looping. First "
                        "friction is not an escalation."
                        if name == "attempts"
                        else ""
                    ),
                )
            )
        item = frag.get("items", {})
        for element in value:
            _check_object(name, element, item, out)


def _check_object(name, value, frag, out):
    if frag.get("type") != "object":
        if not _type_ok(value, frag):
            out.append(Refusal("E-BAD-TYPE", f"{name}[]: expected {frag.get('type')}"))
        return
    if not isinstance(value, dict):
        out.append(Refusal("E-BAD-TYPE", f"{name}[]: expected object"))
        return
    for key in frag.get("required", []):
        if key not in value:
            out.append(Refusal("E-MISSING-FIELD", f"{name}[].{key} is required"))
    if not frag.get("additionalProperties", True):
        for key in value:
            if key not in frag.get("properties", {}):
                out.append(Refusal("E-UNKNOWN-FIELD", f"{name}[].{key} is not a field"))
    for key, sub in frag.get("properties", {}).items():
        if key in value:
            _check_frag(f"{name}[].{key}", value[key], sub, out)


def validate(packet):
    """Structural + cross-field refusals. Returns a list of `Refusal`.

    Environmental refusals (is the branch on the remote, does the revision
    resolve, is the rendered prompt inside the channel budget) need git or a
    target and live in `compile.py`.
    """
    out = []
    if not isinstance(packet, dict):
        return [Refusal("E-BAD-TYPE", "packet must be a JSON object")]

    role = packet.get("role")
    if role not in ROLES:
        return [
            Refusal(
                "E-BAD-ENUM",
                f"role: {role!r} not one of {list(ROLES)}. The schema is a "
                "discriminated union on role; nothing else can be checked "
                "until it is valid.",
            )
        ]

    props, required = fields_for(role)

    for key in required:
        if key not in packet:
            out.append(Refusal("E-MISSING-FIELD", f"{key} is required for role {role}"))
    # Closed, per SYS-018 decision 2: an ADDED field is a detectable breaking
    # change rather than a silent one.
    for key in packet:
        if key not in props:
            out.append(
                Refusal(
                    "E-UNKNOWN-FIELD",
                    f"{key} is not a field of a {role} packet (the schema is closed)",
                )
            )
    for key, frag in props.items():
        if key in packet:
            _check_frag(key, packet[key], frag, out)

    out.extend(_cross_field(packet, role))
    return out


def _cross_field(packet, role):
    out = []
    seat = packet.get("target_seat")
    issuer = packet.get("issuer_seat")
    family = packet.get("target_model_family")
    reason = packet.get("route_reason")
    authority = packet.get("write_authority")

    # The harness/family axis. For four of the five seats the harness settles
    # the family, so a declared mismatch is a typo or a misunderstanding. For
    # cursor it genuinely does not, which is why cursor is absent from
    # SEAT_FAMILY and the field is load-bearing there rather than redundant.
    if seat in SEAT_FAMILY and family and family != SEAT_FAMILY[seat]:
        out.append(
            Refusal(
                "E-FAMILY-MISMATCH",
                f"target_seat {seat} is family {SEAT_FAMILY[seat]}, not {family}.",
            )
        )

    # ADR-010 decision 5, made checkable. "Model-family independence is
    # required when independence is the reason for the handoff. Selecting
    # Claude or GPT inside Cursor or Antigravity does not satisfy that
    # requirement." No prose template carries a model-family field at all, so
    # today this is checkable only against the operator's memory.
    if reason == "independence" and issuer in SEAT_FAMILY and family:
        if SEAT_FAMILY[issuer] == family:
            out.append(
                Refusal(
                    "E-INDEPENDENCE-SAME-FAMILY",
                    f"route_reason is independence but issuer {issuer} and "
                    f"target are both family {family}. A different harness is "
                    "not a different opinion (ADR-010 decision 5).",
                )
            )

    # Wired is not allocated. Grok Build has guards and a telltale seat and no
    # lane; Codex has a lane that does not include implement, plus a standing
    # repo exception for agent-ops. Both cases are the same rule: say what
    # role you are invoking and on whose authority.
    if seat in LANES and role not in LANES[seat]:
        if not (packet.get("off_lane_justification") or "").strip():
            lane = sorted(LANES[seat]) or "no lane role at all (guard wiring only)"
            out.append(
                Refusal(
                    "E-OFF-LANE",
                    f"target_seat {seat} has {lane} under ADR-010, and this "
                    f"packet asks for {role}. Set off_lane_justification to "
                    "name the role being invoked and the authority for it.",
                )
            )

    if role in ("review", "challenge"):
        author = packet.get("authored_by")
        if author and author == seat:
            out.append(
                Refusal(
                    "E-SELF-REVIEW",
                    f"authored_by == target_seat ({seat}). ADR-012 decision 5 "
                    "keeps the author/reviewer boundary out of the "
                    "capability-parity sweep; a self-report is not a verifier.",
                )
            )
        if authority and authority != "none":
            out.append(
                Refusal(
                    "E-REVIEW-WRITE",
                    f"a {role} packet must carry write_authority: none "
                    "(ADR-012 decision 5: Codex stays read-only on review).",
                )
            )

    # Authority is DECLARED, never inferred from an English verb. Lifted from
    # telltale's flow parser, whose comment is the canonical statement of the
    # rule: the `write:` token is "the ONLY thing that confers write authority
    # on a hop... English does not grant permissions."
    paths = packet.get("write_paths")
    if authority == "paths" and not paths:
        out.append(
            Refusal(
                "E-WRITE-PATHS",
                "write_authority: paths requires a non-empty write_paths. "
                "Without it boundary_violations is not computable.",
            )
        )
    if authority in ("none", "workspace") and paths:
        out.append(
            Refusal(
                "E-WRITE-PATHS",
                f"write_authority: {authority} must carry an empty write_paths.",
            )
        )

    out.extend(_vendor_options(packet, seat))
    return out


def _vendor_options(packet, seat):
    """The adapter layer: measured, vendor-specific, and closed per seat."""
    out = []
    opts = packet.get("vendor_options")
    if not isinstance(opts, dict):
        return out

    allowed = {
        "codex": {"sandbox", "skip_git_repo_check", "cd", "resume_session_id"},
        "agy": {"output_format"},
        "cursor": {"workspace_root", "launch_parent"},
        "claude": set(),
        "grok": set(),
    }.get(seat, set())

    for key in opts:
        if key not in allowed:
            out.append(
                Refusal(
                    "E-UNKNOWN-FIELD",
                    f"vendor_options.{key} is not an option for seat {seat} "
                    f"(allowed: {sorted(allowed) or 'none'})",
                )
            )

    if seat == "codex":
        sandbox = opts.get("sandbox")
        if sandbox is not None and sandbox not in CODEX_SANDBOXES:
            out.append(
                Refusal(
                    "E-BAD-ENUM",
                    f"vendor_options.sandbox: {sandbox!r} not one of "
                    f"{list(CODEX_SANDBOXES)}",
                )
            )
        # Measured against codex-cli 0.147.0: `codex exec resume --help`
        # carries neither `-s/--sandbox` nor `-C/--cd`. Passing them anyway
        # dies at argument parsing with empty stdout, which is
        # indistinguishable from a vendor that answered nothing.
        if opts.get("resume_session_id"):
            for flag in ("sandbox", "cd"):
                if opts.get(flag) is not None:
                    out.append(
                        Refusal(
                            "E-CODEX-RESUME-FLAGS",
                            f"vendor_options.{flag} cannot ride a resume: "
                            "`codex exec resume` accepts neither -s/--sandbox "
                            "nor -C/--cd (measured, codex-cli 0.147.0), and "
                            "fails at argument parsing with empty stdout.",
                        )
                    )

    if seat == "agy":
        fmt = opts.get("output_format")
        if fmt is not None and fmt not in AGY_OUTPUT_FORMATS:
            out.append(
                Refusal(
                    "E-BAD-ENUM",
                    f"vendor_options.output_format: {fmt!r} not one of "
                    f"{list(AGY_OUTPUT_FORMATS)}",
                )
            )

    if seat == "cursor":
        parent = opts.get("launch_parent")
        if parent is not None and parent not in CURSOR_LAUNCH_PARENTS:
            out.append(
                Refusal(
                    "E-BAD-ENUM",
                    f"vendor_options.launch_parent: {parent!r} not one of "
                    f"{list(CURSOR_LAUNCH_PARENTS)}",
                )
            )
        if parent == "git-bash":
            out.append(
                Refusal(
                    "E-CURSOR-GIT-BASH",
                    "launch_parent: git-bash kills the Cursor lane fail-closed "
                    "on Windows -- cursor-agent selects its bash executor but "
                    "builds the hook command as a PowerShell pipeline, bash "
                    "dies on the syntax, and EVERY tool call is denied "
                    "(vendors/cursor/README.md, measured 2026-08-04). Launch "
                    "from a PowerShell or cmd parent.",
                )
            )
        if not (opts.get("workspace_root") or "").strip():
            out.append(
                Refusal(
                    "E-MISSING-FIELD",
                    "vendor_options.workspace_root is required for cursor: "
                    "sessions often start from an empty window rather than "
                    "inside a repo (vendors/cursor/README.md).",
                )
            )

    return out


def surviving(refusals, overrides):
    """Drop refusals the packet explicitly overrode, keeping the three ADR
    predicates non-overridable."""
    allowed = {code for code in (overrides or []) if code not in NON_OVERRIDABLE}
    return [r for r in refusals if r.code not in allowed]


# --------------------------------------------------------------------------
# Schema generation (SYS-018 decision 1: generated, never hand-edited)
# --------------------------------------------------------------------------


def build_schema():
    branches = []
    for role in ROLES:
        props, required = fields_for(role)
        branches.append(
            {
                "title": f"{role} packet",
                "type": "object",
                "properties": props,
                "required": sorted(set(required)),
                # SYS-018 decision 2. This is the property whose absence let a
                # new field through silently in the /classify incident.
                "additionalProperties": False,
            }
        )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://github.com/sanlee-ys/agent-ops/blob/main/vendors/packet/packet.schema.json",
        "title": "agent-ops cross-vendor transfer packet",
        "description": (
            "GENERATED from vendors/packet/packet.py by "
            "`python vendors/packet/compile.py schema --write`. Do not hand "
            "edit: tests/test_packet_schema.py fails the build on drift "
            "(SYS-018 decision 3). A discriminated union on `role`, closed "
            "per SYS-018 decision 2. NOTE: this artifact carries the "
            "STRUCTURAL rules only. The cross-field refusals -- model-family "
            "independence, the author/reviewer boundary, off-lane routing, "
            "the codex resume flags -- are implemented in packet.py and are "
            "not expressible here; a consumer validating with this schema "
            "alone gets strictly less."
        ),
        "packet_version": PACKET_VERSION,
        "oneOf": branches,
    }


def schema_text():
    return json.dumps(build_schema(), indent=2, sort_keys=True) + "\n"
