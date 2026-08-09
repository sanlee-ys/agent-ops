#!/usr/bin/env python3
"""Test suite for vendors/packet/packet.py -- the schema and its refusals.

Two things are pinned here, and they are different in kind.

**The artifact.** ``packet.schema.json`` is generated from ``packet.py``, and
`SYS-018` decision 3 requires the provider's own build to fail on a stale
artifact -- "before a stale contract can reach a consumer". This repo's CI
runs `python -m unittest discover -s tests`, so the drift check lives here
rather than as a new CI step: it fails in the same place, and it does not put
a second edit into `.github/workflows/ci.yml`, which two open dependabot PRs
are already touching.

**The refusals.** Every rule gets both directions -- a packet it fires on and
a packet it must not fire on. The clean-packet assertions are not padding:
`ADR-007` records that "a guard that cries wolf gets routed around -- which is
a worse outcome than the mistake it prevents", and this compiler is trivially
easy to stop using.

Stdlib only, same as the sibling suites.
"""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vendors" / "packet"))

import packet as P  # noqa: E402

SCHEMA_PATH = ROOT / "vendors" / "packet" / "packet.schema.json"

REVISION = "a" * 40


def base(**over):
    """A minimal, clean `review` packet. Every test starts from valid."""
    pkt = {
        "packet_version": P.PACKET_VERSION,
        "packet_id": P.new_ulid(),
        "issued_at": "2026-08-09T12:00:00Z",
        "issuer_seat": "claude",
        "target_seat": "codex",
        "target_model_family": "openai",
        "role": "review",
        "route_reason": "independence",
        "off_lane_justification": None,
        "repo": "sanlee-ys/agent-ops",
        "branch": "feat/thing",
        "branch_pushed": True,
        "base_revision": REVISION,
        "concern": "review the packet compiler's refusal set",
        "files_in_scope": ["vendors/packet/**"],
        "files_out_of_scope": ["vendors/*/README.md"],
        "write_authority": "none",
        "write_paths": [],
        "verification_already_run": [
            {"command": "python -m unittest discover -s tests", "exit_code": 0}
        ],
        "vendor_options": {},
        "overrides": [],
        "authored_by": "claude",
        "packet_digest": "",
    }
    pkt.update(over)
    return P.sealed(pkt)


def codes(pkt):
    return {r.code for r in P.validate(pkt)}


