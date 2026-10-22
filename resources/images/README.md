# Documentation images

[Product tour](../../README.md) · [Screenshot helper](../../frontend/scripts/capture-readme.mjs)

Keep published screenshots and rendered diagrams here. Use lowercase snake_case filenames, such as `chat_reading_desktop.png`, and keep the conventional `README.md` entry point. Every image must be embedded in or linked from current documentation. Reusable diagram icons live in [icons/](icons/), with [source attribution](icons/sources.md). Linked scalable SVG downloads stay alongside their PNG previews.

Verification captures and temporary screenshots belong under ignored `resources/screenshots/`; editable diagram sources remain under `docs/diagrams/`.

## Product screenshots

The screenshot helper generates the five product-tour views (`readme_upload.png`, `readme_overview.png`, `readme_sprint.png`, `readme_backlog.png`, `readme_agent.png`) and the two technical chat views (`readme_agent_context.png`, `readme_agent_settings.png`). Every generated image is referenced by a current guide.

- Use the fictional 100-ticket CSV in `resources/demo/`, never private project data.
- Capture a 1440 × 1040 viewport at scale 1 in the light theme, without browser chrome or full-page scrolling. Preserve the original aspect ratio.
- Keep actual loading and model states visible. Do not invent answers. Chat captures have no connected model by default; set `SCREENSHOT_MODEL` and `SCREENSHOT_MODEL_BASE_URL` for a real local-model response.

Regenerate from `frontend/` after building the app:

```sh
pnpm build
pnpm exec playwright install chromium
pnpm docs:screenshots
```

Other screenshots in this folder remain linked from technical guides. `readme_project_prompts.png` uses the operations browser fixture with fictional guidance; regenerate it with the `project prompts can be versioned` test in `frontend/tests/operations.spec.ts` and copy the desktop capture from `frontend/test-results/`.

`chat_reading_desktop.png` uses a 1440 × 1120 viewport to show the complete real local-model answer, related-ticket sources and tool details on fictional password-reset tickets. Regenerate it from `frontend/` with `node scripts/capture-chat-reading.mjs`, with local Ollama, EmbeddingGemma and the configured Qwen3 8B alias available. The capture helper saves its response/tool provenance under `resources/screenshots/chat-reading/`. Never replace it with a placeholder scroll-test capture.

## Diagrams and validation

Guides embed PNG previews for portable rendering. Mermaid and draw.io sources under `docs/diagrams/` remain editable. `llmops_loop.png`, `agent_trace.png` and `agent_configuration.png` render their corresponding Mermaid sources. Architecture and lifecycle guides link the scalable exports they use.

Run `make check-docs` to validate local links, exact filename case, heading anchors and images. It also rejects unused image assets throughout this folder, names outside the documentation snake_case convention, SVG embeds and unrendered Mermaid blocks. External websites are not fetched.
