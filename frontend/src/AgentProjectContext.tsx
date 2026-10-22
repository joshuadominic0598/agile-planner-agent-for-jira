import { useEffect, useState } from 'react';
import { Check, LoaderCircle } from 'lucide-react';
import { api, params } from './api';

type Brief = {
  content: string;
  updated_at: string | null;
  version_number?: number;
  head_version_id?: string;
};
type Project = { key: string; name: string };

export default function AgentProjectContext({ dataset, project }: { dataset: string; project: string }) {
  const [scope, setScope] = useState(project);
  const [projects, setProjects] = useState<Project[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState<Record<string, Brief>>({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const endpoint = `/datasets/${dataset}/agent/project-context?${params({ project: scope })}`;
  useEffect(() => {
    api<Project[]>(`/datasets/${dataset}/projects`)
      .then(setProjects)
      .catch((e) => setError(e.message));
  }, [dataset]);
  useEffect(() => {
    let live = true;
    setLoading(true);
    setError('');
    setNotice('');
    api<Brief>(endpoint)
      .then((data) => {
        if (live) {
          setDrafts((old) => ({ ...old, [scope]: old[scope] ?? data.content }));
          setSaved((old) => ({ ...old, [scope]: data }));
        }
      })
      .catch((e) => {
        if (live) setError(e.message);
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [endpoint, scope]);
  async function save() {
    setSaving(true);
    setError('');
    setNotice('');
    try {
      const value = await api<Brief>(endpoint, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          content: drafts[scope] || '',
          base_version_id: saved[scope]?.head_version_id,
        }),
      });
      setSaved((old) => ({ ...old, [scope]: value }));
      setNotice(
        `Project context saved${value.version_number ? ` as prompt v${value.version_number}` : ''}. The agent will use it for relevant questions.`
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }
  return (
    <details className="agent-project-context">
      <summary>Project context &amp; working agreements</summary>
      <p>
        Give the agent the goals and conventions behind the tickets. Shared guidance applies across this
        export; a project brief adds specifics. Saved text is sent to your selected model with relevant
        questions.
      </p>
      <label>
        Context for
        <select
          aria-label="Project context scope"
          value={scope}
          disabled={saving}
          onChange={(e) => setScope(e.target.value)}>
          <option value="">Whole export · shared guidance</option>
          {projects.map((p) => (
            <option key={p.key} value={p.key}>
              {p.name || p.key} ({p.key})
            </option>
          ))}
        </select>
      </label>
      <label>
        Project brief
        <textarea
          aria-label="Project context prompt"
          rows={7}
          maxLength={12000}
          disabled={loading || saving}
          value={drafts[scope] || ''}
          placeholder={
            'What are we building and why?\nCurrent product/sprint goals and priorities\nWhat do our workflow stages and Done mean?\nHow do we estimate work and define available capacity?\nWorking agreements, team structure and success measures'
          }
          onChange={(e) => {
            setDrafts((old) => ({ ...old, [scope]: e.target.value }));
            setNotice('');
          }}
        />
      </label>
      <small>
        {(drafts[scope] || '').length.toLocaleString()} / 12,000 characters · Kept with this imported
        snapshot.
      </small>
      <p className="muted">
        {saved[scope]?.version_number ? `Active prompt v${saved[scope].version_number}. ` : ''}View, edit and
        compare prompt history in{' '}
        <a href="http://localhost:8013/evaluation" target="_blank" rel="noreferrer">
          Evaluation → Project prompts
        </a>
        .
      </p>
      <div className="agent-context-save">
        <button
          type="button"
          className={`button primary${notice ? ' agent-context-saved' : ''}`}
          disabled={loading || saving}
          aria-busy={saving}
          onClick={() => void save()}>
          {saving ? (
            <LoaderCircle size={16} className="agent-context-spinner" aria-hidden="true" />
          ) : notice ? (
            <Check size={16} aria-hidden="true" />
          ) : null}
          {saving ? 'Saving…' : notice ? 'Saved' : 'Save project context'}
        </button>
        {notice && (
          <p className="agent-context-confirmation" role="status">
            <Check size={18} aria-hidden="true" />
            <span>{notice}</span>
          </p>
        )}
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </details>
  );
}
