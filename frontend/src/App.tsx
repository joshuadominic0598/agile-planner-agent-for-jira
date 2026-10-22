import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ArrowRight, ArrowUpRight, BarChart3, Check, ChevronLeft, ChevronRight, CircleHelp, FileSpreadsheet, FolderKanban, LayoutDashboard, LoaderCircle, Search, ShieldCheck, Sparkles, Upload, X } from 'lucide-react';
import { api, params } from './api';
import type { Dashboard, Import, IssueDetail, IssuePage, Metrics, Project, Split, WorkflowStage } from './types';
import WorkflowEditor from './WorkflowEditor';
import People from './People';
import AgentChat, { AgentSetup, type Attachment } from './AgentChat';
import EmbeddingChoice from './EmbeddingChoice';
import SprintRoles from './SprintRoles';
import { ParentBadge, TypeBadge, typeColor } from './IssueIdentity';
import TicketFinder from './TicketFinder';
import DuplicateTickets from './DuplicateTickets';
import { useBackLayer } from './useBackLayer';
import ThemeToggle from './ThemeToggle';
import BacklogEstimation from './BacklogEstimation';
import FeatureAnalysis from './FeatureAnalysis';
import FieldExplorer, { type FieldFilter } from './FieldExplorer';

const COLORS = ['#0c66e4', '#579dff', '#8590a2', '#6e5dc6', '#227d9b', '#8fb8e8', '#44546f', '#b8cce7'];
const categoryColor = (name: string) => ({ 'to do': '#0c66e4', 'in progress': '#e7791a', done: '#1f845a' } as Record<string, string>)[name.trim().toLowerCase()];
const chartColor = (name: string, index: number, types: boolean, categories: boolean) => (categories && categoryColor(name)) || (types ? typeColor(name) : COLORS[index % COLORS.length]);
const number = (n: number) => n.toLocaleString();
const read = (key: string) => { try { return localStorage.getItem(key); } catch { return null; } };
const save = (key: string, value: string) => { try { localStorage.setItem(key, value); } catch { /* Session still works without browser storage. */ } };

function Brand() { return <div className="brand" title="Project insights, backlog planning and AI support"><img className="brand-icon" src="/assets/agileplanner.svg" alt="" aria-hidden="true" />AgilePlanner<span className="brand-dot">.</span></div>; }
function ErrorMessage({ message }: { message: string }) { return <div className="error" role="alert">{message}</div>; }
function Status({ name }: { name: string }) {
  const color = COLORS[Array.from(name).reduce((sum, c) => sum + c.charCodeAt(0), 0) % COLORS.length];
  return <span className="status" style={{ '--status-color': color, background: `${color}10`, borderColor: `${color}30` } as React.CSSProperties}><i />{name}</span>;
}

