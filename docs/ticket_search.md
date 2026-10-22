# Overview ticket finder

The Overview page includes **Find a ticket**. Enter a number, title or topic; click a result or use arrow keys and Enter to open the existing ticket drawer. Eight filters cover project, status, status category, issue type, priority, assignee, reporter and sprint. Values come from the current MongoDB import. The project filter initially follows the Overview project; selecting its empty option searches the whole export.

## Query routing and ranking

- Bare numbers, `ticket 1232`, `issue #1232`, `PROJECT 1232` and `PROJECT-1232` use exact Jira key suffix/issue-ID matching. They never fall through to title/description similarity. Ambiguous numbers return choices; selected filters remain in force.
- Exact discovered statuses/categories/types and phrases such as `high priority`, `tickets in progress` and `high priority bugs` become metadata filters. This is a small deterministic parser, not an LLM call. Arbitrary natural-language instructions and assignee extraction are outside its scope. The controls provide explicit filtering for all eight fields.
- Other text searches title and description. Exact title and title keyword coverage rank before description keyword matches, then vector-retrieved candidates. Tokens are literal text, never user-supplied regex or database operators. Query-derived and explicit filters intersect, including conflicting filters.
- Requests read MongoDB summaries/descriptions. The similarity pass uses the narrative vector + FTS5/BM25 hybrid index (also covering acceptance criteria, comments and file references) and reranker in SQLite, then joins results to current MongoDB records. Semantic candidates cannot escape selected filters. No CSV is queried and no chat model is required.

## Progressive suggestions

Input is debounced for 350 ms. A keyword-only request renders first; if the narrative index is ready, a second request adds similar tickets. Old requests are aborted and stale responses are ignored. Search results are capped at 12 by default. Narrative results are labeled top matches, not an exact count of all semantically related tickets. Metadata/identifier queries have full matching counts.

Missing/stale indexes or failed embedding calls retain keyword results and show a useful message. Prepare the index from Sprint Agent → Configure. The local default uses TF-IDF text similarity; learned semantic matches require the configured embedding model. The UI does not display heuristic scores as confidence percentages.

## API and code

- `GET /api/datasets/{id}/ticket-search/options` returns the eight discovered field lists.
- `GET /api/datasets/{id}/ticket-search?q=...` returns keyword/metadata results, applied filters and `can_expand`.
- Add `semantic=true` for the hybrid pass. Filters are separate query parameters; issue type uses `issue_type`.
- `backend/app/ticket_search.py` implements query parsing, scoped database reads and ranking.
- `frontend/src/TicketFinder.tsx` handles progressive requests, filters, highlighting and keyboard selection. Its styles are in `ticket-finder.css`.

## Ticket evidence in chat

`get_ticket` includes a bounded `ticket_context` packet independently of the general original-field budget. Automatic grounding preserves this packet instead of passing only a narrative excerpt. It includes parent/children, explicit incoming/outgoing links (resolved keys and titles, with unresolved references marked), labeled acceptance criteria, comments, and attachment names/references. Relationship metadata is fetched from MongoDB, not inferred from shared labels or semantic similarity.

Attachment bytes are never downloaded, opened, indexed or interpreted. The agent receives `contents_available: false` and guidance to name relevant files and ask the user to inspect them in Jira. File/image names do not prove contents. Comments describe reported work, not independently verified deployment/testing. Missing exported criteria or relationships do not prove none exist in Jira. Small ownership/status follow-ups should remain concise instead of repeating a full checklist.

## Verification

The implementation passed 187 backend tests, 60 desktop/mobile browser checks, production TypeScript/Vite compilation and targeted Ruff/Prettier checks. Tests cover repeated attachments and comments, original-field truncation, explicit/incoming links, criteria extraction, identifier ambiguity, discovered/custom statuses, all eight filter intersections, missing embeddings, title-first merging, keyboard selection and progressive suggestions. Mocked semantic candidates verify routing/ranking boundaries; relevance still depends on the configured embedding model.
