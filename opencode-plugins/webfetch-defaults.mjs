// OpenCode 1.18.33 serializes webfetch args into permission metadata.
// Optional undefined values break its JSON response encoder. Keep approval required.
const RETRY_BLOCKED = "DREADOS_WEBFETCH_RETRY_BLOCKED";

function normalizedURL(value) {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    if (!["http:", "https:"].includes(url.protocol)) return null;
    url.hash = ""; // Fragments are not sent to the server; changing one is not a retry fix.
    return url.href;
  } catch { return null; }
}

// OpenCode 1.18 puts a per-message summary ({diffs, title?}) on every user message, so a truthy
// summary is not a compaction marker. Compaction is summary === true, the compaction agent/mode,
// or a compaction part.
function isCompaction(message) {
  const info = message?.info || {};
  return info.summary === true || info.agent === "compaction" || info.mode === "compaction" ||
    (message?.parts || []).some(part => part.type === "compaction");
}

function isUserTask(message) {
  return message?.info?.role === "user" && !isCompaction(message) && message.parts?.some(part =>
    (part.type === "file" || part.type === "text") && !part.synthetic && !part.ignored);
}

// A missing page stays missing, so only the user naming the URL again lifts a 404/410 block.
function userAsksFor(message, url) {
  const target = new URL(url), needle = (target.host + target.pathname + target.search).toLowerCase();
  return message.parts.some(part => part.type === "text" && !part.synthetic && !part.ignored &&
    String(part.text || "").toLowerCase().includes(needle));
}

async function failedFetch(client, directory, input, url) {
  if (!client?.session?.messages || !input.sessionID) return null;
  let messages;
  try {
    // Errors do not reach tool.execute.after in OpenCode 1.18.33. Read recorded
    // tool state instead; only the current session's recent history is needed.
    const result = await client.session.messages({
      path: { id: input.sessionID }, query: { directory, limit: 120 },
      signal: AbortSignal.timeout(3000),
    });
    if (result.error || !Array.isArray(result.data)) return null;
    messages = result.data.filter(message => message.info?.sessionID === input.sessionID);
  } catch { return null; } // A history outage must not disable ordinary tool use.
  let failures = 0;
  let reason = "";
  let missing = ""; // 404/410 for this URL; survives new user tasks in the same session.
  for (const message of messages) {
    if (isUserTask(message)) {
      failures = 0; reason = "";
      if (userAsksFor(message, url)) missing = "";
    }
    if (message.info.role !== "assistant") continue;
    for (const part of message.parts || []) {
      if (part.type !== "tool" || part.tool !== "webfetch" || part.callID === input.callID ||
          normalizedURL(part.state?.input?.url) !== url) continue;
      if (part.state.status === "completed") { failures = 0; reason = ""; missing = ""; }
      if (part.state.status !== "error") continue;
      const error = String(part.state.error || "").slice(0, 1000);
      if (error.includes(RETRY_BLOCKED)) {
        // Older 404s may have scrolled out of the history window; the block message still records them.
        const earlier = /failed with HTTP (404|410)\b/.exec(error);
        if (earlier) missing = "HTTP " + earlier[1]; else reason = "a previous fetch failure";
        continue;
      }
      // Rejected approvals and interrupted tasks are not failed HTTP requests.
      if (/permission|rejected|denied|cancelled|canceled|aborted|interrupted/i.test(error)) continue;
      failures++;
      const status = /(?:status(?:\s*code)?|http)[\s\S]{0,100}?\b(404|410)\b/i.exec(error) ||
        /\b(404)\s+not found\b|\b(410)\s+gone\b/i.exec(error);
      if (status) missing = "HTTP " + (status[1] || status[2]);
    }
  }
  return missing || reason || (failures >= 2 ? "two failed fetch attempts" : null);
}

export const WebFetchDefaults = async ({ client, directory } = {}) => ({
  "tool.execute.before": async (input, output) => {
    if (input.tool === "bash" && process.platform === "win32" && typeof output.args.command === "string") {
      // PowerShell aliases curl to Invoke-WebRequest. Explicit executable keeps curl flags valid.
      output.args.command = output.args.command.replace(/^(\s*)curl(?=\s)/, "$1curl.exe");
    }
    if (input.tool !== "webfetch") return;
    if (output.args.timeout === undefined) output.args.timeout = 30;
    if (output.args.format === undefined) output.args.format = "markdown";
    const url = normalizedURL(output.args.url);
    const reason = url && await failedFetch(client, directory, input, url);
    if (reason) {
      const permanent = /^HTTP (404|410)$/.test(reason);
      throw new Error(`${RETRY_BLOCKED}: This URL already failed with ${reason} ${permanent ? "in this session; the page does not exist" : "during the current user task"}. No new request was sent. Do not fetch this URL again, change only its fragment or format, or retry through a shell. Do not plan around this page. Use a different source if essential, otherwise continue from the project files and disclose that this reference was unavailable. ${permanent ? "It stays blocked unless the user explicitly asks for this URL again." : "A new user request can retry the URL."}`);
    }
  },
  "tool.execute.after": async (input, output) => {
    if (input.tool === "bash" && /Invoke-WebRequest[\s\S]*missing mandatory parameters[\s\S]*Uri/i.test(output.output || "")) {
      throw new Error("PowerShell curl alias failed; no download was verified. Do not repeat this command. Use curl.exe --fail --show-error --location --output <file> <url>, then verify the file is nonempty. Avoid shell output redirection for downloads.");
    }
  },
});
