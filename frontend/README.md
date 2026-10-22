# Frontend

[Product tour](../README.md) · [Architecture and development](../docs/README.md) · [Backend API](../backend/README.md) · [Chat behavior](../docs/chat_experience.md)

React 19, TypeScript and Vite provide the upload/setup journey, Overview, Sprint explorer, ticket details, people profiles and streaming Sprint Agent chat.

The separate operations entry point includes monitoring, golden dataset editing, versioned project prompts, one/two-model evaluations and per-question comparisons. `operations/PromptVersions.tsx` handles prompt history and activation; the selected revision is pinned for evaluation without changing chat settings. See [LLMOps](../docs/llmops.md).

## Run locally

Requires Node.js 24+, pnpm 11.25.0 and the backend running separately. From the repository root:

```sh
make setup
make frontend
```

Open `http://127.0.0.1:5173`. Vite proxies `/api` to FastAPI on port 8000. `make setup` also prepares the backend environment; see [full development setup](../docs/README.md#local-development).

## UI modules

| Component | Responsibility |
| --- | --- |
| `frontend/src/People.tsx` | People metrics, role drilldowns, profile editing, and save feedback |
| `frontend/src/RoleChart.tsx` | Shared horizontal role chart and optional people drilldown |
| `frontend/src/SprintRoles.tsx` | Project/sprint scoped role counts and chart loading/errors |
| `frontend/src/IssueIdentity.tsx` | Independent type colors and purple parent badges |
| `frontend/src/FieldExplorer.tsx` | Optional exported-field charts and click-to-filter |
| `frontend/src/WorkflowEditor.tsx` | Single status-to-display-name setup at import and on the dashboard |
| `frontend/src/AgentChat.tsx` | Streaming chat, model selector, attachments, activity, charts, cross-page sessions and retry feedback |
| `frontend/src/AgentAnswer.tsx` | Safe Markdown/GFM rendering, verified ticket links and data-backed charts |
| `frontend/src/AgentHistory.tsx` | Paginated saved chats and original-snapshot restoration |
| `frontend/src/useAgentWindow.ts` / `AgentProgress.tsx` | Window geometry/full screen and dismissible, honest progress |
| `frontend/src/AgentConnections.tsx` | Saved local/GPT/Azure connection forms, key editing and connection tests |
| `frontend/src/App.tsx` | Upload, processing, dashboard, filters, and issue details |
| `frontend/src/styles.css` | Blue theme tokens, interactive states, and responsive desktop/mobile layout |

## Build and browser checks

From this `frontend/` directory, after dependency setup:

```sh
pnpm build
pnpm exec playwright install chromium
pnpm test:e2e
pnpm check:chat-format
```

Browser tests start a real backend on port 8011, serve the built frontend and use isolated synthetic data under `resources/tests/e2e` and the isolated `sprintlens_e2e` MongoDB database. They cover desktop and mobile. Run `make database` from the project root and build before running them; keep port 8011 available. The formatting command intentionally targets the listed chat files rather than the entire frontend.

The [dashboard counting guide](../docs/README.md#dashboard-counting-and-configuration) explains filters, categories, status grouping, role counts and estimates. The [chat guide](../docs/chat_experience.md) covers scrolling, window geometry, progress and response presentation.

## README screenshots

After `make setup`, run from this directory:

```sh
pnpm build
pnpm exec playwright install chromium
pnpm docs:screenshots
```

With MongoDB running (`make database`), the helper starts an isolated backend with synthetic data under `resources/screenshots/` and a temporary MongoDB database, captures the five product-tour screens plus context/configuration views and removes that temporary workspace afterward. It does not connect to the running app. By default it captures the unconfigured chat honestly; optionally set SCREENSHOT_MODEL and SCREENSHOT_MODEL_BASE_URL to capture a real compatible-model response using the synthetic project. All images use a 1440 × 1040 viewport, scale 1, light theme and the same demo project. Captures are viewport-only so the blue sidebar ends at the image bottom. Use `PLAYWRIGHT_EXECUTABLE_PATH` to select an existing compatible browser if needed.

See [image conventions](../resources/images/README.md) before adding screenshots.

[Model-led management chat](../docs/agile_agent.md) adds the scoped project brief editor and compact repeated-tool summaries. The normal chat UI requires a model.


## Theme palette

Use shared surface, text and border variables from `src/theme.css` for application UI. Both themes define every semantic color, including code, info/success/error notices, selected rows and badges. Keep chart data colors and deliberate solid brand buttons separate from surface colors. Avoid literal white/light backgrounds in components.

`pnpm exec playwright test tests/theme.spec.ts` exercises dark onboarding, overview, people/status editors, sprint/ticket/backlog views, every provider form and rich chat states on desktop and mobile. It scans rendered elements for bright opaque surfaces and checks code contrast, including interactions that reveal hidden panels. This catches new theme gaps without relying on a hand-maintained component list.

The independent operations entry point is `operations.html` / `src/operations/main.tsx`. Vite builds it alongside the product app; `make monitor` and `make evaluation-dashboard` serve it from separate localhost servers. Browser checks: `pnpm exec playwright test -c playwright.operations.config.ts`.

`useBackLayer` registers same-URL browser-history entries for workspace ticket details. The agent uses separate local navigation (`useAgentBack`): touch right-swipes and horizontal trackpad back gestures within its window dismiss Configure, History or Context without changing website history. Vertical scrolling, text editing, window dragging and horizontal content scrollers keep their normal behavior. A back gesture in the conversation stays in the agent. Agent retries preserve pending input and use the current model connection. Response feedback is linked by durable run ID.
