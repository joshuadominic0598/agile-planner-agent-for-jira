import { useEffect, useState } from 'react';

type Row = Record<string, any>;
async function request(path: string, body?: unknown) {
  const response = await fetch(
    '/api/ops/evaluation/prompts/' + path,
    body
      ? {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        }
      : undefined
  );
  const data = await response.json();
  if (!response.ok)
    throw new Error(typeof data.detail === 'string' ? data.detail : 'Check the project prompt.');
  return data;
}
export function PromptSnapshot({ value }: { value?: Row }) {
  return (
    <details className="prompt-snapshot">
      <summary>
        Project prompt used ·{' '}
        {value ? `v${value.number} · ${value.sha256?.slice(0, 10)}` : 'Not recorded for this historical run'}
      </summary>
      {value?.briefs
        ?.filter((b: Row) => b.content)
        .map((b: Row) => (
          <section key={b.project}>
            <h4>{b.project || 'Whole export · shared guidance'}</h4>
            <pre>{b.content}</pre>
          </section>
        ))}
      {value && !value.briefs?.some((b: Row) => b.content) && (
        <p>No project guidance was configured for this revision.</p>
      )}
      {value && (
        <p className="muted">
          {value.change_note} · {value.created_at} · App instructions are tracked by the pipeline fingerprint;
          exact model requests appear in Monitoring.
        </p>
      )}
    </details>
  );
}
export default function PromptVersions({
  dataset,
  editing,
  onSelect,
}: {
  dataset: string;
  editing: boolean;
  onSelect: (id: string, dirty: boolean) => void;
}) {
  const [data, setData] = useState<Row>();
  const [id, setId] = useState('');
  const [briefs, setBriefs] = useState<Row[]>([]);
  const [scope, setScope] = useState('');
  const [note, setNote] = useState('');
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  useEffect(() => {
    let live = true;
    setData(undefined);
    setId('');
    setError('');
    setDirty(false);
    setStatus('');
    onSelect('', false);
    if (dataset)
      void request(dataset)
        .then((value) => {
          if (!live) return;
          setData(value);
          setId(value.active_version_id);
          setBriefs(value.versions.find((v: Row) => v.id === value.active_version_id)?.briefs || []);
          onSelect(value.active_version_id, false);
        })
        .catch((e) => {
          if (live) setError(e.message);
        });
    return () => {
      live = false;
    };
  }, [dataset]);
  const selected = data?.versions.find((v: Row) => v.id === id);
  async function save() {
    setBusy(true);
    setError('');
    setStatus('');
    try {
      const v = await request(dataset, {
        base_version_id: data!.head_version_id,
        briefs,
        change_note: note || `Revise prompt v${selected.number}`,
      });
      setData(await request(dataset));
      setId(v.id);
      setBriefs(v.briefs);
      setDirty(false);
      setNote('');
      onSelect(v.id, false);
      setStatus(
        `Prompt v${v.number} saved and selected for testing. Chat stays on its active revision until you choose Use for chat.`
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="ops-card prompt-workbench" aria-label="Project prompt versions">
      <h2>{editing ? 'Project prompts & working agreements' : 'Prompt revision for this test'}</h2>
      <p>
        Save goals, terminology, finished-work definitions and planning conventions. Each revision captures
        shared guidance and all project briefs for this export. Tests pin the chosen revision for every
        question and model.
      </p>
      {error && (
        <p role="alert" className="ops-error">
          {error}
        </p>
      )}
      {!dataset ? (
        <p>Choose a ticket export to configure its prompts.</p>
      ) : !data ? (
        <p>Loading prompt revisions…</p>
      ) : (
        <>
          <label>
            Prompt revision
            <select
              aria-label="Project prompt revision"
              disabled={busy}
              value={id}
              onChange={(e) => {
                if (dirty && !window.confirm('Discard unsaved prompt edits?')) return;
                const v = data.versions.find((v: Row) => v.id === e.target.value);
                setId(v.id);
                setBriefs(v.briefs);
                setDirty(false);
                setStatus('');
                onSelect(v.id, false);
              }}>
              {data.versions.map((v: Row) => (
                <option key={v.id} value={v.id}>
                  v{v.number} · {v.change_note || 'Project guidance'}
                  {v.id === data.active_version_id ? ' · Active in chat' : ''}
                </option>
              ))}
            </select>
          </label>
          {editing ? (
            <>
              <label>
                Guidance for
                <select
                  aria-label="Prompt project scope"
                  value={scope}
                  onChange={(e) => setScope(e.target.value)}>
                  <option value="">Whole export · shared guidance</option>
                  {data.projects.map((p: string) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Project context prompt
                <textarea
                  aria-label="Versioned project prompt"
                  rows={8}
                  maxLength={12000}
                  disabled={busy}
                  value={briefs.find((b) => b.project === scope)?.content || ''}
                  onChange={(e) => {
                    setBriefs([
                      ...briefs.filter((b) => b.project !== scope),
                      { project: scope, content: e.target.value },
                    ]);
                    setDirty(true);
                    setStatus('');
                    onSelect(id, true);
                  }}
                />
              </label>
              <label>
                What changed?
                <input
                  aria-label="Prompt change note"
                  maxLength={500}
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                />
              </label>
              <div className="ops-toolbar">
                <button className="ops-button primary" disabled={busy || !dirty} onClick={() => void save()}>
                  Save new prompt version
                </button>
                <button
                  className="ops-button"
                  disabled={busy || dirty || id === data.active_version_id}
                  onClick={() => {
                    setBusy(true);
                    setError('');
                    void request(dataset + '/activate', { version_id: id })
                      .then(() => request(dataset))
                      .then((value) => {
                        setData(value);
                        setStatus(`Prompt v${selected.number} is now active for future chat messages.`);
                      })
                      .catch((e) => setError(e.message))
                      .finally(() => setBusy(false));
                  }}>
                  Use for chat
                </button>
              </div>
              <p className="muted">
                Editing an older revision creates a new version. Saved revisions remain unchanged. Use for
                chat can reactivate an earlier revision.
              </p>
            </>
          ) : (
            <PromptSnapshot value={selected} />
          )}
          {dirty && (
            <p className="ops-note">
              Unsaved prompt edits. Save them in Project prompts before running a test.
            </p>
          )}
          {status && (
            <p role="status" className="ops-note">
              {status}
            </p>
          )}
        </>
      )}
    </section>
  );
}
