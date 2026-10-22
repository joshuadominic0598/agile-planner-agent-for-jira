import { useEffect, useState } from 'react';
import { api, params } from './api';
export type FieldFilter = { field: string; value: string; label?: string; missing: boolean } | null;
type Field = { name: string; populated: number; distinct: number; occurrences: number; chartable: boolean };
type Breakdown = { issues: number; populated: number; multiple_values: boolean; values: { value: string; label?: string; count: number; missing: boolean }[] };
export default function FieldExplorer({ base, project, sprint, selected, onSelect }: { base: string; project: string; sprint: string; selected: FieldFilter; onSelect: (filter: FieldFilter) => void }) {
  const [catalog, setCatalog] = useState<Field[]>([]);
  const [field, setField] = useState('');
  const [data, setData] = useState<Breakdown | null>(null);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let live = true;
    setCatalog([]); setField(''); setError('');
    api<Field[]>(`${base}/fields?${params({ project })}`).then(result => { if (live) setCatalog(result); }).catch(e => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [base, project, retry]);
  useEffect(() => {
    let live = true;
    setData(null); setError('');
    if (field) api<Breakdown>(`${base}/field-analytics?${params({ field, project, sprint })}`).then(result => { if (live) setData(result); }).catch(e => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [base, project, sprint, field, retry]);
  const current = catalog.find(f => f.name === field);
  const max = Math.max(1, ...data?.values.map(v => v.count) || []);
  return <section className="card field-explorer" aria-label="Exported field explorer"><div className="card-heading"><div><span className="eyebrow">YOUR PROJECT’S OWN FIELDS</span><h3>Explore an exported field</h3></div><select aria-label="Explore field" value={field} onChange={e => { setField(e.target.value); onSelect(null); }}><option value="">Choose a field…</option>{catalog.map(f => <option key={f.name} value={f.name} disabled={!f.chartable}>{f.name} ({f.distinct} values){!f.chartable ? ' · details only' : ''}</option>)}</select></div><p className="card-subtitle">Exact value counts across this project view. Choose any bar to open matching tickets in Sprint explorer with All issues selected. Long text, empty fields, and fields with over 50 distinct values stay in issue details.</p>
    {error && <div className="error" role="alert">{error} <button className="text-button" onClick={() => setRetry(v => v + 1)}>Retry fields</button></div>}
    {!field && <p className="muted small">{catalog.length} exported fields preserved. No meaning or measurement unit is assumed for custom fields.</p>}
    {field && !data && !error && <p role="status">Loading field values…</p>}
    {data && <><p className="muted small">{data.populated} of {data.issues} issues have a value{current && current.occurrences > 1 ? ` · ${current.occurrences} repeated columns` : ''}. {data.multiple_values ? 'An issue can appear in several values; totals may overlap.' : 'Each issue appears in one value, including blanks.'}</p><div className="field-bars">{data.values.map(item => <button key={`${item.missing}:${item.value}`} className={`field-bar ${selected?.field === field && selected.value === item.value && selected.missing === item.missing ? 'active' : ''}`} aria-pressed={selected?.field === field && selected.value === item.value && selected.missing === item.missing} aria-label={`Filter ${field}: ${item.missing ? 'Not provided (blank)' : item.label || item.value}`} onClick={() => onSelect({ field, value: item.value, label: item.label, missing: item.missing })}><span className="field-value">{item.missing ? 'Not provided (blank)' : item.label || item.value}</span><span className="bar-track"><i style={{ width: `${item.count / max * 100}%` }} /></span><strong>{item.count.toLocaleString()}</strong></button>)}</div>{!data.issues && <p className="muted">No issues in this project view.</p>}</>}
  </section>;
}
