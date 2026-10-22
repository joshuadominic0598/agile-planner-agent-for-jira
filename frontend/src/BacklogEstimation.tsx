import { useEffect, useState, type FormEvent } from 'react';
import { api } from './api';
import type { Project, Split } from './types';
import FeatureAnalysis, { type AnalysisResult } from './FeatureAnalysis';
import BacklogPeople, { type PlanningPerson } from './BacklogPeople';
import './planning.css';

type ResourceCapacity = { available: boolean; unit: 'points' | 'hours'; budget: number | null };
const readinessLabels: Record<string, string> = {
  triage: 'Needs triage',
  owner_refinement: 'Assignee refinement',
  needs_owner: 'Choose owner',
  ready: 'Ready for planning',
  parent_tracking: 'Parent tracking',
};
type Config = {
  project: string;
  scope: 'project' | 'sprint';
  sprint: string;
  completion: 'category' | 'statuses';
  finished_statuses: string[];
  focus_priorities: string[];
  unit: 'points' | 'hours';
  time_field: 'remaining_seconds' | 'original_seconds';
  budget: number | null;
  capacity_unit: 'points' | 'hours' | null;
  capacity_cadence: 'per_sprint';
  resources: Record<string, ResourceCapacity>;
  pending_priorities: string[];
  basis: 'open' | 'all';
  parent_policy: 'leaf_only' | 'all_estimated';
  roster: 'developers' | 'configured';
};
type Ticket = {
  key: string;
  summary: string;
  status: string;
  type: string;
  priority: string;
  assignee: string;
  estimate: number | null;
  estimate_counted: boolean;
  readiness: string;
  next_step: string;
};
type Report = {
  config: Config;
  scope_label: string;
  fingerprint: string;
  allocation_basis: string;
  forecast: { minimum_sprints: number | null; capacity_per_sprint: number; unit: string; message: string };
  metrics: Record<string, number>;
  statuses: Split;
  priorities: Split;
  priority_options: Split;
  types: Split;
  notes: string[];
  people: PlanningPerson[];
  readiness: Split;
  tickets: Ticket[];
};
const defaults = (project: string, sprint: string): Config => ({
  project,
  scope: project && sprint ? 'sprint' : 'project',
  sprint,
  completion: 'category',
  finished_statuses: [],
  focus_priorities: [],
  unit: 'points',
  time_field: 'remaining_seconds',
  budget: null,
  capacity_unit: 'points',
  capacity_cadence: 'per_sprint',
  resources: {},
  pending_priorities: [],
  basis: 'all',
  parent_policy: 'leaf_only',
  roster: 'developers',
});
export default function BacklogEstimation({
  dataset,
  project,
  sprints,
  currentSprint,
  statuses,
  onTicket,
  projects,
  onProject,
  requestedScope,
  onScope,
}: {
  dataset: string;
  project: string;
  sprints: Split;
  currentSprint: string;
  statuses: Split;
  onTicket: (key: string) => void;
  projects: Project[];
  onProject: (key: string) => void;
  requestedScope: Config['scope'] | null;
  onScope: (scope: Config['scope']) => void;
}) {
  const [config, setConfig] = useState<Config>(() => ({
    ...defaults(project, currentSprint),
    scope: requestedScope || defaults(project, currentSprint).scope,
  }));
  const [report, setReport] = useState<Report>();
  const [analysis, setAnalysis] = useState<AnalysisResult>();
  const [group, setGroup] = useState('');
  const [readiness, setReadiness] = useState('');
  const [priority, setPriority] = useState('');
  const [page, setPage] = useState(1);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);
  const [notice, setNotice] = useState('');
  const base = `/datasets/${dataset}`;
  useEffect(() => {
    let live = true;
    setBusy(true);
    setReport(undefined);
    setAnalysis(undefined);
    setGroup('');
    setReadiness('');
    setPriority('');
    setPage(1);
    setError('');
    if (!project) {
      setBusy(false);
      return;
    }
    api<Config & { notice?: string }>(`${base}/planning/settings?project=${encodeURIComponent(project)}`)
      .then(async (value) => {
        const { notice: message, ...stored } = value;
        const selectedScope = requestedScope || (stored.sprint || currentSprint ? stored.scope : 'project');
        const initial = {
          ...stored,
          focus_priorities: [],
          pending_priorities: [],
          project,
          scope: selectedScope,
          sprint: selectedScope === 'sprint' ? stored.sprint || currentSprint : '',
        };
        if (live) {
          setConfig(initial);
          setNotice(message || '');
        }
        const result = await api<Report>(`${base}/planning/report`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(initial),
        });
        if (live) setReport(result);
      })
      .catch((e) => {
        if (live) setError(e.message);
      })
      .finally(() => {
        if (live) setBusy(false);
      });
    return () => {
      live = false;
    };
  }, [base, project]);
  const change = <K extends keyof Config>(key: K, value: Config[K]) => {
    if (key === 'scope') {
      onScope(value as Config['scope']);
      setConfig((c) => ({
        ...c,
        scope: value as Config['scope'],
        sprint: value === 'sprint' ? currentSprint : '',
      }));
    } else setConfig((c) => ({ ...c, [key]: value }));
    setSaved(false);
  };
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError('');
    setSaved(false);
    try {
      await api(`${base}/planning/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      });
      const value = await api<Report>(`${base}/planning/report`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      });
      setReport(value);
      setAnalysis(undefined);
      setGroup('');
      setReadiness('');
      setPriority('');
      setPage(1);
      setSaved(true);
      setNotice('');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const matches =
    report?.tickets.filter(
      (t) =>
        (!group ||
          (group === '__unreviewed__'
            ? !analysis?.groups.some((g) => g.keys.includes(t.key))
            : analysis?.groups.find((g) => g.name === group)?.keys.includes(t.key))) &&
        (!readiness || t.readiness === readiness) &&
        (!priority || (t.priority || 'Unspecified') === priority)
    ) || [];
  return (
    <section aria-label="Backlog Management" className="planning-page">
      <form className="card planning-config" onSubmit={submit}>
        <h2>Your planning rules</h2>
        <p className="muted">
          Define unfinished work and what capacity means for your team. Saved rules are also available to
          Sprint Agent.
        </p>
        <fieldset className="planning-rule-controls" disabled={busy}>
          <div className="planning-fields">
            <label>
              Backlog scope
              <select
                aria-label="Backlog scope"
                value={config.scope}
                onChange={(e) => change('scope', e.target.value as Config['scope'])}>
                <option value="project">Whole project</option>
                <option value="sprint">Selected sprint</option>
              </select>
            </label>
            <label>
              Project
              <select
                aria-label="Project"
                value={project}
                onChange={(e) => {
                  onScope(config.scope);
                  onProject(e.target.value);
                }}>
                <option value="">Choose project</option>
                {projects.map((p) => (
                  <option key={p.key} value={p.key}>
                    {p.name} ({p.count})
                  </option>
                ))}
              </select>
            </label>
            {config.scope === 'sprint' && project && (
              <label>
                Backlog sprint
                <select
                  aria-label="Backlog sprint"
                  value={config.sprint}
                  onChange={(e) => change('sprint', e.target.value)}>
                  <option value="">Choose sprint</option>
                  {sprints.map((s) => (
                    <option key={s.name}>{s.name}</option>
                  ))}
                </select>
              </label>
            )}
            {project && (
              <>
                <label>
                  Finished work
                  <select
                    aria-label="Finished work"
                    value={config.completion}
                    onChange={(e) => change('completion', e.target.value as Config['completion'])}>
                    <option value="category">Status Category = Done</option>
                    <option value="statuses">Statuses I choose</option>
                  </select>
                </label>
                <label>
                  Estimate unit
                  <select
                    aria-label="Estimate unit"
                    value={config.unit}
                    onChange={(e) => change('unit', e.target.value as Config['unit'])}>
                    <option value="points">Story points</option>
                    <option value="hours">Hours</option>
                  </select>
                </label>
                {(config.unit === 'hours' ||
                  config.capacity_unit === 'hours' ||
                  Object.values(config.resources).some((r) => r.unit === 'hours')) && (
                  <label>
                    Time estimate
                    <select
                      aria-label="Time estimate"
                      value={config.time_field}
                      onChange={(e) => change('time_field', e.target.value as Config['time_field'])}>
                      <option value="remaining_seconds">Remaining estimate</option>
                      <option value="original_seconds">Original estimate</option>
                    </select>
                  </label>
                )}
                <label>
                  Default capacity unit
                  <select
                    aria-label="Default capacity unit"
                    value={config.capacity_unit || config.unit}
                    onChange={(e) => change('capacity_unit', e.target.value as ResourceCapacity['unit'])}>
                    <option value="points">Story points per sprint</option>
                    <option value="hours">Hours per sprint</option>
                  </select>
                </label>
                <label>
                  Default budget per person, per sprint
                  <input
                    aria-label="Budget per person"
                    type="number"
                    min="0.01"
                    max="10000"
                    step="any"
                    placeholder="Set your team's sprint budget"
                    value={config.budget ?? ''}
                    onChange={(e) => change('budget', e.target.value ? Number(e.target.value) : null)}
                  />
                </label>
                {config.scope === 'sprint' && (
                  <label>
                    Sprint workload counted
                    <select
                      aria-label="Workload counted"
                      value={config.basis}
                      onChange={(e) => change('basis', e.target.value as Config['basis'])}>
                      <option value="all">All work in this sprint</option>
                      <option value="open">Unfinished work in this sprint</option>
                    </select>
                  </label>
                )}
                <label>
                  Estimate counting
                  <select
                    aria-label="Estimate counting"
                    value={config.parent_policy}
                    onChange={(e) => change('parent_policy', e.target.value as Config['parent_policy'])}>
                    <option value="leaf_only">Exclude parents/epics</option>
                    <option value="all_estimated">Include parents/epics</option>
                  </select>
                </label>
                <label>
                  Eligible people
                  <select
                    aria-label="Eligible people"
                    value={config.roster}
                    onChange={(e) => change('roster', e.target.value as Config['roster'])}>
                    <option value="developers">Active saved developers</option>
                    <option value="configured">All active saved profiles</option>
                  </select>
                </label>
              </>
            )}
          </div>
          {!project && <p className="muted">Choose a project to see its planning rules and tickets.</p>}
          {project && config.completion === 'statuses' && (
            <fieldset>
              <legend>Treat these statuses as finished</legend>
              {statuses.map((s) => (
                <label className="checkbox" key={s.name}>
                  <input
                    type="checkbox"
                    checked={config.finished_statuses.includes(s.name)}
                    onChange={(e) =>
                      change(
                        'finished_statuses',
                        e.target.checked
                          ? [...config.finished_statuses, s.name]
                          : config.finished_statuses.filter((n) => n !== s.name)
                      )
                    }
                  />
                  {s.name}
                </label>
              ))}
            </fieldset>
          )}
        </fieldset>
        <button className="button primary" disabled={busy || !project}>
          {busy ? 'Loading report…' : 'Save rules and update report'}
        </button>
        {saved && (
          <strong role="status" className="planning-saved">
            ✓ Rules saved · Report updated
          </strong>
        )}
      </form>
      {notice && (
        <p className="selected-filter" role="status">
          {notice}
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {report && (
        <>
          <p className="muted small">
            Showing report: {report.config.scope === 'project' ? 'Whole project' : report.config.sprint} ·
            unfinished ={' '}
            {report.config.completion === 'category'
              ? 'outside Done category (including unknown)'
              : `outside ${report.config.finished_statuses.join(', ')}`}{' '}
            · {report.config.unit}. Apply rule changes above to refresh.
          </p>
          <div className="metrics planning-metrics" role="group" aria-label="Backlog metrics">
            {[
              ['Unfinished tickets', report.metrics.backlog_tickets],
              ['Estimated tickets', report.metrics.estimated_tickets],
              ['Unestimated tickets', report.metrics.missing_estimates],
              ['Total active devs', report.metrics.active_developers],
              [
                'People with headroom',
                report.config.scope === 'project'
                  ? '—'
                  : report.people.some((p) => p.developer && p.headroom !== null)
                    ? report.metrics.headroom_people
                    : 'Unknown',
              ],
              [
                'Overloaded devs',
                report.config.scope === 'project' ? '—' : report.metrics.overloaded_developers,
              ],
            ].map(([label, count]) => (
              <article className="metric" key={label}>
                <span>{label}</span>
                <strong>{count}</strong>
              </article>
            ))}
          </div>
          <p className="muted small">
            Estimate counts{' '}
            {report.config.parent_policy === 'leaf_only' ? 'exclude parents/epics' : 'include parents/epics'}.{' '}
            Mark active developers in People & planning → Manage people.
            {report.config.scope === 'project' &&
              ' Choose a sprint to compare assigned workload with sprint budgets.'}
          </p>
          <BacklogBreakdown
            title="Backlog by priority"
            items={report.priorities}
            selected={priority}
            onSelect={(value) => {
              setPriority(value);
              setPage(1);
            }}
          />
          <BacklogBreakdown
            title="Planning readiness"
            items={report.readiness.map((r) => ({ ...r, label: readinessLabels[r.name] || r.name }))}
            selected={readiness}
            onSelect={(value) => {
              setReadiness(value);
              setPage(1);
            }}
          />
          <section className="card" aria-label="Backlog Tickets">
            <div className="card-heading">
              <div>
                <h2>Backlog Tickets</h2>
                <p className="muted small">{matches.length} matching tickets · 20 per page</p>
              </div>
              <div className="planning-filters">
                <label>
                  Priority
                  <select
                    aria-label="Backlog priority"
                    value={priority}
                    onChange={(e) => {
                      setPriority(e.target.value);
                      setPage(1);
                    }}>
                    <option value="">All priorities</option>
                    {report.priorities.map((p) => (
                      <option key={p.name}>{p.name}</option>
                    ))}
                  </select>
                </label>
                <label>
                  Planning readiness
                  <select
                    aria-label="Planning readiness"
                    value={readiness}
                    onChange={(e) => {
                      setReadiness(e.target.value);
                      setPage(1);
                    }}>
                    <option value="">All tickets</option>
                    {Object.entries(readinessLabels).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                {analysis && (
                  <label>
                    AI work theme
                    <select
                      aria-label="AI work theme"
                      value={group}
                      onChange={(e) => {
                        setGroup(e.target.value);
                        setPage(1);
                      }}>
                      <option value="">All work themes</option>
                      <option value="__unreviewed__">Not yet reviewed by AI</option>
                      {analysis.groups.map((g) => (
                        <option key={g.name} value={g.name}>
                          {g.name} ({g.keys.length})
                        </option>
                      ))}
                    </select>
                  </label>
                )}
              </div>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Ticket</th>
                    <th>Title / status</th>
                    <th>Priority</th>
                    <th>Assignee</th>
                    <th>Estimate ({report.config.unit})</th>
                    <th>Next step</th>
                  </tr>
                </thead>
                <tbody>
                  {matches.slice((page - 1) * 20, page * 20).map((t) => (
                    <tr key={t.key}>
                      <td>
                        <button className="issue-key" onClick={() => onTicket(t.key)}>
                          {t.key}
                        </button>
                      </td>
                      <td>
                        {t.summary}
                        <br />
                        <small>
                          {t.status} · {t.type}
                        </small>
                      </td>
                      <td>{t.priority || 'Unspecified'}</td>
                      <td>{t.assignee || 'Unassigned'}</td>
                      <td>
                        {t.estimate === null ? 'Unknown' : t.estimate}
                        {!t.estimate_counted && ' (parent excluded)'}
                      </td>
                      <td>
                        <span className={`readiness-tag readiness-${t.readiness}`}>
                          {readinessLabels[t.readiness]}
                        </span>
                        <br />
                        <small>{t.next_step}</small>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!matches.length && <p>No tickets match these filters.</p>}
            {!!matches.length && (
              <nav className="planning-pagination" aria-label="Backlog ticket pages">
                <span className="muted small">
                  {(page - 1) * 20 + 1}–{Math.min(page * 20, matches.length)} of {matches.length}
                </span>
                <button
                  className="button secondary"
                  disabled={page === 1}
                  onClick={() => setPage((p) => p - 1)}>
                  Previous
                </button>
                <span className="small">
                  Page {page} of {Math.ceil(matches.length / 20)}
                </span>
                <button
                  className="button secondary"
                  disabled={page * 20 >= matches.length}
                  onClick={() => setPage((p) => p + 1)}>
                  Next
                </button>
              </nav>
            )}
          </section>
          <BacklogPeople
            people={report.people}
            onTicket={onTicket}
            base={base}
            project={report.config.project}
            onPeopleSaved={async () => {
              const updated = await api<Report>(`${base}/planning/report`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(report.config),
              });
              setReport(updated);
              setAnalysis(undefined);
              setGroup('');
            }}
          />
          <FeatureAnalysis
            key={report.fingerprint}
            dataset={dataset}
            request={{ kind: 'backlog', config: report.config }}
            onTicket={onTicket}
            onResult={(result) => {
              if (result.fingerprint === report.fingerprint) {
                setAnalysis(result);
                setPage(1);
              }
            }}
          />
          {!!analysis?.assignments.length && (
            <section className="card">
              <h2>Suggested allocations</h2>
              <p className="muted small">
                {report.allocation_basis}. Review with your team. No Jira assignments have changed.
              </p>
              {analysis.assignments.map((a) => (
                <p key={a.key}>
                  <button className="issue-key" onClick={() => onTicket(a.key)}>
                    {a.key}
                  </button>{' '}
                  → <strong>{a.person}</strong> · {a.estimate} {a.unit || report.config.unit}
                  <br />
                  <span className="muted small">{a.reason}</span>
                </p>
              ))}
            </section>
          )}
          <details className="card">
            <summary>How to read this report</summary>
            <ul>
              {report.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
            <p>
              Estimate coverage: {report.metrics.estimated_tickets}/{report.metrics.counted_tickets} counted
              tickets. {report.metrics.unclassified} tickets have no Status Category.
            </p>
          </details>
        </>
      )}
    </section>
  );
}

function BacklogBreakdown({
  title,
  items,
  selected,
  onSelect,
}: {
  title: string;
  items: (Split[number] & { label?: string })[];
  selected: string;
  onSelect: (value: string) => void;
}) {
  const max = Math.max(1, ...items.map((item) => item.count));
  return (
    <section className="card planning-breakdown" aria-label={title}>
      <div className="card-heading">
        <h2>{title}</h2>
        <span className="muted small">Select a bar to filter tickets</span>
      </div>
      <div className="planning-bars">
        {items.map((item) => (
          <button
            type="button"
            key={item.name}
            className={`planning-bar readiness-${item.name}`}
            aria-pressed={selected === item.name}
            onClick={() => onSelect(selected === item.name ? '' : item.name)}>
            <span>{item.label || item.name}</span>
            <i>
              <b style={{ width: `${(item.count / max) * 100}%` }} />
            </i>
            <strong>{item.count.toLocaleString()}</strong>
          </button>
        ))}
      </div>
    </section>
  );
}
