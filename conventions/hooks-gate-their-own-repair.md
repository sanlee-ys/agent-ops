# A hook-hosting directory cannot be moved by the session it gates (hard rule)

Global agent hooks are usually **symlinks into a working clone**, so the live
hook tracks canonical with no sync step. That is a good arrangement, and it puts
a directory on disk with this property: **moving it disarms the session doing
the moving, and the repair needs exactly the tool the move took away.**

This is a agent-ops-local convention — no consumer repo mirrors it, so there is
no shared block to propagate.

The rule: **never move, rename or delete a directory that live hooks resolve
through, from inside a session those hooks gate.** Either

- re-point the links in the **same command** as the move —
  `mv X Y && ln -sfn Y/security/credential-guard.py ~/.claude/hooks/credential-guard.py && ln -sfn ...`
  — so there is no window in which the hooks are dangling and a tool call could
  be attempted; or
- do the move from a **shell outside the session** (a terminal the agent does
  not run in), then re-provision.

Chaining is not a style preference here. The usual advice is the opposite — emit
discrete commands, because compound commands prompt. Take the prompt. A separate
`ln -sfn` call is a call that will never execute.

## Why there is no in-band recovery

A `PreToolUse` hook whose script is missing is a **hard error, not a skip**: the
tool call it matches is refused. Guards of this kind are matched broadly on
purpose, so the refusal covers `Bash`, `Read` and `Write` at once. From there:

- Restoring the symlink needs `Bash` — gated.
- Writing a shim at the old path needs `Write` — gated by the same hook.
- Editing `settings.json` to unwire the hook needs `Read`/`Write` — gated.

Every candidate repair is a gated tool call, so the recovery path always leaves
the session and lands on a human. On 2026-08-03 that cost three hand-run
`ln -sfn` commands
(see [`../debug-notes/2026-08-03-rename-dangled-live-hook-symlinks.md`](../debug-notes/2026-08-03-rename-dangled-live-hook-symlinks.md)).

## The generalisation

Symlinks are the instance; the class is larger. **Before moving, renaming or
deleting anything, ask which tool the repair would need, and whether that tool
survives the operation.** If the repair needs the capability the operation
removes, the operation does not belong in the session. The same shape covers:

- the interpreter or virtualenv a hook, formatter or linter is invoked through;
- a settings/config file an active control reads at call time;
- the credential or SSH agent socket the session's own git access depends on;
- any path referenced from *outside* the repo pointing *in* — a rename is local
  and reversible from inside, and a remote configuration change from outside.

The inventory question is short enough to just ask: **what points at this
directory from somewhere I am not editing?**

## Do not "fix" it by failing open

The tempting repair is to make a missing hook script a skip. That trades a loud
total wedge for a session that works perfectly with its security controls
silently absent — the false-green shape from
[`agent-success-signals.md`](agent-success-signals.md), where the broken run is
indistinguishable from a healthy one. Fail-closed is correct; the wedge is the
control working, and it is the reason the outage lasted minutes instead of
however long until someone next read a hook file.

The corollary is that a machine in that state **had no guards**, whatever the
absence of exposure suggests. Calls were rejected before executing rather than
inspected and allowed; any surface those hooks did not gate was unguarded for
the whole window. Treat "nothing leaked" as luck about traffic, not as evidence
the control held.

## The check

Whenever a plan includes moving or renaming a directory: resolve
`~/.claude/hooks/*` (and any equivalent per-vendor hook dir) first, and check
whether any of them point inside the target. If one does, the move goes in the
same command as the re-link, or it goes to a shell outside the session. A
provisioning script's install-time check does not cover this — it verified the
clone existed *when it ran*, and this failure is created after that, by a
command whose own success is what breaks it.
