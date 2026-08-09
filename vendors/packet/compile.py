#!/usr/bin/env python3
"""compile.py -- build, refuse, dispatch, and account for transfer packets.

    python vendors/packet/compile.py new --role review --to codex \\
        --repo sanlee-ys/telltale --branch council/needs-you \\
        --scope 'internal/council/**' --concern '...' --authored-by claude \\
        --repo-dir . --out packet.json

    python vendors/packet/compile.py check packet.json      # the gate
    python vendors/packet/compile.py dispatch packet.json    # check + subprocess
    python vendors/packet/compile.py report                  # the instrument
    python vendors/packet/compile.py schema --check          # SYS-018 drift gate

`check` and `dispatch` are separate verbs so `check` can run over a corpus in
CI without spawning anything, and so nothing that spends money is one typo
away from a validation run.

Exit codes are the interface, matching this repo's other gates:
    0  clean
    1  refused (one or more rules fired)
    2  operator / environment error

What this does NOT do
---------------------
It is a schema, a validator, and a subprocess. It is not a work-graph runtime.
It does not close [`SYS-022`]'s `state consistency` row: the council room is
still last-save-wins, the seat roster is still fixed, dynamic node spawning is
still "No" at the graph layer. It hardens one edge and reports a number about
how often that edge held. See `README.md`.

[`SYS-022`]: https://github.com/sanlee-ys/architecture/blob/main/decisions/SYS-022-org-graph-and-the-mechanization-split.md
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import packet as P  # noqa: E402

OK, REFUSED, ERROR = 0, 1, 2

SCHEMA_PATH = Path(__file__).resolve().parent / "packet.schema.json"

# Outside any git tree, and 0700, for the same reason telltale's artifact
# store is: a returned finding must not be one `git add -A` away from being
# published. (The mode is a no-op on Windows; it is set anyway so the POSIX
# machines in this fleet get it.)
def store_root():
    return Path(os.environ.get("AGENT_OPS_PACKET_STORE", Path.home() / ".agent-ops" / "packets"))


# --------------------------------------------------------------------------
# git -- the source of truth for what happened
# --------------------------------------------------------------------------


def git(repo_dir, *args, check=True):
    proc = subprocess.run(
        ["git", "-C", str(repo_dir), *args],
        capture_output=True,
        text=True,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc


def resolve_revision(repo_dir, rev):
    proc = git(repo_dir, "rev-parse", "--verify", f"{rev}^{{commit}}", check=False)
    return proc.stdout.strip() if proc.returncode == 0 else None


def branch_on_remote(repo_dir, branch, remote="origin"):
    """Ask the REMOTE, never the tracking ref.

    A tracking ref (`refs/remotes/origin/<branch>`, and therefore `git branch
    -r`) is a local cache written by the last fetch. It will happily claim a
    branch exists on the remote after someone else deleted it, and it will
    claim a stale SHA after someone else pushed. That blind spot is the same
    one that makes `--force-with-lease` unsafe on this fleet: the lease is
    checked against the cache, so it passes and clobbers anyway. `ls-remote`
    is a live query and is the only thing that answers the question.

    Returns the remote SHA, or None if the branch is not there.
    """
    proc = git(repo_dir, "ls-remote", "--heads", remote, branch, check=False)
    if proc.returncode != 0:
        return None
    for line in proc.stdout.splitlines():
        sha, _, ref = line.partition("\t")
        if ref.strip() in (f"refs/heads/{branch}", branch):
            return sha.strip()
    return None


def worktree_state(repo_dir):
    """A bracketing snapshot: HEAD plus the porcelain status of every path.

    This is what makes `files_changed` git-derived rather than model-reported.
    telltale's `VerifyReceipt` carries the doctrine and also its bound: a
    receipt proves create/change-after-start, it does NOT prove authorship.
    The same bound applies here, which is why the return field is named
    `files_changed` and not `files_the_seat_changed` -- a human or a parallel
    session editing the tree mid-dispatch lands in the same bucket.
    """
    head = resolve_revision(repo_dir, "HEAD")
    proc = git(repo_dir, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    entries = {}
    tokens = [t for t in proc.stdout.split("\0") if t]
    i = 0
    while i < len(tokens):
        token = tokens[i]
        status, path = token[:2], token[3:]
        # A rename entry is followed by its origin path in the next record.
        if status[0] == "R" or status[1] == "R":
            i += 1
            if i < len(tokens):
                entries[tokens[i]] = status
        entries[path] = status
        i += 1
    return {"head": head, "dirty": entries}


def files_changed(repo_dir, before, after):
    """Union of committed movement and working-tree movement, from git alone."""
    changed = set()
    if before["head"] and after["head"] and before["head"] != after["head"]:
        proc = git(
            repo_dir, "diff", "--name-only", before["head"], after["head"], check=False
        )
        if proc.returncode == 0:
            changed.update(p for p in proc.stdout.splitlines() if p.strip())
    for path, status in after["dirty"].items():
        if before["dirty"].get(path) != status:
            changed.add(path)
    for path in before["dirty"]:
        if path not in after["dirty"]:
            changed.add(path)
    return sorted(changed)


# --------------------------------------------------------------------------
# Boundary violations
# --------------------------------------------------------------------------


def glob_to_re(pattern):
    """Repo-relative glob -> regex. `**` crosses `/`, `*` and `?` do not.

    A pattern naming a directory (`docs/`, or a bare `docs`) matches
    everything under it, because that is what every one of the prose templates
    meant when it wrote `Files in scope: internal/council/`.
    """
    pattern = pattern.strip().replace("\\", "/")
    if pattern.endswith("/"):
        pattern += "**"
    out, i = [], 0
    while i < len(pattern):
        ch = pattern[i]
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
            if pattern.startswith("/", i):
                i += 1
        elif ch == "*":
            out.append("[^/]*")
            i += 1
        elif ch == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(ch))
            i += 1
    body = "".join(out)
    # A bare `docs` should also cover `docs/a.md`; a glob with a wildcard
    # should not silently acquire that behaviour.
    return re.compile(rf"^{body}(?:/.*)?$")


def matches_any(path, patterns):
    path = path.replace("\\", "/")
    return any(glob_to_re(p).match(path) for p in patterns or [])


def boundary_violations(pkt, changed):
    """files_changed minus what the packet actually licensed.

    The licensing set is `write_paths`, and ONLY `write_paths`. `files_in_scope`
    is a READING boundary -- it says where to look, not where to write -- so a
    change to an in-scope file under `write_authority: none` is a violation,
    loudly. This is where the design departs from the scoping brief, which
    proposed `files_changed - (write_paths | files_in_scope)`: that union
    quietly hands a review packet a write licence it never asked for, and
    write authority is declared, never inferred.

    `write_authority: workspace` licenses the whole tree, so it can produce no
    violations by construction. It is reported as such rather than as a zero
    that looks like a clean run.
    """
    authority = pkt.get("write_authority")
    if authority == "workspace":
        return []
    if authority == "none":
        return sorted(changed)
    return sorted(p for p in changed if not matches_any(p, pkt.get("write_paths")))


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def render(pkt):
    """The typed packet as the prose a vendor CLI actually accepts.

    Deliberately readable: the receiving seat is a language model, and the
    fields exist to be honoured, not parsed. Nothing is invented here that is
    not in the packet.
    """
    lines = [
        "# agent-ops transfer packet",
        "",
        f"packet_id: {pkt['packet_id']}",
        f"packet_digest: {pkt['packet_digest']}",
        f"issued_at: {pkt['issued_at']}  by: {pkt['issuer_seat']}",
        f"role: {pkt['role']}   route_reason: {pkt['route_reason']}",
        f"target: {pkt['target_seat']} (model family: {pkt['target_model_family']})",
        "",
        f"Repo: {pkt['repo']}",
        f"Branch: {pkt['branch']} (pushed: {str(pkt['branch_pushed']).lower()})",
        f"Exact revision: {pkt['base_revision']}",
        "",
        f"Concern: {pkt['concern']}",
        "",
        "Files in scope:",
    ]
    lines += [f"  - {p}" for p in pkt["files_in_scope"]]
    lines.append("Out of scope:")
    lines += [f"  - {p}" for p in pkt["files_out_of_scope"]] or ["  (none declared)"]
    lines.append("")

    authority = pkt["write_authority"]
    lines.append(f"Write authority: {authority}")
    if authority == "paths":
        lines += [f"  - {p}" for p in pkt["write_paths"]]
    if authority == "none":
        lines.append(
            "  Do not modify any file. This is a declared token, not a "
            "preference: files changed under this packet are reported as "
            "boundary violations, computed from git rather than from your "
            "own account of what you did."
        )
    else:
        # ADR-012 as corrected 2026-08-09. The honest statement, because the
        # packet cannot verify the receiving machine's guard deployment and
        # nothing in this repo can: "nothing in this repo can prove a given
        # machine deployed it."
        lines.append(
            "  Tool-time guard wiring on the receiving machine is NOT "
            "verifiable from here. A wired hook's deny has been measured "
            "surviving a permission bypass; the redlines have not. Do not run "
            "this packet under a permission-bypass flag."
        )
    lines.append("")

    lines.append("Verification already run:")
    if pkt["verification_already_run"]:
        for entry in pkt["verification_already_run"]:
            code = entry["exit_code"]
            shown = "COULD NOT RUN (not a pass)" if code is None else f"exit {code}"
            lines.append(f"  - {entry['command']} -> {shown}")
    else:
        lines.append("  (none)")
    lines.append("")

    role = pkt["role"]
    if role == "diagnose":
        lines += [
            f"Expected: {pkt['expected']}",
            f"Observed: {pkt['observed']}",
            f"Exact error: {pkt.get('exact_error') or '(none captured)'}",
            "",
            f"Attempts already made ({len(pkt['attempts'])}):",
        ]
        for n, a in enumerate(pkt["attempts"], 1):
            lines += [
                f"  {n}. hypothesis: {a['hypothesis']}",
                f"     test:       {a['test']}",
                f"     result:     {a['result']}",
            ]
        lines.append("")
    if role in ("review", "challenge"):
        lines += [
            f"Authored by: {pkt['authored_by']} (you are not the author; "
            "do not edit the branch under review)",
            "",
        ]
    if role == "implement":
        lines.append("Acceptance (the return is typed pass/fail on these):")
        lines += [f"  - {c}" for c in pkt["acceptance"]]
        lines.append("")
    if role in ("research", "verify"):
        lines += [f"Question: {pkt['question']}", ""]

    if (pkt.get("off_lane_justification") or "").strip():
        lines += [
            "Off-lane note: this packet asks for a role outside this seat's "
            "ADR-010 lane. Stated authority: "
            + pkt["off_lane_justification"],
            "",
        ]
    if pkt.get("overrides"):
        lines += [
            "Overridden refusals: " + ", ".join(pkt["overrides"]),
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------
# Environmental refusals
# --------------------------------------------------------------------------


def environmental(pkt, repo_dir, remote="origin"):
    out = []
    seat = pkt.get("target_seat")

    if repo_dir:
        if resolve_revision(repo_dir, pkt.get("base_revision", "")) is None:
            out.append(
                P.Refusal(
                    "E-REVISION-UNRESOLVABLE",
                    f"base_revision {pkt.get('base_revision')!r} does not "
                    f"resolve to a commit in {repo_dir}. A review pinned to a "
                    "revision nobody can check out is prose.",
                )
            )
        remote_sha = branch_on_remote(repo_dir, pkt.get("branch", ""), remote)
        if remote_sha is None:
            out.append(
                P.Refusal(
                    "E-BRANCH-NOT-PUSHED",
                    f"{remote} has no branch {pkt.get('branch')!r} "
                    "(git ls-remote, a live query -- not the tracking ref, "
                    "which is a local cache and lies about exactly this). "
                    "Uncommitted or unpushed work is invisible across a "
                    "harness boundary.",
                )
            )
        elif pkt.get("branch_pushed") is not True:
            out.append(
                P.Refusal(
                    "E-BRANCH-NOT-PUSHED",
                    "branch_pushed is false but the branch IS on the remote; "
                    "the packet disagrees with git.",
                )
            )

    channel, budget = P.PROMPT_CHANNEL.get(seat, ("argv", P.ARGV_BUDGET))
    size = len(render(pkt).encode("utf-8"))
    if budget is not None and size > budget:
        out.append(
            P.Refusal(
                "E-PROMPT-TOO-LARGE",
                f"rendered packet is {size} bytes; seat {seat} takes its "
                f"prompt in {channel} and the budget is {budget}. Refusing "
                "rather than truncating: a packet clipped in half makes the "
                "seat act on a partial boundary while the log records it as "
                "briefed.",
            )
        )
    return out


def all_refusals(pkt, repo_dir=None, remote="origin"):
    found = P.validate(pkt)
    # Environmental checks assume a structurally sound packet.
    if not any(r.code in ("E-MISSING-FIELD", "E-BAD-TYPE", "E-BAD-ENUM") for r in found):
        found += environmental(pkt, repo_dir, remote)
    return P.surviving(found, pkt.get("overrides"))


# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------


def build_argv(pkt, prompt):
    """The measured invocation for a seat. Improvising here is the bug."""
    seat = pkt["target_seat"]
    opts = pkt.get("vendor_options") or {}

    if seat == "codex":
        argv = ["codex", "exec"]
        if opts.get("resume_session_id"):
            # Measured: `codex exec resume` carries neither -s nor -C.
            argv += ["resume", opts["resume_session_id"]]
            if opts.get("skip_git_repo_check", True):
                argv.append("--skip-git-repo-check")
            argv.append("--json")
        else:
            if opts.get("skip_git_repo_check", True):
                argv.append("--skip-git-repo-check")
            if opts.get("cd"):
                argv += ["--cd", opts["cd"]]
            if opts.get("sandbox"):
                argv += ["--sandbox", opts["sandbox"]]
            argv.append("--json")
        argv.append(prompt)
        return argv

    if seat == "agy":
        # EVERY flag goes BEFORE -p, and the prompt is the value that
        # immediately follows it. `-p` is a value-taking string flag (`agy
        # --help`, 1.1.11), so `agy -p --output-format json "<prompt>"`
        # swallows the literal "--output-format" AS the prompt and exits 0
        # with a paragraph about CLI output formats -- a silent wrong
        # answer, which is why the order is encoded here rather than
        # remembered.
        #
        # A TRAILING flag (`agy -p "<prompt>" --output-format json`) is
        # honored on 1.1.11 -- measured 2026-08-09, it returns JSON. So the
        # leading order below is not a workaround for a broken parser; it is
        # the one arrangement that cannot decay into the swallow case if a
        # flag is ever appended to this argv later.
        argv = ["agy", "--output-format", opts.get("output_format", "json")]
        argv += ["--disable-slash-commands"]
        argv += ["-p", prompt]
        return argv

    raise ValueError(f"no phase-1 dispatch path for seat {seat!r}")


def dispatch(pkt, repo_dir, timeout=None, runner=None):
    """Bracket the spawn with git, run it, and type the return.

    Three sources, ranked, and the ranking is the design:
      1. git for what happened  -- files_changed, boundary_violations
      2. the vendor's exit code and stream for transport
      3. free text for nothing  -- stored verbatim, never parsed into a claim
    """
    prompt = render(pkt)
    argv = build_argv(pkt, prompt)

    before = worktree_state(repo_dir) if repo_dir else {"head": None, "dirty": {}}
    started = _now()
    if runner is None:
        runner = _subprocess_runner
    result = runner(argv, timeout)
    ended = _now()
    after = worktree_state(repo_dir) if repo_dir else {"head": None, "dirty": {}}

    changed = files_changed(repo_dir, before, after) if repo_dir else []

    stdout = result.get("stdout", "")
    parse_errors = 0
    if not result.get("timed_out"):
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                json.loads(line)
            except ValueError:
                # Degrade, do not fail: counted and reported once.
                parse_errors += 1

    if result.get("timed_out"):
        outcome = "timeout"
    elif result.get("exit_code") not in (0, None):
        outcome = "failed"
    elif not stdout.strip():
        # `no-output` is NOT `answered` with an empty body. Zero and absent
        # are different states and collapsing them is the one regression this
        # fleet's observability layer exists to prevent.
        outcome = "no-output"
    else:
        outcome = "answered"

    return {
        "packet_id": pkt["packet_id"],
        "packet_digest": pkt["packet_digest"],
        "target_seat": pkt["target_seat"],
        "role": pkt["role"],
        "argv": argv,
        "started_at": started,
        "ended_at": ended,
        "exit_code": result.get("exit_code"),
        "outcome": outcome,
        "head_revision_at_return": after["head"],
        "files_changed": changed,
        "boundary_violations": boundary_violations(pkt, changed),
        "write_authority": pkt["write_authority"],
        "stream_parse_errors": parse_errors,
        # Absent is not zero. No usage field is invented here: the event
        # schemas of `codex --json` and `agy --output-format json` were not
        # measured in this change, and naming a field that was never observed
        # is the failure this fleet's honesty rules exist to prevent.
        "usage": None,
    }


def _subprocess_runner(argv, timeout):
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        return {
            "exit_code": None,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "timed_out": True,
        }
    except FileNotFoundError:
        return {"exit_code": None, "stdout": "", "stderr": f"{argv[0]}: not found",
                "timed_out": False, "not_found": True}
    return {
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "timed_out": False,
    }


def _now():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------


def write_store(pkt, ret=None, findings=None):
    root = store_root() / pkt["packet_id"]
    root.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(root.parent, 0o700)
    except OSError:
        pass
    (root / "packet.json").write_text(json.dumps(pkt, indent=2) + "\n", encoding="utf-8")
    if ret is not None:
        (root / "return.json").write_text(json.dumps(ret, indent=2) + "\n", encoding="utf-8")
    if findings is not None:
        (root / "findings.md").write_text(findings, encoding="utf-8")
    return root


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _print_refusals(refusals):
    for r in refusals:
        marker = " [not overridable]" if r.code in P.NON_OVERRIDABLE else ""
        print(f"REFUSED {r.code}{marker}\n  {r.message}", file=sys.stderr)


def cmd_new(args):
    repo_dir = args.repo_dir
    base = resolve_revision(repo_dir, args.base or args.branch or "HEAD") if repo_dir else None
    remote_sha = branch_on_remote(repo_dir, args.branch) if repo_dir else None

    pkt = {
        "packet_version": P.PACKET_VERSION,
        "packet_id": P.new_ulid(),
        "issued_at": _now(),
        "issuer_seat": args.issuer,
        "target_seat": args.to,
        "target_model_family": args.family or P.SEAT_FAMILY.get(args.to, ""),
        "role": args.role,
        "route_reason": args.route_reason,
        "off_lane_justification": args.off_lane,
        "repo": args.repo,
        "branch": args.branch,
        "branch_pushed": remote_sha is not None,
        "base_revision": base or "",
        "concern": args.concern,
        "files_in_scope": args.scope or [],
        "files_out_of_scope": args.out_of_scope or [],
        "write_authority": args.write_authority,
        "write_paths": args.write_path or [],
        "verification_already_run": [],
        "vendor_options": json.loads(args.vendor_options) if args.vendor_options else {},
        "overrides": args.allow or [],
        "packet_digest": "",
    }
    for command in args.verified or []:
        cmd, _, code = command.rpartition("=")
        pkt["verification_already_run"].append(
            {"command": cmd or command, "exit_code": None if code in ("", "null") else int(code)}
        )
    if args.role == "diagnose":
        pkt.update({"attempts": [], "expected": "", "observed": "", "exact_error": None})
    if args.role in ("review", "challenge"):
        pkt["authored_by"] = args.authored_by or ""
    if args.role == "implement":
        pkt["acceptance"] = args.acceptance or []
    if args.role in ("research", "verify"):
        pkt["question"] = args.question or ""

    pkt = P.sealed(pkt)
    text = json.dumps(pkt, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out} ({pkt['packet_id']})")
    else:
        print(text, end="")

    refusals = all_refusals(pkt, repo_dir)
    if refusals:
        print(
            "\nThe skeleton is incomplete by design -- fill it in and re-run "
            "`check`. Outstanding:",
            file=sys.stderr,
        )
        _print_refusals(refusals)
    return OK


def cmd_check(args):
    pkt = _load(args.packet)
    if P.digest(pkt) != pkt.get("packet_digest"):
        print(
            f"REFUSED E-DIGEST\n  packet_digest does not match the packet body "
            f"(expected {P.digest(pkt)}). Re-seal it; a return can only be "
            "bound to a dispatch by this value.",
            file=sys.stderr,
        )
        return REFUSED
    refusals = all_refusals(pkt, args.repo_dir, args.remote)
    if refusals:
        _print_refusals(refusals)
        return REFUSED
    channel, budget = P.PROMPT_CHANNEL.get(pkt["target_seat"], ("argv", None))
    size = len(render(pkt).encode("utf-8"))
    print(
        f"OK {pkt['packet_id']} {pkt['role']} -> {pkt['target_seat']} "
        f"({pkt['target_model_family']}); rendered {size} bytes via {channel}"
        + (f" of {budget}" if budget else "")
    )
    return OK


def cmd_dispatch(args):
    pkt = _load(args.packet)
    if P.digest(pkt) != pkt.get("packet_digest"):
        print("REFUSED E-DIGEST\n  re-seal the packet before dispatch", file=sys.stderr)
        return REFUSED
    refusals = all_refusals(pkt, args.repo_dir, args.remote)
    if refusals:
        _print_refusals(refusals)
        return REFUSED
    if pkt["target_seat"] not in P.DISPATCHABLE:
        print(
            f"REFUSED E-NO-DISPATCH-PATH\n  phase 1 dispatches to "
            f"{list(P.DISPATCHABLE)} only. A {pkt['target_seat']} packet "
            "compiles and validates and is emitted as a file for a "
            "human-driven or telltale-driven session. Saying so is better "
            "than shipping a path that cannot work.",
            file=sys.stderr,
        )
        return REFUSED

    prompt = render(pkt)
    argv = build_argv(pkt, prompt)
    if args.dry_run:
        print(json.dumps({"argv": argv, "prompt_bytes": len(prompt.encode("utf-8"))}, indent=2))
        return OK

    ret = dispatch(pkt, args.repo_dir, timeout=args.timeout, runner=_fake_runner())
    root = write_store(pkt, ret)
    print(json.dumps(ret, indent=2))
    print(f"\nstored: {root}", file=sys.stderr)
    return OK if not ret["boundary_violations"] else OK  # reported, never gated


def _fake_runner():
    """The dispatch path is exercisable without spending anything.

    `AGENT_OPS_PACKET_FAKE_RUNNER` names an executable that stands in for the
    vendor CLI; the real argv is still built, and the whole git-bracketing and
    return-typing path still runs. It is an environment variable rather than a
    CLI flag on purpose -- a `--runner-command` flag on a public tool is an
    invitation to point a dispatch at something else by accident.
    """
    fake = os.environ.get("AGENT_OPS_PACKET_FAKE_RUNNER")
    if not fake:
        return None

    def run(argv, timeout):
        return _subprocess_runner([sys.executable, fake, *argv], timeout)

    return run


def cmd_report(args):
    """The instrument, not the gate.

    Boundary-violation rate needs no gold set, no second arm and no judge --
    the return handler computes it anyway. It is REPORTED. A floor on a rate
    measured over a few dozen non-independent dispatches would be an
    aspirational floor wearing a measured number's clothes, and this fleet has
    a decision saying so.
    """
    root = store_root()
    rows = []
    for return_file in sorted(root.glob("*/return.json")):
        try:
            rows.append(json.loads(return_file.read_text(encoding="utf-8")))
        except ValueError:
            continue
    if not rows:
        print(f"no returns under {root}")
        return OK
    counted = [r for r in rows if r.get("write_authority") != "workspace"]
    violated = [r for r in counted if r.get("boundary_violations")]
    print(f"dispatches with a return: {len(rows)}")
    print(f"  countable (write_authority != workspace): {len(counted)}")
    print(f"  with at least one boundary violation:     {len(violated)}")
    if counted:
        print(f"  boundary-violation rate: {len(violated)}/{len(counted)}")
    print(
        "\nReported, not gated. n is small and the dispatches are not "
        "independent; a zero here is a finding, not a pass."
    )
    for r in violated:
        print(f"\n  {r['packet_id']} {r['role']} -> {r['target_seat']}")
        for path in r["boundary_violations"]:
            print(f"    {path}")
    return OK


def cmd_schema(args):
    text = P.schema_text()
    if args.write:
        SCHEMA_PATH.write_text(text, encoding="utf-8")
        print(f"wrote {SCHEMA_PATH}")
        return OK
    if args.check:
        current = SCHEMA_PATH.read_text(encoding="utf-8") if SCHEMA_PATH.exists() else ""
        if current != text:
            print(
                "packet.schema.json is stale. Regenerate with "
                "`python vendors/packet/compile.py schema --write` "
                "(SYS-018 decision 3: the provider's build fails on a stale "
                "artifact, at the source, before it can reach a consumer).",
                file=sys.stderr,
            )
            return REFUSED
        print("packet.schema.json is current")
        return OK
    print(text, end="")
    return OK


def build_parser():
    ap = argparse.ArgumentParser(prog="compile.py", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    new = sub.add_parser("new", help="emit a packet skeleton with git-resolved facts")
    new.add_argument("--role", required=True, choices=P.ROLES)
    new.add_argument("--to", required=True, choices=P.SEATS)
    new.add_argument("--issuer", default="claude", choices=P.SEATS)
    new.add_argument("--family", choices=P.MODEL_FAMILIES)
    new.add_argument("--route-reason", default="surface-fit", choices=P.ROUTE_REASONS)
    new.add_argument("--off-lane", default=None)
    new.add_argument("--repo", required=True, help="owner/name, never a local path")
    new.add_argument("--branch", required=True)
    new.add_argument("--base", default=None)
    new.add_argument("--concern", required=True)
    new.add_argument("--scope", action="append")
    new.add_argument("--out-of-scope", action="append")
    new.add_argument("--write-authority", default="none", choices=P.WRITE_AUTHORITY)
    new.add_argument("--write-path", action="append")
    new.add_argument("--verified", action="append", metavar="CMD=EXIT")
    new.add_argument("--authored-by", choices=P.SEATS)
    new.add_argument("--acceptance", action="append")
    new.add_argument("--question")
    new.add_argument("--vendor-options", help="JSON object")
    new.add_argument("--allow", action="append", metavar="CODE")
    new.add_argument("--repo-dir", default=None)
    new.add_argument("--out", default=None)
    new.set_defaults(func=cmd_new)

    check = sub.add_parser("check", help="the gate; exits 1 on any refusal")
    check.add_argument("packet")
    check.add_argument("--repo-dir", default=None)
    check.add_argument("--remote", default="origin")
    check.set_defaults(func=cmd_check)

    disp = sub.add_parser("dispatch", help="check, then spawn, then type the return")
    disp.add_argument("packet")
    disp.add_argument("--repo-dir", default=None)
    disp.add_argument("--remote", default="origin")
    disp.add_argument("--timeout", type=float, default=None)
    disp.add_argument("--dry-run", action="store_true", help="print the argv and stop")
    disp.set_defaults(func=cmd_dispatch)

    rep = sub.add_parser("report", help="boundary-violation rate over the store")
    rep.set_defaults(func=cmd_report)

    sch = sub.add_parser("schema", help="print, write, or drift-check the artifact")
    sch.add_argument("--write", action="store_true")
    sch.add_argument("--check", action="store_true")
    sch.set_defaults(func=cmd_schema)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return ERROR


if __name__ == "__main__":
    sys.exit(main())
