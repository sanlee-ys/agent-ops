/**
 * fleet-guard.ts. Thin Pi wrapper for the fleet guards.
 *
 * This file holds no redline patterns. On tool_call and user_bash it
 * writes the event as JSON and it runs vendors/pi/hooks/pi-guard-adapter.py.
 * A pass returns nothing. A tool_call deny returns { block: true, reason }.
 * A user_bash deny returns a finished command result with exitCode 2.
 *
 * How this file finds Python. Fail closed if no interpreter is found.
 * 1. Use process.execPath only when its file name is a Python interpreter.
 * 2. Search PATH for py, then python3, then python.
 * 3. Try %LOCALAPPDATA%\Python\bin\python3.exe.
 * For each candidate, run `import sys; print(sys.executable)` and use
 * that path. This selects the real interpreter, not a WindowsApps alias.
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const MARKER = join("security", "credential-guard.py");
const ADAPTER_REL = join("vendors", "pi", "hooks", "pi-guard-adapter.py");
const TIMEOUT_MS = 135_000;
const PYTHON_PROBE = "import sys; print(sys.executable)";

function thisDir(): string {
  try {
    return dirname(fileURLToPath(import.meta.url));
  } catch {
    return process.cwd();
  }
}

function walkForMarker(start: string): string | undefined {
  let here = start;
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

function repoRoot(): string | undefined {
  const env = process.env.AGENT_OPS_ROOT;
  if (env && existsSync(join(env, MARKER))) {
    return env;
  }
  return walkForMarker(thisDir()) ?? walkForMarker(process.cwd());
}

function adapterPath(root: string): string | undefined {
  const nextToExt = join(thisDir(), "..", "hooks", "pi-guard-adapter.py");
  if (existsSync(nextToExt)) {
    return nextToExt;
  }
  const inRepo = join(root, ADAPTER_REL);
  if (existsSync(inRepo)) {
    return inRepo;
  }
  return undefined;
}

function looksLikePython(execPath: string): boolean {
  const base = execPath.replace(/\\/g, "/").split("/").pop() ?? "";
  return /^(python(\d+(\.\d+)*)?|py)(\.exe)?$/i.test(base);
}

function probePython(cmd: string): string | undefined {
  const result = spawnSync(cmd, ["-c", PYTHON_PROBE], {
    encoding: "utf8",
    timeout: 15_000,
    windowsHide: true,
  });
  if (result.error || result.status !== 0) {
    return undefined;
  }
  const line =
    (result.stdout ?? "").trim().split(/\r?\n/).filter(Boolean).pop() ?? "";
  if (!line || /WindowsApps/i.test(line) || !existsSync(line)) {
    return undefined;
  }
  return line;
}

let cachedPython: string | "missing" | undefined;

function findPython(): string | undefined {
  if (cachedPython === "missing") {
    return undefined;
  }
  if (cachedPython) {
    return cachedPython;
  }
  const names: string[] = [];
  if (looksLikePython(process.execPath)) {
    names.push(process.execPath);
  }
  names.push("py", "python3", "python");
  const local = process.env.LOCALAPPDATA
    ? join(process.env.LOCALAPPDATA, "Python", "bin", "python3.exe")
    : "";
  if (local && existsSync(local)) {
    names.push(local);
  }
  for (const name of names) {
    const resolved = probePython(name);
    if (resolved) {
      cachedPython = resolved;
      return resolved;
    }
  }
  cachedPython = "missing";
  return undefined;
}

function asRecord(value: unknown): Record<string, unknown> {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return {};
}

function resolveCwd(eventCwd: unknown, ctx: { cwd?: unknown } | undefined): string {
  if (typeof eventCwd === "string" && eventCwd) {
    return eventCwd;
  }
  if (typeof ctx?.cwd === "string" && ctx.cwd) {
    return ctx.cwd;
  }
  return process.cwd();
}

/** Spawn the adapter. Return the deny reason, or undefined when the call may run. */
function runAdapter(
  payload: Record<string, unknown>,
  cwd: string,
): string | undefined {
  try {
    const python = findPython();
    if (!python) {
      return "PI FLEET GUARD: no Python interpreter. The fleet adapter cannot run. A check that did not run is not a pass.";
    }
    const root = repoRoot();
    if (!root) {
      return "PI FLEET GUARD: agent-ops checkout not found. Set AGENT_OPS_ROOT or run from the checkout. A check that did not run is not a pass.";
    }
    const adapter = adapterPath(root);
    if (!adapter) {
      return "PI FLEET GUARD: pi-guard-adapter.py is missing. A check that did not run is not a pass.";
    }

    const result = spawnSync(python, [adapter], {
      input: JSON.stringify(payload),
      encoding: "utf8",
      timeout: TIMEOUT_MS,
      windowsHide: true,
      env: { ...process.env, AGENT_OPS_ROOT: root },
      cwd,
    });

    if (result.error) {
      const code = (result.error as NodeJS.ErrnoException).code;
      if (code === "ETIMEDOUT") {
        return "PI FLEET GUARD: the adapter did not finish in time. A check that did not run is not a pass.";
      }
      return `PI FLEET GUARD: the adapter did not start. ${result.error.message}`;
    }
    if (result.status === 0) {
      return undefined;
    }
    if (result.status === 2) {
      return (
        (result.stdout || "").trim() ||
        (result.stderr || "").trim() ||
        "PI FLEET GUARD: the adapter denied this call and gave no reason."
      );
    }
    return `PI FLEET GUARD: the adapter exited ${result.status}. A check that did not run is not a pass.`;
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err);
    return `PI FLEET GUARD: internal error. ${detail}`;
  }
}

function bashPayload(command: string, cwd: string): Record<string, unknown> {
  const input = { command };
  return {
    toolName: "bash",
    tool_name: "bash",
    input,
    toolInput: input,
    tool_input: input,
    cwd,
  };
}

export default function (pi: ExtensionAPI) {
  pi.on("tool_call", async (event, ctx) => {
    const input = asRecord(event.input);
    const cwd = resolveCwd(undefined, ctx);
    const reason = runAdapter(
      {
        toolName: event.toolName,
        tool_name: event.toolName,
        toolCallId: event.toolCallId,
        input,
        toolInput: input,
        tool_input: input,
        cwd,
      },
      cwd,
    );
    if (reason) {
      return { block: true, reason };
    }
  });

  // !command and !!command fire user_bash, not tool_call.
  pi.on("user_bash", async (event, ctx) => {
    const command = typeof event.command === "string" ? event.command : "";
    if (!command.trim()) {
      return;
    }
    const cwd = resolveCwd(event.cwd, ctx);
    const reason = runAdapter(bashPayload(command, cwd), cwd);
    if (reason) {
      return {
        result: {
          output: reason,
          exitCode: 2,
          cancelled: false,
          truncated: false,
        },
      };
    }
  });
}
