import { useEffect, useState } from 'react';
import { api, params } from './api';
import RoleChart from './RoleChart';
import type { Split } from './types';

export default function SprintRoles({ base, project, sprint }: { base: string; project: string; sprint: string }) {
  const [data, setData] = useState<{ selected_work_areas: Split; selected_people: number; selected_role_people: number } | null>(null);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let live = true;
    setData(null); setError('');
    api<{ selected_work_areas: Split; selected_people: number; selected_role_people: number }>(`${base}/people?${params({ project, sprint })}`).then(result => { if (live) setData(result); }).catch(e => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [base, project, sprint, retry]);
  if (error) return <section className="card" aria-label="Sprint people by role"><div className="error" role="alert">{error}</div><button className="text-button" onClick={() => setRetry(r => r + 1)}>Retry role chart</button></section>;
  if (!data) return <section className="card" aria-label="Sprint people by role"><p role="status">Loading sprint roles…</p></section>;
  return <RoleChart data={data.selected_work_areas} title="Sprint people by role" description={`${data.selected_role_people} of ${data.selected_people} distinct assignees have assigned roles in this sprint view. Includes active and inactive members. People with several roles appear once in each.`} />;
}
