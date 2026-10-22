import { useEffect, useRef, useState } from 'react';
import { ArrowUpRight, LoaderCircle, Search, SlidersHorizontal, X } from 'lucide-react';
import { api, params } from './api';
import { ParentBadge, TypeBadge } from './IssueIdentity';
import type { Issue } from './types';
import './ticket-finder.css';

type Filters = Record<
  'project' | 'status' | 'category' | 'type' | 'priority' | 'assignee' | 'reporter' | 'sprint',
  string
>;
type Result = { ticket: Issue; match: string; excerpt: string };
type SearchResult = {
  items: Result[];
  total: number | null;
  keyword_matches: number;
  highlight_terms: string[];
  applied_filters: { field: string; value: string; source: string }[];
  can_expand: boolean;
  mode: string;
  notice: string;
};
const fields: { key: keyof Filters; label: string }[] = [
  { key: 'project', label: 'Project' },
  { key: 'status', label: 'Status' },
  { key: 'category', label: 'Status category' },
  { key: 'type', label: 'Issue type' },
  { key: 'priority', label: 'Priority' },
  { key: 'assignee', label: 'Assignee' },
  { key: 'reporter', label: 'Reporter' },
  { key: 'sprint', label: 'Sprint' },
];
const empty = (project = ''): Filters => ({
  project,
  status: '',
  category: '',
  type: '',
  priority: '',
  assignee: '',
  reporter: '',
  sprint: '',
});

function Highlight({ text, terms }: { text: string; terms: string[] }) {
  const pattern = terms.map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
  if (!pattern) return <>{text}</>;
  return (
    <>
      {text
        .split(new RegExp(`(${pattern})`, 'gi'))
        .map((part, i) => (i % 2 ? <mark key={i}>{part}</mark> : part))}
    </>
  );
}

