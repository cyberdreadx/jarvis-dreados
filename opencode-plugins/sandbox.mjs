// DreadOS sandbox: for projects with the sandbox on, Bash calls run inside that project's Docker
// container instead of on this PC. Only the plugin is exported: OpenCode calls every export.
// The command is handed to sandbox.py as base64 JSON so no shell
// (PowerShell, cmd or bash) can reinterpret it; DreadOS decodes it again for approvals and display.
import { readFileSync, existsSync } from "fs";
import path from "path";
import { fileURLToPath } from "url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const STATE = process.env.DREADOS_SANDBOX_STATE || path.join(ROOT, "data", "opencode", "sandbox.json");
const SCRIPT = path.join(ROOT, "sandbox.py");
const PYTHON = [path.join(ROOT, ".venv-voice", "Scripts", "python.exe"), path.join(ROOT, ".venv-voice", "bin", "python")]
  .find(p => existsSync(p)) || (process.platform === "win32" ? "python" : "python3");
const WINDOWS = process.platform === "win32";

function norm(p) {
  const value = path.resolve(p);
  return WINDOWS ? value.toLowerCase() : value;
}

function sandboxRoot(workdir, statePath = STATE) {
  let projects;
  try { projects = JSON.parse(readFileSync(statePath, "utf8")).projects || {}; } catch { return null; }
  const target = norm(workdir);
  for (const root of Object.keys(projects)) {
    if (target === root || target.startsWith(root.replace(/[\\/]+$/, "") + path.sep)) return root;
  }
  return null;
}

function arg(p) {
  // Forward slashes work in PowerShell, cmd and bash; quoting is only needed with spaces.
  const value = WINDOWS ? p.replace(/\\/g, "/") : p;
  if (!/\s/.test(value)) return value;
  return WINDOWS ? `& "${value}"` : `'${value.replace(/'/g, "'\\''")}'`;
}

function wrap(command, workdir, root, timeoutMs) {
  // The Windows PowerShell curl fix (webfetch-defaults) must not leak into the Linux container.
  const original = command.replace(/^(\s*)curl\.exe(?=\s)/, "$1curl");
  const seconds = Math.ceil((Number(timeoutMs) > 0 ? Number(timeoutMs) : 120000) / 1000);
  const payload = Buffer.from(JSON.stringify({ c: original, w: workdir, r: root, t: seconds })).toString("base64");
  const python = arg(PYTHON);
  const script = /\s/.test(SCRIPT) ? `"${SCRIPT.replace(/\\/g, "/")}"` : arg(SCRIPT);
  return `${python} -X utf8 ${script} run ${payload}`;
}

export const DreadOSSandbox = async ({ directory } = {}) => ({
  "tool.execute.before": async (input, output) => {
    if (input.tool !== "bash" || typeof output.args?.command !== "string") return;
    const base = directory || process.cwd();
    const workdir = path.resolve(base, output.args.workdir || ".");
    const root = sandboxRoot(workdir) || sandboxRoot(base);
    if (!root) return;
    // A workdir outside the sandboxed project is refused inside sandbox.py, never run on the host.
    output.args.command = wrap(output.args.command, workdir, root, output.args.timeout);
  },
});
