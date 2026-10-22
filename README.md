# AgilePlanner · Agentic AI for Jira & sprint planning

**A little less noise. Good decisions start with a clearer picture.**

Meet **Sprint Agent**: investigate Jira work, plan your backlog and improve AI answers with built-in monitoring and evaluation.

> **Your tickets. Your AI.** Run chat and semantic search locally with Ollama—no AI API key or Jira login needed. [Get started →](#try-it)

[![React](https://img.shields.io/badge/React-19-149ECA.svg?logo=react&logoColor=white)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.9-3178C6.svg?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![Vite](https://img.shields.io/badge/Vite-8-646CFF.svg?logo=vite&logoColor=white)](https://vite.dev/)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-API-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![MongoDB](https://img.shields.io/badge/MongoDB-Tickets_%26_Metadata-47A248.svg?logo=mongodb&logoColor=white)](https://www.mongodb.com/)
[![SQLite](https://img.shields.io/badge/SQLite-Vector_%26_Keyword_Search-003B57.svg?logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED.svg?logo=docker&logoColor=white)](https://www.docker.com/)
[![Ollama](https://img.shields.io/badge/Ollama-Optional_Local_AI-111111.svg?logo=ollama&logoColor=white)](https://ollama.com/)
[![Langfuse](https://img.shields.io/badge/Langfuse-Tracing_%26_Feedback-111111.svg)](https://langfuse.com/)
[![Ragas](https://img.shields.io/badge/Ragas-Retrieval_Evaluation-6D5DFB.svg)](https://docs.ragas.io/)
[![Pytest](https://img.shields.io/badge/Tests-Pytest-0A9EDC.svg?logo=pytest&logoColor=white)](https://pytest.org/)
[![Playwright](https://img.shields.io/badge/Tests-Playwright-2EAD33.svg)](https://playwright.dev/)

![Upload a Jira export or try the fictional demo](resources/images/readme_upload.png)

## Architecture

![AgilePlanner architecture](resources/images/agile_llmops.png)

## What you can do

| 🤖 **[Sprint Agent](#sprint-agent)** | 🧪 **[Testing & evaluation](#evaluation)** | 🔎 **[Monitoring](#monitoring)** |
| :--- | :--- | :--- |
| • Ask about tickets, sprints & people<br>• Find related work with hybrid search<br>• Get streamed answers with sources | • Compare models on golden questions<br>• Version project prompts & test data<br>• Review evidence, scores & latency | • Follow conversations & tool calls<br>• Track tokens, context & estimated cost<br>• Inspect errors & user feedback |
| 📊 **[Overview](#overview)** | 🏃 **[Sprint Explorer](#sprint-explorer)** | 🧩 **[Backlog Management](#backlog-management)** |
| • Explore status, type & team metrics<br>• Search tickets by ID, title or topic<br>• Flag similar To Do tickets | • Switch sprints & filter ticket lists<br>• See assignees, reporters & work mix<br>• Open tickets and linked work | • Define unfinished work & capacity<br>• Find priority, estimate & owner gaps<br>• Get AI assessments, themes & suggested owners |

### AI beyond chat

- **Find similar tickets:** discover related work through keyword/semantic search and flag potential To Do duplicates.
- **Get a ticket assessment:** open **Generate AI Summary and Suggestions** to review requirements, acceptance criteria, comments and similar-ticket evidence.
- **Enhance ticket descriptions:** ask Sprint Agent to draft clearer requirements and acceptance criteria using the available ticket context.
- **Explore code and solution suggestions:** ask for implementation approaches, potential fixes and illustrative code snippets grounded in the exported work.
- **Manage the backlog with AI:** review ticket batches, uncover refinement gaps, group work into themes and assess suggested owners against team roles and planning budgets.

Description and code drafts are requested through Sprint Agent. AI suggestions stay reviewable; they do not edit Jira or your code.

[Get started](#try-it) · [Agent engineering](#engineering-for-relevance-latency-and-cost) · [LLMOps workflow](#llmops-improve-your-agent-with-evidence) · [Project guides](#project-guides)

## Sprint Agent

**Ask a project question. Let the agent investigate the evidence.**

Find and explain tickets, summarize sprints, explore related work or review the backlog. The agent resolves conversation context, chooses tools and writes an answer from the results. Ticket summaries and suggestions also appear inside ticket details.

> “What did this developer work on?” · “Who can take this up?” · “Which tickets still need estimates?”

![Sprint Agent investigating a project question](resources/images/readme_agent.png)

### Engineering for relevance, latency and cost

The goal is useful project decisions with answers you can inspect and improve. These choices make the agent's work easier to control:

| Design choice | Why it's there |
| --- | --- |
| **Intent-led tool use** | Query MongoDB for people, filters and totals; retrieve narrative evidence for meaning and related work |
| **Hybrid search + relationships** | Combine exact/keyword matches, vectors, reranking and exported ticket links |
| **Batched evidence review** | Inspect bounded chunk packets with the selected model; retain verified quotes and report review coverage |
| **Retrieval caching** | Reuse query vectors, results and conservative candidate pools with bounded TTL/LRU caches; generate answers afresh |
| **Context & memory budgets** | Refresh conversation scope, select relevant evidence and trim history/tool payloads to the configured window |
| **Effort limits** | Bound tool actions, model requests and investigation passes; reserve room for the final answer |
| **Input & evidence checks** | Screen inappropriate input, clarify ambiguous references and validate quoted evidence against source chunks |
| **Measured iteration** | Compare prompt/data revisions and models using answer quality, latency, calls, tokens and estimated cost |

Streaming exposes progress while work continues. Reuse of the persisted index avoids rebuilding it for every conversation. Batching and caching target repeated retrieval work; model-based evidence review can add calls, so effort settings control that tradeoff.

**Improve performance over time:** inspect slow or weak answers, change one setting or prompt revision, replay the same golden questions, then compare quality and resource use. [Engineering decisions & measurement workflow](docs/agent_engineering.md).

### Configure your agent

<img src="resources/images/agent_configuration.png" alt="Configure Sprint Agent with a model, project knowledge prompt, context and follow-up behavior" width="760">

**Share the knowledge behind your tickets.** Your **project knowledge prompt** explains what you're building, your goals, team terminology and working agreements. Saved guidance gives the selected model project-specific context for relevant questions.

Find it under **Configure → Project context & working agreements**. View and edit prompt versions in **Evaluation → Project prompts**, test a change, then choose **Use for chat**.

Move, resize or expand the chat. Resume conversations, retry failed messages and leave thumbs feedback or a short note. Your export, settings and retrieval index survive refreshes and restarts.

[Model setup](backend/app/agent/README.md) · [Conversation controls](docs/conversations.md) · [Retrieval design](docs/retrieval.md)

#### Embedding models and configuration

**Embeddings find the evidence. Your chat model writes the answer.** Choose a search profile during import or under **Sprint Agent → Configure**.

| Search profile | Model | Chunk size | Overlap |
| --- | --- | ---: | ---: |
| **Keyword only** · no download | Local keyword search | 1,000 characters | 200 characters |
| **Smaller** · lower memory use | EmbeddingGemma | 1,000 characters | 200 characters |
| **Larger** · more passage context | Qwen3 Embedding 4B | 3,000 characters | 500 characters |

**Choose a profile, prepare the index and start chatting.** Your saved index is reused across conversations and restarts. [Setup, chunking & troubleshooting →](docs/retrieval.md#embedding-setup-and-chunking)

## Try it

Start Docker Desktop, clone the repo, then run:

```sh
git clone https://github.com/joshuadominic0598/agile-planner-agent-for-jira.git
cd agile-planner-agent-for-jira
make start
```

Open **[localhost:8000](http://localhost:8000)**. Analytics needs no AI key or Jira login.

1. **Load:** upload a Jira CSV or try the **100-ticket demo**.
2. **Configure:** keep your statuses or group, reorder and color them.
3. **Explore:** browse analytics, sprints and tickets. Add AI whenever you're ready.

[Download the demo](resources/demo/agileplanner-demo.csv) · [CSV requirements & setup](backend/README.md) · Excel users: export as **CSV UTF-8**.

### Private local AI setup

Install and start [Ollama](https://ollama.com/), then:

1. Open **Sprint Agent → Configure → Model connections**.
2. Choose **Download Qwen 8B** or **Download Nemotron 8B**. Follow progress, cancel or retry in the app; the connection is saved and selected for you.
3. Choose **Test selected connection**. For semantic search, download an embedding model below, select its [search profile](#embedding-models-and-configuration) and prepare the index.

```sh
ollama pull embeddinggemma       # smaller embedding model
ollama pull qwen3-embedding:4b    # larger alternative
```

Keyword search works without either download. For a private workflow, use local chat and embeddings, leave public web search off and external tracing unconfigured. [Model setup & local endpoints](docs/jira_agent.md) · [Privacy & limitations](#privacy--limitations)

## Explore the workspace

### Overview

Project totals, status charts and team insights. Search by ticket number, title or topic; filter results and flag **similar To Do tickets** for review.

![Overview with project metrics and charts](resources/images/readme_overview.png)

### Sprint explorer

Switch sprints, filter tickets from metric cards and see who's involved. Open tickets full screen to inspect details, hierarchy, linked work, comments and attachment references.

![Sprint explorer with metrics, people and charts](resources/images/readme_sprint.png)

### Backlog Management

Set your unfinished-work rule and review **Ready for planning**, **Needs triage** and **Assignee refinement**. Filter by priority and browse 20 tickets at a time.

**People & planning** shows roles, typical work, average assigned points per sprint and recent tickets. Ask AI to review a batch and suggest next steps or assignments.

AI reviews include ticket-specific findings, work themes and suggested owners where estimates, priorities and capacity allow. Continue through more batches while retaining earlier assessments.

![Backlog Management planning rules and metrics](resources/images/readme_backlog.png)

**Make it yours:** custom status names, order and colors; people roles; story-point or hourly budgets; light/dark themes.

## LLMOps: improve your agent with evidence

**Version the guidance. Test the change. Learn from real use.**

![AgilePlanner LLMOps workflow from versioned prompts and tests to monitoring and feedback](resources/images/llmops_loop.png)

| Step | What you can do |
| --- | --- |
| **Version** | Save project prompts and golden conversations as separate revisions |
| **Test** | Pin a prompt + test-data revision; evaluate one model or compare two |
| **Review** | Compare answers, evidence, timing, calls and human scores |
| **Improve** | Use feedback to revise, retest and activate your chosen prompt |

**Evaluation → Project prompts** lets you view, edit and revisit guidance. **Use for chat** activates a saved revision; experiments can stay separate from live chat.

![Versioned project guidance in the evaluation workspace](resources/images/readme_project_prompts.png)

*Fictional guidance shown. Each test keeps its prompt snapshot and version identifiers.*

For a prompt comparison, hold the model and test data constant. For a model comparison, hold the prompt and test data constant. [LLMOps workflow & versioning](docs/llmops.md).

## Monitoring

After the one-time `make setup`:

```sh
make monitor
```

Open **[localhost:8012/monitoring](http://localhost:8012/monitoring)**. View all conversations or drill into one response. Metrics refresh every five seconds.

| Performance | Usage | Traceability |
| --- | --- | --- |
| Latency, first token, throughput | Tokens, requests, estimated costs | Prompt revision, model/tool calls |
| Failures & blocked inputs | Context sizes & retrieved chunks | Evidence, errors & user feedback |

![Standalone monitoring dashboard](resources/images/readme_monitoring.png)

*Fictional demo traces.*

**Optional Langfuse:** add project credentials in `.env` to export observations and feedback. MongoDB keeps the local record. Unknown model prices remain **unpriced**.

![Agent retrieval, model orchestration and trace flow into monitoring and evaluation](resources/images/agent_trace.png)

[Monitoring & Langfuse setup](docs/observability.md)

## Evaluation

```sh
make evaluation-setup       # once
make evaluation-dashboard
```

Open **[localhost:8013/evaluation](http://localhost:8013/evaluation)**.

| Screen | What you'll find |
| --- | --- |
| **Golden datasets** | Editable questions, expected answers and evidence; DOCX/JSON/CSV import |
| **Project prompts** | Shared/project guidance, revision history and chat activation |
| **Run tests** | One model or two, pinned versions and optional Ragas scoring |
| **Performance history** | Version filters, answer comparisons and human ratings |

Compare **latency, model/tool calls, Ragas, BLEU/ROUGE 2–5 and ROUGE-L** for each question. Rate answers **1–5** and add feedback. A CSV template and **10-exchange demo benchmark** are included.

![Evaluation comparison and human review dashboard](resources/images/readme_evaluation.png)

*Fictional examples and illustrative scores; not live benchmark results.*

Saved revisions stay unchanged. Expected evidence and actual retrieval remain separate; missing data is labeled. Wording scores support comparison; evidence and human review judge quality.

[Evaluation guide & metric definitions](docs/evaluation.md)

## Your workspace stays with you

```sh
make stop        # keep data
make start       # reopen workspace
make restart     # restart with saved data
make fresh-start # reset after confirmation and a private backup
```

Your imported tickets, settings, conversations and search index are saved locally. Private exports and runtime data stay outside Git.

## Project guides

Application code lives in `backend/` and `frontend/`; technical guides and editable diagrams live in `docs/`. Published README and reference images live in [resources/images](resources/images/README.md), with reusable icons in `resources/images/icons/`. Documentation and asset names use lowercase snake_case; conventional `README.md` entry points stay unchanged. See the [project layout](docs/README.md#project-structure) and [resources guide](resources/README.md) for public assets and private runtime folders.

**Sharing the project:** commit source, setup files, lockfiles, documentation and the fictional demo. Personal exports, credentials, databases, vectors, conversations, installed models and generated files stay local through `.gitignore`; private files are also excluded from Docker builds. New users run `make start` to create their own workspace. See [what to commit and how to review it](docs/repository_setup.md).

[Backend & API](backend/README.md) · [Frontend](frontend/README.md) · [Agent engineering](docs/agent_engineering.md) · [Model setup](backend/app/agent/README.md) · [LLMOps](docs/llmops.md) · [Monitoring](docs/observability.md) · [Evaluation](docs/evaluation.md) · [Commands](scripts/README.md) · [Data & privacy](resources/README.md)

## Privacy & limitations

- **Local privacy:** with local chat, local embeddings, web search off and external tracing unconfigured, ticket context stays on your machine. Hosted chat/legacy embedding providers, cloud tracing and remote evaluation judges can receive context when enabled.
- **Downloads & hardware:** models need internet for installation, then support offline inference. Chat downloads are about 5 GB each; EmbeddingGemma is about 622 MB and Qwen3 Embedding 4B about 2.5 GB. Runtime memory, speed and electricity costs depend on your hardware. `make start` does not download weights automatically.
- **Model choice:** Qwen 8B is the starter suggestion, not a benchmark winner. Larger models or chunks do not guarantee better answers; compare them on your own tickets. Missing local models show a retry message and never silently fall back to cloud embeddings.
- **Snapshot limits:** exports cannot establish historical velocity, past sprint progress or actual availability. Missing estimates remain unknown; attachment contents are not read.
- **Review AI suggestions:** related tickets do not prove a shared cause or verified fix. Drafts and assignments need review and never change Jira or your code. Evaluation screenshots show illustrative scores, not benchmark results.

[EmbeddingGemma model & terms](https://ollama.com/library/embeddinggemma) · [Qwen3 Embedding model & license](https://huggingface.co/Qwen/Qwen3-Embedding-4B) · [Data & privacy guide](resources/README.md)
