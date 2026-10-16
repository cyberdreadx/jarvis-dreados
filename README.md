# DreadOS AI

## Everyday startup

Use **Start DreadOS** / **Stop DreadOS** on the desktop, or `Start-DreadOS.cmd` / `Stop-DreadOS.cmd`. Closing the browser leaves the server available to your iPhone. Start restores saved providers and MCP connections; for the selected local model it checks LM Studio, starts the default local server if necessary, and loads the exact saved model. Custom local servers must be started separately. The header shows startup problems.

## Saved connections, live answers, and chat tools

Provider settings and MCP bearer credentials saved through the UI are encrypted with Windows DPAPI in `data/settings.dpapi`, tied to this Windows account. They restore at server startup. Remove a saved provider key or connection in Setup/Connections to remove it from this store. Environment configuration is still supported; OAuth refresh is not implemented, so expired sign-ins require reconnection. Back up original data; copying the encrypted file to another account is not a credential migration mechanism.

Chat displays provider answer text as it is generated, refreshed roughly every 700 ms. **Stop** requests cancellation at the next received provider event; it does not undo external actions. Partial responses are not saved as complete answers. Provider/network stalls can delay cancellation.

Enable **Use tools** beside the chat composer to request a connected MCP action in plain language. DreadOS proposes one tool and its inputs, or asks for missing information. Nothing runs until **Approve & run**. Approvals expire after ten minutes and cannot run twice. Check the service after a timeout before requesting another action. Text tool results are saved in the chat; inline binary media are currently displayed for that session. This is a single-action approval flow, not an autonomous multi-step agent.

The older implementation notes below describe earlier milestones and may mention superseded session-only credential behavior.

# JARVIS

A local Windows assistant with a dark dashboard, click-to-talk voice input, spoken replies, app shortcuts, and OpenAI, Claude, Grok, or local-model conversation, a content studio, and MCP connections. The base web server uses the Python standard library; voice and tool integrations use their installed runtimes.

The animated interface uses a perspective-projected orbital lattice with a luminous particle field, pointer response, and distinct listening/thinking/speaking states. The visual system pairs midnight-blue surfaces with cyan accents, violet gradients, and angular controls inspired by the RougeChain reference. Rendering uses Canvas without external libraries, pauses when hidden, and respects reduced-motion preferences.

## Run

Double-click `Start-JARVIS.cmd`, then open http://127.0.0.1:8765 in Chrome or Edge. Alternatively run `python server.py` with Python 3.10+. Leave the terminal running; press Ctrl+C to stop.

## Try it

- “Open calculator”, “open notepad”, “open file explorer”, “open paint”
- “Open YouTube”, “open Google”, “open GitHub”
- “Search for space news” (opens a browser search)
- “What time is it?”, “what day is it?”, “help”

Click **Talk to JARVIS** and allow microphone access. This version is click-to-talk, with no wake word or background listening. You can always type. Voice availability depends on browser support, microphone permissions, and the browser's speech service; recognition may send audio to that provider. Speech synthesis uses available browser/system voices. Stop audio cancels playback and active listening.

## AI conversation

Open **Setup**, choose **OpenAI**, **Claude (Anthropic)**, or **Grok (xAI)**, enter that provider's API key and model ID, then click **Use this provider**. Model suggestions are editable. Claude also supports an optional workspace ID for keys that require one. No restart is needed. Saving configures credentials; the next AI message verifies access. API access, model availability, and billing belong to each provider.

Keys entered in Setup live only in server memory until it stops. They are never returned to the browser, added to chat, or written to local storage or disk. Leave the key field blank to keep an existing key for that provider. **Remove session key** disables that provider's key for the current server run. Keys and models remain separate when you switch providers. Switching starts a fresh conversation in that tab; existing messages are not carried to the new provider. Other tabs keep their explicitly selected provider.

