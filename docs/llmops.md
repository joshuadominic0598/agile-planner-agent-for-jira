# LLMOps in AgilePlanner

AgilePlanner connects the project prompt, retrieved Jira evidence, model behavior and user feedback in one local improvement workflow. A test records its prompt revision and golden-data revision so you can inspect what changed before deciding which configuration to use.

## The improvement loop

![AgilePlanner configuration, evaluation, monitoring and feedback loop](../resources/images/llmops_loop.png)

1. Import a ticket export and prepare its persistent index. Configure statuses, people and planning conventions.
2. Add shared project guidance and optional project-specific briefs. Each save captures the complete guidance bundle as a prompt revision.
3. Curate questions, expected answers and reference evidence. Each save creates a separate golden-dataset revision.
4. Choose both revisions in Evaluation and test one model or compare two. Review each answer and its evidence, timing, calls and scores.
5. Choose **Use for chat** to activate a prompt. Monitor usage, inspect failures and collect feedback. Update guidance or tests and repeat.

The workflow adapts the prompt catalog, model comparison and feedback-loop concepts from the supplied LLMOps materials. The diagrams show this repository's implementation. They do not imply model training, automatic promotion, compliance certification or drift detection.

## Prompt history

Open **Evaluation → Project prompts**, select the ticket export and choose shared guidance or a project brief. Edit the text, describe the change and save a new revision. Older revisions remain available. Editing an older revision copies it into a new version; **Use for chat** can reactivate an existing version.

Saving in **Sprint Agent → Configure → Project context & working agreements** also creates and activates a revision. Existing saved guidance is captured as v1 on first use of the registry. Earlier overwritten prompts cannot be recovered retroactively.

Test prompts can remain separate from chat. An evaluation pins a revision at launch, sends its ID on every turn and records the exact guidance snapshot, content hash and version number. Both generation context and the `get_project_context` tool read that revision, even if someone changes the active prompt mid-test. Ordinary chat also pins its active revision at message start, including subsequent steering boundaries.

Project guidance is owner-supplied context, not verified ticket facts or permission to override the agent's read-only boundaries. The application may shorten injected guidance to fit a model window. Monitoring retains model request previews; the prompt snapshot identifies the original saved guidance rather than claiming every character was injected.

## Compare a model or a prompt

For a model comparison, choose two connections in one job. Both use the same prompt, questions, source export, effort and judge settings with separate conversation histories. Results retain model IDs and the application's pipeline fingerprint.

For a prompt comparison, hold the golden dataset and model constant, choose another prompt revision and launch another test. Use **Performance history** to filter by test-data and prompt versions, then compare the runs. Review answer quality, failures and costs together. There is no automatic winner or production rollout.

Changing expected answers changes the benchmark. Changing the source export or application pipeline can also affect scores. Keep saved people profiles, workflow mappings and planning rules constant during a controlled comparison as well; those settings are not a separately versioned evaluation fixture. Such runs remain useful history, but should not be presented as an isolated prompt/model improvement. Provider aliases may change behind the same model name; the app records the configured identity, not a vendor's private model weights.

## What is observable

![How agent questions, evidence and responses reach the operations dashboards](../resources/images/agent_trace.png)

| Record | What you can inspect |
| --- | --- |
| Conversation and response | Question, answer, status, errors, user feedback and page hints |
| Project prompt | Revision, content hash, saved shared guidance and project briefs |
| Model activity | Request/output previews, model identity, timing and token usage |
| Retrieval and tools | Tool inputs/results, evidence excerpts, chunk counts and context sizes |
| Evaluation configuration | Golden version, prompt version, export fingerprint, model, effort, judge and pipeline fingerprint |
| Quality signals | Ragas support/retrieval metrics where applicable, BLEU/ROUGE overlap, human scores and feedback |

MongoDB stores local records. SQLite holds reusable keyword/vector retrieval and exported relationships. Optional Langfuse integration exports native observations and feedback when credentials are configured. Provider-reported token counts and estimates remain distinct, and unknown prices remain unpriced.

Input screening and relevance checks are bounded application guardrails. They do not establish complete protection against prompt injection, inappropriate content, bias or data disclosure. Attachments are references only. Live provider calls send relevant project context and evidence to that configured provider.

## Guides and diagram sources

- [Evaluation workflow and metric definitions](evaluation.md)
- [Monitoring and Langfuse setup](observability.md)
- [Editable improvement-loop diagram](diagrams/llmops_loop.mmd)
- [Editable agent trace diagram](diagrams/agent_trace.mmd)

Prompt/data version history is application history in MongoDB, separate from Git. Real prompts, exports, traces and evaluation conversations remain private runtime data under the project workspace. Only fictional examples and diagram sources belong in the public repository.
