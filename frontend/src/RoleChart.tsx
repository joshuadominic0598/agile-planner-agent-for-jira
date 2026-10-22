import type { Split } from './types';

export default function RoleChart({ data, title = 'People by role', description, onSelect }: { data: Split; title?: string; description: string; onSelect?: (role: string) => void }) {
  const max = Math.max(1, ...data.map(r => r.count));
  return <section className="card people-role-chart" aria-label={title}><h3>{title}</h3><p className="card-subtitle">{description}</p>{data.length ? <div className="role-chart-bars" role={onSelect ? 'group' : 'img'} aria-label={`${title} counts`}>{data.map(a => {
    const content = <><span title={a.name}>{a.name}</span><span className="bar-track"><i style={{ width: `${a.count / max * 100}%` }} /></span><strong>{a.count.toLocaleString()}</strong></>;
    return onSelect ? <button className="role-chart-row role-chart-button" key={a.name} aria-label={`Show people with role ${a.name}`} onClick={() => onSelect(a.name)}>{content}</button> : <div className="role-chart-row" key={a.name}>{content}</div>;
  })}</div> : <p className="muted small">No roles assigned to people in this view yet. Add roles in Overview → Manage people.</p>}</section>;
}
