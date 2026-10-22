# Agent quality and observability implementation

## Delivery plan

1. Navigation and retry: use browser history for ticket and agent subviews, preserve the originating sprint/filters/scroll, add touch back navigation, and provide explicit retry/edit actions for failed messages.
2. Persistent workspace: retain uploaded source files, MongoDB datasets, configuration, conversations and the SQLite retrieval index across refresh/restart. Add an explicit fresh-workspace command with a recoverable backup. Ordinary restart preserves everything.
3. Duplicate discovery: compare only tickets in the exported To Do status category (fall back to an exact To Do status when category is missing). Compare title/description fingerprints and indexed embeddings; display evidence and similarity, never auto-delete. Add a clearly marked synthetic near-duplicate fixture and preserve CSV duplicate headers.
4. Response feedback: thumbs up/down and an optional 300-character note, saved against a durable run ID and conversation/message. Feedback persists and appears in monitoring and Langfuse when configured.
5. Instrumentation: persist run lifecycle, latency, first-token timing, throughput, model/tool/skill calls, provider-reported or explicitly estimated tokens, context/retrieval evidence, errors, feedback and versioned pricing in MongoDB. Never log credentials or private model reasoning. Optional Langfuse export mirrors agent/model/tool traces and scores.
6. Guardrails: validate every submitted message before the workflow, screen inappropriate content and secret-exfiltration requests, resolve relevance in the context-analysis stage, and answer unrelated/unmatched requests gracefully without inventing ticket evidence.
7. Two standalone dashboards: make monitor and make evaluation-dashboard launch independent browser views for live aggregate/conversation/run monitoring and model evaluation/human review. Selecting a conversation scopes all metrics and charts. Both read persisted MongoDB records.
8. Evaluation and documentation: parse the complete Downloads/Conversation.docx into private, versioned cases; retain original responses as provisional references requiring human verification. Replay every question against the configured Gemini connection, compute retrieval/answer metrics including Ragas where applicable, support comparison runs and 1–5 human ratings. Update the product README and keep setup/detail guides in their respective folders.

## Verification

Use targeted tests for navigation history and swipes, retries, guardrail boundaries, To Do-only duplicates, persistence/reset isolation, telemetry/token arithmetic, feedback validation, evaluation parsing/runs and dashboard drill-down. Run backend checks and the frontend build, exercise desktop/mobile flows, and verify the deployed app plus both dashboards. Live evaluation reports must distinguish successful, failed, skipped and unverified-reference cases; never substitute fabricated scores.

## Sources

- https://developers.openai.com/api/docs/pricing
- https://developers.openai.com/api/docs/guides/moderation
- https://langfuse.com/docs/observability/sdk/instrumentation
- https://langfuse.com/docs/observability/features/token-and-cost-tracking
- https://docs.ragas.io/en/stable/getstarted/rag_eval/

## Progress

- Navigation layers, right-swipe dismissal, retries after configuration changes/refresh, and durable pending messages implemented and exercised on desktop/mobile.
- Imports now retain source copies and active-workspace metadata. Index format/configuration are checked and reused across conversations/restarts. Explicit reset was tested only in an isolated workspace; the real workspace was preserved.
- To Do-only duplicate review implemented. A labeled synthetic pair was added to the private export with a backup, and a separate fictional pair is included in the public 100-ticket demo.
- Response feedback, MongoDB telemetry, provider/estimated token accounting, versioned prices, input screening and model relevance handling implemented. Native Langfuse traces and scores are optional; no project keys were available for an external export test.
- Separate monitoring/evaluation dashboards implemented with conversation/run drill-down, context evidence, feedback and human reference review.
- Downloads/Conversation.docx extracted completely (181 paragraphs, 14,208 characters, 16 question/answer cases). All questions were attempted on the saved Gemini connection: 13 answers, 3 low-effort budget failures. Ragas scoring covers applicable evidence; original answers remain provisional.
- A second replay uses saved GPT-3.5 with Gemini as judge. Results and failures are retained privately in MongoDB and resources/evaluation. These initial comparisons are exploratory; human scores and controlled pipeline versions are still required for a model recommendation.
- README and component guides updated. Verification details and private live results are recorded in resources/evaluation/verification-report.md.