For persistent configuration, manually copy `.env.example` to `.env` and set `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and/or `XAI_API_KEY`, along with the corresponding model variables and `JARVIS_PROVIDER` (`openai`, `claude`, `grok`, or `local`). Restart to load environment changes. `.env` is a plaintext local file ignored by Git and never served as an asset. Environment settings load again after restart, including keys removed only for a session.

Adapters use the [OpenAI Responses API](https://developers.openai.com/api/docs/guides/text), [Anthropic Messages API](https://platform.claude.com/docs/en/api/overview), and [xAI Chat Completions API](https://docs.x.ai/developers/model-capabilities/legacy/chat-completions). The current message and up to 12 recent messages go only to the selected provider's fixed HTTPS endpoint; there is no automatic fallback. OpenAI requests use `store: false`; each provider's own data policies apply. Saved conversations live locally in data/chats.sqlite3. New chat starts a separate conversation; refreshing or switching providers preserves saved chats. AI conversation cannot access files or execute commands.

## Local AI / LM Studio

In LM Studio, load a chat model and start the local API server. In JARVIS **Setup**, choose **Local AI**, enter `http://127.0.0.1:1234/v1`, and click **Find local models**. Select the model ID and click **Use this provider**. The server key is optional. Any compatible local server exposing `/v1/models` and `/v1/chat/completions` can be used by changing the port. See [LM Studio's endpoint documentation](https://lmstudio.ai/docs/developer/openai-compat).

Local requests stay on loopback, bypass system proxies, and reject redirects. This first version supports servers on the same computer, not LAN machines. Generation allows up to 120 seconds; model loading and hardware affect speed. For persistent settings, set `LOCAL_BASE_URL`, `LOCAL_MODEL`, optional `LOCAL_API_KEY`, and `JARVIS_PROVIDER=local` in `.env`. Browser voice recognition may still use an external speech service; local AI does not make microphone processing offline.

## Terminal Code (your own Claude sign-in)

Terminal Code lets you chat through Claude Code, Anthropic's command-line program, using your own Claude plan instead of an API key. Install Claude Code, open a terminal, run `claude` and sign in. Then choose **Terminal Code** in **Setup** and click **Use this provider**. Leave Model ID blank for your Claude Code default, or enter `sonnet`, `opus` or `haiku`. To keep it selected after restart, set `JARVIS_PROVIDER=claudecode` in `.env`.

DreadOS never asks for, sees or stores your Claude sign-in; it only runs your own installed `claude` program. Usage counts against your own Claude plan and Anthropic's terms. Each reply runs `claude` once in print mode with all of its tools turned off, so it can only chat. The system prompt is passed in a temporary file and the conversation on standard input, so chat text never appears on the command line. Your DreadOS API keys are not passed to it. Image attachments need an API provider; text files work.

## Create workspace

**Create** offers guided forms for social posts, artwork prompts, and video briefs. It uses your configured AI provider. Artwork/video drafting produces text direction, not fabricated media. Edit responses, copy or download them, or save up to 30 text drafts to the browser's local storage. Drafts are stored unencrypted in that browser profile; use downloads for backups. Clearing browser data removes them.

Connect a generation service to create actual media. Select its connection and tool under **Connected creative tools**. JARVIS builds fields from the server's tool schema; complex fields accept JSON and additional arguments can be supplied. **Use draft as prompt** copies text into common prompt fields. Press **Run selected tool** to explicitly invoke it. No model autonomously selects or executes tools. Results show returned text, inline image data, resource links, and expandable raw output. Asynchronous jobs may require using that service's status tool with its returned job ID. JARVIS does not automatically publish or schedule content.

## MCP connections

