import { StrictMode, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  Activity,
  ArrowLeft,
  BarChart3,
  CheckCircle2,
  Clock3,
  MessageSquare,
  RefreshCw,
  Search,
  ShieldCheck,
  Star,
} from 'lucide-react';
import AgentFeedback from '../AgentFeedback';
import ThemeToggle from '../ThemeToggle';
import EvaluationWorkbench from './EvaluationWorkbench';
import { PromptSnapshot } from './PromptVersions';
import { NgramMetrics, AggregateOverlap, QuestionComparison, ContextEvidence } from './EvaluationMetrics';
import './operations.css';

type Row = Record<string, any>;
const number = (n: any) =>
  typeof n === 'number' ? n.toLocaleString(undefined, { maximumFractionDigits: 2 }) : '—';
const duration = (n: any) => (typeof n === 'number' ? `${number(n / 1000)}s` : '—');
const money = (n: any) => (typeof n === 'number' ? `$${n.toFixed(n < 0.01 ? 6 : 3)}` : 'Unpriced');
const score = (n: any) => (typeof n === 'number' ? `${(n * 100).toFixed(1)}%` : 'Not scored');
async function api(path: string, body?: unknown) {
  const response = await fetch(
    '/api/ops' + path,
    body
      ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
      : undefined
  );
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Request failed');
  return data;
}
function Markdown({ text }: { text?: string }) {
  return (
    <div className="ops-markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text || ''}</ReactMarkdown>
    </div>
  );
}
function Cards({ values }: { values: [string, string, string?][] }) {
  return (
    <div className="ops-cards">
      {values.map(([label, value, detail]) => (
        <article key={label}>
          <span>{label}</span>
          <strong>{value}</strong>
          {detail && <small>{detail}</small>}
        </article>
      ))}
    </div>
  );
}
function Bars({ title, rows, label = 'count' }: { title: string; rows: Row[]; label?: string }) {
  const max = Math.max(1, ...rows.map((r) => r[label] || 0));
  return (
    <section className="ops-card">
      <h3>{title}</h3>
      <div className="ops-bars" role="img" aria-label={title}>
        {rows.slice(0, 12).map((r) => (
          <div key={String(r._id)}>
            <span title={String(r._id)}>{r._id || 'Not recorded'}</span>
            <i>
              <b style={{ width: `${((r[label] || 0) / max) * 100}%` }} />
            </i>
            <strong>{number(r[label])}</strong>
          </div>
        ))}
        {!rows.length && <p className="muted">No recorded data in this scope.</p>}
      </div>
    </section>
  );
}
function Timeline({ rows }: { rows: Row[] }) {
  const data = [...rows].sort((a, b) => String(a._id).localeCompare(String(b._id))).slice(-48);
  const max = Math.max(1, ...data.map((r) => r.count));
  return (
    <section className="ops-card">
      <h3>Request volume over time</h3>
      <p className="muted">Hourly UTC buckets · current filter</p>
      <div className="ops-timeline" role="img" aria-label="Hourly agent request volume">
        {data.map((r) => (
          <div key={r._id} title={`${r._id}: ${r.count} requests`}>
            <b style={{ height: `${Math.max(4, (r.count / max) * 100)}%` }} />
            <small>{String(r._id).slice(11)}h</small>
          </div>
        ))}
        {!data.length && <p className="muted">Your next question starts the timeline.</p>}
      </div>
    </section>
  );
}
function RunDetail({ run, back }: { run: Row; back: () => void }) {
  return (
    <section className="ops-card ops-run-detail">
      <button className="ops-button" onClick={back}>
        <ArrowLeft size={15} /> Back to runs
      </button>
      <h2>Response trace</h2>
      <p className="muted">
        {run.id} · {run.model} · {run.status}
      </p>
      <h3>User message</h3>
      <p>{run.question}</p>
      <h3>{run.status === 'error' ? 'Error' : 'Response'}</h3>
      <Markdown text={run.error || run.response} />
      <AgentFeedback runId={run.id} initial={run.feedback} />
      <PromptSnapshot value={run.prompt_version} />
      <Cards
        values={[
          ['Latency', duration(run.latency_ms)],
          ['First token', duration(run.first_token_ms)],
          [
            'Input / output tokens',
            `${number(run.usage?.input_tokens)} / ${number(run.usage?.output_tokens)}`,
            `${run.usage?.estimated_calls || 0} calls use estimated tokens`,
          ],
          ['Model / tool calls', `${run.model_call_count || 0} / ${run.tool_call_count || 0}`],
          ['Estimated cost', money(run.cost_usd), `${run.unpriced_calls || 0} calls unpriced`],
          [
            'Output throughput',
            `${number(run.output_tokens_per_second)} tokens/s`,
            'Output tokens / total run duration',
          ],
        ]}
      />
      <details open>
        <summary>Context & retrieval</summary>
        <pre>{JSON.stringify(run.context, null, 2)}</pre>
        {run.retrieved_contexts?.map((text: string, i: number) => (
          <details key={i}>
            <summary>
              Retrieved excerpt {i + 1} · {text.length} characters
            </summary>
            <pre>{text}</pre>
          </details>
        ))}
      </details>
      <details>
        <summary>Model calls · {run.model_calls?.length || 0}</summary>
        {run.model_calls?.map((m: Row, i: number) => (
          <section key={i} className="ops-subtrace">
            <h4>
              Call {i + 1} · {m.model} · {duration(m.latency_ms)} · {m.status}
            </h4>
            <p className="muted">
              {m.usage?.source} token usage · {money(m.cost?.usd)} · {m.cost?.basis}
            </p>
            <details>
              <summary>Request context</summary>
              <pre>{m.input}</pre>
            </details>
            <details>
              <summary>Model output</summary>
              <pre>{m.output}</pre>
            </details>
            {m.error && <p className="ops-error">{m.error}</p>}
          </section>
        ))}
      </details>
      <details>
        <summary>Tool calls · {run.tool_calls?.length || 0}</summary>
        {run.tool_calls?.map((t: Row, i: number) => (
          <section key={i} className="ops-subtrace">
            <h4>
              {i + 1}. {t.tool} · {duration(t.latency_ms)}
            </h4>
            <pre>{JSON.stringify(t.arguments, null, 2)}</pre>
            <pre>{t.result}</pre>
          </section>
        ))}
      </details>
      <details>
        <summary>Observable activity · {run.events?.length || 0}</summary>
        {run.events?.map((e: Row, i: number) => (
          <div className="ops-event" key={i}>
            <strong>
              {duration(e.at_ms)} · {e.event}
            </strong>
            <pre>{e.data}</pre>
          </div>
        ))}
      </details>
      <p className="muted">
        Credentials and private model reasoning are excluded. Prompt and excerpt displays are bounded;
        character counts describe the original sizes.
      </p>
    </section>
  );
}
function Pricing() {
  const [catalog, setCatalog] = useState<Row>();
  const [model, setModel] = useState('gpt-6.1-sol');
  const [provider, setProvider] = useState('openai');
  const [input, setInput] = useState('');
  const [output, setOutput] = useState('');
  const [status, setStatus] = useState('');
  useEffect(() => {
    void api('/pricing')
      .then(setCatalog)
      .catch((e) => setStatus(e.message));
  }, []);
  return (
    <details className="ops-card">
      <summary>Token prices & cost assumptions</summary>
      <p>
        Versioned standard USD prices per million text tokens. Current catalog:{' '}
        {catalog?.checked_at?.slice(0, 10)}. Unknown models stay unpriced. Local inference excludes hardware
        costs. Free API tiers can be recorded with an explicit zero-rate override.
      </p>
      <a href={catalog?.source} target="_blank" rel="noreferrer">
        Official pricing source
      </a>
      <div className="ops-fields">
        <label>
          Provider
          <select value={provider} onChange={(e) => setProvider(e.target.value)}>
            {['openai', 'gemini', 'azure', 'compatible'].map((p) => (
              <option key={p}>{p}</option>
            ))}
          </select>
        </label>
        <label>
          Model
          <input value={model} onChange={(e) => setModel(e.target.value)} list="ops-models" />
          <datalist id="ops-models">
            {Object.keys(catalog?.models || {}).map((m) => (
              <option key={m}>{m}</option>
            ))}
          </datalist>
        </label>
        <label>
          Input / million
          <input type="number" min="0" step="any" value={input} onChange={(e) => setInput(e.target.value)} />
        </label>
        <label>
          Output / million
          <input
            type="number"
            min="0"
            step="any"
            value={output}
            onChange={(e) => setOutput(e.target.value)}
          />
        </label>
        <button
          className="ops-button"
          disabled={input === '' || output === ''}
          onClick={async () => {
            const r = await fetch(`/api/ops/pricing/${provider}/${encodeURIComponent(model)}`, {
              method: 'PUT',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ input: Number(input), output: Number(output) }),
            });
            setStatus(r.ok ? 'Saved for future calls.' : 'Check the provider, model and rates.');
          }}>
          Save override
        </button>
      </div>
      <p role="status">{status}</p>
      <details>
        <summary>Browse catalog</summary>
        <div className="ops-table">
          <table>
            <thead>
              <tr>
                <th>Model</th>
                <th>Input</th>
                <th>Output</th>
                <th>Cached input</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(catalog?.models || {}).map(([name, rate]: [string, any]) => (
                <tr key={name}>
                  <td>{name}</td>
                  <td>${rate.input}</td>
                  <td>${rate.output}</td>
                  <td>{rate.cached_input == null ? '—' : `$${rate.cached_input}`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </details>
  );
}
function Monitor() {
  const [conversations, setConversations] = useState<Row[]>([]);
  const [conversationOffset, setConversationOffset] = useState(0);
  const [moreConversations, setMoreConversations] = useState(false);
  const [session, setSession] = useState('');
  const [search, setSearch] = useState('');
  const [hours, setHours] = useState('168');
  const [kind, setKind] = useState('');
  const [summary, setSummary] = useState<Row>();
  const [runs, setRuns] = useState<Row[]>([]);
  const [run, setRun] = useState<Row>();
  const [error, setError] = useState('');
  const [tick, setTick] = useState(0);
  const [tab, setTab] = useState('runs');
  const [messages, setMessages] = useState<Row[]>([]);
  const [older, setOlder] = useState<Row>();
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setTick((i) => i + 1), 5000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    let live = true;
    const query = new URLSearchParams({ session_id: session, hours, kind, offset: String(offset) });
    void Promise.all([
      api('/summary?' + query),
      api('/runs?' + query),
      api('/conversations?limit=100&offset=' + conversationOffset),
    ])
      .then(([s, r, c]) => {
        if (live) {
          setSummary(s);
          setRuns(r.items);
          setTotal(r.total);
          setConversations((previous) =>
            conversationOffset === 0
              ? c.sessions
              : [...new Map([...previous, ...c.sessions].map((item) => [item.session_id, item])).values()]
          );
          setMoreConversations(!!c.has_more);
          setError('');
        }
      })
      .catch((e) => {
        if (live) setError(e.message);
      });
    return () => {
      live = false;
    };
  }, [session, hours, kind, tick, offset, conversationOffset]);
  useEffect(() => {
    if (!run?.id) return;
    let live = true;
    void api(`/runs/${run.id}`)
      .then((value) => {
        if (live) setRun(value);
      })
      .catch((e) => {
        if (live) setError(e.message);
      });
    return () => {
      live = false;
    };
  }, [run?.id, tick]);
  useEffect(() => {
    if (!session || tab !== 'conversation') return;
    void api(`/conversations/${session}/messages`).then((r) => {
      setMessages(r.items);
      setOlder(r);
    });
  }, [session, tab, tick]);
  const selected = conversations.find((c) => c.session_id === session);
  const m = summary?.metrics || {};
  const showTrace = async (id: string) => {
    try {
      setRun(await api('/runs/' + id));
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <div className="ops-layout">
      <aside>
        <h2>
          <MessageSquare size={17} /> Conversations
        </h2>
        <label className="ops-search">
          <Search size={14} />
          <input
            aria-label="Search conversations"
            placeholder="Find a conversation…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <button
          className={!session ? 'selected' : ''}
          onClick={() => {
            setSession('');
            setConversationOffset(0);
            setRun(undefined);
            setOffset(0);
          }}>
          All conversations
        </button>
        {conversations
          .filter((c) => (c.title + ' ' + c.preview).toLowerCase().includes(search.toLowerCase()))
          .map((c) => (
            <button
              key={c.session_id}
              className={session === c.session_id ? 'selected' : ''}
              onClick={() => {
                setSession(c.session_id);
                setRun(undefined);
                setOffset(0);
              }}>
              <strong>{c.title}</strong>
              <small>
                {c.message_count} messages · {c.filename}
              </small>
            </button>
          ))}
        {moreConversations && (
          <button onClick={() => setConversationOffset(conversationOffset + 100)}>
            Load older conversations
          </button>
        )}
      </aside>
      <main>
        <div className="ops-page-heading">
          <div>
            <span className="ops-eyebrow">AGENT MONITORING</span>
            <h1>{selected ? selected.title : 'The agent, in view.'}</h1>
            <p>Latency, usage, evidence and feedback. Every chart follows your selected conversation.</p>
          </div>
          <div className="ops-toolbar">
            <select
              aria-label="Run type"
              value={kind}
              onChange={(e) => {
                setKind(e.target.value);
                setOffset(0);
              }}>
              <option value="">All workflows</option>
              <option value="chat">Chat responses</option>
              <option value="ticket_analysis">Ticket summaries</option>
              <option value="backlog_analysis">Backlog reviews</option>
              <option value="evaluation_judge">Evaluation judges</option>
            </select>
            <select
              aria-label="Monitoring time range"
              value={hours}
              onChange={(e) => {
                setHours(e.target.value);
                setOffset(0);
              }}>
              <option value="1">Last hour</option>
              <option value="24">Last 24 hours</option>
              <option value="168">Last 7 days</option>
              <option value="87600">All recorded time</option>
            </select>
            <button className="ops-button" onClick={() => setTick(tick + 1)}>
              <RefreshCw size={15} /> Refresh
            </button>
          </div>
        </div>
        {error && (
          <p className="ops-error" role="alert">
            {error}
          </p>
        )}
        <p className="ops-live">
          <i /> Refreshes every 5 seconds · Langfuse{' '}
          {summary?.langfuse?.configured ? 'configured' : 'optional; not configured'} · MongoDB records
          persist locally
        </p>
        <Cards
          values={[
            ['Recorded requests', number(m.requests), `${m.running || 0} active · ${m.failed || 0} failed`],
            [
              'Average latency',
              duration(m.avg_latency_ms),
              `p95 ${duration(m.p95_latency_ms)} · ${m.p95_sample_size || 0} samples`,
            ],
            ['First response token', duration(m.avg_first_token_ms)],
            [
              'Input / output tokens',
              `${number(m.input_tokens)} / ${number(m.output_tokens)}`,
              `${m.estimated_calls || 0} calls estimated`,
            ],
            ['Model / tool calls', `${number(m.model_calls)} / ${number(m.tool_calls)}`],
            ['Estimated known cost', money(m.known_cost_usd), `${m.unpriced_calls || 0} calls unpriced`],
            [
              'Throughput',
              `${number(m.avg_output_tokens_per_second)} tokens/s`,
              `${number(m.requests_per_minute)} requests/min in selected window`,
            ],
            [
              'Retrieved chunks',
              number(m.chunks_returned),
              `${number(m.avg_chunk_chars)} avg characters per chunk`,
            ],
            [
              'Average model context',
              `${number(m.avg_prompt_chars)} chars`,
              'Serialized input, including tools and instructions',
            ],
            ['User feedback', `${m.thumbs_up || 0} helpful · ${m.thumbs_down || 0} unhelpful`],
            ['Blocked inputs', number(m.blocked_inputs)],
          ]}
        />
        <div className="ops-charts">
          <Timeline rows={summary?.timeline || []} />
          <Bars title="Usage by model" rows={summary?.models || []} />
          <Bars title="Tools used" rows={summary?.tools || []} />
          <Bars title="Skills used" rows={summary?.skills || []} />
        </div>
        <div className="ops-tabs">
          <button className={tab === 'runs' ? 'selected' : ''} onClick={() => setTab('runs')}>
            Responses & traces
          </button>
          <button
            disabled={!session}
            className={tab === 'conversation' ? 'selected' : ''}
            onClick={() => setTab('conversation')}>
            Conversation messages
          </button>
        </div>
        {run ? (
          <RunDetail run={run} back={() => setRun(undefined)} />
        ) : tab === 'conversation' ? (
          <section className="ops-card">
            {older?.has_more && (
              <button
                className="ops-button"
                onClick={async () => {
                  const r = await api(`/conversations/${session}/messages?before_id=${older.before_id}`);
                  setMessages([...r.items, ...messages]);
                  setOlder(r);
                }}>
                Load earlier messages
              </button>
            )}
            {messages.map((message, i) => (
              <article className={`ops-message ${message.role}`} key={message.id || i}>
                <h4>{message.role === 'user' ? 'You' : 'Sprint Agent'}</h4>
                <Markdown text={message.content} />
                {message.run_id && (
                  <button className="ops-button" onClick={() => void showTrace(message.run_id)}>
                    Inspect this response
                  </button>
                )}
              </article>
            ))}
          </section>
        ) : (
          <section className="ops-card">
            <h2>Responses & traces</h2>
            <div className="ops-table">
              <table>
                <thead>
                  <tr>
                    <th>Message</th>
                    <th>Model</th>
                    <th>Status</th>
                    <th>Latency</th>
                    <th>Input / output</th>
                    <th>Calls</th>
                    <th>Feedback</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((r) => (
                    <tr key={r.id} onClick={() => void showTrace(r.id)}>
                      <td>
                        <button className="ops-link">
                          {r.question?.slice(0, 110) || 'Historical response'}
                        </button>
                        <small>{r.started_at?.replace('T', ' ').slice(0, 19)}</small>
                      </td>
                      <td>
                        {r.model}
                        <small>{r.kind || 'chat'}</small>
                      </td>
                      <td>
                        <span className={`ops-badge ${r.status}`}>{r.status}</span>
                      </td>
                      <td>{duration(r.latency_ms)}</td>
                      <td>
                        {number(r.usage?.input_tokens)} / {number(r.usage?.output_tokens)}
                      </td>
                      <td>
                        {r.model_call_count || 0} model · {r.tool_call_count || 0} tool
                      </td>
                      <td>
                        {r.feedback?.vote === 1 ? 'Helpful' : r.feedback?.vote === -1 ? 'Unhelpful' : '—'}
                        {r.feedback?.note && <small>{r.feedback.note}</small>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!runs.length && (
              <p>No traces yet in this scope. Ask Sprint Agent a question to start collecting them.</p>
            )}
            <div className="ops-pagination">
              <span>
                {offset + (runs.length ? 1 : 0)}–{offset + runs.length} of {total}
              </span>
              <button
                className="ops-button"
                disabled={!offset}
                onClick={() => setOffset(Math.max(0, offset - 30))}>
                Previous
              </button>
              <button
                className="ops-button"
                disabled={offset + runs.length >= total}
                onClick={() => setOffset(offset + 30)}>
                Next
              </button>
            </div>
          </section>
        )}
        <Pricing />
        <p className="muted">
          Costs are estimates from each call’s price snapshot, not provider billing. Historical responses
          without telemetry are labeled legacy. Only new instrumented requests contribute measured usage.
        </p>
      </main>
    </div>
  );
}
function Review({ result, saved }: { result: Row; saved: () => void }) {
  const [rating, setRating] = useState(result.human?.score || 3);
  const [feedback, setFeedback] = useState(result.human?.feedback || '');
  const [verify, setVerify] = useState(false);
  const [reference, setReference] = useState(result.reference || '');
  const [status, setStatus] = useState('');
  return (
    <section className="ops-card">
      <h2>
        {result.case_number}. {result.question}
      </h2>
      <div className="ops-answer-comparison">
        <div>
          <h3>Reference · {result.reference_status?.replaceAll('_', ' ')}</h3>
          <Markdown text={result.reference} />
        </div>
        <div>
          <h3>{result.model} response</h3>
          {result.error ? <p className="ops-error">{result.error}</p> : <Markdown text={result.response} />}
        </div>
      </div>
      {result.reference_validation && (
        <p className="ops-note">
          This checks an uploaded expected answer against supplied reference evidence. It does not generate an
          answer or report self-overlap as a score.
        </p>
      )}
      <NgramMetrics values={result.metrics?.ngrams} />
      <ContextEvidence result={result} />
      {result.metric_story?.map((text: string, i: number) => (
        <p className="ops-note" key={i}>
          {text}
        </p>
      ))}
      <details>
        <summary>Metrics & retrieval evidence</summary>
        <pre>{JSON.stringify({ metrics: result.metrics, ragas: result.ragas }, null, 2)}</pre>
        {result.retrieved_contexts?.map((text: string, i: number) => (
          <pre key={i}>{text}</pre>
        ))}
      </details>
      <form
        className="ops-review-form"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            const review = await api(`/evaluation/results/${result.id}/review`, {
              score: rating,
              feedback,
              reference_verified: verify,
              corrected_reference: verify ? reference : null,
            });
            setStatus(
              'Human review saved' +
                (review.new_version_number
                  ? ` · Reference saved in dataset version ${review.new_version_number}`
                  : '')
            );
            saved();
          } catch (error) {
            setStatus((error as Error).message);
          }
        }}>
        <h3>Human review</h3>
        <fieldset>
          <legend>Answer quality · 1 poor to 5 excellent</legend>
          {[1, 2, 3, 4, 5].map((n) => (
            <label key={n}>
              <input
                type="radio"
                name={`rating-${result.id}`}
                value={n}
                checked={rating === n}
                onChange={() => setRating(n)}
              />{' '}
              {n}
            </label>
          ))}
        </fieldset>
        <label>
          Feedback
          <textarea
            aria-label="Evaluation feedback"
            maxLength={300}
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            placeholder="What was correct, missing or misleading?"
          />
        </label>
        <label className="ops-checkbox">
          <input type="checkbox" checked={verify} onChange={(e) => setVerify(e.target.checked)} /> I verified
          the reference against source tickets
        </label>
        {verify && (
          <label>
            Verified or corrected reference
            <textarea maxLength={12000} value={reference} onChange={(e) => setReference(e.target.value)} />
          </label>
        )}
        <button className="ops-button primary" type="submit">
          Save human review
        </button>
        <span role="status">{status}</span>
      </form>
    </section>
  );
}
function Evaluations() {
  const [pane, setPane] = useState<'datasets' | 'prompts' | 'run' | 'history'>('datasets');
  const [runs, setRuns] = useState<Row[]>([]);
  const [selected, setSelected] = useState('');
  const [data, setData] = useState<Row>();
  const [compareId, setCompareId] = useState('');
  const [compare, setCompare] = useState<Row>();
  const [focus, setFocus] = useState('');
  const [error, setError] = useState('');
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setTick((n) => n + 1), 10000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    void api('/evaluation/runs')
      .then((r) => {
        setRuns(r);
        if (!selected && r.length) setSelected(r[0].id);
      })
      .catch((e) => setError(e.message));
  }, [tick]);
  useEffect(() => {
    if (selected)
      void api('/evaluation/runs/' + selected)
        .then(setData)
        .catch((e) => setError(e.message));
  }, [selected, tick]);
  useEffect(() => {
    if (compareId)
      void api('/evaluation/runs/' + compareId)
        .then(setCompare)
        .catch((e) => setError(e.message));
    else setCompare(undefined);
  }, [compareId, tick]);
  const summary = data?.summary || {};
  const result = data?.results?.find((r: Row) => r.id === focus);
  return (
    <main className="ops-evaluation">
      <div className="ops-page-heading">
        <div>
          <span className="ops-eyebrow">EVALUATION & HUMAN REVIEW</span>
          <h1>Better answers, with evidence.</h1>
          <p>
            Replay the same conversation, compare models, and review answers against verified project data.
          </p>
        </div>
        <button className="ops-button" onClick={() => setTick(tick + 1)}>
          <RefreshCw size={15} /> Refresh
        </button>
      </div>
      {error && (
        <p role="alert" className="ops-error">
          {error}
        </p>
      )}
      <nav className="evaluation-tabs" aria-label="Evaluation sections">
        {(
          [
            ['datasets', 'Golden datasets'],
            ['prompts', 'Project prompts'],
            ['run', 'Run tests'],
            ['history', 'Performance history'],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            className={`ops-button${pane === id ? ' active' : ''}`}
            aria-pressed={pane === id}
            onClick={() => setPane(id)}>
            {label}
          </button>
        ))}
      </nav>
      <EvaluationWorkbench
        pane={pane}
        refresh={tick}
        onSaved={() => setTick((n) => n + 1)}
        onResults={(ids) => {
          setSelected(ids[0]);
          setCompareId(ids[1] || '');
          setPane('history');
          setFocus('');
          setTick((n) => n + 1);
        }}
      />
      <div hidden={pane !== 'history'}>
        <div className="ops-card ops-fields">
          <label>
            Evaluation run
            <select
              aria-label="Evaluation run"
              value={selected}
              onChange={(e) => {
                setSelected(e.target.value);
                setFocus('');
              }}>
              <option value="">Select a run</option>
              {runs.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.model} · {r.completed}/{r.case_count} ·{' '}
                  {r.golden_version_number ? `v${r.golden_version_number} · ` : ''}
                  {r.status} · {r.started_at?.slice(0, 16)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Compare another model/run
            <select
              aria-label="Compare evaluation"
              value={compareId}
              onChange={(e) => setCompareId(e.target.value)}>
              <option value="">No comparison</option>
              {runs
                .filter((r) => r.id !== selected)
                .map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.model} · {r.started_at?.slice(0, 16)}
                  </option>
                ))}
            </select>
          </label>
        </div>
        {!data ? (
          <section className="ops-card">
            <h2>Start with a real conversation</h2>
            <p>
              Run <code>make evaluation-import DOCUMENT="/path/Conversation.docx"</code>, then{' '}
              <code>make evaluate</code>. The runner defaults to your saved Gemini connection. Add{' '}
              <code>RAGAS=1</code> for Ragas scoring.
            </p>
          </section>
        ) : (
          <>
            <div className="ops-card">
              <h2>Configuration used for these results</h2>
              <p>
                Test data {data.golden_version_number ? `v${data.golden_version_number}` : 'legacy'} ·{' '}
                {data.model} · effort {data.effort} · pipeline{' '}
                {data.pipeline_version?.slice(0, 10) || 'not recorded'}
              </p>
              <PromptSnapshot value={data.prompt_snapshot} />
              {compare && (
                <>
                  <p>
                    Compared with {compare.model} · test data{' '}
                    {compare.golden_version_number ? `v${compare.golden_version_number}` : 'legacy'}
                  </p>
                  <PromptSnapshot value={compare.prompt_snapshot} />
                  {data.prompt_version_id !== compare.prompt_version_id && (
                    <p className="ops-note">
                      Prompt comparison: these runs use different project guidance. To measure its effect,
                      keep the model, test dataset, source export, pipeline, effort and judge the same.
                    </p>
                  )}
                </>
              )}
            </div>
            <p className="ops-live">
              <i /> {data.status} · {data.completed}/{data.case_count} generated · {data.failed} failed ·{' '}
              {data.source_file}
            </p>
            <Cards
              values={[
                [
                  'Successful answers',
                  score(summary.success_rate),
                  `${data.completed} successful · ${data.failed} failed`,
                ],
                ['Ragas faithfulness', score(summary.faithfulness)],
                ['Ragas context precision', score(summary.context_precision)],
                [
                  'Human quality',
                  typeof summary.human_score === 'number'
                    ? `${summary.human_score.toFixed(2)} / 5`
                    : 'Awaiting review',
                  `${summary.reviewed || 0} answers reviewed`,
                ],
              ]}
            />
            <p className="ops-note">
              Original AI answers are provisional references until verified. Ragas scores cover sampled
              retrieved evidence and can share the answer model’s biases. Token overlap is a descriptive
              baseline. Human review remains the deciding signal.
            </p>
            <AggregateOverlap runs={compare ? [data, compare] : [data]} />
            {compare && <QuestionComparison first={data} second={compare} />}
            {compare && (
              <section className="ops-card">
                <h2>Model comparison</h2>
                {compare.dataset_version !== data.dataset_version ||
                compare.case_count !== data.case_count ? (
                  <p className="ops-note">
                    Different dataset versions or case counts. Compare common questions before choosing a
                    model.
                  </p>
                ) : null}
                {(!data.pipeline_version ||
                  !compare.pipeline_version ||
                  data.pipeline_version !== compare.pipeline_version ||
                  data.effort !== compare.effort ||
                  data.source_snapshot_sha256 !== compare.source_snapshot_sha256) && (
                  <p className="ops-note">
                    Pipeline versions, effort or source snapshots differ or are unrecorded. Treat this as an
                    exploratory comparison, not a controlled model ranking.
                  </p>
                )}
                <div className="ops-table">
                  <table>
                    <thead>
                      <tr>
                        <th>Run</th>
                        <th>Coverage</th>
                        <th>Faithfulness</th>
                        <th>Context precision</th>
                        <th>Human score</th>
                      </tr>
                    </thead>
                    <tbody>
                      {[data, compare].map((r) => (
                        <tr key={r.id}>
                          <td>{r.model}</td>
                          <td>
                            {r.completed}/{r.case_count}
                          </td>
                          <td>{score(r.summary?.faithfulness)}</td>
                          <td>{score(r.summary?.context_precision)}</td>
                          <td>{number(r.summary?.human_score)} / 5</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}
            <section className="ops-card">
              <h2>Questions & results</h2>
              <div className="ops-table">
                <table>
                  <thead>
                    <tr>
                      <th>Question</th>
                      <th>Status</th>
                      <th>Answer latency</th>
                      <th>Faithfulness</th>
                      <th>Context precision</th>
                      <th>Human</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.results?.map((r: Row) => (
                      <tr key={r.id} onClick={() => setFocus(r.id)}>
                        <td>
                          <button className="ops-link">
                            {r.case_number}. {r.question}
                          </button>
                        </td>
                        <td>{r.status}</td>
                        <td>{duration(r.generation_latency_ms ?? r.latency_ms)}</td>
                        <td>{score(r.ragas?.metrics?.faithfulness)}</td>
                        <td>{score(r.ragas?.metrics?.context_precision)}</td>
                        <td>{r.human?.score ? `${r.human.score}/5` : 'Review'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
            {result && <Review key={result.id} result={result} saved={() => setTick(tick + 1)} />}
          </>
        )}
        <section className="ops-card">
          <h3>Command line evaluation is also available</h3>
          <pre>make evaluate CONNECTION=&lt;saved-connection-id&gt; RAGAS=1</pre>
          <p>
            Full question history is replayed in order. Every attempted case, including quota failures, is
            recorded. Choose a saved connection in Sprint Agent’s Configure menu first.
          </p>
          <a href="https://docs.ragas.io/en/stable/" target="_blank" rel="noreferrer">
            Ragas metric definitions
          </a>
        </section>
      </div>
    </main>
  );
}
function App() {
  const evaluation = location.pathname.includes('evaluation');
  return (
    <>
      <header className="ops-header">
        <a href={evaluation ? '/evaluation' : '/monitoring'}>
          <img src="/assets/agileplanner.svg" alt="" /> AgilePlanner <span>Agent operations</span>
        </a>
        <nav>
          <a className={!evaluation ? 'active' : ''} href="/monitoring">
            <Activity size={16} /> Monitoring
          </a>
          <a className={evaluation ? 'active' : ''} href="/evaluation">
            <Star size={16} /> Evaluation
          </a>
        </nav>
        <ThemeToggle />
        <span className="ops-local">
          <ShieldCheck size={15} /> Local workspace
        </span>
      </header>
      {evaluation ? <Evaluations /> : <Monitor />}
      <footer className="ops-footer">AgilePlanner · Observable decisions, traceable answers.</footer>
    </>
  );
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
