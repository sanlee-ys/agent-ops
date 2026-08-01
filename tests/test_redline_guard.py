#!/usr/bin/env python3
"""Adversarial test suite for scripts/redline-guard.py.

The redline guard is the mechanical backstop that ADR-002 leans on: this repo
went public-first and canonical on the reasoning that redaction risk was
"addressed mechanically rather than avoided". Until this file existed, that
mechanism had **no behavioural tests** — CI only ran `py_compile` on it, which
proves the file parses and nothing else. A backstop that is itself only a
behavioural rule is the failure ADR-002 argued against, one level down.

These tests drive `scan()` directly, which is the pure part: given a path, a
blob of text and any local terms, return violations. The git plumbing around it
(`staged_files`, `staged_content`) is deliberately not tested here — it is a
thin `git` shell-out, and faking git buys less than it costs.

**No literal violation appears in this file.** Every fixture is assembled at
runtime from fragments, because a test file full of credential-shaped strings
and private memory links would be blocked by the very guard it tests. That
constraint is not an inconvenience; a guard you cannot write tests for without
disabling it would be a design smell, and building fixtures dynamically is the
demonstration that it fires on shape rather than on provenance.

Hashed terms (private repo names, identifying words) cannot be tested with
their real values — the whole point is that those plaintexts never appear in a
public repo. Instead the hashed sets are swapped for the hash of a known
innocuous word, which exercises the same code path with a value safe to publish.

Stdlib only, matching test_credential_guard.py, so CI stays a bare
`python -m unittest`.
"""
import hashlib
import importlib.util
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GUARD_PATH = REPO_ROOT / "scripts" / "redline-guard.py"

# The guard is a hyphenated script, not an importable module name.
_spec = importlib.util.spec_from_file_location("redline_guard", GUARD_PATH)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


def sha(word: str) -> str:
    return hashlib.sha256(word.lower().encode()).hexdigest()


def labels(violations) -> set:
    """Violation tuples are (path, lineno, label, snippet)."""
    return {v[2] for v in violations}


class TestCredentialShapes(unittest.TestCase):
    """Rule 1: credential-shaped strings, real or "example", are violations."""

    def test_github_classic_token(self):
        fixture = "token = " + "gh" + "p_" + ("A1b2C3d4E5" * 3)
        self.assertIn("github token", labels(guard.scan("f.md", fixture, [])))

    def test_github_fine_grained_pat(self):
        fixture = "PAT: " + "github" + "_pat_" + ("x" * 25)
        self.assertIn(
            "github fine-grained PAT", labels(guard.scan("f.md", fixture, []))
        )

    def test_anthropic_key(self):
        fixture = "key=" + "sk-" + "ant-" + ("abc123_" * 4)
        self.assertIn("anthropic key", labels(guard.scan("f.md", fixture, [])))

    def test_aws_access_key_id(self):
        fixture = "id " + "AKIA" + "ABCDEFGHIJKLMNOP"
        self.assertIn("aws access key id", labels(guard.scan("f.md", fixture, [])))

    def test_private_key_block(self):
        fixture = "-" * 5 + "BEGIN RSA PRIVATE KEY" + "-" * 5
        self.assertIn("private key block", labels(guard.scan("f.md", fixture, [])))

    def test_an_example_token_is_still_blocked(self):
        """"It's only an example" is exactly how a real one ships."""
        fixture = "# example only, not real: " + "gh" + "s_" + ("Z" * 24)
        self.assertTrue(guard.scan("docs.md", fixture, []))


class TestPrivateMemoryLinks(unittest.TestCase):
    """Rule 2: wiki-style links leak the private notes layer's structure."""

    def test_memory_link_is_blocked(self):
        fixture = "see " + "[" * 2 + "some-private-note" + "]" * 2
        self.assertIn("private memory link", labels(guard.scan("f.md", fixture, [])))

    def test_memory_link_at_line_start_is_blocked(self):
        """The lookbehind must not require a preceding character to exist."""
        fixture = "[" * 2 + "some-private-note" + "]" * 2
        self.assertIn("private memory link", labels(guard.scan("f.md", fixture, [])))

    def test_escaped_bracket_regex_is_allowed(self):
        """An escaped \\[ before a negated class is regex syntax, not a link.

        The exact pattern credential-guard.py v2.6 (PR #42) had to assemble by
        string concatenation purely to dodge this false positive. These are
        safe to write literally here: post-fix they are not violations.
        """
        fixture = r'_INDEX = re.compile(r"\[[^\]]*\]")'
        self.assertEqual(guard.scan("guard.py", fixture, []), [])

    def test_escaped_double_bracket_regex_is_allowed(self):
        """Even a regex that MATCHES wiki links is not itself one."""
        fixture = r'PAT = re.compile(r"\[\[[^\]]+\]\]")'
        self.assertEqual(guard.scan("guard.py", fixture, []), [])

    def test_ordinary_brackets_are_allowed(self):
        self.assertEqual(guard.scan("f.md", "an array like [1, 2] is fine", []), [])

    def test_markdown_link_is_allowed(self):
        fixture = "a [real link](https://example.com) in prose"
        self.assertEqual(guard.scan("f.md", fixture, []), [])


