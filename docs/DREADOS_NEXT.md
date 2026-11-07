# Taking dreadOS to the next level

Product recommendation, November 5, 2026. Based on a targeted review of the current repository; proposed capabilities and success targets below are not implemented or measured by this review.

## The product promise

**Tell dreadOS what you want to make happen. Get something you can use, see what it did, and keep control of your work.**

Everyday users should experience a clear request, visible progress, and a useful result. Technical users should be able to inspect the model, data destination, files, tool activity, and verification evidence behind that same result.

The strongest next move is to connect the capabilities already present into complete tasks. Local voice, provider choice, memory, image generation, the coding workspace, offline references, and preview capture give dreadOS a substantial foundation.

## What the code says

| Existing foundation | Current friction | Opportunity |
| --- | --- | --- |
| Six workspaces in `web/index.html` | Users choose Assistant, Create, Library, Connections, Build, or Map before accomplishing something | Start with outcomes; retain workspaces for deeper work |
| Chat tool proposals in `chat_tools.py` | The planner explicitly chooses one tool; approvals expose raw arguments in `web/app.js` | Explain the action in plain language, with exact arguments available under details |
| OpenCode integration in `opencode_bridge.py` | Its prompt explicitly says Assistant chat is separate and points to `PROJECT_BRIEF.md` | Carry an editable brief and selected attachments into Build |
| Static preview and capture in `build_workspace.py` and `preview_capture.py` | Capture does not test interactions or backend behavior; model review is currently prompt guidance | Record checks and their scope as first-class task results |
| Chat summaries and retrieval in `context_memory.py` | Context is scoped to a chat | Add an explicit project brief before attempting broad memory across projects |
| Persistent media jobs in `media_library.py` | General tool proposals and chat progress are in memory | Reuse durable records and duplicate-prevention patterns for shared tasks |
| Distinctive orb and real activity states in `web/core.js` | The home page emphasizes generic chat and app shortcuts | Keep the visual identity; give the result and current task the main space |

## Priorities

1. **One outstanding complete task.** Start with a static website from a plain-language brief. Connect Assistant to Build, return a working preview, and support a follow-up revision from the same task.
2. **An approachable first session.** Detect configured capabilities, explain missing prerequisites, and guide users to their first result. Show advanced model settings on demand. Resolve the launch/distribution issues documented in README before promising a one-click installation.
3. **A shared project.** Collect the brief, selected sources, generated assets, code, and versions in one place. Explicit actions such as “Use in Build” and “Create an image for this” can precede more autonomous workflows.
4. **Visible evidence.** Show real stages, an accurate local/cloud destination, saved results, and specific recovery actions. Experts can expand file changes, tool inputs, model information, and checks. Only label a task verified to the extent supported by recorded evidence.
5. **Natural follow-up.** Let people type or speak “make the heading smaller” while keeping the same project context. Later, add selection-based visual edits and interruptible voice after the task lifecycle is reliable.

The home screen could lead with “Build a website,” “Create a launch kit,” and “Research a question.” Expose each as a complete workflow only when it is ready; the first release should lead with the website task. Retain the orb as an activity cue, with the result taking visual priority once work exists.

## First release: describe, build, check, deliver

Example request: “Make a website for my food truck. Here is the menu. Use black and lime green, and make it work on phones.”

1. **Capture the brief.** Extract purpose, content, style, and required behavior into a short editable summary. Ask only for genuinely missing essentials. Use explicit sample content when business details are absent.
2. **Prepare the workspace.** Check the selected Build provider, engine, project, attachment support, and capture capability. Create/open the project and pass the brief plus explicitly selected context. Display where inference will run; do not silently switch local work to a cloud model.
3. **Build.** Start one task using existing Build execution and approval controls. Show actual progress such as “Creating the page” or “Waiting for approval.” Explain approvals as actions, retaining technical detail on demand.
4. **Check.** Capture saved desktop and mobile views, record runtime errors and overflow, and request visual review when the selected model supports it. Bound repair attempts. Mark unsupported or unperformed checks explicitly. Screenshots alone do not prove buttons or forms work; interaction testing is a separate extension.
5. **Deliver.** Present the preview, saved files, and a concise check summary, with “Open result” and “Make a change” as the primary actions. Keep unresolved issues visible. An idle coding session is not proof that the requested work is complete.
6. **Revise.** Carry a follow-up such as “Add a vegetarian section” into the same brief/project, preserve existing work, and attach the new result and check evidence to a new task revision.

### Implementation boundaries

- Introduce a durable task record with `task_id`, request ID, chat/project/session references, brief version, selected provider, status, artifact references, and check results.
- Suggested states: `draft`, `preparing`, `running`, `checking`, `needs_approval`, `needs_attention`, `ready_for_review`, and `cancelled`. Derive transitions from execution evidence.
- Use a small task coordinator around current subsystems. Keep OpenCode as the coding executor; start with this bounded workflow before general orchestration across arbitrary tools.
- Preserve project path checks, stale-write detection, recovery copies, and current approval boundaries. A brief handoff does not grant permission to publish or spend media credits.
- Refresh should reload the task. After server restart, reconcile execution state before offering continuation. An uncertain external action needs a status check before any retry that could duplicate it.
- Keep context explicit and editable. Include the brief and chosen assets; do not silently copy unrelated chats into Build.
- Begin with static HTML/CSS/JS, matching the existing preview. Framework dev servers, backend execution, publishing, and visual point-and-edit need separate work.

Likely integration points: a new task store/coordinator; task endpoints in `server.py`; handoff and progress UI in `web/app.js` and `web/build.js`; brief/session integration in `opencode_bridge.py`; references to existing capture and workspace results. Exact filenames should be claimed on the Agent Bus at implementation time.

### Proposed acceptance gates

- A user can go from the request to a saved, usable preview and one revision without manually copying text between workspaces.
- A refresh preserves the brief, task state, and result links; a restart produces an accurate resumable or needs-attention state.
- Duplicate submission does not create duplicate projects or runs. Uncertain external actions are reconciled before retry.
- Failed provider setup, unavailable vision, missing browser runtime, and interrupted execution each have a specific recovery action.
- “Checked” labels correspond to saved evidence; incomplete checks remain visible.
- The default path requires no raw JSON or model IDs after setup, while technical details remain inspectable.
- Pilot with five first-time users and aim for at least four completing the task without coaching. Record setup time, time to first usable preview, manual interventions, and successful revisions on specified hardware/model configurations. These are proposed evaluation goals, not current performance claims.

## What follows

Once the website task works consistently, build two further demonstrations on the same task model: a launch kit that combines copy, an approved generated image, and a landing page; then a research brief with linked sources and a saved result. Project memory, voice steering, and reusable task recipes become more valuable when they operate on this shared foundation.

The public demo should show one continuous request, real tool activity, a usable result, and a visible revision. Use consistent dreadOS naming and current launch instructions across the app and marketing site. Keep advanced local-model controls available for the technical audience.

## External context

Open WebUI already documents provider choice, voice, images, knowledge, and tool use in one interface. My inference is that breadth alone will be a weak differentiator; dreadOS should compete on the quality and continuity of a few complete experiences. [Open WebUI features](https://docs.openwebui.com/features/).

Anthropic's agent design guidance recommends simple composable patterns and increasing complexity when justified. The bounded first workflow above applies that principle to dreadOS's existing subsystems; it does not require adopting a new framework. The article notes that its tooling landscape has evolved since initial publication. [Building effective agents](https://www.anthropic.com/research/building-effective-agents).
