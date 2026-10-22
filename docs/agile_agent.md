# Model-led project-management assistant

[Product tour](../README.md) · [Agent implementation](../backend/app/agent/README.md)

## Investigation flow

The connected model interprets the question and conversation, chooses the retrieval route and orchestrates tools. For substantive investigations, `plan_investigation` records a short intent and intended actions. Metadata tools answer counts, status, priorities, people, sprint membership and estimates. Semantic/keyword retrieval finds work themes in titles, descriptions, acceptance criteria, comments and exported file references. Graph tools follow exported relationships. The model can combine them, then streams its own answer from the results.

The normal chat requires a model. It never streams a prebuilt report, chooses items from a fixed findings catalog, or substitutes a deterministic answer when the model fails. Model errors retain the draft and prior saved conversation. The explicit `mode=retrieval` HTTP diagnostic remains for developers and retrieval tests; it is not offered or automatically selected in chat. Existing saved diagnostic messages remain viewable.

Reports and metadata tools return structured evidence. Charts are not emitted by default in AI mode. An explicit visual request can allow up to two verified charts. Tool results and public action summaries are observable; private model reasoning is not displayed. Repeated actions are summarized as `Calculator ×8`, with an optional non-repetitive activity timeline.

## Scrum and Jira guidance

The role is based on the [Scrum Guide](https://scrumguides.org/scrum-guide.html) and Atlassian's guidance on [sprint planning](https://www.atlassian.com/agile/scrum/sprint-planning), [estimation](https://www.atlassian.com/agile/project-management/estimation) and [retrospectives](https://www.atlassian.com/agile/scrum/retrospectives).

Planning connects valuable goals, selected work, capacity and the team's Definition of Done. Estimates support forecasts rather than guaranteed commitments. A retrospective inspects how the team works and identifies actionable improvement experiments; a Sprint Review concerns product outcomes. Story points represent relative effort and uncertainty, not hours or individual productivity.

Project/sprint answers should explain current focus, specific evidence, a useful concern/opportunity and the next management decision. They should not treat an archive-wide Done share as current health. A snapshot cannot establish historical throughput, velocity, carry-over, bottleneck duration or a missed commitment. The model can formulate hypotheses and ask for the missing evidence without inventing it. Teams using other working methods can explain their conventions in project context.

For sprint backlog questions, remaining work includes all exported sprint tickets whose Status Category is outside Done, including To Do, In Progress, Testing and custom unfinished statuses. `sprint_remaining_work` aggregates every sprint in one call, keeping missing categories unknown and counting repeated sprint membership once per ticket per sprint. A fully Done sprint has no remaining work. These are current snapshot counts, not evidence of status at historical sprint closure or spillover; they do not establish placement in Jira's board backlog. The model reads the aggregates and writes the answer.

## Project context

Under the blue header's **Configure → Project context & working agreements**, users can save goals, workflow meanings, estimation conventions, team structure and measures. Shared guidance applies to the entire export; project-specific briefs add detail. Up to 12,000 characters per brief are persisted in `agent_project_context`, isolated by snapshot/project. Clearing and saving removes the brief's content.

Relevant briefs accompany model requests as owner-provided assumptions, separately from verified ticket data. Prompt inclusion is bounded to 16,000 characters and 4,000 per brief; a `truncated` flag lets the model fetch the full brief through `get_project_context`. Saved guidance cannot change read-only/data boundaries. It is sent to the selected provider when asking relevant questions. Importing another CSV creates a separate configuration scope.

## Capacity without guessing

If a manager asks “Who is free?”, the agent should first use an already-provided definition, otherwise ask for one. If the manager defines a budget of 10 story points per active developer per sprint, the model passes that explicit assumption to `capacity_analysis`. A successful check remembers the project-scoped planning assumption in conversation memory, so follow-ups can reuse it even after older transcript turns leave the model window. Start fresh clears it.

The tool selects a project and named sprint, reads the full assignment set, and reports known point load, missing estimates, saved active developer roles and potential headroom. `committed` counts all assigned sprint work; `open` excludes only the CSV Done category. These bases answer different planning questions and must be stated. Earlier person/priority filters do not hide other assigned work from the load calculation.

Missing estimates remain unknown; they are not zero. Saved active developers with no selected-sprint assignments are included, while inactive profiles are excluded. Unknown roles cannot establish developer availability. If estimated parents and children overlap, headroom remains unknown until the user provides a counting convention (`leaf_only` or `all_estimated`). Positive headroom is conditional planning room, not proof of calendar availability, skills, leave or absence of other-project work.

## Responsibilities

| File | Responsibility |
| --- | --- |
| [provider.py](../backend/app/agent/provider.py) | Model-owned tool loop, streamed synthesis and grounding checks |
| [skills/management.md](../backend/app/agent/skills/management.md) | Project-management role, intent/retrieval decisions and Scrum guidance |
| [project_context.py](../backend/app/agent/project_context.py) | Scoped owner briefs and bounded prompt inclusion |
| [capacity.py](../backend/app/agent/capacity.py) | Conditional point-load/headroom evidence |
| [AgentProjectContext.tsx](../frontend/src/AgentProjectContext.tsx) | Brief editor and save feedback |
| [AgentProgress.tsx](../frontend/src/AgentProgress.tsx) | Visible intent/action summaries and grouped tool counts |

Tests cover absence of automatic responses, both provider protocols, streamed model-only text after retrieval, model failure without a substituted report, brief validation/isolation/persistence and capacity uncertainty. Browser metadata integration tests explicitly bridge to the diagnostic API in their harness; that is not normal app behavior. A separate streamed-AI test asserts that the UI requests AI mode and groups calculator usage.

## Recorded live check

[Local 8B capacity check](verification/model_orchestration.json) used synthetic tickets and a saved per-developer rule. The model called intent planning and capacity analysis, then generated the correct conditional headroom (+2, −3, unknown). It took 110.4 seconds and needed a planning retry. This is a small smoke check, not a general accuracy guarantee; local model latency and interpretation quality still need iterative evaluation. Tool evidence now separates complete committed points from the known estimated portion.

Reference ambiguity is resolved before retrieval. The model can use the clarify planning route to ask one question and wait. Ticket ownership follow-ups preserve the entire discussed list and require complete MongoDB evidence, with a bounded model revision if the answer omits requested keys. See [conversation reference handling](conversations.md#clarify-references-and-preserve-the-question).