class TestLocalUserPaths(unittest.TestCase):
    """Rule 3: publish ~-style paths, never a real user directory."""

    def test_windows_path_blocked(self):
        fixture = "C" + ":/Users/" + "someone/code"
        self.assertIn("local user path", labels(guard.scan("f.md", fixture, [])))

    def test_git_bash_path_blocked(self):
        fixture = "/c" + "/Users/" + "someone/code"
        self.assertIn("local user path", labels(guard.scan("f.md", fixture, [])))

    def test_tilde_path_allowed(self):
        self.assertEqual(guard.scan("f.md", "~/code/project is fine", []), [])


class TestHashedTerms(unittest.TestCase):
    """Rules 4-5, exercised with a stand-in term safe to publish.

    The real terms ship as hashes precisely so they never appear in this repo;
    swapping the hashed set for a known word tests the same code path without
    reintroducing the disclosure the hashing exists to prevent.
    """

    def setUp(self):
        self._always = guard.HASHED_ALWAYS
        self._context = guard.HASHED_REPO_CONTEXT
        guard.HASHED_ALWAYS = {sha("zzplaceholder")}
        guard.HASHED_REPO_CONTEXT = {sha("mercury")}

    def tearDown(self):
        guard.HASHED_ALWAYS = self._always
        guard.HASHED_REPO_CONTEXT = self._context

    def test_always_term_blocked_anywhere(self):
        found = guard.scan("f.md", "a sentence mentioning zzplaceholder here", [])
        self.assertIn("identifying term", labels(found))

    def test_always_term_is_case_insensitive(self):
        found = guard.scan("f.md", "ZZPlaceholder", [])
        self.assertIn("identifying term", labels(found))

    def test_context_term_blocked_near_repo_words(self):
        found = guard.scan("f.md", "the mercury repo is private", [])
        self.assertIn("private repo name in repo context", labels(found))

    def test_context_term_allowed_in_ordinary_prose(self):
        """Precision over reach: a guard that fires on English gets routed around."""
        found = guard.scan("f.md", "mercury is the first planet from the sun", [])
        self.assertEqual(found, [])

    def test_context_window_is_bounded(self):
        """Far enough from a repo word, a common term is prose again."""
        far = "mercury " + " ".join(["filler"] * 10) + " repo"
        self.assertEqual(guard.scan("f.md", far, []), [])

    def test_owner_slug_with_private_repo_blocked(self):
        found = guard.scan("f.md", "see sanlee-ys/mercury for details", [])
        self.assertIn("private repo slug", labels(found))

    def test_owner_slug_with_public_repo_allowed(self):
        found = guard.scan("f.md", "see sanlee-ys/claude-ops for details", [])
        self.assertEqual(found, [])


class TestLocalTerms(unittest.TestCase):
    """Machine-local terms extend the guard without publishing the term."""

    def test_local_term_blocked(self):
        found = guard.scan("f.md", "a line about Wombat Corp", ["wombat corp"])
        self.assertIn("local redline term", labels(found))

    def test_local_term_is_case_insensitive(self):
        found = guard.scan("f.md", "WOMBAT CORP", ["wombat corp"])
        self.assertIn("local redline term", labels(found))

    def test_no_local_terms_is_not_an_error(self):
        self.assertEqual(guard.scan("f.md", "ordinary prose", []), [])


class TestMasking(unittest.TestCase):
    """The guard must never echo a secret in full — that would be incident 1.

    A guard that prints what it caught, in full, into a terminal and a CI log
    has moved the secret rather than blocked it.
    """

    def test_long_value_is_truncated(self):
        secret = "A" * 40
        masked = guard.mask(secret)
        self.assertNotIn(secret, masked)
        self.assertIn("40 chars", masked)
        self.assertLessEqual(len(masked.split("...")[0]), 6)

    def test_short_value_is_shown(self):
        """Below the threshold there is nothing to protect and detail helps."""
        self.assertEqual(guard.mask("abc"), "abc")

    def test_reported_snippet_never_contains_the_full_match(self):
        token = "gh" + "p_" + ("Q7w8E9r0T1" * 3)
        found = guard.scan("f.md", f"leaked = {token}", [])
        self.assertTrue(found)
        for _, _, _, snippet in found:
            self.assertNotIn(token, snippet)


class TestCleanContentAndReporting(unittest.TestCase):
    def test_clean_file_yields_no_violations(self):
        text = "# A heading\n\nOrdinary prose about ~/code and public repos.\n"
        self.assertEqual(guard.scan("README.md", text, []), [])

    def test_line_numbers_are_reported_accurately(self):
        fixture = "clean\nclean\n" + "C" + ":/Users/" + "someone\n"
        found = guard.scan("f.md", fixture, [])
        self.assertEqual([v[1] for v in found], [3])

    def test_guard_exempts_its_own_source(self):
        """The guard's source contains the patterns it hunts; it must skip itself."""
        self.assertIn("scripts/redline-guard.py", guard.EXEMPT)


if __name__ == "__main__":
    unittest.main()
