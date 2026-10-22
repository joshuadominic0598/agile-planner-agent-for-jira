import { useEffect, useRef, useState } from 'react';
import { Download, LoaderCircle, RefreshCw, Square } from 'lucide-react';
import { api } from './api';

type DownloadJob = {
  attempt: string;
  status: string;
  message: string;
  completed: number;
  total: number;
  connection_id?: string;
};
type LocalModel = {
  id: string;
  name: string;
  download: string;
  recommended: boolean;
  license_url: string;
  installed: boolean;
  job?: DownloadJob;
};
type Catalogue = { ollama_available: boolean; message: string; models: LocalModel[] };
const running = (job?: DownloadJob) =>
  !!job && ['queued', 'downloading', 'configuring', 'cancelling'].includes(job.status);

export default function LocalModels({ onConfigured }: { onConfigured: (id?: string) => void }) {
  const [data, setData] = useState<Catalogue>();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  const [revision, setRevision] = useState(0);
  const attempt = useRef('');
  const seenReady = useRef(new Set<string>());
  const configured = useRef(onConfigured);
  configured.current = onConfigured;
  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      try {
        const next = await api<Catalogue>('/agent/local-models');
        if (!live) return;
        setData(next);
        setError('');
        for (const model of next.models) {
          const job = model.job;
          if (job?.status === 'ready' && job.connection_id && !seenReady.current.has(job.attempt)) {
            seenReady.current.add(job.attempt);
            const select = attempt.current === job.attempt;
            if (select) attempt.current = '';
            configured.current(select ? job.connection_id : undefined);
          }
        }
        if (next.models.some((model) => running(model.job))) timer = setTimeout(refresh, 1200);
      } catch (e) {
        if (live) setError((e as Error).message);
      }
    };
    void refresh();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [revision]);
  const install = async (model: LocalModel) => {
    setBusy(model.id);
    setError('');
    try {
      const job = await api<DownloadJob>(`/agent/local-models/${model.id}/install`, { method: 'POST' });
      attempt.current = job.attempt;
      setRevision((value) => value + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy('');
    }
  };
  const cancel = async (id: string) => {
    try {
      await api(`/agent/local-models/${id}/cancel`, { method: 'POST' });
      setRevision((value) => value + 1);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const downloading = data?.models.some((model) => running(model.job));
  return (
    <section className="agent-local-models" aria-label="Download local models">
      <h4>Local AI, ready in a few clicks</h4>
      <p>
        Start Ollama, then download a model here. Setup creates its connection automatically. Cached files are
        reused.
      </p>
      {!data && !error && <p role="status">Checking local models…</p>}
      {data && !data.ollama_available && (
        <p role="status">
          {data.message}{' '}
          <a href="https://ollama.com/download" target="_blank" rel="noreferrer">
            Get Ollama
          </a>
        </p>
      )}
      <div className="agent-local-model-grid">
        {data?.models.map((model) => {
          const job = model.job;
          const active = running(job);
          return (
            <article className="agent-local-model" key={model.id}>
              <strong>{model.name}</strong>
              <small>
                {model.recommended ? 'Suggested starting model · ' : ''}
                {model.download}
              </small>
              <button
                className="button secondary"
                type="button"
                disabled={!!busy || downloading || !data.ollama_available}
                onClick={() => void install(model)}>
                {busy === model.id || active ? (
                  <LoaderCircle size={14} className="spin" />
                ) : (
                  <Download size={14} />
                )}
                {model.installed ? `Use ${model.name}` : `Download ${model.name}`}
              </button>
              {job && (
                <p
                  className={`agent-local-model-status${job.status === 'failed' ? ' error-text' : ''}`}
                  role="status">
                  {job.message}
                </p>
              )}
              {active && job && (
                <>
                  <progress
                    aria-label={`${model.name} download progress`}
                    max={job.total || 1}
                    value={job.total ? Math.min(job.completed, job.total) : undefined}
                  />
                  {job.total > 0 && job.status === 'downloading' && (
                    <small>Current file: {Math.floor((job.completed / job.total) * 100)}%</small>
                  )}
                  <button
                    type="button"
                    className="text-button"
                    disabled={job.status === 'cancelling'}
                    onClick={() => void cancel(model.id)}>
                    <Square size={12} />
                    Cancel download
                  </button>
                </>
              )}
              <a href={model.license_url} className="small" target="_blank" rel="noreferrer">
                Model license
              </a>
            </article>
          );
        })}
      </div>
      <p className="small muted">
        Downloads require internet and disk space. Ticket data is not sent with model downloads. Model files
        are stored by your local Ollama service.
      </p>
      <button type="button" className="text-button" onClick={() => setRevision((value) => value + 1)}>
        <RefreshCw size={13} />
        Check Ollama and downloads
      </button>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
    </section>
  );
}
