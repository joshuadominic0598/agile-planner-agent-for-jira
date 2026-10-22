# Sprint Agent engineering decisions

Sprint Agent combines structured Jira queries with narrative retrieval and model-led investigation. Its goal is to produce useful answers with traceable evidence while keeping context and model work bounded. The implementation is a local, export-based application; the design controls are implemented, while changes in answer quality, latency or cost must be established by evaluation.

## Choose the right evidence path

The context stage resolves intent and conversation scope before investigation. Identity, assignment, status and aggregate questions use MongoDB metadata. A question about a technical theme or related work can use keyword/vector retrieval and exported relationships. Exact ticket references have a direct lookup path.

This matters because a semantic search sample cannot establish a project total. A generic staffing question can be answered from distinct people and aggregates without sending every ticket description to the model. Narrative questions still need source text rather than metadata alone.

Implementation: [scope planner](../backend/app/agent/scope_planner.py), [grounding](../backend/app/agent/grounding.py), [tool orchestration](../backend/app/agent/provider.py), [structured tools](../backend/app/agent/tools.py).

## Retrieve, rerank and investigate in batches

The persisted SQLite index combines narrative vectors with FTS5/BM25 keyword retrieval. Fusion, local relevance signals and diversity selection rank the initial candidates. Exported hierarchy and issue links provide related-ticket context.

For larger questions, `investigate_tickets` filters the MongoDB ticket set first, then reviews bounded chunk packets with the selected chat model. Returned quote/ID pairs must match indexed sources. Repeating an investigation advances its cursor; coverage records what was reviewed and what remains.

Effort policies bound candidate pools, evidence passes, tool actions and combined model requests. Packets shrink when the configured model window requires it. Workers here are bounded model evidence-review tasks, executed in passes; this is not a claim of concurrent multi-agent execution. More review may improve evidence coverage but adds model calls. Batching manages scope and context, and does not by itself guarantee lower latency.

Implementation: [hybrid index](../backend/app/agent/index.py), [investigation workers](../backend/app/agent/investigation.py), [retrieval guide](retrieval.md).

## Cache retrieval work with scope isolation

The process-local retrieval cache uses bounded TTL/LRU buckets for query vectors, results and semantic candidate pools. Entries expire after ten minutes. Conservative semantic reuse checks scope, query similarity and important tokens such as ticket numbers and negation; new queries still receive fresh lexical candidates and reranking.

Exact evidence-review cache keys include the dataset, connection/model, question and source packet. Generated answers are not replayed from a similarity cache. The persistent index is separate from these short-lived caches and survives ordinary restarts.

This reduces opportunities for repeated embedding/search/evidence work. Actual savings depend on repeated queries and cache eligibility. Cold and warm requests should be measured separately.

Implementation: [cache adapter](../backend/app/agent/retrieval_cache.py), [investigation cache](../backend/app/agent/investigation.py).

## Keep memory and context within budget

Conversation scope is refreshed for each message so follow-ups can retain a person or ticket, while corrections can broaden the question. Page context is optional. The agent can ask for clarification when a reference is ambiguous.

Context budgeting reserves output space and reduces evidence, history and tool payloads to fit the configured window. Recent examples help answer broad work-history questions, while complete metadata aggregates establish totals. Trimming and review coverage must remain visible so a limited sample does not become an unsupported absence claim.

These controls target input-token growth and context-limit failures. A smaller packet can require another investigation pass, so token reduction and total latency should be assessed together.

Implementation: [context budget](../backend/app/agent/context_budget.py), [conversation scope](../backend/app/agent/conversation.py), [AI scope refresh](../backend/app/agent/scope_planner.py).

## Measure changes rather than assume improvements

1. Inspect a real weak or slow response in Monitoring. Review the prompt, evidence, model/tool calls, token usage and error details.
2. Turn the case into a golden question with a human-verified answer and supporting evidence.
3. Hold the source export, golden dataset, pipeline, people/planning settings and judge constant. Change one prompt revision, model or effort setting.
4. Compare answer support and human ratings alongside latency, first-token timing, calls, tokens and available estimated cost. For cache experiments, compare cold and repeated requests separately.
5. Activate the chosen prompt for chat, then continue collecting feedback.

Model comparisons use the same pinned prompt and test-data versions. Prompt comparisons keep the model constant. BLEU/ROUGE describe wording overlap; Ragas and human review provide separate quality signals. Unknown prices remain unpriced. Local-model cost estimates exclude hardware/electricity, and provider quotas still apply.

Streaming improves visibility of progress and answers; it does not establish faster completion. The repository documents the controls and measured runs separately so performance claims can be tied to a reproducible comparison.

[LLMOps and versioning](llmops.md) · [Evaluation workflow](evaluation.md) · [Monitoring and Langfuse](observability.md)
