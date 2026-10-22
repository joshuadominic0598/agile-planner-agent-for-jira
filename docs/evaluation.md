# Conversation evaluation and human review

## Configure and run from the screen

Open **Evaluation → Golden datasets**. The existing imported Word conversation appears alongside the bundled 10-exchange demo benchmark. Select a version to inspect questions, expected answers, conversation IDs, reference evidence and verification status. Add, remove or reorder exchanges; exclude cases temporarily; edit expected ticket keys and clarification behavior. **Save as new version** publishes a new immutable revision. Historical versions are read-only and can be restored as another revision. Download a version as JSON for a portable, Git-compatible snapshot; keep private datasets outside public repositories.

**Project prompts** shows shared guidance and project briefs for a ticket export. Select an existing revision, edit text and save a new immutable version. **Use for chat** activates a saved revision; saving in this screen alone leaves chat unchanged. Saving project context from Sprint Agent creates and activates a revision. [Prompt history and LLMOps workflow](llmops.md).

**Run tests** evaluates one generating model or compares two against the same saved questions and chosen prompt revision. Select the ticket export, prompt revision, investigation effort and common Ragas judge. Workers run independently of the browser/dashboard and persist progress/results in MongoDB. The prompt is pinned for every question and tool read, even if active guidance changes during the job. Fresh conversation memory is used per model, with conversation IDs preserving each dialogue. Unsaved dataset or prompt changes cannot be tested. An index is required for agent runs, and source fingerprints prevent accidentally testing the demo benchmark against private project data. Rebinding an export requires saving a new version and re-verifying expected facts.

**Score uploaded answers / evidence** skips agent generation. If a candidate response exists, it is compared to the expected answer and its actual retrieved context. If only an expected answer is supplied, it can be checked for support in provided reference evidence; self-overlap and nonexistent retrieval/generation metrics are not reported as measured scores. This mode does not require an agent index.

**Performance history** filters results by golden dataset, data version and prompt revision (latest 100 runs in the selected dataset/data-version scope). Old run references and answers remain frozen with a prompt snapshot, revision and content hash. Open two results to compare latency, model/tool calls, evidence scores and wording scores **for each question**, and inspect both answers. For a prompt experiment, hold the model, golden data, source export, effort, judge and pipeline constant. Different questions, references, verification states, pipeline versions and source exports limit the validity of a comparison. Legacy tests and unrecorded prompts are labeled rather than assigned a revision retroactively. Uploaded-output scoring does not claim that a newly selected prompt produced historical answers.

## CSV acceptance criteria

Use **Import DOCX / JSON / CSV**, or download the CSV template from the screen. CSV rules:

- UTF-8 (BOM accepted), a header plus 1–200 exchanges, distinct column names, up to 3 MB. Quote answer/context cells containing commas or line breaks.
- Required: `question` (alias `user_input`) and `reference_answer` (aliases `reference`, `ground_truth`, `expected_answer`) **or** `answer` (`response`). Questions may contain up to 3,000 characters; expected answers 12,000.
- `reference_contexts` stores expected evidence. Each context field accepts a JSON array of strings, a single quoted text cell, or chunks separated by `|||`. Reference evidence permits 12 chunks; captured retrieval permits 24, each at most 6,000 characters. A saved version is limited to 6 MB; split larger sets.
- When both `reference_answer` and `answer` are present, `answer` is the recorded candidate response and `retrieved_contexts` is its actual retrieval. With only `answer`, it becomes the expected answer and `retrieved_contexts` supplies candidate reference evidence. This distinction is shown in the screen and prevents accidental self-scoring.
- Optional: `conversation_id`, `reference_status` (`verified`, `needs_human_verification`, `curated_behavior`), `context_status` (`verified`, `needs_human_verification`, `missing`), `expected_ticket_keys` (comma-separated), `should_clarify`, `enabled` (true/false).
- Imported answers/evidence default to unverified. The app reports missing fields, malformed arrays, inconsistent row widths and size errors. It does not invent missing context.

```csv
question,reference_answer,reference_contexts,answer,retrieved_contexts,conversation_id
"What needs testing?","APP-2 needs testing.","[""APP-2 | Testing""]","APP-2 needs testing.","[""APP-2 | Testing""]",conversation-1
```

## Expected evidence versus actual retrieval

Expected/reference evidence belongs to the golden version. Actual retrieved evidence belongs to each execution result. Editing one never rewrites the other. The fictional demo includes source-backed evidence for all 10 exchanges. The existing conversation adopts available historical snippets as **candidate evidence**, with run provenance, pending human verification; one question had no captured retrieval and remains explicitly missing. A historical model's retrieval is not automatically ground truth.

Ragas faithfulness checks whether answer claims are supported by supplied context. Verified expected answers enable reference-based context precision and context recall. Verified reference evidence also enables Ragas non-LLM text precision/recall (Levenshtein threshold 0.5); chunk boundaries and wording affect this heuristic. Structured queries and reference-only validation are not presented as ranked agent retrieval. Sampling, applicability, missing context and judge errors remain visible. This separates retrieval quality, answer grounding and expected-answer quality instead of treating them as one score.

## BLEU and ROUGE

Each completed response with a distinct reference gets **BLEU-2/3/4/5**, **ROUGE-2/3/4/5 precision, recall and F1**, and **ROUGE-L precision, recall and F1**. Sentence BLEU uses NLTK's uniform cumulative weights and Chen–Cherry method 1 smoothing. ROUGE uses Google's `rouge-score`; both share Unicode word tokenization, case-folding and no stemming. Orders longer than either text are marked not applicable. Existing results gain these derived metrics on inspection without changing their saved references.

