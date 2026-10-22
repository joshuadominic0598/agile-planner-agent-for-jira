# Jira configuration and implications for AgilePlanner

Checked against Atlassian's Jira Cloud documentation on 17 October 2026.

Status movement is the main dimension of progress, but project configuration extends to work types, fields, boards, hierarchy, estimates, priorities, resolutions, and access. Jira configuration changes depend on administrator permissions and project type.

## Progress has several distinct representations

- **Status Category** groups statuses into To do, In progress, and Done. These support a consistent overview. A status's assigned category can be edited in Jira. [Workflow categories](https://support.atlassian.com/jira-software-cloud/docs/manage-how-work-flows-in-your-team-managed-project/), [editing status categories](https://support.atlassian.com/jira-software-cloud/docs/create-edit-and-delete-statuses-in-team-managed-projects/).
- **Status** is the specific state, such as Testing or Waiting for approval. Workflows define allowed transitions and rules. Different work types in a project can use different workflows. [Workflow schemes](https://support.atlassian.com/jira-cloud-administration/docs/configure-workflow-schemes/).
- **Board column** is a board's presentation of work. A column may contain multiple statuses, and board filters affect which issues appear. CSV statuses alone do not reveal column mappings or board scope. [Board columns](https://support.atlassian.com/jira-software-cloud/docs/configure-columns/).
- **Resolution** records why an issue ended, such as Fixed, Duplicate, or Won't do. Some Jira reports rely on Resolution rather than status alone. Category Done, a board's completion column, and resolved are related but have different reporting semantics. [Resolution behavior](https://support.atlassian.com/jira-cloud-administration/docs/what-is-a-resolution-in-jira/).

## Other configuration that affects analytics

| Area | What varies | Application implication |
| --- | --- | --- |
| Work types | Custom types and per-type workflows | Discover types; do not assume every issue follows the same process |
| Fields and screens | Custom text, number, date, selection fields; different fields by work type | Optional data and CSV columns can differ |
| Priority | Available priorities, meanings, and defaults | Discover values; do not assume every project uses High/Medium/Low |
| Hierarchy | Parent/child structures and configurable levels, depending on plan | Distinguish issue counts from parent-level rollups |
| Estimation | Story points or time; different tracking settings | Never equate missing points with zero effort or combine units |
| Project management model | Team-managed independent configuration versus company-managed shared schemes | Scope settings to the relevant project; shared names do not establish shared process |

Sources: [custom fields](https://support.atlassian.com/jira-software-cloud/docs/mapping-csv-data-to-jira-fields/), [priorities](https://support.atlassian.com/jira-cloud-administration/docs/what-are-issue-statuses-priorities-and-resolutions/), [hierarchy](https://support.atlassian.com/jira-cloud-administration/docs/configure-the-issue-type-hierarchy/), [estimation](https://support.atlassian.com/jira-software-cloud/docs/configure-estimation-and-tracking/), [project management models](https://support.atlassian.com/jira-software-cloud/docs/what-are-team-managed-and-company-managed-spaces/).

## Design decision for this release

Use source Status Category for the high-level view and exact Status values for detailed cards. Let users optionally rename/combine detailed statuses in one setup after import, without changing source values or category totals. Discover other values such as types, priorities, sprints, and people. Preserve repeated fields and complete ticket details. Do not infer workflow transitions, board columns, or historical sprint completion from a snapshot.

The importer now recognizes common core aliases and preserves arbitrary extra columns, including repeated custom fields. Optional categorical value charts and filters expose new fields without inferring their business meaning. Header aliases, numeric point/time units, and parent key/ID resolution have explicit rules; localized or unrecognized core names still need renaming. This broadens compatibility but does not guarantee every Jira export, spreadsheet dialect, or custom numeric/date interpretation. The original sample-column allowlist has been superseded by this policy.

Future Jira write support also needs actual transition rules, required fields, and permissions; a list of status names is insufficient to decide which moves are allowed.

The supplied export illustrates why category and resolution metrics must remain distinct: 375 issues in the Done status category have an empty Resolution, and three issues outside that category have a populated Resolution. These are observed source values; the application does not alter or infer them. The high-level Done category count remains 1,749.
