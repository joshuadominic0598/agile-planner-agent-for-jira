import { useEffect, useRef, useState } from 'react';
import { Sparkles } from 'lucide-react';
import { api, streamAgent } from './api';
import { AnswerText, type AgentSource } from './AgentAnswer';
import AgentProgress, { type Activity } from './AgentProgress';
import AgentFeedback from './AgentFeedback';

export type AnalysisResult = {
  run_id?: string;
  content: string;
  model: string;
  sources: AgentSource[];
  tools: { tool: string; ok: boolean }[];
  groups: { name: string; keys: string[] }[];
  assignments: { key: string; person: string; reason: string; estimate: number; unit?: 'points' | 'hours' }[];
  assessments?: {
    key: string;
    summary: string;
    assignee: string;
    priority: string;
    readiness: string;
    estimate: number | null;
    estimate_counted?: boolean;
    assessment: string;
  }[];
  fingerprint?: string;
  review_id?: string;
  coverage?: {
    reviewed: number;
    total: number;
    remaining: number;
    batch_start: number;
    batch_count: number;
    has_more: boolean;
  };
};
type Status = {
  status: string;
  progress: number;
  message: string;
  choices: { id: string; name: string; model: string }[];
};
export default function FeatureAnalysis({
  dataset,
  request,
  onTicket,
  onResult,
}: {
  dataset: string;
  request: Record<string, unknown>;
  onTicket: (key: string) => void;
  onResult?: (result: AnalysisResult) => void;
}) {
  const [status, setStatus] = useState<Status>();
  const [connection, setConnection] = useState(() => {
    try {
      return localStorage.getItem('sprintlens.agent.connection') || '';
    } catch {
      return '';
    }
  });
  const [busy, setBusy] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [error, setError] = useState('');
  const [content, setContent] = useState('');
  const [activity, setActivity] = useState<Activity[]>([]);
  const [result, setResult] = useState<AnalysisResult>();
  const [batchLimit, setBatchLimit] = useState(20);
  const [previousReviews, setPreviousReviews] = useState<AnalysisResult[]>([]);
  const controller = useRef<AbortController | null>(null);
  const base = `/datasets/${dataset}`;
  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const value = await api<Status>(`${base}/agent/status`);
        if (!live) return;
        setStatus(value);
        timer = setTimeout(poll, value.status === 'building' ? 1200 : 15000);
      } catch (e) {
        if (live) setError((e as Error).message);
      }
    };
    void poll();
    return () => {
      live = false;
      clearTimeout(timer);
      controller.current?.abort();
    };
  }, [base]);
  const selected = status?.choices.find((c) => c.id === connection) || status?.choices[0];
  async function prepare() {
    setPreparing(true);
    setError('');
    try {
      await api(`${base}/agent/index`, { method: 'POST' });
      setStatus((s) => (s ? { ...s, status: 'building', message: 'Preparing ticket retrieval…' } : s));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPreparing(false);
    }
  }
  async function generate(continuing = false) {
    const previous = result;
    setBusy(true);
    setError('');
    setContent('');
    setActivity([]);
    if (!continuing) {
      setResult(undefined);
      setPreviousReviews([]);
    }
    controller.current = new AbortController();
    try {
      const value = await streamAgent<AnalysisResult>(
        `${base}/analysis`,
        {
          ...request,
          connection_id: selected?.id,
          ...(request.kind === 'backlog'
            ? { batch_limit: batchLimit, review_id: continuing ? previous?.review_id : '' }
            : {}),
        },
        (event) => {
          if (event.event === 'text_delta') setContent((c) => c + String(event.text || ''));
          if (event.event === 'activity')
            setActivity((a) => [
              ...a,
              { message: String(event.message || ''), tool: event.tool as string, ok: event.ok as boolean },
            ]);
        },
        controller.current.signal
      );
      setResult(value);
      if (continuing && previous) setPreviousReviews((reviews) => [...reviews, previous]);
      setContent(value.content);
      onResult?.(value);
    } catch (e) {
      setError(
        (e as Error).name === 'AbortError' ? 'Analysis stopped. You can try again.' : (e as Error).message
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="card feature-analysis" aria-label="AI analysis">
      <div className="card-heading">
        <div>
          <span className="eyebrow">SPRINT AGENT</span>
          <h3>{request.kind === 'ticket' ? 'A second pair of eyes' : 'Turn the backlog into a plan'}</h3>
        </div>
        <Sparkles size={20} />
      </div>
      <p className="muted small">
        {request.kind === 'ticket'
          ? 'Review requirements, comments, acceptance criteria and similar work. Attachment references are available; file contents are not.'
          : 'Review a batch of backlog tickets using team roles, typical work, story sizes and planning budgets. Continue when you want to explore more; assignments are suggestions only.'}
      </p>
      <div className="analysis-controls">
        <label>
          Model
          <select
            aria-label="Analysis model"
            value={selected?.id || ''}
            disabled={busy}
            onChange={(e) => {
              setConnection(e.target.value);
              setResult(undefined);
              setContent('');
              setPreviousReviews([]);
              try {
                localStorage.setItem('sprintlens.agent.connection', e.target.value);
              } catch {
                /* Selection remains in this session. */
              }
            }}>
            {!selected && <option value="">Connect a model in Sprint Agent → Configure</option>}
            {status?.choices.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name || c.model}
              </option>
            ))}
          </select>
        </label>
        {request.kind === 'backlog' && (
          <label>
            Tickets per review
            <select
              aria-label="AI review batch size"
              value={batchLimit}
              disabled={busy}
              onChange={(e) => setBatchLimit(Number(e.target.value))}>
              {[10, 20, 30, 50].map((size) => (
                <option value={size} key={size}>
                  {size} tickets
                </option>
              ))}
            </select>
          </label>
        )}
        {status?.status !== 'ready' ? (
          <button
            className="button secondary"
            onClick={prepare}
            disabled={!status || preparing || status.status === 'building'}>
            {preparing || status?.status === 'building' ? 'Preparing retrieval…' : 'Prepare ticket retrieval'}
          </button>
        ) : (
          <button className="button primary" disabled={!selected || busy} onClick={() => void generate()}>
            <Sparkles size={16} />
            {busy
              ? 'Analysing…'
              : request.kind === 'ticket'
                ? 'Generate AI Summary and Suggestions'
                : result
                  ? 'Start a new AI review'
                  : 'Generate AI Analysis and Plan'}
          </button>
        )}
        {busy && (
          <button className="button secondary" onClick={() => controller.current?.abort()}>
            Stop
          </button>
        )}
      </div>
      {status && status.status !== 'ready' && (
        <div className="analysis-index-status">
          <p role="status" className="small muted">
            {status.message}
          </p>
          {status.status === 'building' && (
            <progress aria-label="Ticket retrieval progress" max={100} value={status.progress || undefined} />
          )}
        </div>
      )}
      {!selected && (
        <p className="small muted">Add your local or API model connection in Sprint Agent → Configure.</p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {!!previousReviews.length && (
        <details className="analysis-evidence">
          <summary>Previous review summaries · {previousReviews.length}</summary>
          {previousReviews.map((review, i) => (
            <section key={i}>
              <p className="small muted">
                Tickets {review.coverage?.batch_start}–{review.coverage?.reviewed}
              </p>
              <AnswerText content={review.content} sources={review.sources} onTicket={onTicket} />
              <AgentFeedback runId={review.run_id} />
            </section>
          ))}
        </details>
      )}
      <AgentProgress activity={activity} working={busy} responding={!!content} tools={result?.tools} />
      {content && (
        <div className="agent-message-text">
          <AnswerText content={content} sources={result?.sources} onTicket={onTicket} />
        </div>
      )}
      {!!result?.assessments?.length && (
        <section className="batch-assessments" aria-label="Ticket-by-ticket assessment">
          <h4>Ticket-by-ticket assessment · {result.assessments.length}</h4>
          <p className="small muted">
            AI findings for this batch. Open a ticket to verify the details before acting.
          </p>
          <div className="batch-assessment-list">
            {result.assessments.map((ticket) => (
              <article key={ticket.key}>
                <div>
                  <button className="issue-key" onClick={() => onTicket(ticket.key)}>
                    {ticket.key}
                  </button>{' '}
                  <strong>{ticket.summary}</strong>
                </div>
                <p className="small muted">
                  {ticket.assignee || 'No assignee'} · {ticket.priority || 'Priority missing'} ·{' '}
                  {ticket.estimate_counted === false
                    ? 'Excluded from estimate totals'
                    : ticket.estimate === null
                      ? 'Estimate missing'
                      : `${ticket.estimate} ${request.config && (request.config as { unit?: string }).unit === 'hours' ? 'hours' : 'points'}`}{' '}
                  ·{' '}
                  {{
                    ready: 'Ready for planning',
                    needs_owner: 'Ready · needs owner',
                    owner_refinement: 'Assignee refinement',
                    triage: 'Needs triage',
                    parent_tracking: 'Parent/epic tracking',
                  }[ticket.readiness] || ticket.readiness}
                </p>
                <p>{ticket.assessment}</p>
              </article>
            ))}
          </div>
        </section>
      )}
      {result?.coverage && (
        <div className="analysis-coverage">
          <p role="status">
            <strong>
              {result.coverage.reviewed} of {result.coverage.total} tickets reviewed
            </strong>
            <br />
            <small className="muted">
              {result.coverage.remaining
                ? `${result.coverage.remaining} still to explore. Work themes cover reviewed tickets only.`
                : 'All backlog tickets in this report have been reviewed.'}{' '}
              Small model windows may reduce the batch size.
            </small>
          </p>
          {result.coverage.has_more && (
            <button className="button secondary" disabled={busy} onClick={() => void generate(true)}>
              Continue with next tickets
            </button>
          )}
        </div>
      )}
      {!!result?.sources.length && (
        <details className="analysis-evidence">
          <summary>Ticket evidence · {result.sources.length}</summary>
          <ul>
            {result.sources.map((source) => (
              <li key={source.key}>
                <button className="issue-key" onClick={() => onTicket(source.key)}>
                  {source.key}
                </button>{' '}
                · {source.summary}
                <br />
                <small className="muted">
                  {source.reason} · {source.status}
                </small>
              </li>
            ))}
          </ul>
        </details>
      )}
      {!busy && result && <AgentFeedback runId={result.run_id} />}
      {result && (
        <p className="small muted">
          {result.model} · {result.tools.length} tool calls · AI suggestions; verify before acting.
        </p>
      )}
    </section>
  );
}
