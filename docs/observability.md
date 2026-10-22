# Agent monitoring and Langfuse

## Open the separate monitoring dashboard

Run `make setup` once for local Python dependencies, build the frontend with `pnpm --dir frontend build`, and start the application with `make start`. Then run `make monitor` for http://localhost:8012/monitoring, or `make dashboards` for monitoring and evaluation together. These are separate localhost servers; the main app has no operations page in its navigation.

Monitoring reads MongoDB. Both monitoring and evaluation include the same light/dark switch as AgilePlanner, with a persistent browser preference. Selecting a conversation applies its session filter to the cards, charts and run list. Time ranges remain explicit. A response opens its input/output, context, model generations, tool arguments/results, observable activity and feedback. The conversation tab includes earlier messages with pagination. Old answers can be reviewed, but their missing telemetry is never reconstructed as measured data.

New chat traces retain the pinned project prompt bundle, revision and content hash. Expand **Project prompt used** in a response trace to view the saved guidance. Model-call request previews show the actual bounded request context. Older traces without prompt snapshots explicitly show that the revision was not recorded. See the [LLMOps workflow](llmops.md) for prompt/data versioning and controlled comparisons.

## Records and definitions

- `agent_runs`: durable run ID, dataset/session/kind, lifecycle status, timestamps, question/answer, model calls, tool calls, observable events, context evidence, cost snapshot and latest feedback.
- `agent_guardrails`: rejected input decisions before the model workflow.
- `agent_prompt_versions`, `agent_prompt_heads`: immutable guidance bundles and the separate latest/active revision pointers. Editing in evaluation does not silently switch the live chat prompt.
- `agent_messages` and `agent_sessions`: saved conversations; answers link to `run_id`.
- `agent_evaluations`, `agent_eval_cases`, `agent_eval_results`: evaluation definitions, outputs, metrics and human reviews.
- `workspace_settings`: active import and explicit per-model price overrides.

Latency is the full run duration. First-token time is the first visible answer text; observable activity is not treated as an answer token. Output throughput is output tokens divided by total run duration, including tool work. Request volume counts instrumented runs, not individual provider calls. Model calls include the context planner, evidence workers and synthesis; tool calls are listed separately. Generation and tool counts update during a running request. Query-only work can have zero narrative chunks.

`context.average_prompt_chars` measures serialized model request size, including history, instructions and tool schemas. Chunk counts distinguish total returned excerpts and unique stored evidence. Full character counts are retained even when displayed prompts/excerpts are bounded. The UI streams operational actions; private model reasoning is neither exposed nor stored. API credentials and authorization headers are excluded; recognizable key patterns in text are redacted. Ticket content remains sensitive local project data.

Provider usage is preferred. Chat SSE usage events and Responses usage objects are retained. Missing token usage uses a labeled UTF-8/4 estimate; this is not the provider tokenizer or a billing statement. Failed requests may have incomplete usage.

## Costs

`backend/app/observability/model-pricing.json` records the source URL, check time and standard USD text-token rates. `make pricing-refresh` refreshes published prices from the official OpenAI page. Cached-input discounts and known service-tier multipliers are applied; long-context rates are used where the catalog supplies them. Tax, regional uplifts, public web/tool fees, hardware, embedding/index builds and non-text modalities are excluded.

An unknown model/deployment remains unpriced. Use the dashboard’s Token prices section to add a rate override, including an explicit zero-rate assumption for a free tier. New calls retain their rate snapshot; editing a rate does not rewrite old estimates. Local Ollama calls have zero API-token cost, excluding compute/electricity. An external OpenAI-compatible endpoint does not automatically count as free.

Source: https://developers.openai.com/api/docs/pricing

## Native Langfuse integration

Set these values in `.env`, then rebuild/restart the application:

```dotenv
LANGFUSE_PUBLIC_KEY=your-project-public-key
LANGFUSE_SECRET_KEY=your-project-secret-key
LANGFUSE_BASE_URL=https://cloud.langfuse.com
```

Use your own self-hosted Langfuse base URL if preferred. A Langfuse project is optional; no data is sent there when keys are absent. When configured, sanitized project inputs, outputs, tool evidence and usage are exported to that project. Configure it only for a destination appropriate for your project data.

The native Python SDK emits an agent root with child generation/retriever/tool observations under a shared trace/session ID. Model usage and available estimated costs are attached. User votes and optional comments are scores, and human evaluation uses a 1–5 score. Applicable Ragas metrics are exported as named evaluation scores on the answer trace. MongoDB records remain available if Langfuse export fails; the run exposes export status instead of failing the answer. No Langfuse account or external export is assumed when the dashboard reports not configured.

References: https://langfuse.com/docs/observability/sdk/instrumentation and https://langfuse.com/docs/observability/features/token-and-cost-tracking

## Input and relevance guardrails

The `better-profanity` screen, Unicode/control-character checks and credential-disclosure checks run before chat/steering reaches the workflow. Software terms such as terminating a worker are handled in context. Screening is a practical first pass, not a guarantee of perfect language classification.

The selected model’s context-analysis stage classifies relevance against conversation and project context. Clearly unrelated requests get a short model-written boundary response. Unknown terms require investigation; an empty relevant search should be acknowledged, not replaced with invented tickets. Ambiguous identifiers and planning measures can require clarification.