class TestGeneratedArtifact(unittest.TestCase):
    def test_committed_schema_is_not_stale(self):
        """SYS-018 decision 3, in the only place this repo's CI already runs."""
        self.assertEqual(
            SCHEMA_PATH.read_text(encoding="utf-8"),
            P.schema_text(),
            "packet.schema.json is stale -- regenerate with "
            "`python vendors/packet/compile.py schema --write`",
        )

    def test_schema_is_a_closed_discriminated_union(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        branches = schema["oneOf"]
        self.assertEqual(len(branches), len(P.ROLES))
        seen = set()
        for branch in branches:
            # SYS-018 decision 2: closed, so an ADDED field is a detectable
            # breaking change rather than a silent one.
            self.assertFalse(branch["additionalProperties"])
            seen.add(branch["properties"]["role"]["const"])
        self.assertEqual(seen, set(P.ROLES))

    def test_diagnose_branch_carries_the_two_attempt_minimum(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        branch = next(
            b for b in schema["oneOf"] if b["properties"]["role"]["const"] == "diagnose"
        )
        self.assertEqual(branch["properties"]["attempts"]["minItems"], 2)
        self.assertIn("attempts", branch["required"])


class TestRosterIsNotTheLaneTable(unittest.TestCase):
    """Wired is not allocated. Five harnesses are guard-wired; four have lanes."""

    def test_grok_is_a_seat(self):
        self.assertIn("grok", P.SEATS)

    def test_grok_has_no_lane_role(self):
        self.assertEqual(P.LANES["grok"], frozenset())

    def test_targeting_grok_requires_saying_what_role_is_invoked(self):
        pkt = base(
            target_seat="grok",
            target_model_family="xai",
            role="research",
            question="what does the hook log say",
            route_reason="capacity",
            authored_by=None,
        )
        pkt.pop("authored_by")
        pkt = P.sealed(pkt)
        self.assertIn("E-OFF-LANE", codes(pkt))

    def test_an_off_lane_packet_passes_once_it_names_its_authority(self):
        pkt = base(
            target_seat="grok",
            target_model_family="xai",
            role="research",
            question="what does the hook log say",
            route_reason="capacity",
            off_lane_justification="guard-wiring verification, not fleet routing",
        )
        pkt.pop("authored_by")
        pkt = P.sealed(pkt)
        self.assertNotIn("E-OFF-LANE", codes(pkt))

    def test_codex_asked_to_implement_is_the_same_rule(self):
        pkt = base(role="implement", acceptance=["pytest -q"], write_authority="none")
        pkt.pop("authored_by")
        pkt = P.sealed(pkt)
        self.assertIn("E-OFF-LANE", codes(pkt))


class TestTheThreeADRPredicates(unittest.TestCase):
    def diagnose(self, attempts, **over):
        pkt = base(
            role="diagnose",
            attempts=attempts,
            expected="the hook denies",
            observed="the hook allows",
            exact_error=None,
            **over,
        )
        pkt.pop("authored_by")
        return P.sealed(pkt)

    def attempt(self, n):
        return {"hypothesis": f"h{n}", "test": f"t{n}", "result": f"r{n}"}

    def test_zero_attempt_escalation_is_a_compile_error(self):
        self.assertIn("E-ATTEMPTS-TOO-FEW", codes(self.diagnose([])))

    def test_one_attempt_is_still_first_friction(self):
        self.assertIn("E-ATTEMPTS-TOO-FEW", codes(self.diagnose([self.attempt(1)])))

    def test_two_attempts_clear_the_threshold(self):
        pkt = self.diagnose([self.attempt(1), self.attempt(2)])
        self.assertNotIn("E-ATTEMPTS-TOO-FEW", codes(pkt))

    def test_the_attempt_minimum_cannot_be_overridden(self):
        pkt = self.diagnose([], overrides=["E-ATTEMPTS-TOO-FEW"])
        left = P.surviving(P.validate(pkt), pkt["overrides"])
        self.assertIn("E-ATTEMPTS-TOO-FEW", {r.code for r in left})

    def test_self_review_is_refused(self):
        pkt = base(authored_by="codex")
        self.assertIn("E-SELF-REVIEW", codes(pkt))

    def test_self_review_cannot_be_overridden(self):
        pkt = base(authored_by="codex", overrides=["E-SELF-REVIEW"])
        left = P.surviving(P.validate(pkt), pkt["overrides"])
        self.assertIn("E-SELF-REVIEW", {r.code for r in left})

    def test_independence_to_the_same_model_family_is_refused(self):
        pkt = base(
            issuer_seat="claude",
            target_seat="cursor",
            target_model_family="anthropic",
            role="review",
            authored_by="codex",
            route_reason="independence",
        )
        pkt["vendor_options"] = {"workspace_root": "/w", "launch_parent": "powershell"}
        pkt = P.sealed(pkt)
        self.assertIn("E-INDEPENDENCE-SAME-FAMILY", codes(pkt))

    def test_independence_cannot_be_overridden(self):
        pkt = base(
            issuer_seat="claude",
            target_seat="cursor",
            target_model_family="anthropic",
            authored_by="codex",
            overrides=["E-INDEPENDENCE-SAME-FAMILY"],
            vendor_options={"workspace_root": "/w", "launch_parent": "powershell"},
        )
        left = P.surviving(P.validate(pkt), pkt["overrides"])
        self.assertIn("E-INDEPENDENCE-SAME-FAMILY", {r.code for r in left})

    def test_a_cursor_review_by_a_different_family_is_fine(self):
        """The rule is about the family, not about the harness."""
        pkt = base(
            target_seat="cursor",
            target_model_family="composer",
            role="review",
            authored_by="claude",
            route_reason="independence",
            off_lane_justification="bounded IDE-native review of the open file",
            vendor_options={"workspace_root": "/w", "launch_parent": "powershell"},
        )
        self.assertEqual(codes(pkt), set())


class TestCoreFields(unittest.TestCase):
    def test_the_clean_packet_produces_no_refusals(self):
        self.assertEqual(codes(base()), set())

    def test_the_schema_is_closed(self):
        pkt = base()
        pkt["extra_field"] = "surprise"
        self.assertIn("E-UNKNOWN-FIELD", codes(P.sealed(pkt)))

    def test_a_local_path_is_not_a_repo(self):
        """`cursor/README.md`'s template says `Repo: <path>`; this repo's own
        pre-commit guard rejects a local user path in a commit. `owner/name`
        is the only shape that can safely be written down."""
        pkt = base(repo="/home/someone/code/agent-ops")
        self.assertIn("E-BAD-FORMAT", codes(pkt))

    def test_an_overlong_concern_is_two_packets(self):
        pkt = base(concern="x" * (P.CONCERN_MAX + 1))
        self.assertIn("E-CONCERN-TOO-LONG", codes(pkt))

    def test_an_empty_file_boundary_is_refused(self):
        pkt = base(files_in_scope=[])
        self.assertIn("E-EMPTY-SCOPE", codes(pkt))

    def test_a_verification_row_must_carry_an_exit_code(self):
        pkt = base(verification_already_run=[{"command": "pytest"}])
        self.assertIn("E-MISSING-FIELD", codes(pkt))

    def test_a_null_exit_code_is_legal_and_visible(self):
        """A check that could not run is not a pass -- but it is sayable."""
        pkt = base(verification_already_run=[{"command": "pytest", "exit_code": None}])
        self.assertEqual(codes(pkt), set())

    def test_a_review_packet_cannot_carry_write_authority(self):
        pkt = base(write_authority="workspace")
        self.assertIn("E-REVIEW-WRITE", codes(pkt))

    def test_write_paths_are_required_when_authority_is_paths(self):
        pkt = base(
            role="implement",
            acceptance=["pytest -q"],
            write_authority="paths",
            write_paths=[],
            off_lane_justification="agent-ops repo exception for codex",
        )
        pkt.pop("authored_by")
        self.assertIn("E-WRITE-PATHS", codes(P.sealed(pkt)))

    def test_write_paths_must_be_empty_when_authority_is_none(self):
        pkt = base(write_paths=["vendors/packet/**"])
        self.assertIn("E-WRITE-PATHS", codes(pkt))

    def test_a_declared_family_that_contradicts_the_harness_is_refused(self):
        pkt = base(target_model_family="google", route_reason="capacity")
        self.assertIn("E-FAMILY-MISMATCH", codes(pkt))


class TestVendorOptions(unittest.TestCase):
    def test_codex_resume_rejects_the_sandbox_flag(self):
        pkt = base(
            vendor_options={"resume_session_id": "abc", "sandbox": "workspace-write"}
        )
        self.assertIn("E-CODEX-RESUME-FLAGS", codes(pkt))

    def test_codex_resume_rejects_the_cd_flag(self):
        pkt = base(vendor_options={"resume_session_id": "abc", "cd": "/w"})
        self.assertIn("E-CODEX-RESUME-FLAGS", codes(pkt))

    def test_codex_first_turn_accepts_both(self):
        pkt = base(vendor_options={"sandbox": "read-only", "cd": "/w"})
        self.assertEqual(codes(pkt), set())

    def test_an_unmeasured_sandbox_value_is_refused(self):
        pkt = base(vendor_options={"sandbox": "read-write"})
        self.assertIn("E-BAD-ENUM", codes(pkt))

    def test_an_option_from_the_wrong_vendor_is_refused(self):
        pkt = base(vendor_options={"output_format": "json"})
        self.assertIn("E-UNKNOWN-FIELD", codes(pkt))

    def test_cursor_launched_from_git_bash_is_a_compile_error(self):
        pkt = base(
            target_seat="cursor",
            target_model_family="composer",
            authored_by="claude",
            route_reason="surface-fit",
            off_lane_justification="IDE-native review",
            vendor_options={"workspace_root": "/w", "launch_parent": "git-bash"},
        )
        self.assertIn("E-CURSOR-GIT-BASH", codes(pkt))

    def test_cursor_requires_a_workspace_root(self):
        pkt = base(
            target_seat="cursor",
            target_model_family="composer",
            authored_by="claude",
            route_reason="surface-fit",
            off_lane_justification="IDE-native review",
            vendor_options={"launch_parent": "powershell"},
        )
        self.assertIn("E-MISSING-FIELD", codes(pkt))


class TestDigest(unittest.TestCase):
    def test_the_digest_binds_the_body(self):
        pkt = base()
        self.assertEqual(P.digest(pkt), pkt["packet_digest"])

    def test_editing_any_field_breaks_the_digest(self):
        pkt = copy.deepcopy(base())
        pkt["concern"] = "something else entirely"
        self.assertNotEqual(P.digest(pkt), pkt["packet_digest"])

    def test_key_order_does_not_change_the_digest(self):
        pkt = base()
        shuffled = dict(reversed(list(pkt.items())))
        self.assertEqual(P.digest(shuffled), pkt["packet_digest"])

    def test_ulids_are_time_sortable(self):
        early = P.new_ulid(now_ms=1, entropy=b"\xff" * 10)
        late = P.new_ulid(now_ms=2, entropy=b"\x00" * 10)
        self.assertLess(early, late)
        self.assertRegex(early, P.RE_ULID)


if __name__ == "__main__":
    unittest.main()