The screen combines evidence support, retrieval relevance/recall, wording overlap and human ratings. It supplies descriptive interpretation rather than an arbitrary blended grade: a faithful paraphrase may have low BLEU, and copying an incorrect reference may have high overlap. Provisional references are labeled. Aggregate profiles are per-answer means over applicable completed responses, not corpus BLEU or scores for failed requests.

Sources: [NLTK BLEU](https://www.nltk.org/api/nltk.translate.bleu_score.html), [Google ROUGE](https://github.com/google-research/google-research/blob/master/rouge/rouge_scorer.py), [Ragas recall](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/context_recall/).

## Command line workflow

```sh
make evaluation-setup
make evaluation-import DOCUMENT="/path/Conversation.docx"
make evaluate DOCUMENT="/path/Conversation.docx" DATASET=<import-id> CONNECTION=<connection-id> RAGAS=1
make evaluation-dashboard
```

The default document is `~/Downloads/Conversation.docx`. Without `DATASET`, the runner uses the active/latest import; without `CONNECTION`, it selects a saved Gemini connection. Use the same source export and document version for comparisons. Saved connection IDs are available through `/api/agent/connections` or your browser’s configuration requests; keys are never CLI arguments.

The separate dashboard opens at http://localhost:8013/evaluation. Select a run, inspect question/reference/response/evidence, compare another model, and assign a human score from 1 poor to 5 excellent with a 300-character note. A reviewer can verify or correct the reference by publishing a new golden version for subsequent runs; historical test references stay unchanged. Human scores are never fabricated by the runner.

For a second model, repeat `make evaluate` with a different saved connection. Compare common questions, reference versions and source snapshot hashes and pipeline fingerprints. Older runs without a pipeline fingerprint are explicitly marked as exploratory comparisons. Different coverage, model settings or source data can invalidate a direct aggregate ranking.

## Dataset provenance

The importer reads Word paragraph text, preserving the ordered question/answer pairs and preceding conversation. It records document SHA-256, source filename, case number, original response, current reference, reference status and expected behaviors. It extracts every agent-marked turn, even where a visible “You” label was omitted. The provided conversation contains 16 such pairs.

A pasted AI answer is not automatically verified truth. Original responses remain `needs_human_verification`. Ambiguous “explain this ticket” and wrong-ticket correction cases use an explicit clarification expectation while retaining the original answer for audit. Private cases are stored in MongoDB and `resources/evaluation/conversation-cases.jsonl`, excluded from Git. The source export is also excluded.

The live runner starts a new conversation and replays questions in order. It records every attempt, response, run ID, retrieval evidence and failure. Subsequent questions use the generated conversation. Failed responses do not replace saved memory. Resuming continues past attempted cases; create a new run to retest prior failures. Low effort is a useful constrained baseline; standard effort is the default for new evaluations.

## Metrics

- **Execution success and latency:** whether the application completed an answer, plus the observed run time. A quota or investigation-budget error is a recorded failure, not a zero-quality answer.
- **Ticket reference recall:** whether explicitly requested keys are cited or present. This is a narrow identifier check, not complete answer correctness.
- **Clarification behavior:** checks whether curated ambiguous cases receive a clarifying response. Human review validates whether the question was useful.
- **Reference token F1:** lexical overlap baseline; it is descriptive and does not prove factual correctness.
- **Ragas faithfulness:** support for answer claims in the supplied retrieved evidence.
- **Ragas context precision:** relevance of ranked narrative retrieval to the question/response. SQL/metadata-only cases are labeled not applicable rather than forced to a precision score.
- **Human score and feedback:** the final review signal, with reference verification kept separate from answer rating.

Ragas uses the selected connection as judge through its OpenAI-compatible interface. Set `JUDGE_CONNECTION=<saved-id>` to use a separate judge, and `EFFORT=low|standard|high` to choose investigation effort. This works with the saved Gemini profile; a separate paid OpenAI account is not required. Judge calls consume provider quota/tokens and can share the answer model’s biases. Errors are recorded independently of successful answer generation.

Scoring v3 uses up to eight distinct evidence packets within the declared model window, capped at 24,000 characters. It records available/scored characters, coverage, sampling policy and applicability. Scores describe that packet; inspect incomplete coverage before interpreting them. Older scoring versions retain their original sampling metadata. To re-score existing answers without generating them again:

```sh
PYTHONPATH=backend .venv-evaluation/bin/python -m app.observability.evaluation --score-run <evaluation-id> --delay 20
```

Previous Ragas results remain in `ragas_history`. Verified reference-dependent factual metrics are not claimed for unverified references. Human review is needed before treating the original conversation as a gold benchmark.

## Dependencies and records

Evaluation dependencies are isolated in `.venv-evaluation`. Ragas 0.4.3 requires `langchain-community==0.3.31` because newer community versions removed its legacy Vertex import. The application itself does not need the evaluation stack.

`agent_eval_datasets` and `agent_eval_versions` hold the revision chain and immutable cases; `agent_eval_jobs` holds background execution state. `agent_evaluations` tracks experiment metadata and progress. `agent_eval_cases` stores source/versioned cases. `agent_eval_results` stores answers, metrics, reference provenance and human reviews. Agent and judge traces are separate run kinds, linked by IDs for debugging. Langfuse receives native traces/scores when configured; local records work without it.

Ragas definitions and setup: https://docs.ragas.io/en/stable/getstarted/rag_eval/ and https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/