**Connections** includes verified endpoint presets for [Higgsfield](https://higgsfield.ai/mcp), [Canva](https://www.canva.dev/docs/apps/mcp/verify-app/), and [Exa](https://exa.ai/mcp), plus custom HTTPS/localhost Streamable HTTP servers. Adding a server performs initialization and tool discovery only. It does not generate, publish, or invoke its tools.

Connections support optional bearer tokens and OAuth browser sign-in via protected-resource discovery, dynamic public-client registration, and PKCE. Click **Sign in**, follow the generated service link, then refresh connections after authorization. Some services require a preregistered/approved OAuth client; these report that limitation and need an authorized HTTP bridge or suitable access token. There is no automatic token refresh: reconnect/sign in after expiry. Connections, credentials, and OAuth states are memory-only and lost on server restart. Account access and credits must be supplied by you; connected Codex accounts are not inherited.

The transport handles legacy MCP 2025 Streamable HTTP JSON/SSE responses and a basic 2026-07-28 stateless fallback when initialization is unsupported. Advanced server-to-client sampling/elicitation, stdio process launch, notifications subscriptions, custom schema-directed MCP headers, and full durable background jobs are not implemented. Unsupported servers report an error rather than appear connected. Tool responses are rendered as text/media, never interpreted as browser HTML or executed as code.

## Design and boundaries

The server binds only to `127.0.0.1`. App commands use a fixed allowlist and never execute user text as a shell command. Requests require a same-origin session token; static files are explicitly allowlisted. This is a personal local prototype, not a multi-user or public server. Don't expose its port publicly. Only basic command patterns are supported; natural-language tool planning, wake-word detection, file access, and persistent memory are future work.

## Verify

Run `python -m unittest discover -s tests -v`, `node --check web/app.js`, `node --check web/core.js`, and `node --check web/studio.js`. Tests mock app/browser launches and cloud AI calls, and use a local fixture server for model discovery, chat, MCP tool discovery, JSON/SSE responses, and OAuth state handling; they do not incur API charges or open applications. Live microphone recognition, audio output, and API credentials must be checked on your own device/account.

## Search, attachments, and personality

Use Web search beside the composer or type “search for …”. Search settings accepts a Brave Search API key (or BRAVE_SEARCH_API_KEY in .env). Without a key, direct browser search links appear with an explicit explanation. The previous Bing RSS feed was removed because it returned unrelated results. Search retrieves snippets, not full pages; it does not automatically research every AI answer.

Attach up to three PNG/JPEG/WebP images (4 MB each, 9 MB total), paste screenshots into the message field, or attach text/code files (40,000 characters each). Images require a vision-capable model/server. Files are stored in the local chat database. Images are sent to the model only with the original message; reattach them for later visual analysis. Text excerpts can be used in subsequent chat context. PDF, audio, and video attachments are not supported.

Personality opens an editable system prompt with JARVIS, Creative partner, Technical expert, and Patient coach presets. Custom edits are saved in this browser and sent to the selected AI provider with each chat request.

## Chat library and memory

Chats opens the local library: create and rename folders, move and rename chats, search titles, and archive or restore conversations. Removing a folder preserves its chats as unfiled. There is no permanent-delete control. Each chat retains its own editable personality and memory notes. Memory notes are sent with each AI request; up to 24 recent messages supply context. Full transcripts, search results and original attachments remain on disk, but older messages outside the context window are not automatically summarized or retrieved. Other chats are never added to the active model context.

The SQLite database is stored at data/chats.sqlite3, ignored by Git, and contains readable personal content (not encrypted). API keys are excluded. Back up the data directory while JARVIS is stopped. Metadata version checks prevent two tabs from silently overwriting a chat.

## Kokoro local voice

Start-JARVIS.cmd uses .venv-voice when installed. Voice beside Talk to JARVIS opens the engine selector, six English voices, speed slider, and preview. Kokoro (George by default) generates speech on CPU using two inference threads; Qwen remains a separate model. Stop audio also cancels queued playback. Browser voice remains selectable. Audio is generated in memory, and reply speech is split into short chunks; the first request loads the model. Voice preferences persist in this browser.

Voice dependencies: requirements-voice.txt. Model assets: data/kokoro/kokoro-v1.0.onnx and voices-v1.0.bin from the kokoro-onnx model-files-v1.1 release. Kokoro weights use Apache 2.0; kokoro-onnx uses MIT. The adapter corrects speed input typing for the pinned runtime/export pair without modifying installed packages.

## Free local search

Start Docker Desktop, then run `docker compose -f compose.search.yaml up -d`. In Search settings choose SearXNG and save `http://127.0.0.1:8088`. No API key is required. JSON results are enabled in the supplied configuration. The service binds only to loopback; this configuration is for this computer, not public hosting. Upstream engines can still rate-limit searches. Provider and address persist locally; Brave keys remain session-only.

## Optional Qwen3-TTS voice

Qwen runs in `.venv-qwen`, independently of Kokoro. Model directory: `data/qwen-tts` (Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice). The `ready.json` marker is created only after an audio smoke test. The CPU worker releases its memory after each request; CPU speech can be much slower than Kokoro. Choose Qwen in Voice studio, preview Ryan or Aiden, and optionally describe the speaking style. The speed slider is unavailable for this engine. Kokoro stays the default.


## Conversation continuity

Saved chats automatically compact older discussion before the estimated context budget fills, or when more than 24 messages remain unsummarized. DreadOS reads the selected loaded model's context length from LM Studio; other servers/providers use a conservative 8,192-token application budget. Counts are estimates, with space reserved for the answer and a safety margin. Very large individual messages/images can still require a larger loaded context or smaller input.

Compaction uses the selected AI provider to maintain a factual summary. It prefers retaining six recent messages verbatim, and always retains at least the latest exchange. The summary is committed atomically with the successful reply and chat version check. A provider failure leaves saved originals and memory unchanged. Manual memory notes remain separate. The full conversation and attachments stay in SQLite; older relevant text excerpts are recalled by keyword matching within that chat. Inspect the summary under **Chat settings & memory → Automatic conversation memory**, or scroll the conversation for original messages. Summaries are lossy and can be corrected through manual memory notes or a new message. Earlier images must be reattached for visual analysis.

The main headline and orb follow actual app stages, including web search, source reading, and memory compaction. Local commands such as `Open calculator` take precedence over the Web search checkbox.

## Build IDE

Build includes a collapsible file explorer, file tabs, line numbers, Ctrl+S, saved HTML preview, change review, and OpenCode chat. Connect OpenCode, create or select a project, then describe what to build. OpenCode uses the selected local model from Setup. Edit and command approvals appear in the agent panel. Projects live under `data/build-projects`.

Save drafts before asking the agent to edit. Revision checks reject stale saves; previous saved text has recovery copies in `.dreados-history`. Clean open files refresh after agent changes. Preview isolates saved HTML/CSS/JS and blocks external connections; framework projects need built HTML output. This initial editor does not yet include IntelliSense, a terminal, or an automatic framework dev server.

## LM Studio model manager

Use **Models** in the header to list downloaded models, loaded instances, capabilities, sizes, maximum context and actual load settings. Load with optional context and evaluation batch settings, unload individual instances, and choose a loaded chat model for Assistant/Create and subsequent OpenCode requests. Embedding models can be loaded but cannot be selected as chat models. Settings use the existing local server URL and in-memory key from Setup. Calls use LM Studio 0.4+ native `/api/v1/models` endpoints, stay on loopback, and reject redirects. Downloads and GPU layer controls remain in LM Studio.

Reference: https://lmstudio.ai/docs/developer/rest/list and https://lmstudio.ai/docs/developer/rest/load

Local microphone input defaults to Parakeet TDT 0.6B v3 (INT8 ONNX CPU), with faster-whisper large-v3-turbo available in the engine selector, separate from Kokoro speech output. Parakeet automatically detects language; language override is available for Whisper. Install requirements-voice.txt into .venv-voice and download the converted mobiuslabsgmbh/faster-whisper-large-v3-turbo model into data/whisper-turbo. Audio stays in memory on the local server; recordings are capped at 60 seconds. Microphone settings offer input selection, language detection (or English/Spanish), pause detection and optional auto-send. Review-before-send is the default. Browser microphone permission is required.

Parakeet model: NVIDIA Parakeet TDT 0.6B v3, using istupakov’s ONNX conversion (CC BY 4.0): https://huggingface.co/istupakov/parakeet-tdt-0.6b-v3-onnx . Place config.json, vocab.txt, nemo128.onnx, encoder-model.int8.onnx and decoder_joint-model.int8.onnx in data/parakeet. The ONNX runtime is CPU-only and preserves GPU memory for the chat model.

### Build syntax editor

Build uses locally bundled CodeMirror 6 with a Cascadia Code / Consolas font stack, One Dark syntax colors, line numbers, folding, bracket matching, autocomplete and per-file undo history. Language is selected from the file extension (HTML, CSS, JavaScript/TypeScript, JSON, Python and Markdown; others remain plain text). Prettier still handles the existing Format / Format on save actions. Alt+Z toggles wrapping, Ctrl+S saves, and Shift+Alt+F formats.

To rebuild the editor asset, run `npm ci` followed by `npm run build-editor` inside `.editor-runtime`. The source is `.editor-runtime/editor.mjs`; the output is `web/vendor/code-editor.js`. The app supplies a per-response CSP nonce for CodeMirror styles. No CDN is needed.

### Quick Windows launch

**Current status: Norton has blocked `DreadOS.exe` as IDP.Generic. Leave it blocked pending vendor review; no false-positive verdict has been confirmed.** The following describes its intended behavior once cleared: double-click `DreadOS.exe` in the project folder. It starts the local server hidden and opens your default browser, or reuses a healthy running server. Keep the executable with this project and `.venv-voice`; it is a launcher, not a standalone installation. Startup errors are logged in `data/launcher-server.log`. LM Studio and Docker-backed services remain separate. You can create a Windows shortcut to the executable. Launcher source and rebuild script are in `launcher/`.

### GLTCH media generation

Connections → GLTCH Runner → paste your API key → Connect. Keys remain in server memory for this session and are passed only to the pinned local GLTCH MCP process. Creator Studio → Generate media exposes Browse models, Generate image, Edit image, Animate image, and Check video progress. Editing/animation require a publicly reachable source image URL. Generation uses your GLTCH account credits; discovery does not generate media. After a timeout, check the job/library before retrying. This works independently of the selected chat model; automatic Assistant tool-calling is not enabled.

Restore the runtime with `npm install --prefix .gltch-runtime --save-exact gltch-runner-mcp@1.0.0 --ignore-scripts`. Node 20+ is required. The adapter launches only this fixed package, without a shell or arbitrary command configuration.

### Shared creative library

Use **Image** in chat (or **Library → Create image**) to review a prompt, choose an image model and shape, and approve the displayed GLTCH credit cost. Direct requests starting with “generate/create/draw/make an image/picture/illustration/artwork” open the same review. The free model catalog supplies current prices; reviews expire after ten minutes. No generation runs just by opening the review.

Approved images run on a background server thread and are tracked in `data/media.sqlite3`. Closing the browser is fine. Keep DreadOS running. Repeated submissions with the same request ID do not generate twice. After a server restart, interrupted jobs become **Check service** instead of being retried automatically; check GLTCH before paying for another request. Provider timeouts and responses with only a job ID also need checking through the connected service.

**Library** shares new image/video tool results, prompts, and saved Create drafts across PC and iPhone using the same private DreadOS server. Search and filter the library, reopen a draft, reuse a prompt, or open a result to download it. Existing browser drafts can be imported explicitly. Remote image/video assets remain provider-hosted URLs and may expire; this is not an offline media backup. Inline image blocks returned by tools are saved in the database. The view shows the newest 500 records; older records remain in the database. Image edit/video generation still use the connected tools in Create.