export default function TicketFinder({
  dataset,
  project,
  onOpen,
}: {
  dataset: string;
  project: string;
  onOpen: (key: string) => void;
}) {
  const [query, setQuery] = useState('');
  const [filters, setFilters] = useState<Filters>(() => empty(project));
  const [options, setOptions] = useState<Partial<Record<keyof Filters, string[]>>>({});
  const [showFilters, setShowFilters] = useState(false);
  const [result, setResult] = useState<SearchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [similar, setSimilar] = useState(false);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const [active, setActive] = useState(-1);
  const [dismissed, setDismissed] = useState(false);
  const list = useRef<HTMLDivElement>(null);
  const count = Object.values(filters).filter(Boolean).length;
  const searching =
    !!query.trim() ||
    fields.some(({ key }) => key !== 'project' && filters[key] !== '') ||
    filters.project !== project;
  useEffect(() => {
    setFilters(empty(project));
  }, [project]);
  useEffect(() => {
    let live = true;
    api<{ fields: typeof options }>(`/datasets/${dataset}/ticket-search/options`)
      .then((data) => {
        if (live) setOptions(data.fields);
      })
      .catch((e) => {
        if (live) setError(e.message);
      });
    return () => {
      live = false;
    };
  }, [dataset, revision]);
  useEffect(() => {
    setDismissed(false);
    setActive(-1);
    setResult(null);
    setError('');
    if (!searching) {
      setBusy(false);
      setSimilar(false);
      return;
    }
    const controller = new AbortController();
    let live = true;
    const timer = setTimeout(async () => {
      setBusy(true);
      setSimilar(false);
      const url = `/datasets/${dataset}/ticket-search?${params({ ...filters, type: undefined, issue_type: filters.type, q: query.trim() })}`;
      try {
        const keywords = await api<SearchResult>(url, { signal: controller.signal });
        if (!live) return;
        setResult(keywords);
        if (keywords.can_expand) {
          setSimilar(true);
          const expanded = await api<SearchResult>(`${url}&semantic=true`, { signal: controller.signal });
          if (live) setResult(expanded);
        }
      } catch (e) {
        if (live && (e as Error).name !== 'AbortError') setError((e as Error).message);
      } finally {
        if (live) {
          setBusy(false);
          setSimilar(false);
        }
      }
    }, 350);
    return () => {
      live = false;
      clearTimeout(timer);
      controller.abort();
    };
  }, [dataset, query, filters, revision, searching]);
  const items = result?.items || [];
  return (
    <section className="card ticket-finder" aria-label="Find tickets">
      <div className="ticket-finder-heading">
        <div>
          <h2>Find a ticket.</h2>
          <p>
            Search a number, title, or topic. Try “ticket 1232”, “high priority”, or a few words about the
            work.
          </p>
        </div>
        <button
          type="button"
          className="button secondary"
          aria-expanded={showFilters}
          aria-controls="ticket-finder-filters"
          onClick={() => setShowFilters(!showFilters)}>
          <SlidersHorizontal size={15} /> Filters{count ? ` (${count})` : ''}
        </button>
      </div>
      <div className="ticket-finder-input">
        <Search size={18} />
        <input
          role="combobox"
          aria-label="Find tickets by number, title or topic"
          aria-autocomplete="list"
          aria-controls="ticket-finder-results"
          aria-expanded={!!items.length && !dismissed}
          aria-activedescendant={active >= 0 && !dismissed ? `ticket-result-${active}` : undefined}
          value={query}
          maxLength={300}
          placeholder="Ticket number, title, or topic…"
          onFocus={() => setDismissed(false)}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              setDismissed(true);
              setActive(-1);
            }
            if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
              e.preventDefault();
              setDismissed(false);
              const next = !items.length
                ? -1
                : active < 0
                  ? e.key === 'ArrowDown'
                    ? 0
                    : items.length - 1
                  : (active + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
              setActive(next);
              if (next >= 0)
                list.current?.querySelector(`#ticket-result-${next}`)?.scrollIntoView({ block: 'nearest' });
            }
            if (e.key === 'Enter' && active >= 0 && items[active] && !dismissed) {
              e.preventDefault();
              onOpen(items[active].ticket.key);
            }
          }}
        />
        {busy && <LoaderCircle className="spin" size={16} aria-label="Searching tickets" />}
        {searching && (
          <button
            type="button"
            className="icon-button"
            aria-label="Clear ticket search"
            onClick={() => {
              setQuery('');
              setFilters(empty(project));
            }}>
            <X size={16} />
          </button>
        )}
      </div>
      {showFilters && (
        <div className="ticket-finder-filters" id="ticket-finder-filters">
          {fields.map(({ key, label }) => (
            <label key={key}>
              {label}
              <select
                aria-label={`Ticket finder ${label.toLowerCase()}`}
                value={filters[key]}
                onChange={(e) => setFilters({ ...filters, [key]: e.target.value })}>
                <option value="">Any {label.toLowerCase()}</option>
                {(options[key] || []).map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </div>
      )}
      {!!result?.applied_filters.length && (
        <div className="ticket-finder-applied" aria-label="Applied search filters">
          {result.applied_filters.map((filter, i) => (
            <span key={i}>
              {fields.find((field) => field.key === filter.field)?.label || filter.field}: {filter.value}
              {filter.source === 'query' && ' · from search'}
            </span>
          ))}
        </div>
      )}
      <div className="ticket-finder-state" role="status">
        {similar
          ? 'Finding similar tickets… Keyword matches are ready.'
          : result
            ? `${result.total === null ? 'Top matches' : `${result.total} matching tickets`} · ${items.length} shown`
            : 'Title matches first, then description matches. Results open the full ticket.'}
      </div>
      {error && (
        <div className="error" role="alert">
          {error}{' '}
          <button type="button" className="text-button" onClick={() => setRevision((value) => value + 1)}>
            Retry search
          </button>
        </div>
      )}
      {result?.notice && <p className="ticket-finder-note">{result.notice}</p>}
      {!dismissed && (
        <div
          id="ticket-finder-results"
          role="listbox"
          aria-label="Ticket search results"
          ref={list}
          className="ticket-finder-results">
          {items.map(({ ticket, match, excerpt }, i) => (
            <button
              type="button"
              role="option"
              aria-selected={active === i}
              id={`ticket-result-${i}`}
              key={ticket.key}
              onClick={() => onOpen(ticket.key)}
              className={ticket.is_parent ? 'ticket-result ticket-result-parent' : 'ticket-result'}>
              <span className="ticket-result-top">
                <strong>{ticket.key}</strong>
                <span className="ticket-result-match">{match}</span>
                <ArrowUpRight size={14} />
              </span>
              <span className="ticket-result-title">
                <Highlight text={ticket.summary} terms={result?.highlight_terms || []} />
              </span>
              <span className="ticket-result-meta">
                <TypeBadge name={ticket.type} />
                <ParentBadge issue={ticket} />
                <span>{ticket.status}</span>
                <span>{ticket.priority || 'No priority'}</span>
                <span>{ticket.assignee || 'Unassigned'}</span>
              </span>
              {excerpt && (
                <span className="ticket-result-excerpt">
                  <Highlight text={excerpt} terms={result?.highlight_terms || []} />
                </span>
              )}
            </button>
          ))}
        </div>
      )}
      {result && !items.length && !busy && !error && (
        <p className="ticket-finder-note">
          No matching tickets. Try fewer words, another number, or adjust the filters.
        </p>
      )}
    </section>
  );
}