function UploadScreen({ onReady, onBack }: { onReady: (data: Import) => void; onBack?: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [prepareAgent, setPrepareAgent] = useState(true);
  const [embeddingPreset, setEmbeddingPreset] = useState('lexical');
  const [error, setError] = useState('');
  const [job, setJob] = useState<Import | null>(null);
  const [busy, setBusy] = useState(false);
  const [drag, setDrag] = useState(false);
  const [retryJob, setRetryJob] = useState(0);
  const fileInput = useRef<HTMLInputElement>(null);
  const readyRef = useRef(onReady);
  readyRef.current = onReady;

  useEffect(() => {
    if (!job?.id || job.status === 'failed' || job.status === 'ready') return;
    let live = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const result = await api<Import>(`/imports/${job.id}`);
        if (!live) return;
        setJob(result);
        if (result.status === 'ready') { readyRef.current(result); return; }
        if (result.status === 'failed') { setError(result.message); setBusy(false); return; }
        timer = setTimeout(poll, 600);
      } catch (e) { if (live) { setError((e as Error).message); setBusy(false); } }
    };
    void poll();
    return () => { live = false; clearTimeout(timer); };
  }, [job?.id, retryJob]);

  function choose(candidate?: File) {
    setError('');
    if (!candidate) return;
    if (!candidate.name.toLowerCase().endsWith('.csv')) { setError('Choose a .csv export from Jira.'); return; }
    if (candidate.size > 30 * 1024 * 1024 || !candidate.size) { setError('Choose a nonempty CSV up to 30 MB.'); return; }
    setFile(candidate);
    setJob(null);
  }
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!file || busy) return;
    setBusy(true); setError(''); setJob(null);
    try {
      const body = new FormData(); body.append('file', file); body.append('prepare_agent', String(prepareAgent)); body.append('embedding_preset', embeddingPreset);
      const result = await api<{ id: string }>('/imports', { method: 'POST', body });
      setJob({ id: result.id, status: 'queued', progress: 0, message: 'CSV uploaded; waiting to process' } as Import);
    } catch (e) { setError((e as Error).message); setBusy(false); }
  }

  return <div className="welcome">
    <aside className="welcome-story"><Brand /><div className="welcome-copy"><span className="eyebrow light">A CLEARER VIEW OF YOUR WORK</span><h1>From Jira export<br />to project insight.</h1><p>See the big picture. Find the details.<br />Know where your next sprint stands.</p><div className="illustration" aria-hidden="true"><div className="mock-top"><span /><span /><span /></div><div className="mock-metrics"><div /><div /><div /></div><div className="mock-chart">{[40, 68, 52, 87, 70, 98, 78, 115, 96].map((height, i) => <i key={i} style={{ height }} />)}</div><div className="mock-caption"><span /><span /></div></div></div><div className="welcome-footer"><ShieldCheck size={16} /> Runs locally. Your project stays with you.</div></aside>
    <main className="upload-main"><div className="upload-top">AGILEPLANNER <ThemeToggle /></div><div className="upload-content">
      {busy ? <div className="processing" aria-live="polite"><span className="upload-symbol"><LoaderCircle className="spin" size={32} /></span><span className="eyebrow">CONNECTING THE DOTS</span><h2>Making sense of your project.</h2><p>{job?.message || 'Uploading your CSV to the local server…'}</p><progress max={100} value={job?.progress || undefined} aria-label="Import progress" /><div className="processing-steps"><span><Check size={15} /> CSV selected</span><span><LoaderCircle className="spin" size={15} /> Processing issues</span><span>Analytics ready</span></div><p className="muted small">Large exports can take a moment. Keep this page open.</p></div> : <>
        <span className="upload-symbol"><FileSpreadsheet size={30} /></span><span className="eyebrow">LET’S START WITH YOUR DATA</span><h2>Plan with a<br />clearer picture.</h2><p className="upload-description">Upload a Jira CSV export to explore your issues, workflow, and sprints in one place.</p>
        <form onSubmit={submit}><div className={`dropzone ${drag ? 'dragging' : ''}`} onDragOver={e => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={e => { e.preventDefault(); setDrag(false); choose(e.dataTransfer.files[0]); }}><Upload size={26} /><strong>{file ? file.name : 'Drop your Jira CSV here'}</strong><span>{file ? `${(file.size / 1024 / 1024).toFixed(1)} MB · Ready to import` : 'or choose a file from your computer'}</span><button type="button" className="button secondary" onClick={() => fileInput.current?.click()}>{file ? 'Choose another file' : 'Browse files'}</button><input ref={fileInput} type="file" accept=".csv,text/csv" aria-label="Jira CSV file" onChange={e => choose(e.target.files?.[0])} hidden /><small>UTF-8 CSV · Up to 30 MB · Extra columns welcome</small></div>
          {error && <ErrorMessage message={error} />}
          {job && job.status !== 'failed' && error && <button type="button" className="text-button" onClick={() => { setBusy(true); setError(''); setRetryJob(v => v + 1); }}>Check import again</button>}
          <EmbeddingChoice value={embeddingPreset} onChange={setEmbeddingPreset} />
          <label className="checkbox"><input type="checkbox" checked={prepareAgent} onChange={e => setPrepareAgent(e.target.checked)} /> Prepare the Sprint Agent index after import</label><p className="small muted">Optional. Your model choice is saved with this import; you can prepare retrieval from the chat later.</p><button className="button primary upload-submit" disabled={!file}>Explore my project <ArrowRight size={18} /></button>
        </form><p className="muted small">No Jira export yet? Start with our fictional 100-ticket software project.</p><div className="demo-actions"><button type="button" className="text-button" onClick={async () => { try { const response = await fetch('/api/demo.csv'); if (!response.ok) throw new Error('Demo export is unavailable. Try again.'); choose(new File([await response.blob()], 'agileplanner-demo.csv', { type: 'text/csv' })); } catch (e) { setError((e as Error).message); } }}>Try the fictional 100-ticket demo</button><a href="/api/demo.csv" download>Download demo CSV</a></div><div className="upload-requirements"><CircleHelp size={16} /><span>Required columns: Issue key, Summary, Status, and Issue Type. Common Jira header aliases are supported. Additional columns are preserved and can be explored after import. <a href="/api/csv-schema" target="_blank" rel="noreferrer">View recognized headers</a></span></div>
        {onBack && <button className="text-button" onClick={onBack}><ChevronLeft size={16} /> Back to dashboard</button>}
      </>}
    </div><div className="upload-bottom">Built for a better project conversation.</div></main><AgentChat />
  </div>;
}

function BarChart({ data, types = false, categories = false }: { data: Split; types?: boolean; categories?: boolean }) {
  const max = Math.max(...data.map(i => i.count), 1);
  return <div className="bar-chart" role="img" aria-label={`Issues by status. ${data.map(i => `${i.name}: ${i.count}`).join(', ')}`}>
    {data.map((item, i) => <div className="bar-row" key={item.name}><span title={item.name}>{item.name}</span><div className="bar-track"><div style={{ width: `${item.count / max * 100}%`, background: chartColor(item.name, i, types, categories), minWidth: item.count ? 2 : 0 }} /></div><strong>{number(item.count)}</strong></div>)}
  </div>;
}
function Donut({ data, label = 'issues', types = false, categories = false }: { data: Split; label?: string; types?: boolean; categories?: boolean }) {
  const total = data.reduce((sum, i) => sum + i.count, 0);
  let position = 0;
  const stops = data.map((i, index) => { const from = position; position += i.count / (total || 1) * 100; return `${chartColor(i.name, index, types, categories)} ${from}% ${position}%`; });
  return <div className="donut-layout"><div className="donut" style={{ background: total ? `conic-gradient(${stops.join(',')})` : 'var(--line)' }} role="img" aria-label={data.map(i => `${i.name}: ${i.count}`).join(', ') || 'No issues'}><div><strong>{number(total)}</strong><span>{label}</span></div></div><div className="legend">{data.map((i, index) => <div key={i.name}><i style={{ background: chartColor(i.name, index, types, categories) }} /><span>{i.name}</span><strong>{number(i.count)}</strong><small>{total ? Math.round(i.count / total * 100) : 0}%</small></div>)}{!total && <span className="muted">No issues in this view.</span>}</div></div>;
}
function MetricCards({ metrics, stages, sprint = false, selected = '', onSelect, includeTotal = true, groupLabel, categoryCards = false }: { metrics: Metrics; stages: WorkflowStage[]; sprint?: boolean; selected?: string; onSelect?: (stage: string) => void; includeTotal?: boolean; groupLabel?: string; categoryCards?: boolean }) {
  const cards = [...(includeTotal ? [{ id: '', label: 'Total issues', count: metrics.total, statuses: [] as string[], color: undefined as string | undefined }] : []), ...stages.map(s => categoryCards ? { ...s, color: categoryColor(s.label) } : s)];
  return <div className="metrics status-metrics" role="group" aria-label={groupLabel || (sprint ? 'Sprint metric filters' : 'Project metrics')}>{cards.map(({ id, label, count, statuses, color }) => {
    const content = <><div><span>{label}</span></div><strong>{number(count)}</strong><small>{!id ? sprint ? 'All issues in this sprint' : 'All issues in this project view' : categoryCards ? 'From CSV Status Category' : statuses.length > 1 ? `${statuses.length} statuses combined` : 'Discovered status'}</small></>;
    return onSelect ? <button key={id} style={color ? { backgroundColor: `${color}14`, borderTopColor: color, borderTopWidth: 3 } : undefined} className={`metric metric-button ${selected === id ? 'metric-selected' : ''}`} aria-label={id ? `Show ${label} issues` : 'Show all issues'} aria-pressed={selected === id} title={statuses.join(', ')} onClick={() => onSelect(id)}>{content}</button> : <article className="metric" style={color ? { backgroundColor: `${color}14`, borderTopColor: color, borderTopWidth: 3 } : undefined} key={id} title={statuses.join(', ')}>{content}</article>;
  })}</div>;
}

