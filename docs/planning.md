# Backlog Management and inline AI

The screen reads MongoDB summaries and saved people profiles. CSV files are used only during import. Planning rules are stored per import/project in `planning_settings`.

## Scope and rules

Choose a whole project or one named sprint. Finished work means Status Category Done or the selected raw statuses. Missing categories remain unfinished under the category rule. The interface offers **Exclude parents/epics** or **Include parents/epics**; excluded records remain visible but contribute no estimate. Exported parents, indirect ancestors and epics are excluded by the first option. Including overlapping parent/child estimates makes capacity uncertain.

Story points and hours are separate units. Hours use the selected original/remaining seconds field divided by 3,600. Missing estimates remain unknown. A default budget is per person, per sprint. The individual-capacity editor and optional priority-rule panels have been removed; saved individual budgets remain available to the report and are visible in people profiles. Legacy priority-focus/refinement selections are cleared when reading saved rules. Populated priorities are ready for planning; blank priorities require refinement.

Selected-sprint workload uses only that sprint, with all work by default or unfinished work when selected. People with reliable estimates and explicit active developer profiles can have positive planning room. Known assigned load exceeding a developer budget counts as overload, even when other estimates are missing. Whole-project scope cannot establish current sprint availability: the corresponding metric cards show a dash, and allocation proposals model one hypothetical sprint without existing commitments deducted. Points, hours and different project point scales are never combined.

## Report and people

Six cards show unfinished tickets, estimated tickets, unestimated tickets, active developers, people with headroom and overloaded developers. Estimate counts follow parent/epic counting; developer counts follow explicitly saved profiles. Priority and readiness charts cover the whole configured scope. Their bars filter ticket records, as do the priority/readiness selectors. Records are sorted by exported Updated/Created dates, falling back to issue number, and paged 20 at a time.

Readiness retains Ready for planning, Assignee refinement, Needs triage, Choose owner and Parent tracking. Assigned gaps go to the existing owner; unassigned estimate/priority gaps require triage before allocation. Readiness is derived from metadata, never an AI guess.

People & planning shows all marked developers, including clearly labelled inactive people. Manage people opens the shared profile editor directly in this section. Saving refreshes the planning report and developer cards. When no developers are configured, assignees appear as an explicitly unconfirmed fallback. Profiles include saved work areas, project-wide ticket-type mix, unfinished assignments, average known assigned points per sprint and five recent tickets with individual point estimates. Missing points remain unknown. Current sprint membership and assignment do not establish historical velocity, completion attribution or productivity.

## Bounded AI reviews

`POST /api/datasets/{id}/analysis` streams NDJSON activity, answer deltas and a final result. Ticket analysis retrieves bounded ticket details and similar work. Backlog requests accept `batch_limit` (default 20, maximum 100) and an optional `review_id` for continuation. The model-window ticket cap can reduce the requested count, including at most 10 below 8K. A review processes only that selected slice, then the selected model writes a concise response using backlog metrics, saved roles, typical work, story sizes and current workload evidence.

Internal structured assessment uses one ticket per request below 8K, or up to eight per request for larger windows, preserving output room for every required finding. Every internal chunk must partition all its keys through `record_backlog_plan`. Suggested owners are restricted to unassigned, estimated, priority-ready counted tickets and explicitly eligible people whose remaining budget covers the combined proposal in the same unit. Unknown estimates cannot be allocated. Assigned tickets are never reassigned. Whole-project allocations are hypothetical, not actual availability.

Responses include `coverage` (reviewed, total, remaining, current batch and has_more), cumulative groups/allocations and a `review_id`. The browser offers **Continue with next tickets**, keeps earlier summaries collapsed, and labels unreviewed work. Full-scope counts remain exact; AI themes and ticket-specific conclusions apply only to reviewed keys. Review state and capacity reservations persist in MongoDB `backlog_reviews`, with a 30-day TTL. Continuation rejects changed report fingerprints, different model connections, expired/missing reviews, completed reviews and concurrent cursor changes. A failed/cancelled review does not advance the cursor.

Small windows compact optional fields and use a labelled subset of people profiles while preserving batch keys/titles and exact report counts. Omitted profiles do not establish absence or unavailability. Context optimisation appears in activity. The selected model always writes the final summary; no prewritten answer or Jira mutation is involved.

The screen metrics need no model. AI requires a configured connection and ready retrieval index. Stop prevents further batch/tool work, although an in-flight provider request may finish. Review state persists, while the current screen retains its review handle and earlier summaries until it is replaced or closed.

Routes relative to `/api/datasets/{id}`: `GET/PUT /planning/settings`, `POST /planning/report`, `POST /analysis`. Tests cover MongoDB scope/counts, parent/epic exclusion, missing/overlapping point data, developer metrics, story-size profiles, bounded continuation, stale cursors, allocation validation and native model-request context budgets. Browser checks cover 20-ticket paging, filtering, saved rules, people detail views, themes and continuation payloads.

## Inspectable AI batch reviews

Each reviewed ticket must have a model-written, ticket-specific finding and next action in the validated plan. Categories alone are insufficient. The model receives bounded narrative excerpts alongside readiness, estimates, owners and saved people profiles. Final synthesis uses these per-ticket findings and batch counts, with whole-backlog totals labelled separately. The UI shows every ticket assessment in a bounded scrolling list; continuing retains earlier summaries and produces a new batch. Internal continuation flags are never user-facing instructions. Missing estimates and priorities trigger refinement, not invented forecasts.

## People cards

Wide screens show five people per row; smaller screens use three, two or one column. Each card retains saved roles and common ticket types, with average known assigned story points per distinct exported sprint. Counted ticket estimates are summed within each sprint then averaged across all named sprints that person appears in; unscheduled tickets are excluded from this average, parent/epic counting follows the report rule, and missing estimates make it partial. Repeated sprint membership counts the ticket in each sprint. This is current assignment evidence, not completion history or velocity. The recent-work disclosure shows up to five latest assigned tickets with their own point values; size-range buckets and the finished-points disclosure are not displayed.
