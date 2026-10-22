import { useEffect, useState } from 'react';
import { ArrowDown, ArrowUp, LoaderCircle, X } from 'lucide-react';
import { api, params } from './api';
import type { Project, Workflow } from './types';

type SetupProject = Project & { workflow: Workflow };

export default function WorkflowEditor({ base, project, onSaved, onClose, onboarding = false }: { base: string; project?: string; onSaved: () => void; onClose: () => void; onboarding?: boolean }) {
  const [projects, setProjects] = useState<SetupProject[] | null>(null);
  const [originals, setOriginals] = useState<SetupProject[]>([]);
  const [selected, setSelected] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [retry, setRetry] = useState(0);
  const url = `${base}/workflows?${params({ project })}`;
  useEffect(() => {
    let live = true;
    setError(''); setProjects(null);
    api<{ projects: SetupProject[] }>(url).then(data => { if (live) { setProjects(data.projects); setOriginals(data.projects); setSelected(data.projects[0]?.key || ''); } }).catch(e => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [url, retry]);
  const current = projects?.find(p => p.key === selected);
  const config = current?.workflow;
  function update(change: (workflow: Workflow) => Workflow) {
    setProjects(existing => existing?.map(p => p.key === selected ? { ...p, workflow: change(p.workflow) } : p) || null);
  }
  function rename(status: string, label: string) {
    update(w => {
      const peer = w.order.find(s => s !== status && w.assignments[s].trim() === label.trim());
      return { ...w, assignments: { ...w.assignments, [status]: label }, colors: { ...w.colors, [status]: peer ? w.colors[peer] : w.colors[status] } };
    });
  }
  function color(status: string, value: string) {
    update(w => ({ ...w, colors: Object.fromEntries(w.order.map(s => [s, w.assignments[s].trim() === w.assignments[status].trim() ? value : w.colors[s]])) }));
  }
  function move(status: string, direction: number) {
    update(w => {
      const order = [...w.order], from = order.indexOf(status), to = from + direction;
      if (to < 0 || to >= order.length) return w;
      [order[from], order[to]] = [order[to], order[from]];
      return { ...w, order };
    });
  }
  function reset() {
    update(w => ({ ...w, assignments: Object.fromEntries(w.statuses.map(s => [s.name, s.name])) }));
  }
  async function save(original = false) {
    if (!projects) return;
    setSaving(true); setError('');
    try {
      await api(`${base}/workflows`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ projects: Object.fromEntries(projects.map(p => [p.key, {
        assignments: original ? Object.fromEntries(p.workflow.statuses.map(s => [s.name, s.name])) : p.workflow.assignments,
        order: original ? originals.find(o => o.key === p.key)!.workflow.order : p.workflow.order,
        colors: original ? originals.find(o => o.key === p.key)!.workflow.colors : p.workflow.colors,
      }])) }) });
      onSaved();
    } catch (e) { setError((e as Error).message); }
    finally { setSaving(false); }
  }
  const preview = new Map<string, { count: number; color: string }>();
  config?.order.forEach(status => {
    const name = config.assignments[status].trim(), count = config.statuses.find(s => s.name === status)!.count;
    if (name) preview.set(name, { count: (preview.get(name)?.count || 0) + count, color: preview.get(name)?.color || config.colors[status] });
  });
  return <section className="card workflow-editor" aria-label="Status configuration" id="status-configuration" tabIndex={-1}>
    <div className="card-heading"><div><span className="eyebrow">{onboarding ? 'YOUR CSV IS READY' : 'STATUS DISPLAY'}</span><h2>{onboarding ? 'Choose how your statuses appear.' : 'Your statuses, your names.'}</h2></div>{!onboarding && <button className="icon-button" aria-label="Close status configuration" disabled={saving} onClick={onClose}><X size={18} /></button>}</div>
    <p className="card-subtitle">Keep or rename each status, move it into your preferred order, and choose its card color. Give statuses the same name to combine them into one card. Combined cards use the first status’s position and share its color. High-level Status Category totals stay unchanged.</p>
    {error && <div className="error" role="alert">{error}</div>}
    {!projects && !error && <p className="loading-inline"><LoaderCircle className="spin" /> Discovering statuses in your CSV…</p>}
    {!projects && error && <button className="button secondary" onClick={() => setRetry(v => v + 1)}>Retry status setup</button>}
    {projects && config && <fieldset disabled={saving} className="workflow-fieldset"><legend className="sr-only">Status appearance</legend>
      <div className="status-setup-toolbar">{projects.length > 1 ? <label><span>PROJECT</span><select aria-label="Configure project" value={selected} onChange={e => setSelected(e.target.value)}>{projects.map(p => <option key={p.key} value={p.key}>{p.name} ({p.count})</option>)}</select></label> : <strong>{current?.name} · {current?.count.toLocaleString()} issues</strong>}<button className="text-button" onClick={reset}>Restore original names</button></div>
      <div className="status-name-header"><span>DISCOVERED STATUS</span><span>DISPLAY AS / COMBINE INTO</span><span>COLOR</span><span>ORDER</span></div>
      <div className="status-name-list">{config.order.map((name, index) => {
        const status = config.statuses.find(s => s.name === name)!;
        return <div className="status-name-row" key={name}><div><strong>{name}</strong><small>{status.count.toLocaleString()} issues</small></div><label><span className="sr-only">Stage name for {name}</span><input type="text" aria-label={`Stage name for ${name}`} value={config.assignments[name]} onChange={e => rename(name, e.target.value)} placeholder={name} /></label><label className="status-color-picker"><span className="sr-only">Card color for {name}</span><input type="color" aria-label={`Card color for ${name}`} value={config.colors[name]} onChange={e => color(name, e.target.value)} /></label><div className="status-order-buttons"><button className="icon-button" aria-label={`Move ${name} up`} disabled={index === 0} onClick={() => move(name, -1)}><ArrowUp size={16} /></button><button className="icon-button" aria-label={`Move ${name} down`} disabled={index === config.order.length - 1} onClick={() => move(name, 1)}><ArrowDown size={16} /></button></div></div>;
      })}</div>
      <div className="status-card-preview" aria-live="polite"><span>KPI CARD PREVIEW</span><div>{[...preview].map(([name, item]) => <div key={name} style={{ borderColor: item.color, backgroundColor: `${item.color}14` }}><span>{name}</span><strong>{item.count.toLocaleString()}</strong></div>)}</div></div>
      <div className="workflow-actions"><span>{projects.length > 1 ? 'Switch projects to configure each project. Save applies all edits together.' : 'Names, order and colors are saved for this project and used in every sprint.'}</span><button className="button secondary" onClick={() => { if (onboarding) void save(true); else onClose(); }}>{onboarding ? 'Use original statuses' : 'Cancel'}</button><button className="button primary" onClick={() => void save()}>{saving ? 'Saving…' : onboarding ? 'Save & open dashboard' : 'Save status names'}</button></div>
    </fieldset>}
  </section>;
}