function IssueDrawer({ dataset, issueKey, onClose, onNavigate, onAttach }: { dataset: string; issueKey: string; onClose: () => void; onNavigate: (key: string) => void; onAttach: (key: string, title: string) => void }) {
  const [issue, setIssue] = useState<IssueDetail | null>(null);
  const [error, setError] = useState('');
  const [fieldSearch, setFieldSearch] = useState('');
  const [empty, setEmpty] = useState(false);
  const [originalValues, setOriginalValues] = useState(false);
  const [retry, setRetry] = useState(0);
  const panel = useRef<HTMLDivElement>(null);
  useBackLayer(true, onClose, panel);
  const closeRef = useRef(onClose); closeRef.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    panel.current?.focus();
    const handler = (e: KeyboardEvent) => {
      if (!panel.current?.contains(document.activeElement)) return;
      if (e.key === 'Escape') closeRef.current();
      if (e.key !== 'Tab') return;
      const nodes = panel.current?.querySelectorAll<HTMLElement>('button, input, select, textarea, summary, [tabindex="0"]');
      if (!nodes?.length) return;
      const first = nodes[0], last = nodes[nodes.length - 1];
      if (e.shiftKey && (document.activeElement === first || document.activeElement === panel.current)) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', handler);
    return () => { document.body.style.overflow = overflow; document.removeEventListener('keydown', handler); previous?.focus(); };
  }, []);
  useEffect(() => {
    let live = true;
    setIssue(null); setError(''); setFieldSearch(''); setEmpty(false); setOriginalValues(false); panel.current?.scrollTo(0, 0); panel.current?.focus();
    api<IssueDetail>(`/datasets/${dataset}/issues/${encodeURIComponent(issueKey)}`).then(i => { if (live) setIssue(i); }).catch(e => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [dataset, issueKey, retry]);
  return <div className="drawer-backdrop" onClick={onClose}><div className="drawer ticket-screen" ref={panel} role="dialog" aria-modal="true" aria-labelledby="issue-title" tabIndex={-1} onClick={e => e.stopPropagation()}><div className="drawer-top"><button className="button secondary" onClick={onClose}><ChevronLeft size={16} /> Back to workspace</button><span className="eyebrow">ISSUE DETAILS / {issueKey}</span><button className="icon-button" aria-label="Close issue details" onClick={onClose}><X size={22} /></button></div>
    {error && <><ErrorMessage message={error} /><button className="button secondary" onClick={() => setRetry(r => r + 1)}>Try again</button></>}
    {!issue && !error && <p className="loading-inline"><LoaderCircle className="spin" /> Loading issue…</p>}
    <h2 id="issue-title">{issue?.summary || issueKey}</h2>
    {issue && <><button className="button secondary ask-agent" onClick={() => onAttach(issue.key, issue.summary)}><Sparkles size={16} /> Ask Sprint Agent</button><div className="issue-tags"><Status name={issue.status} /><TypeBadge name={issue.type} /><ParentBadge issue={issue} /><span className="type-tag">{issue.priority || 'Unspecified priority'}</span></div><dl className="issue-facts">{[['Project', `${issue.project_name} (${issue.project_key})`], ['Assignee', issue.assignee || 'Unassigned'], ['Reporter', issue.reporter || 'Not provided'], ['Sprints', issue.sprints.join(', ') || 'Unscheduled'], ['Story points', issue.points ?? 'Not provided'], ['Original estimate (hours)', issue.original_seconds == null ? 'Not provided' : number(issue.original_seconds / 3600)], ['Remaining estimate (hours)', issue.remaining_seconds == null ? 'Not provided' : number(issue.remaining_seconds / 3600)], ['Time spent (hours)', issue.spent_seconds == null ? 'Not provided' : number(issue.spent_seconds / 3600)], ['Resolution', issue.resolution || 'Not provided'], ['Created', issue.created || 'Not provided'], ['Updated', issue.updated || 'Not provided'], ['Resolved', issue.resolved || 'Not provided']].map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}</dl><section className="issue-relations" aria-label="Issue relationships"><h3>Related work</h3>{issue.hierarchy_warning && <p className="muted small">{issue.hierarchy_warning}</p>}{issue.has_parent && <div><span className="eyebrow">PARENT</span>{issue.parent ? <button className="relation-link" title={issue.parent.key} onClick={() => onNavigate(issue.parent!.key)}><span>{issue.parent.summary}</span><TypeBadge name={issue.parent.type} /></button> : <p className="muted" title={issue.parent_reference}>{issue.parent_title || (issue.parent_reference_problem === 'ambiguous' ? 'Ambiguous parent reference' : 'Parent ticket not included in this export')}</p>}</div>}{issue.children.length > 0 && <div><span className="eyebrow">{issue.children.length} DIRECT CHILD ISSUES · ALL SPRINTS</span>{issue.children.map(child => <button className="relation-link" title={child.key} key={child.key} onClick={() => onNavigate(child.key)}><span>{child.summary}</span><TypeBadge name={child.type} /></button>)}</div>}{!issue.has_parent && !issue.children.length && <p className="muted small">No parent or children found in exported relationship fields.</p>}</section><section className="issue-description"><h3>Description</h3><p>{issue.description || 'No description in this export.'}</p></section><FeatureAnalysis key={issue.key} dataset={dataset} request={{ kind: 'ticket', key: issue.key }} onTicket={onNavigate} /><section className="raw-fields"><h3>All exported fields <span>{Object.keys(issue.fields).length}</span></h3><p className="muted small">Repeated values, comments, links, and attachments are preserved as exported. Dates retain Jira’s original format.</p><label className="search-box"><Search size={17} /><input aria-label="Search exported fields" placeholder="Find a field or value…" value={fieldSearch} onChange={e => setFieldSearch(e.target.value)} /></label><label className="checkbox"><input type="checkbox" checked={originalValues} onChange={e => setOriginalValues(e.target.checked)} /> Show original CSV values</label><label className="checkbox"><input type="checkbox" checked={empty} onChange={e => setEmpty(e.target.checked)} /> Include empty fields</label>{Object.entries(issue.fields).filter(([name, values]) => (empty || values.some(v => v.trim())) && `${name} ${values.join(' ')} ${issue.display_fields?.[name]?.flat().map(p => p.text).join(' ') || ''}`.toLowerCase().includes(fieldSearch.toLowerCase())).map(([name, values]) => <details key={name}><summary>{name}<span>{values.filter(v => v.trim()).length} value(s)</span></summary>{values.map((value, i) => <div className="exported-value" key={i}>{originalValues || !issue.display_fields?.[name]?.[i] ? <pre>{value || '(empty)'}</pre> : issue.display_fields[name][i].map((part, index) => part.key ? <button className="reference-title" key={index} title={part.key} onClick={() => onNavigate(part.key!)}>{part.text}</button> : <span key={index} className={part.reason ? 'unresolved-reference' : ''} title={part.reference}>{part.text}</span>)}</div>)}</details>)}</section></>}
  </div></div>;
}

function Workspace({ dataset, onUpload, onResumeConversation }: { dataset: Import; onUpload: () => void; onResumeConversation: (dataset: string, session: string) => Promise<void> }) {
  const [attachment, setAttachment] = useState<Attachment>();
  const [agentOpenRequest, setAgentOpenRequest] = useState(0);
  const [planningScope, setPlanningScope] = useState<'project' | 'sprint' | null>(null);
  const hashView = () => window.location.hash === '#backlog' ? 'backlog' : window.location.hash === '#sprint' ? 'sprint' : 'overview';
  const [view, setView] = useState<'overview' | 'sprint' | 'backlog'>(hashView);
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<string | null>(null);
  const [sprint, setSprint] = useState<string | null>(null);
  const [activeSprint, setActiveSprint] = useState('');
  const [data, setData] = useState<Dashboard | null>(null);
  const [issues, setIssues] = useState<IssuePage | null>(null);
  const [query, setQuery] = useState('');
  const [debounced, setDebounced] = useState('');
  const [status, setStatus] = useState('');
  const [priority, setPriority] = useState('');
  const [type, setType] = useState('');
  const [resolution, setResolution] = useState('');
  const [relationship, setRelationship] = useState('');
  const [fieldFilter, setFieldFilter] = useState<FieldFilter>(null);
  const [page, setPage] = useState(1);
  const [stage, setStage] = useState('');
  const [category, setCategory] = useState('');
  const [showWorkflow, setShowWorkflow] = useState(false);
  const [detail, setDetail] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [listError, setListError] = useState('');
  const [retry, setRetry] = useState(0);
  const [notes, setNotes] = useState(false);
  const [tableBusy, setTableBusy] = useState(false);
  const base = `/datasets/${dataset.id}`;
  useEffect(() => {
    const navigate = () => {
      setView(hashView());
      setShowWorkflow(false); setDetail(null);
      window.scrollTo({ top: 0 });
    };
    window.addEventListener('hashchange', navigate);
    return () => window.removeEventListener('hashchange', navigate);
  }, []);
  function navigate(next: 'overview' | 'sprint' | 'backlog') {
    setView(next); setShowWorkflow(false); setDetail(null);
    window.location.hash = next;
    window.scrollTo({ top: 0 });
  }


  useEffect(() => {
    let live = true;
    setError('');
    api<Project[]>(`${base}/projects`).then(result => { if (live) { setProjects(result); const savedProject = read(`sprintlens.project.${dataset.id}`); setProject(current => current ?? (result.some(p => p.key === savedProject) ? savedProject : '') ?? ''); } }).catch(e => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [base, retry]);
  useEffect(() => { const timer = setTimeout(() => setDebounced(query), 250); return () => clearTimeout(timer); }, [query]);
  useEffect(() => {
    if (project === null) return;
    let live = true;
    setError(''); setData(null);
    api<Dashboard>(`${base}/analytics?${params({ project, sprint })}`).then(result => {
      if (!live) return;
      if (sprint === null) {
        const saved = read(`sprintlens.active.${dataset.id}.${project}`) || '';
        const valid = result.sprints.some(s => s.name === saved) ? saved : '';
        setActiveSprint(valid);
        setSprint(valid || result.suggested_sprint || '');
        return;
      }
      setData(result);
    }).catch(e => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [base, dataset.id, project, sprint, retry]);
  useEffect(() => {
    if (view !== 'sprint' || project === null || sprint === null) return;
    let live = true;
    setTableBusy(true); setIssues(null); setListError('');
    api<IssuePage>(`${base}/issues?${params({ project, sprint, q: debounced, status, priority, issue_type: type, stage, category_id: category, resolution_id: resolution, relationship, field: fieldFilter?.field, field_value: fieldFilter?.value, field_missing: fieldFilter?.missing ? 'true' : undefined, page })}`).then(result => { if (live) setIssues(result); }).catch(e => { if (live) setListError(e.message); }).finally(() => { if (live) setTableBusy(false); });
    return () => { live = false; };
  }, [base, view, project, sprint, debounced, status, priority, type, stage, category, resolution, relationship, fieldFilter, page, retry]);

  function clearFilters() { setQuery(''); setDebounced(''); setStatus(''); setPriority(''); setType(''); setStage(''); setCategory(''); setResolution(''); setRelationship(''); setFieldFilter(null); setPage(1); }
  function toggleWorkflow() { setShowWorkflow(v => !v); window.scrollTo({ top: 0, behavior: 'smooth' }); }
  function changeSprint(value: string) { setSprint(value); clearFilters(); }
  const selectedProject = projects.find(p => p.key === project);
  const sprintName = sprint === '__unscheduled__' ? 'Unscheduled issues' : sprint || 'All issues';
  const designation = sprint && sprint === activeSprint ? 'Marked active by you' : sprint && sprint === data?.suggested_sprint ? 'Latest named sprint in export' : 'Selected sprint view';

  return <div className="workspace"><aside className="sidebar"><Brand /><span className="sidebar-label">WORKSPACE</span><nav aria-label="Workspace"><a href="#overview" className={`nav-item ${view === 'overview' ? 'selected' : ''}`} aria-current={view === 'overview' ? 'page' : undefined} onClick={e => { e.preventDefault(); navigate('overview'); }}><LayoutDashboard size={18} /> Overview</a><a href="#sprint" className={`nav-item ${view === 'sprint' ? 'selected' : ''}`} aria-current={view === 'sprint' ? 'page' : undefined} onClick={e => { e.preventDefault(); navigate('sprint'); }}><FolderKanban size={18} /> Sprint explorer</a><a href="#backlog" className={`nav-item ${view === 'backlog' ? 'selected' : ''}`} aria-current={view === 'backlog' ? 'page' : undefined} onClick={e => { e.preventDefault(); navigate('backlog'); }}><BarChart3 size={18} /> Backlog Management</a><button className="nav-item" onClick={() => setAgentOpenRequest(n => n + 1)}><Sparkles size={18} /> Sprint Agent</button></nav><button className="sidebar-help" onClick={() => setNotes(!notes)}><CircleHelp size={17} /> About this data</button><div className="local-badge"><span /> LOCAL WORKSPACE</div></aside>
    <div className="workspace-main"><header className="topbar"><div className="breadcrumbs">Workspace <ChevronRight size={14} /><strong>{view === 'overview' ? 'Overview' : view === 'backlog' ? 'Backlog Management' : 'Sprint explorer'}</strong></div><div className="topbar-actions"><ThemeToggle /><button className="button secondary" aria-expanded={showWorkflow} aria-controls="status-configuration" onClick={toggleWorkflow}>Configure statuses</button><span className="snapshot"><span /> CSV snapshot</span><button className="button secondary" onClick={onUpload}><Upload size={15} /> Import CSV</button></div></header><main className="dashboard">
      <section className="page-heading"><div><span className="eyebrow">{view === 'overview' ? 'PROJECT OVERVIEW' : view === 'backlog' ? 'BACKLOG MANAGEMENT' : 'SPRINT EXPLORER'}</span><h1>{view === 'overview' ? 'Your project, in focus' : view === 'backlog' ? 'Make room for what matters' : 'Your sprint, in focus'}<span>.</span></h1><p>{view === 'overview' ? 'A little less noise. Good decisions start with a clearer picture.' : view === 'backlog' ? 'Define unfinished work, review capacity, and shape a practical plan.' : 'Explore each sprint’s progress, priorities, and tickets.'}</p></div>{view !== 'backlog' && <label className="project-select"><span>PROJECT</span><select aria-label="Project" value={project || ''} onChange={e => { setAttachment(undefined); setProject(e.target.value); save(`sprintlens.project.${dataset.id}`, e.target.value); setSprint(null); setActiveSprint(''); setShowWorkflow(false); clearFilters(); }}><option value="">All projects</option>{projects.map(p => <option key={p.key} value={p.key}>{p.name} ({p.count})</option>)}</select></label>}</section>
      <div className="source-line"><FileSpreadsheet size={14} /><span>{dataset.filename}</span><span className="divider">/</span><span>{number(dataset.metadata.issue_count)} imported issues</span><span className="divider">/</span><span>Imported {new Date(dataset.imported_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}</span><button className="text-button" onClick={() => setNotes(!notes)}>Data notes <CircleHelp size={13} /></button></div>
      {notes && <section className="data-notes"><div><strong>Understand this snapshot</strong><button className="icon-button" aria-label="Close data notes" onClick={() => setNotes(false)}><X size={16} /></button></div><ul>{dataset.metadata.warnings.map(w => <li key={w}>{w}</li>)}<li>High-level cards use the CSV’s Status Category values without reclassification. Detailed status display names do not change those totals. Every discovered status has its own detailed card by default. Only saved display names can rename or combine statuses. Give statuses the exact same name to combine their counts. Stage counts sum to Total; raw Jira status values remain unchanged.</li><li>Each issue counts once per project view and once in each sprint it belongs to. Sprint counts may overlap. The latest sprint is suggested by natural name order; this does not establish active state.</li></ul></section>}
      {showWorkflow && <WorkflowEditor key={project} base={base} project={project || undefined} onClose={() => setShowWorkflow(false)} onSaved={() => { setShowWorkflow(false); clearFilters(); setRetry(r => r + 1); }} />}
      {error && <><ErrorMessage message={error} /><button className="button secondary" onClick={() => setRetry(r => r + 1)}>Try again</button></>}
      {!data && !error && <div className="dashboard-loading" role="status"><LoaderCircle className="spin" size={24} /> Loading project analytics…</div>}
      {data && <>
        {view === 'backlog' && <BacklogEstimation projects={projects} requestedScope={planningScope} onScope={setPlanningScope} onProject={key => { setAttachment(undefined); setProject(key); save(`sprintlens.project.${dataset.id}`, key); setSprint(null); setActiveSprint(''); clearFilters(); }} dataset={dataset.id} project={project || ''} sprints={data.sprints} currentSprint={activeSprint || (sprint !== '__unscheduled__' ? sprint : '') || data.suggested_sprint || ''} statuses={data.statuses} onTicket={setDetail} />}
        {view === 'overview' && <section aria-label="Project overview" id="overview-view">
        <span className="eyebrow">HIGH-LEVEL VIEW · STATUS CATEGORY</span>
        <MetricCards metrics={data.overall} stages={data.categories} groupLabel="Project category metrics" categoryCards selected="__overview__" onSelect={value => { clearFilters(); setCategory(value); setSprint(''); navigate('sprint'); }} />
        <TicketFinder dataset={dataset.id} project={project || ''} onOpen={setDetail} />
        <DuplicateTickets dataset={dataset.id} project={project || ''} onOpen={setDetail} />
        <div className="overview-charts"><article className="card"><div className="card-heading"><div><span className="eyebrow">THE BIG PICTURE</span><h2>Where work stands</h2></div><span className="subtle-tag">{selectedProject?.key || 'ALL PROJECTS'}</span></div><p className="card-subtitle">Issues by the CSV’s Status Category</p><BarChart data={data.categories.map(s => ({ name: s.label, count: s.count }))} categories /></article><article className="card"><div className="card-heading"><div><span className="eyebrow">WORK BREAKDOWN</span><h2>A mix of moving parts</h2></div><BarChart3 size={19} className="muted" /></div><p className="card-subtitle">Issues by type</p><Donut data={data.types} types /></article></div>
<People key={project} base={base} project={project || ''} sprint="" />
<section className="detailed-status-section"><h2>Detailed status breakdown</h2>
        <div className="workflow-summary"><span>{data.workflow.customized_projects ? 'Your status appearance settings are applied' : 'Showing every status discovered in your CSV'}</span></div>
        <MetricCards metrics={data.overall} stages={data.stages} includeTotal={false} selected="__overview__" onSelect={value => { clearFilters(); setStage(value); setSprint(''); navigate('sprint'); }} />
        </section>
        <FieldExplorer base={base} project={project || ''} sprint="" selected={fieldFilter} onSelect={value => {
          if (!value) { setFieldFilter(null); return; }
          clearFilters(); setFieldFilter(value); setSprint(''); navigate('sprint');
        }} />
        </section>}
        {view === 'sprint' && <section aria-label="Sprint explorer">
        <section className="sprint-section" id="sprint-view"><div className="section-heading"><div><span className="eyebrow">SPRINT EXPLORER</span><h2>A closer look at your sprint.</h2><p>Explore the work, priorities, and people behind each iteration.</p></div><div className="sprint-picker"><label><span>SPRINT</span><select aria-label="Sprint" value={sprint || ''} onChange={e => changeSprint(e.target.value)}><option value="">All issues</option><option value="__unscheduled__">Unscheduled issues</option>{data.sprints.map(s => <option key={s.name} value={s.name}>{s.name} ({s.count})</option>)}</select></label></div></div>
          <div className="sprint-caption"><span className="sprint-indicator" /><strong>{sprintName}</strong><span className="subtle-tag">{designation}</span>{sprint && sprint !== '__unscheduled__' && <button className="text-button" onClick={() => { const next = activeSprint === sprint ? '' : sprint; setActiveSprint(next); save(`sprintlens.active.${dataset.id}.${project}`, next); }}>{activeSprint === sprint ? 'Clear active marker' : 'Mark as active'}</button>}<span className="sprint-points">{number(data.sprint.metrics.story_points)} pts <span>· {data.sprint.metrics.estimated_issues}/{data.sprint.metrics.total} with points</span></span></div>
          <div className="people-metrics sprint-people-metrics" role="group" aria-label="Sprint people">
            <article className="card"><span>Total assignees</span><strong>{number(data.sprint.metrics.assignee_count)}</strong><small>Distinct people assigned to sprint tickets</small></article>
            <article className="card"><span>Total reporters</span><strong>{number(data.sprint.metrics.reporter_count)}</strong><small>Distinct people who reported sprint tickets</small></article>
            <article className="card"><span>People involved</span><strong>{number(data.sprint.metrics.people_count)}</strong><small>Unique people across both roles</small></article>
          </div>
          <p className="sprint-people-note">Counts use nonblank names on tickets in this sprint view at export time. People involved counts someone once even when they are both an assignee and a reporter.</p>
          <MetricCards metrics={data.sprint.metrics} stages={data.sprint.categories} sprint groupLabel="Sprint category filters" categoryCards selected={stage ? '__stage__' : category} onSelect={value => { clearFilters(); setCategory(value); }} />
          <section className="sprint-chart-section" aria-label="Sprint charts"><h3>Charts & team</h3><p className="card-subtitle">Progress, priorities, ticket types, and the people behind this sprint.</p><div className="sprint-charts"><article className="card compact-card"><div className="card-heading"><h3>Status categories</h3></div><Donut data={data.sprint.categories.map(c => ({ name: c.label, count: c.count }))} categories /></article><SprintRoles base={base} project={project || ''} sprint={sprint || ''} /><article className="card compact-card"><div className="card-heading"><h3>Priority breakdown</h3><span className="muted small">What needs attention</span></div><Donut data={data.sprint.priorities} /></article><article className="card compact-card"><div className="card-heading"><h3>Issue types</h3><span className="muted small">The shape of this sprint</span></div><BarChart data={data.sprint.types} types /></article></div></section>
          <h3 className="status-breakdown-title">Detailed statuses</h3>
          <MetricCards metrics={data.sprint.metrics} stages={data.sprint.stages} sprint includeTotal={false} selected={category ? '__category__' : stage} onSelect={value => { clearFilters(); setStage(value); }} />
          <p className="status-filter-hint">Click any status card to filter the tickets below. Zero-count cards keep every project status visible in each sprint.</p>
          <div className="estimate-grid" aria-label="Sprint estimates">{[
            ['Story points', data.sprint.metrics.story_points, data.sprint.metrics.estimated_issues, 'pts'],
            ['Original estimate', data.sprint.metrics.original_hours, data.sprint.metrics.time_estimated_issues, 'h'],
            ['Remaining estimate', data.sprint.metrics.remaining_hours, data.sprint.metrics.remaining_time_issues, 'h'],
            ['Time spent', data.sprint.metrics.spent_hours, data.sprint.metrics.spent_time_issues, 'h'],
          ].map(([label, value, coverage, unit]) => <article className="card estimate-card" key={label}><span>{label}</span><strong>{coverage ? `${number(value as number)} ${unit}` : '—'}</strong><small>{coverage}/{data.sprint.metrics.total} issues with values</small></article>)}</div>
          <p className="muted small">Points and time are separate measurements. Recognized Jira time fields are converted from seconds to hours. Missing values are excluded, never treated as estimated work.</p>

        </section>
        <section className="card issue-section" id="issues"><div className="card-heading"><div><h2>The work behind the numbers <span className="count-badge">{issues?.total ?? '…'}</span></h2><p className="card-subtitle">{sprintName} · Select an issue to see the full picture</p></div></div><div className="issue-filters"><label className="search-box"><Search size={17} /><input aria-label="Search issues" placeholder="Search issue, summary, or assignee…" value={query} onChange={e => { setQuery(e.target.value); setPage(1); }} /></label><select aria-label="Filter status" value={status} onChange={e => { setStatus(e.target.value); setPage(1); }}><option value="">All statuses</option>{data.sprint.statuses.map(s => <option key={s.name}>{s.name}</option>)}</select><select aria-label="Filter priority" value={priority} onChange={e => { setPriority(e.target.value); setPage(1); }}><option value="">All priorities</option>{data.sprint.priorities.map(s => <option key={s.name}>{s.name}</option>)}</select><select aria-label="Filter type" value={type} onChange={e => { setType(e.target.value); setPage(1); }}><option value="">All types</option>{data.sprint.types.map(s => <option key={s.name}>{s.name}</option>)}</select><select aria-label="Filter resolution" value={resolution} onChange={e => { setResolution(e.target.value); setPage(1); }}><option value="">All resolutions</option>{data.sprint.resolutions.map(r => <option key={r.id} value={r.id}>{r.label} ({r.count})</option>)}</select><select aria-label="Filter relationship" value={relationship} onChange={e => { setRelationship(e.target.value); setPage(1); }}><option value="">All relationships</option><option value="parents">Parents with children</option><option value="children">Issues with a parent</option><option value="standalone">Standalone issues</option></select>{(query || status || priority || type || stage || category || resolution || relationship || fieldFilter) && <button className="text-button" onClick={clearFilters}>Reset</button>}</div>
          {fieldFilter && <div className="selected-filter" role="status">{fieldFilter.field}: {fieldFilter.missing ? 'Not provided (blank)' : fieldFilter.label || fieldFilter.value}<button className="text-button" onClick={() => { setFieldFilter(null); setPage(1); }}>Clear field filter</button></div>}
          {(stage || category) && <div className="selected-filter" role="status">Showing {category ? data.sprint.categories.find(g => g.id === category)?.label : data.sprint.stages.find(g => g.id === stage)?.label} issues in {sprintName}. Additional filters narrow this list.<button className="text-button" onClick={clearFilters}>Clear selection</button></div>}
          {listError && <><ErrorMessage message={listError} /><button className="button secondary" onClick={() => setRetry(r => r + 1)}>Retry issues</button></>}
          <div className="table-wrap" aria-busy={tableBusy}><table><thead><tr><th>ISSUE</th><th>SUMMARY</th><th>STATUS</th><th>PRIORITY</th><th>ASSIGNEE</th><th>POINTS</th><th aria-label="Open details" /></tr></thead><tbody>{issues?.items.map(i => <tr key={i.key} className={i.is_parent ? 'parent-row' : ''} onClick={() => setDetail(i.key)}><td><button className="issue-key" onClick={e => { e.stopPropagation(); setDetail(i.key); }}>{i.key}</button><span className="table-type"><TypeBadge name={i.type} /></span></td><td className="summary-cell"><span>{i.summary}</span><div className="row-relationships"><ParentBadge issue={i} />{i.has_parent && <span className="child-reference" title={i.parent_reference}>↳ {i.parent_title || (i.parent_reference_problem === 'ambiguous' ? 'Ambiguous parent reference' : 'Parent ticket unavailable in export')}</span>}</div></td><td><Status name={i.status} /></td><td><span className={`priority priority-${i.priority.toLowerCase()}`}><i />{i.priority || 'Unspecified'}</span></td><td><span className="assignee">{i.assignee && <span className="avatar">{i.assignee.split(' ').map(s => s[0]).slice(0, 2).join('')}</span>}{i.assignee || 'Unassigned'}</span></td><td>{i.points ?? '—'}</td><td><ArrowUpRight size={15} className="muted" /></td></tr>)}</tbody></table>{tableBusy && <div className="table-empty" role="status"><LoaderCircle className="spin" size={20} /> Loading issues…</div>}{issues && !issues.total && <div className="table-empty"><Search size={24} /><strong>No issues in this view</strong><span>Try another sprint or adjust your filters.</span></div>}</div><div className="pagination"><span>{issues?.total ? `${(page - 1) * 20 + 1}–${Math.min(page * 20, issues.total)} of ${number(issues.total)} issues` : '0 issues'}</span><div><button className="icon-button" aria-label="Previous page" disabled={page <= 1 || tableBusy} onClick={() => setPage(p => p - 1)}><ChevronLeft size={17} /></button><span>Page {page} of {Math.max(1, Math.ceil((issues?.total || 0) / 20))}</span><button className="icon-button" aria-label="Next page" disabled={!issues || page * 20 >= issues.total || tableBusy} onClick={() => setPage(p => p + 1)}><ChevronRight size={17} /></button></div></div>
        </section></section>}<footer className="dashboard-footer"><Brand /><span>Good decisions start with a clearer picture.</span><span>Snapshot analytics · v0.1</span></footer>
      </>}
    </main></div>{detail && <IssueDrawer dataset={dataset.id} issueKey={detail} onNavigate={setDetail} onClose={() => setDetail(null)} onAttach={(key, title) => { setDetail(null); setAttachment({ key, title, sequence: Date.now() }); }} />}<AgentChat openRequest={agentOpenRequest} key={dataset.id} dataset={dataset.id} project={project || ''} sprint={sprint || ''} activeSprint={activeSprint} page={view} pageTicket={detail || ''} attachment={attachment} onOpenTicket={setDetail} onResumeConversation={onResumeConversation} />
  </div>;
}

export default function App() {
  const [dataset, setDataset] = useState<Import | null>(null);
  const [upload, setUpload] = useState(false);
  const [setup, setSetup] = useState<Import | null>(null);
  const [restoring, setRestoring] = useState(true);
  const [restoreError, setRestoreError] = useState('');
  useEffect(() => {
    const pending = read('sprintlens.setup');
    const id = pending || read('sprintlens.dataset');
    if (!id) {
      let live = true;
      api<{dataset: Import | null}>('/workspace').then(({dataset: saved}) => { if (live && saved?.status === 'ready') { save('sprintlens.dataset', saved.id); setDataset(saved); } }).catch(() => {}).finally(() => { if (live) setRestoring(false); });
      return () => { live = false; };
    }
    let live = true;
    api<Import>(`/imports/${id}`).then(data => { if (live && data.status === 'ready') { if (pending) setSetup(data); else setDataset(data); } }).catch(e => { if (live) { save('sprintlens.dataset',''); save('sprintlens.setup',''); setRestoreError(e.message.includes('not found') ? 'This workspace was cleared. Import an export to begin again.' : e.message); } }).finally(() => { if (live) setRestoring(false); });
    return () => { live = false; };
  }, []);
  const resumeConversation = async (source: string, session: string) => {
    const data = await api<Import>(`/imports/${source}`);
    if (data.status !== 'ready') throw new Error('This CSV snapshot is not ready.');
    save(`sprintlens.chat.${source}`,session); save('sprintlens.chat.open',source); save('sprintlens.dataset',source); save('sprintlens.setup','');
    setSetup(null); setUpload(false); setDataset(data); setRestoreError('');
  };
  if (restoring) return <div className="boot-screen"><Brand /><LoaderCircle className="spin" /><span>Opening your workspace…</span></div>;
  if (setup) return <div className="import-setup"><header><Brand /><span>IMPORT → STATUS SETUP → DASHBOARD</span></header><main><div className="import-discovery"><strong>{number(setup.metadata.issue_count)} issues · {setup.metadata.column_count} column occurrences preserved</strong><p>Recognized: {Object.keys(setup.metadata.recognized_fields || {}).map(role => role.replaceAll('_', ' ')).join(', ') || 'Jira core fields'}.</p>{!!setup.metadata.extra_columns?.length && <p>{setup.metadata.extra_columns.length} additional field(s) preserved: {setup.metadata.extra_columns.join(', ')}. Explore their values on the dashboard.</p>}<details className="import-notes"><summary>Import notes ({setup.metadata.warnings.length})</summary><ul>{setup.metadata.warnings.map(w => <li key={w}>{w}</li>)}</ul></details></div><AgentSetup dataset={setup.id} /><WorkflowEditor base={`/datasets/${setup.id}`} onboarding onSaved={() => { save('sprintlens.dataset', setup.id); save('sprintlens.setup', ''); setDataset(setup); setSetup(null); setRestoreError(''); }} onClose={() => { save('sprintlens.dataset', setup.id); save('sprintlens.setup', ''); setDataset(setup); setSetup(null); setRestoreError(''); }} /></main></div>;
  return <>{restoreError && <div className="restore-note" role="status">Previous workspace could not be restored: {restoreError} <button onClick={() => setRestoreError('')}>Dismiss</button></div>}{!dataset || upload ? <UploadScreen onReady={data => { save('sprintlens.setup', data.id); setSetup(data); setUpload(false); setRestoreError(''); }} onBack={dataset ? () => setUpload(false) : undefined} /> : <Workspace key={dataset.id} dataset={dataset} onUpload={() => setUpload(true)} onResumeConversation={resumeConversation} />}</>;
}
