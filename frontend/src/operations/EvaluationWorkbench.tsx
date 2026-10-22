import { useEffect, useState } from 'react';
import PromptVersions from './PromptVersions';

type Row = Record<string, any>;
type Pane = 'datasets' | 'prompts' | 'run' | 'history';
async function request(path: string, body?: unknown) {
  const response = await fetch(
    '/api/ops/evaluation' + path,
    body
      ? {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        }
      : undefined
  );
  const value = await response.json();
  if (!response.ok)
    throw new Error(typeof value.detail === 'string' ? value.detail : 'Check the dataset fields.');
  return value;
}
const blankCase = () => ({
  id: crypto.randomUUID(),
  conversation_id: 'conversation-1',
  question: '',
  reference: '',
  reference_status: 'needs_human_verification',
  enabled: true,
  reference_contexts: [],
  context_status: 'missing',
  context_source: '',
  provided_answer: null,
  provided_contexts: [],
  expected: { clarification: false, ticket_keys: [] },
});
const percent = (value: any) => (typeof value === 'number' ? `${(100 * value).toFixed(1)}%` : 'Not scored');
export default function EvaluationWorkbench({
  pane,
  refresh,
  onResults,
  onSaved,
}: {
  pane: Pane;
  refresh: number;
  onResults: (ids: string[]) => void;
  onSaved: () => void;
}) {
  const [catalog, setCatalog] = useState<Row>({ datasets: [], exports: [], connections: [] });
  const [datasetId, setDatasetId] = useState('');
  const [versionId, setVersionId] = useState('');
  const [versions, setVersions] = useState<Row[]>([]);
  const [draft, setDraft] = useState<Row>();
  const [creating, setCreating] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState('one');
  const [runMode, setRunMode] = useState('agent');
  const [first, setFirst] = useState('');
  const [second, setSecond] = useState('');
  const [judge, setJudge] = useState('');
  const [ragas, setRagas] = useState(true);
  const [effort, setEffort] = useState('standard');
  const [target, setTarget] = useState('');
  const [promptId, setPromptId] = useState('');
  const [promptDirty, setPromptDirty] = useState(false);
  const [historyPrompt, setHistoryPrompt] = useState('');
  const [job, setJob] = useState<Row>();
  const [history, setHistory] = useState<Row[]>([]);
  const [historyVersion, setHistoryVersion] = useState('');
  const selected = catalog.datasets.find((d: Row) => d.id === datasetId);
  const historical = !!selected && versionId !== selected.head_version_id;
  const loadCatalog = async () => {
    const data = await request('/datasets');
    setCatalog(data);
    if (!datasetId && !creating && data.datasets.length) {
      const preferred =
        data.datasets.find((d: Row) => d.ticket_dataset_id === data.active_export_id && d.kind !== 'demo') ||
        data.datasets[0];
      setDatasetId(preferred.id);
      setVersionId(preferred.head_version_id);
    }
    const preferredModel = data.connections.find((c: Row) => c.provider === 'gemini') || data.connections[0];
    if (!first) setFirst(preferredModel?.id || '');
    if (!second) setSecond(data.connections.find((c: Row) => c.id !== preferredModel?.id)?.id || '');
    if (!judge) setJudge(preferredModel?.id || '');
    return data;
  };
  useEffect(() => {
    void loadCatalog().catch((e) => setError(e.message));
  }, [refresh]);
  useEffect(() => {
    if (!datasetId) return;
    let live = true;
    void request(`/datasets/${datasetId}/versions`)
      .then((values) => {
        if (live) setVersions(values);
      })
      .catch((e) => setError(e.message));
    return () => {
      live = false;
    };
  }, [datasetId, refresh, versionId]);
  useEffect(() => {
    if (!datasetId || !versionId) return;
    let live = true;
    setDraft(undefined);
    setError('');
    setStatus('');
    void request(`/datasets/${datasetId}/versions/${versionId}`)
      .then((v) => {
        if (!live) return;
        setDraft(v);
        setDirty(false);
        setCreating(false);
        const match = catalog.exports.find((e: Row) => e.sha256 === v.source_snapshot_sha256);
        setTarget(v.ticket_dataset_id || match?.id || catalog.active_export_id || '');
      })
      .catch((e) => setError(e.message));
    return () => {
      live = false;
    };
  }, [datasetId, versionId]);
  useEffect(() => {
    if (pane !== 'history' || !datasetId) return;
    void request(`/datasets/${datasetId}/performance?version_id=${historyVersion}`)
      .then(setHistory)
      .catch((e) => setError(e.message));
  }, [pane, datasetId, refresh, historyVersion]);
  useEffect(() => {
    const saved = localStorage.getItem('agileplanner.evaluation.job');
    if (saved)
      void request('/jobs/' + saved)
        .then(setJob)
        .catch(() => {});
  }, []);
  useEffect(() => {
    if (!job || !['queued', 'running'].includes(job.status)) return;
    const timer = setInterval(() => {
      void request('/jobs/' + job.id)
        .then(setJob)
        .catch((e) => setError(e.message));
    }, 2000);
    return () => clearInterval(timer);
  }, [job?.id, job?.status]);
  const change = (values: Row) => {
    setDraft((previous) => ({ ...previous, ...values }));
    setDirty(true);
    setStatus('');
  };
  const updateCase = (pos: number, value: Row) =>
    change({ cases: draft!.cases.map((c: Row, i: number) => (i === pos ? { ...c, ...value } : c)) });
  const choose = (id: string) => {
    if ((dirty || promptDirty) && !window.confirm('Discard unsaved dataset or prompt changes?')) return;
    const found = catalog.datasets.find((d: Row) => d.id === id);
    setCreating(false);
    setDirty(false);
    setDatasetId(id);
    setVersionId(found.head_version_id);
    setHistoryVersion('');
  };
  const save = async (restore = false) => {
    if (!draft) return;
    setBusy(true);
    setError('');
    try {
      const v = await request(creating ? '/datasets' : `/datasets/${datasetId}/versions`, {
        name: draft.name,
        notes: draft.notes,
        ticket_dataset_id: draft.ticket_dataset_id || '',
        cases: draft.cases,
        base_version_id: creating ? '' : selected.head_version_id,
        change_note: restore
          ? `Restore version ${draft.number}`
          : draft.change_note || 'Edited in dataset configuration',
      });
      setCreating(false);
      setDirty(false);
      setDatasetId(v.dataset_id);
      setVersionId(v.id);
      setDraft(v);
      const data = await request('/datasets');
      setCatalog(data);
      onSaved();
      setStatus(`Version ${v.number} saved. Previous versions and test results are unchanged.`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const createNew = () => {
    if (dirty && !window.confirm('Discard unsaved dataset changes?')) return;
    setCreating(true);
    setDatasetId('');
    setVersionId('');
    setVersions([]);
    setStatus('');
    setDraft({
      name: 'My golden dataset',
      notes: '',
      ticket_dataset_id: catalog.active_export_id || '',
      cases: [blankCase()],
    });
    setDirty(true);
  };
  const upload = async (file?: File) => {
    if (!file) return;
    if (dirty && !window.confirm('Discard unsaved dataset changes and import a conversation?')) return;
    setBusy(true);
    setError('');
    try {
      const form = new FormData();
      form.append('file', file);
      form.append('ticket_dataset_id', draft?.ticket_dataset_id || catalog.active_export_id || '');
      const response = await fetch('/api/ops/evaluation/import', { method: 'POST', body: form });
      const v = await response.json();
      if (!response.ok)
        throw new Error(typeof v.detail === 'string' ? v.detail : 'Could not import this file.');
      const data = await request('/datasets');
      setCatalog(data);
      setCreating(false);
      setDirty(false);
      setDatasetId(v.dataset_id);
      setVersionId(v.id);
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const launch = async () => {
    setBusy(true);
    setError('');
    try {
      const value = await request('/jobs', {
        golden_dataset_id: datasetId,
        run_mode: runMode,
        version_id: versionId,
        ticket_dataset_id: target,
        prompt_version_id: promptId,
        connection_ids: mode === 'two' ? [first, second] : [first],
        judge_connection_id: ragas ? judge : '',
        ragas,
        effort,
      });
      setJob(value);
      localStorage.setItem('agileplanner.evaluation.job', value.id);
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const download = () => {
    if (!draft) return;
    const blob = new Blob([JSON.stringify(draft, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `evaluation-v${draft.number || 'draft'}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };
  const running = job && ['queued', 'running'].includes(job.status);
  const exportValue = catalog.exports.find((e: Row) => e.id === target);
  const mismatch = !!draft?.source_snapshot_sha256 && exportValue?.sha256 !== draft.source_snapshot_sha256;
  const filteredHistory = history.filter(
    (r) =>
      (!historyVersion || r.golden_version_id === historyVersion) &&
      (!historyPrompt || r.prompt_version_id === historyPrompt)
  );
  return (
    <section className="evaluation-workbench" aria-label="Evaluation dataset workspace">
      {pane === 'prompts' && (
        <label>
          Ticket export for project prompts
          <select
            aria-label="Prompt ticket export"
            value={target}
            onChange={(e) => {
              if (!promptDirty || window.confirm('Discard unsaved prompt changes?'))
                setTarget(e.target.value);
            }}>
            <option value="">Choose an export</option>
            {catalog.exports.map((d: Row) => (
              <option key={d.id} value={d.id}>
                {d.filename} · {d.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
      )}
      <div hidden={pane !== 'prompts' && (pane !== 'run' || runMode === 'provided')}>
        <PromptVersions
          dataset={target}
          editing={pane === 'prompts'}
          onSelect={(id, dirty) => {
            setPromptId(id);
            setPromptDirty(dirty);
          }}
        />
      </div>
      <div className="ops-card ops-fields" hidden={pane === 'prompts'}>
        <label>
          Golden evaluation dataset
          <select
            aria-label="Golden evaluation dataset"
            value={datasetId}
            onChange={(e) => choose(e.target.value)}>
            <option value="" disabled>
              {creating ? 'New dataset' : 'Select a dataset'}
            </option>
            {catalog.datasets.map((d: Row) => (
              <option key={d.id} value={d.id}>
                {d.name} · v{d.version_number} · {d.case_count} exchanges
              </option>
            ))}
          </select>
        </label>
        <label>
          Dataset version
          <select
            aria-label="Dataset version"
            value={versionId}
            disabled={creating}
            onChange={(e) => {
              if (dirty && !window.confirm('Discard unsaved dataset changes?')) return;
              setVersionId(e.target.value);
            }}>
            {creating && <option value="">New version 1</option>}
            {versions.map((v) => (
              <option key={v.id} value={v.id}>
                v{v.number} · {v.case_count} exchanges · {v.created_at.slice(0, 16)}
                {v.id === selected?.head_version_id ? ' · Latest' : ''}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error && (
        <p role="alert" className="ops-error">
          {error}
        </p>
      )}
      {status && (
        <p role="status" className="ops-note">
          {status}
        </p>
      )}
      {pane === 'datasets' && (
        <>
          <div className="ops-toolbar evaluation-dataset-actions">
            <button className="ops-button" onClick={createNew} disabled={busy}>
              Create dataset
            </button>
            <label className="ops-button evaluation-upload">
              Import DOCX / JSON / CSV
              <input
                type="file"
                aria-label="Import evaluation conversation"
                accept=".docx,.json,.csv"
                disabled={busy}
                onChange={(e) => {
                  void upload(e.target.files?.[0]);
                  e.target.value = '';
                }}
              />
            </label>
            <button className="ops-button" disabled={!draft || dirty} onClick={download}>
              Download this version
            </button>
          </div>
          <details className="ops-card" open>
            <summary>CSV acceptance criteria & template</summary>
            <p>
              UTF-8 CSV, one exchange per row, distinct headers, up to 200 exchanges and 3 MB. Required:{' '}
              <code>question</code> and <code>reference_answer</code> (or <code>answer</code>). Use quoted
              cells for commas and multiline text.
            </p>
            <p>
              <code>reference_contexts</code> stores expected evidence. When both{' '}
              <code>reference_answer</code> and <code>answer</code> are supplied, <code>answer</code> is the
              recorded model output and <code>retrieved_contexts</code> is what that model retrieved. Without
              a separate reference, <code>answer</code> is the expected answer and its contexts are candidate
              reference evidence.
            </p>
            <p>
              Contexts accept a JSON array of strings, one quoted text cell, or chunks separated by{' '}
              <code>|||</code>. Optional: <code>conversation_id</code>, <code>reference_status</code>,{' '}
              <code>context_status</code>, <code>expected_ticket_keys</code>, <code>should_clarify</code>.
              Evidence is unverified unless explicitly verified; each chunk is limited to 6,000 characters (12
              reference chunks, 24 captured chunks).
            </p>
            <a href="/api/ops/evaluation/template.csv" download>
              Download evaluation CSV template
            </a>
          </details>
          {draft && (
            <section className="ops-card">
              <h2>{creating ? 'Create a golden dataset' : `${draft.name} · version ${draft.number}`}</h2>
              <p>
                Each exchange has a question, expected answer and optional retrieval/clarification checks.
                Shared conversation IDs replay in order; a different ID starts a fresh conversation.
              </p>
              {historical && (
                <p className="ops-note">
                  This is a historical version. It is read-only. Restore it as a new version to make changes.
                </p>
              )}
              <fieldset className="evaluation-editor" disabled={historical || busy}>
                <div className="ops-fields">
                  <label>
                    Dataset name
                    <input
                      aria-label="Dataset name"
                      maxLength={120}
                      value={draft.name}
                      onChange={(e) => change({ name: e.target.value })}
                    />
                  </label>
                  <label>
                    Source ticket export
                    <select
                      aria-label="Source ticket export"
                      value={draft.ticket_dataset_id || ''}
                      onChange={(e) => change({ ticket_dataset_id: e.target.value })}>
                      <option value="">Unbound / built-in template</option>
                      {catalog.exports.map((v: Row) => (
                        <option key={v.id} value={v.id}>
                          {v.filename} · {v.id.slice(0, 8)}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <label>
                  Dataset notes
                  <textarea
                    aria-label="Dataset notes"
                    maxLength={2000}
                    rows={2}
                    value={draft.notes}
                    onChange={(e) => change({ notes: e.target.value })}
                  />
                </label>
                <div className="golden-case-list">
                  {draft.cases.map((c: Row, pos: number) => (
                    <details
                      key={c.id}
                      className="golden-case"
                      open={creating && draft.cases.length === 1 ? true : undefined}>
                      <summary>
                        <span>
                          {pos + 1}. {c.question || 'New question'}
                        </span>
                        <small>
                          {c.enabled ? c.reference_status.replaceAll('_', ' ') : 'Excluded'} ·{' '}
                          {c.conversation_id}
                        </small>
                      </summary>
                      <label>
                        Question
                        <textarea
                          aria-label={`Question ${pos + 1}`}
                          maxLength={3000}
                          rows={2}
                          value={c.question}
                          onChange={(e) => updateCase(pos, { question: e.target.value })}
                        />
                      </label>
                      <label>
                        Golden expected answer
                        <textarea
                          aria-label={`Expected answer ${pos + 1}`}
                          maxLength={12000}
                          rows={5}
                          value={c.reference}
                          onChange={(e) =>
                            updateCase(pos, {
                              reference: e.target.value,
                              reference_status: 'needs_human_verification',
                            })
                          }
                        />
                      </label>
                      <label>
                        Expected evidence / ground-truth context
                        <textarea
                          aria-label={`Expected context ${pos + 1}`}
                          rows={5}
                          value={(c.reference_contexts || []).join('\n---\n')}
                          onChange={(e) =>
                            updateCase(pos, {
                              reference_contexts: e.target.value.split('\n---\n'),
                              context_status: 'needs_human_verification',
                              context_source: 'Edited by user; verify against source.',
                            })
                          }
                        />
                      </label>
                      <p className="muted">
                        Separate chunks with a line containing ---. Expected evidence is kept separate from
                        actual retrieved chunks. {c.context_source}
                      </p>
                      <label>
                        Evidence verification
                        <select
                          aria-label={`Evidence verification ${pos + 1}`}
                          value={c.context_status || 'missing'}
                          onChange={(e) => updateCase(pos, { context_status: e.target.value })}>
                          <option value="missing">Missing evidence</option>
                          <option value="needs_human_verification">
                            Candidate evidence · needs verification
                          </option>
                          <option value="verified">Verified ground-truth evidence</option>
                        </select>
                      </label>
                      <details>
                        <summary>Optional captured answer & actual retrieval</summary>
                        <label>
                          Recorded answer
                          <textarea
                            aria-label={`Recorded answer ${pos + 1}`}
                            rows={3}
                            value={c.provided_answer || ''}
                            onChange={(e) => updateCase(pos, { provided_answer: e.target.value || null })}
                          />
                        </label>
                        <label>
                          Actually retrieved context
                          <textarea
                            aria-label={`Recorded context ${pos + 1}`}
                            rows={4}
                            value={(c.provided_contexts || []).join('\n---\n')}
                            onChange={(e) =>
                              updateCase(pos, { provided_contexts: e.target.value.split('\n---\n') })
                            }
                          />
                        </label>
                      </details>
                      <div className="ops-fields">
                        <label>
                          Conversation ID
                          <input
                            aria-label={`Conversation ID ${pos + 1}`}
                            maxLength={80}
                            value={c.conversation_id}
                            onChange={(e) => updateCase(pos, { conversation_id: e.target.value })}
                          />
                        </label>
                        <label>
                          Reference verification
                          <select
                            aria-label={`Reference verification ${pos + 1}`}
                            value={c.reference_status}
                            onChange={(e) => updateCase(pos, { reference_status: e.target.value })}>
                            <option value="needs_human_verification">Needs verification</option>
                            <option value="verified">Verified against source</option>
                            <option value="curated_behavior">Expected behavior</option>
                          </select>
                        </label>
                        <label>
                          Expected ticket keys
                          <input
                            aria-label={`Expected ticket keys ${pos + 1}`}
                            value={c.expected.ticket_keys.join(', ')}
                            onChange={(e) =>
                              updateCase(pos, {
                                expected: {
                                  ...c.expected,
                                  ticket_keys: e.target.value
                                    .split(',')
                                    .map((k) => k.trim())
                                    .filter(Boolean),
                                },
                              })
                            }
                          />
                        </label>
                      </div>
                      <div className="evaluation-case-options">
                        <label className="ops-checkbox">
                          <input
                            type="checkbox"
                            checked={c.enabled}
                            onChange={(e) => updateCase(pos, { enabled: e.target.checked })}
                          />
                          Include in tests
                        </label>
                        <label className="ops-checkbox">
                          <input
                            type="checkbox"
                            checked={c.expected.clarification}
                            onChange={(e) =>
                              updateCase(pos, {
                                expected: { ...c.expected, clarification: e.target.checked },
                              })
                            }
                          />
                          Should ask for clarification
                        </label>
                        <button
                          className="ops-button"
                          disabled={pos === 0}
                          onClick={() => {
                            const values = [...draft.cases];
                            [values[pos - 1], values[pos]] = [values[pos], values[pos - 1]];
                            change({ cases: values });
                          }}>
                          Move up
                        </button>
                        <button
                          className="ops-button"
                          disabled={pos === draft.cases.length - 1}
                          onClick={() => {
                            const values = [...draft.cases];
                            [values[pos + 1], values[pos]] = [values[pos], values[pos + 1]];
                            change({ cases: values });
                          }}>
                          Move down
                        </button>
                        <button
                          className="ops-button"
                          disabled={draft.cases.length === 1}
                          onClick={() =>
                            change({ cases: draft.cases.filter((_: Row, i: number) => i !== pos) })
                          }>
                          Remove exchange
                        </button>
                      </div>
                      {c.original_reference && c.original_reference !== c.reference && (
                        <details>
                          <summary>Original imported answer</summary>
                          <p>{c.original_reference}</p>
                        </details>
                      )}
                    </details>
                  ))}
                </div>
                <button
                  className="ops-button"
                  disabled={draft.cases.length >= 200}
                  onClick={() => change({ cases: [...draft.cases, blankCase()] })}>
                  Add exchange
                </button>
                <label>
                  Version change note
                  <input
                    aria-label="Version change note"
                    maxLength={500}
                    value={draft.change_note || ''}
                    onChange={(e) => change({ change_note: e.target.value })}
                  />
                </label>
              </fieldset>
              <div className="evaluation-save">
                <button
                  className="ops-button primary"
                  disabled={busy || (!dirty && !historical)}
                  onClick={() => void save(historical)}>
                  {busy
                    ? 'Saving…'
                    : historical
                      ? 'Restore as new version'
                      : creating
                        ? 'Create version 1'
                        : 'Save as new version'}
                </button>
                <span>
                  {dirty
                    ? 'Unsaved changes · tests use saved versions only'
                    : 'Saved versions are immutable; historical results keep their original references.'}
                </span>
              </div>
            </section>
          )}
        </>
      )}
      {pane === 'run' && (
        <section className="ops-card">
          <h2>Run an evaluation</h2>
          <p>
            One model or two models, the same frozen questions and expected answers. Comparisons run
            sequentially with fresh conversations and the same effort and judge settings.
          </p>
          <div className="ops-fields">
            <label>
              What to evaluate
              <select
                aria-label="Evaluation input mode"
                value={runMode}
                onChange={(e) => {
                  setRunMode(e.target.value);
                  if (e.target.value === 'provided') setMode('one');
                }}>
                <option value="agent">Generate new answers with the agent</option>
                <option value="provided">Score uploaded answers / evidence</option>
              </select>
            </label>
            <label>
              Evaluation mode
              <select
                aria-label="Evaluation mode"
                value={mode}
                disabled={runMode === 'provided'}
                onChange={(e) => setMode(e.target.value)}>
                <option value="one">Evaluate one model</option>
                <option value="two">Compare two models</option>
              </select>
            </label>
            <label>
              Ticket export for testing
              <select
                aria-label="Ticket export for testing"
                value={target}
                onChange={(e) => setTarget(e.target.value)}>
                <option value="">Choose a ticket export</option>
                {catalog.exports.map((d: Row) => (
                  <option key={d.id} value={d.id}>
                    {d.filename} · {d.id.slice(0, 8)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Model 1
              <select
                aria-label="Evaluation model 1"
                value={first}
                onChange={(e) => setFirst(e.target.value)}>
                {catalog.connections.map((c: Row) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
            {mode === 'two' && (
              <label>
                Model 2
                <select
                  aria-label="Evaluation model 2"
                  value={second}
                  onChange={(e) => setSecond(e.target.value)}>
                  {catalog.connections.map((c: Row) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label>
              Investigation effort
              <select
                aria-label="Evaluation effort"
                value={effort}
                onChange={(e) => setEffort(e.target.value)}>
                <option value="low">Low</option>
                <option value="standard">Standard</option>
                <option value="high">High</option>
              </select>
            </label>
            {ragas && (
              <label>
                Common Ragas judge
                <select
                  aria-label="Evaluation judge"
                  value={judge}
                  onChange={(e) => setJudge(e.target.value)}>
                  {catalog.connections.map((c: Row) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          <label className="ops-checkbox">
            <input type="checkbox" checked={ragas} onChange={(e) => setRagas(e.target.checked)} />
            Score retrieved evidence with Ragas
          </label>
          {mismatch && runMode === 'agent' && (
            <p className="ops-note">
              This version targets a different export. For the built-in benchmark, load the fictional demo CSV
              in the app. For your own data, choose its source export and save a new golden version.
            </p>
          )}
          {dirty && <p className="ops-note">Save your dataset edits before testing.</p>}
          {!catalog.connections.length && (
            <p className="ops-note">Configure a model connection in Sprint Agent first.</p>
          )}
          <p className="muted">
            {draft?.enabled_count ?? draft?.cases.filter((c: Row) => c.enabled).length ?? 0} enabled exchanges
            · saved version {draft?.number || 'not saved'} · calls use your configured provider quota.
          </p>
          <button
            className="ops-button primary"
            disabled={
              busy ||
              running ||
              dirty ||
              creating ||
              !versionId ||
              (runMode === 'agent' && !target) ||
              (runMode === 'agent' && (!promptId || promptDirty)) ||
              !first ||
              (runMode === 'agent' && mismatch) ||
              (mode === 'two' && (!second || second === first))
            }
            onClick={() => void launch()}>
            Start evaluation
          </button>
        </section>
      )}
      {job && pane !== 'datasets' && (
        <section className="ops-card" aria-label="Evaluation job progress">
          <h3>
            Evaluation {job.status} · version {job.version_number}
          </h3>
          <p>
            {job.completed_models || 0}/{job.connection_ids.length} models finished · {job.case_count}{' '}
            exchanges per model
          </p>
          {job.runs?.map((r: Row) => (
            <p key={r.id}>
              {r.model}: {r.completed} answers · {r.failed} failed / {r.case_count}
            </p>
          ))}
          {job.error && (
            <p role="alert" className="ops-error">
              {job.error}
            </p>
          )}
          {!!job.runs?.length && (
            <button className="ops-button" onClick={() => onResults(job.runs.map((r: Row) => r.id))}>
              View evaluation results
            </button>
          )}
          {running && (
            <button
              className="ops-button"
              onClick={() =>
                void request('/jobs/' + job.id + '/cancel')
                  .then(() => setStatus('Stopping evaluation; completed results will be kept.'))
                  .catch((e) => setError(e.message))
              }>
              Stop evaluation
            </button>
          )}
        </section>
      )}
      {pane === 'history' && (
        <section className="ops-card">
          <div className="ops-page-heading">
            <div>
              <h2>Dataset performance history</h2>
              <p>
                Results stay attached to the dataset version used at test time. Different versions test
                different expectations.
              </p>
            </div>
            <label>
              Version filter
              <select
                aria-label="Performance version filter"
                value={historyVersion}
                onChange={(e) => setHistoryVersion(e.target.value)}>
                <option value="">All versions</option>
                {versions.map((v) => (
                  <option key={v.id} value={v.id}>
                    Version {v.number}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Prompt filter
              <select
                aria-label="Performance prompt filter"
                value={historyPrompt}
                onChange={(e) => setHistoryPrompt(e.target.value)}>
                <option value="">All prompt revisions</option>
                {Array.from(
                  new Map(
                    history.filter((r) => r.prompt_version_id).map((r) => [r.prompt_version_id, r])
                  ).values()
                ).map((r) => (
                  <option key={r.prompt_version_id} value={r.prompt_version_id}>
                    Prompt v{r.prompt_version_number} · {r.prompt_version_id.slice(0, 8)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="ops-table">
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Version</th>
                  <th>Prompt</th>
                  <th>Model</th>
                  <th>Answered</th>
                  <th>Faithfulness</th>
                  <th>Context precision</th>
                  <th>Human score</th>
                  <th>Answer latency</th>
                  <th>Result</th>
                </tr>
              </thead>
              <tbody>
                {filteredHistory.map((r) => (
                  <tr key={r.id}>
                    <td>{r.started_at?.slice(0, 16)}</td>
                    <td>{r.golden_version_number ? `v${r.golden_version_number}` : 'Legacy'}</td>
                    <td>{r.prompt_version_number ? `v${r.prompt_version_number}` : 'Not recorded'}</td>
                    <td>{r.model}</td>
                    <td>
                      {r.completed}/{r.case_count}
                    </td>
                    <td>{percent(r.summary?.faithfulness)}</td>
                    <td>{percent(r.summary?.context_precision)}</td>
                    <td>
                      {r.summary?.human_score ? `${r.summary.human_score.toFixed(1)}/5` : 'Awaiting review'}
                    </td>
                    <td>
                      {r.summary?.latency_ms != null ? `${(r.summary.latency_ms / 1000).toFixed(2)}s` : '—'}
                    </td>
                    <td>
                      <button className="ops-link" onClick={() => onResults([r.id])}>
                        View result
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!filteredHistory.length && (
            <p>No tests yet for this dataset/version. Open Run tests to start one.</p>
          )}
        </section>
      )}
    </section>
  );
}
