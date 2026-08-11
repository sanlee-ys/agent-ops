/**
 * fleet-guard.ts — fleet redline guard for the Pi lane (v0).
 *
 * Pi has no built-in permission system. This extension is the ADR-012 guard
 * wiring for this vendor. It blocks the three fleet redlines at tool-call time:
 *   1. Reads of credential and secret stores.
 *   2. Destructive operations on published git history.
 *   3. Broad destructive filesystem mutations.
 *
 * This is a deny floor, not a policy engine. It must stay in sync with the
 * guard posture in agent-ops/vendors/. Version this file there; the copy here
 * is the live install.
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

// Redline 1: credential and secret stores. Match reads AND writes.
const SECRET_PATHS = [
  /\.ssh[\\\/]/i,
  /\.aws[\\\/]credentials/i,
  /\.gnupg[\\\/]/i,
  /\.netrc/i,
  /credentials\.json/i,
  /\.pypirc/i,
];

// Redline 2: published-history destruction. The lesson from the 2026-07-26
// incident: a soft reset erased a pushed commit, so reset is blocked in every
// form, not only --hard.
//
// `git branch -D` is force-delete and blocked. Plain `git branch -d` (merged
// only) must pass. Do not put the /i flag on the -D pattern — it made -d match
// -D and blocked ordinary local cleanup (observed 2026-08-11).
const GIT_DESTRUCTIVE = [
  /git\b.*\bpush\b.*(--force|-f\b|--force-with-lease)/i,
  /git\b.*\breset\b/i,
  /git\b.*\bbranch\b.*(?:\s-D\b|\s--delete\s+--force\b|\s--force\s+--delete\b|\s-d\s+--force\b|\s--force\s+-d\b)/,
  /git\b.*\bclean\b.*-[a-z]*f/i,
  /git\b.*\bfilter-(branch|repo)\b/i,
];

// Redline 3: broad destructive mutations.
const FS_DESTRUCTIVE = [
  /rm\s+(-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r)\b/i,
  /Remove-Item\b.*-Recurse\b.*-Force\b/i,
  /rmdir\s+\/s\b/i,
  /format\s+[a-z]:/i,
];

function matchAny(patterns: RegExp[], text: string): RegExp | undefined {
  return patterns.find((p) => p.test(text));
}

export default function (pi: ExtensionAPI) {
  pi.on("tool_call", async (event) => {
    const input = event.input ?? {};
    const command: string = String(input.command ?? "");
    const path: string = String(input.path ?? input.file_path ?? "");

    if (command) {
      const hit =
        matchAny(GIT_DESTRUCTIVE, command) ??
        matchAny(FS_DESTRUCTIVE, command) ??
        matchAny(SECRET_PATHS, command);
      if (hit) {
        return {
          block: true,
          reason: `FLEET GUARD: the command matches a redline pattern (${hit}). Credentials, published history, and broad destructive mutations are blocked in the Pi lane. Ask San to run this himself if it is intended.`,
        };
      }
    }

    if (path) {
      const hit = matchAny(SECRET_PATHS, path);
      if (hit) {
        return {
          block: true,
          reason: `FLEET GUARD: the path matches a secret-store pattern (${hit}). Credential stores are off limits in the Pi lane.`,
        };
      }
    }
  });
}
