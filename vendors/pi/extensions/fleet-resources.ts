/**
 * fleet-resources.ts: point Pi at the canonical fleet skills.
 *
 * On resources_discover, return skillPaths for
 * <agent-ops-root>/vendors/claude/skills.
 * Hold no redline policy. Do not subscribe to tool_call.
 */
import { existsSync, realpathSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const MARKER = join("security", "credential-guard.py");
const SKILLS_REL = join("vendors", "claude", "skills");

function extensionDir(): string {
  const filePath = fileURLToPath(import.meta.url);
  try {
    return dirname(realpathSync(filePath));
  } catch {
    return dirname(filePath);
  }
}

// AGENT_OPS_ROOT wins. Else walk up from this file for the marker.
// A Windows copy of this file lives outside the repo, so the walk
// finds nothing unless AGENT_OPS_ROOT is set.
function repoRoot(): string | undefined {
  const env = process.env.AGENT_OPS_ROOT;
  if (env && existsSync(join(env, MARKER))) {
    return env;
  }
  let here = extensionDir();
  while (true) {
    if (existsSync(join(here, MARKER))) {
      return here;
    }
    const parent = dirname(here);
    if (parent === here) {
      return undefined;
    }
    here = parent;
  }
}

function isDirectory(path: string): boolean {
  try {
    return statSync(path).isDirectory();
  } catch {
    return false;
  }
}

function discoverSkillPaths(): string[] {
  const root = repoRoot();
  if (!root) {
    return [];
  }
  const skills = join(root, SKILLS_REL);
  if (!isDirectory(skills)) {
    return [];
  }
  return [skills];
}

export default function (pi: ExtensionAPI) {
  pi.on("resources_discover", async () => {
    return { skillPaths: discoverSkillPaths() };
  });
}
