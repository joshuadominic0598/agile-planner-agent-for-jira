import { useEffect, useState, type FormEvent } from 'react';
import { Check, LoaderCircle, Pencil, Plus, Trash2, X } from 'lucide-react';
import { api } from './api';

export type ModelChoice = {
  id: string;
  name: string;
  provider: string;
  model: string;
  web_available: boolean;
  context_profile?: string;
  context_window?: number;
};
type Profile = {
  id: string;
  name: string;
  provider: 'compatible' | 'openai' | 'azure' | 'gemini';
  model: string;
  base: string;
  project_id: string;
  organization_id: string;
  has_key: boolean;
  api_mode?: 'auto' | 'responses' | 'chat';
  web_enabled: boolean;
  reasoning_effort: string;
  context_profile?: 'auto' | 'compact' | 'expanded';
  context_window?: number;
};
type Preset = {
  id: string;
  name: string;
  provider: Profile['provider'];
  model: string;
  base: string;
  pricing_url?: string;
  key_url?: string;
  context_window?: number;
};
const empty = {
  name: '',
  provider: 'openai' as Profile['provider'],
  model: '',
  base: '',
  project_id: '',
  organization_id: '',
  api_key: '',
  api_mode: 'auto' as 'auto' | 'responses' | 'chat',
  web_enabled: false,
  reasoning_effort: '',
  context_profile: 'auto' as 'auto' | 'compact' | 'expanded',
  context_window: 32768,
};

export default function AgentConnections({
  selected,
  onChanged,
}: {
  selected: string;
  onChanged: (id?: string) => void;
}) {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [show, setShow] = useState(false);
  const [draft, setDraft] = useState(empty);
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const refresh = async () => {
    const data = await api<{ profiles: Profile[]; presets: Preset[] }>('/agent/connections');
    setProfiles(data.profiles);
    setPresets(data.presets || []);
  };
  useEffect(() => {
    void refresh().catch((e) => setError(e.message));
  }, []);
  const legacyChat = /^(?:ft:)?gpt-(?:3\.5|35)-turbo(?:$|[-:])/i.test(draft.model);
  const gemini = presets.find((p) => p.id === 'gemini-free-tier');
  const nemotron = presets.find((p) => p.id === 'nemotron-cascade-8b');
  const useNemotron = () => {
    if (!nemotron) return;
    setDraft({
      ...empty,
      name: nemotron.name,
      provider: 'compatible',
      model: nemotron.model,
      base: nemotron.base,
      api_mode: 'chat',
      context_window: nemotron.context_window || 32768,
    });
    setEditing(null);
    setShow(true);
    setError('');
    setNotice(
      'Install the Nemotron Ollama model first using config/ollama/README.md, then save and test this connection.'
    );
  };
  const useGemini = () => {
    if (!gemini) return;
    setDraft({ ...empty, name: gemini.name, provider: 'gemini', model: gemini.model });
    setEditing(null);
    setShow(true);
    setError('');
    setNotice('');
  };
  const reset = () => {
    setDraft(empty);
    setEditing(null);
    setShow(false);
  };
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const result = await api<Profile>(`/agent/connections${editing ? `/${editing}` : ''}`, {
        method: editing ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...draft, api_key: draft.api_key || null }),
      });
      reset();
      await refresh();
      onChanged(result.id);
      setNotice('Connection saved. Select Test connection to check authentication and tool calling.');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const test = async () => {
    if (!selected) return;
    setTesting(selected);
    setError('');
    setNotice('');
    try {
      const result = await api<{ message: string; model: string }>(
        `/agent/connections/${encodeURIComponent(selected)}/test`,
        { method: 'POST' }
      );
      setNotice(`${result.model}: ${result.message}`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setTesting('');
    }
  };
  const remove = async (id: string) => {
    setBusy(true);
    setError('');
    try {
      await api(`/agent/connections/${id}`, { method: 'DELETE' });
      await refresh();
      onChanged();
      if (editing === id) reset();
      setNotice('Connection removed.');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="agent-connections" aria-label="Model connections">
      <h3>Model connections</h3>
      <p>Choose local models, your OpenAI Platform project, Azure, or Gemini.</p>
      {selected && (
        <button type="button" className="button secondary" disabled={!!testing || busy} onClick={test}>
          {testing ? <LoaderCircle size={14} className="spin" /> : <Check size={14} />}Test selected
          connection
        </button>
      )}
      {testing && (
        <p role="status">
          Testing tool calling… Loading a local model can take a few minutes. This test sends no Jira data;
          hosted providers may charge for it.
        </p>
      )}
      {profiles.map((p) => (
        <div key={p.id} className="agent-saved-connection">
          <div>
            <strong>{p.name}</strong>
            <small>
              {p.provider} · {p.model}
              {p.has_key ? ' · Key saved' : ''}
            </small>
          </div>
          <button
            type="button"
            aria-label={`Edit ${p.name}`}
            disabled={busy || !!testing}
            onClick={() => {
              setEditing(p.id);
              setShow(true);
              setDraft({
                ...empty,
                ...p,
                api_mode: p.api_mode || 'auto',
                context_profile: p.context_profile || 'auto',
                context_window: p.context_window || 32768,
                api_key: '',
              });
              setNotice('');
              setError('');
            }}>
            <Pencil size={14} />
          </button>
          <button
            type="button"
            aria-label={`Remove ${p.name}`}
            disabled={busy || !!testing}
            onClick={() => void remove(p.id)}>
            <Trash2 size={14} />
          </button>
        </div>
      ))}
      {!show && nemotron && (
        <button type="button" className="button secondary" disabled={busy || !!testing} onClick={useNemotron}>
          <Plus size={14} />
          Set up Nemotron 8B
        </button>
      )}
      {!show && gemini && (
        <button type="button" className="button secondary" disabled={busy || !!testing} onClick={useGemini}>
          <Plus size={14} />
          Set up Gemini free-tier option
        </button>
      )}
      {!show ? (
        <button
          type="button"
          className="button secondary"
          disabled={busy || !!testing}
          onClick={() => {
            setDraft(empty);
            setEditing(null);
            setShow(true);
            setError('');
          }}>
          <Plus size={14} />
          Add model connection
        </button>
      ) : (
        <form className="agent-connection-form" onSubmit={submit}>
          <div>
            <strong>{editing ? 'Edit connection' : 'New connection'}</strong>
            <button type="button" aria-label="Cancel connection editing" onClick={reset}>
              <X size={16} />
            </button>
          </div>
          <label>
            Connection name
            <input
              aria-label="Connection name"
              required
              maxLength={80}
              placeholder="My project GPT"
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            />
          </label>
          <label>
            Provider
            <select
              aria-label="Connection provider"
              value={draft.provider}
              onChange={(e) => {
                const provider = e.target.value as Profile['provider'];
                setDraft({
                  ...draft,
                  provider,
                  base: '',
                  api_key: '',
                  api_mode: 'auto',
                  model: provider === 'gemini' ? gemini?.model || '' : '',
                  project_id: '',
                  organization_id: '',
                  reasoning_effort: '',
                  web_enabled: false,
                });
              }}>
              <option value="openai">OpenAI Platform · project API key</option>
              <option value="gemini">Google Gemini · AI Studio</option>
              <option value="azure">Azure OpenAI · deployed model</option>
              <option value="compatible">Local / OpenAI-compatible server</option>
            </select>
          </label>
          {(draft.provider === 'compatible' || draft.provider === 'azure') && (
            <label>
              {draft.provider === 'azure' ? 'Azure resource endpoint' : 'API base URL'}
              <input
                aria-label="Model API endpoint"
                required
                type="url"
                placeholder={
                  draft.provider === 'azure'
                    ? 'https://your-resource.openai.azure.com'
                    : 'http://host.docker.internal:11434/v1'
                }
                value={draft.base}
                onChange={(e) => setDraft({ ...draft, base: e.target.value })}
              />
            </label>
          )}
          {draft.provider === 'openai' && (
            <div className="agent-provider-note">
              <p>
                Use an API key created inside your OpenAI Platform project. Usage is attributed to that API
                project. Enter the exact model ID you can access, such as gpt-3.5-turbo (no spaces). GPT-3.5
                uses Chat Completions automatically.
              </p>
              <a href="https://platform.openai.com/api-keys" target="_blank" rel="noreferrer">
                Project API keys
              </a>{' '}
              ·{' '}
              <a href="https://platform.openai.com/usage" target="_blank" rel="noreferrer">
                Project usage dashboard
              </a>
            </div>
          )}
          {draft.provider === 'gemini' && (
            <div className="agent-provider-note">
              <strong>Gemini free-tier setup</strong>
              <p>
                1. Create a key in{' '}
                <a href="https://aistudio.google.com/api-keys" target="_blank" rel="noreferrer">
                  Google AI Studio
                </a>{' '}
                using a free-tier project.
                <br />
                2. Paste it below, save, then test the connection.
              </p>
              <p>
                Google currently lists {gemini?.model} with free-tier input/output. Your project controls
                billing and quotas; this app cannot verify its tier. Google may use free-tier content to
                improve products.
              </p>
              <a href="https://ai.google.dev/gemini-api/docs/pricing" target="_blank" rel="noreferrer">
                Pricing and data terms
              </a>{' '}
              ·{' '}
              <a href="https://aistudio.google.com/usage" target="_blank" rel="noreferrer">
                Usage and limits
              </a>
            </div>
          )}
          <label>
            {draft.provider === 'azure' ? 'Deployment name' : 'Model name'}
            <input
              aria-label="Model or deployment name"
              required
              maxLength={100}
              placeholder={
                draft.provider === 'azure'
                  ? 'your-deployment-name'
                  : draft.provider === 'compatible'
                    ? 'qwen3:8b'
                    : 'Your model ID'
              }
              value={draft.model}
              onChange={(e) => setDraft({ ...draft, model: e.target.value })}
            />
          </label>
          {(draft.provider === 'openai' || draft.provider === 'azure') && (
            <label>
              API compatibility
              <select
                aria-label="API compatibility"
                value={draft.api_mode}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    api_mode: e.target.value as 'auto' | 'responses' | 'chat',
                    web_enabled: false,
                  })
                }>
                <option value="auto">Automatic · GPT-3.5 uses Chat Completions</option>
                <option value="responses">Responses API</option>
                <option value="chat">Chat Completions · older models / deployments</option>
              </select>
            </label>
          )}
          <label>
            API key{editing && ' · leave blank to keep saved key'}
            <input
              aria-label="Model API key"
              type="password"
              required={!editing && draft.provider !== 'compatible'}
              autoComplete="new-password"
              maxLength={4096}
              value={draft.api_key}
              onChange={(e) => setDraft({ ...draft, api_key: e.target.value })}
            />
          </label>
          {draft.provider === 'openai' && (
            <>
              <label>
                OpenAI project ID · optional
                <input
                  aria-label="OpenAI project ID"
                  maxLength={100}
                  placeholder="proj_…"
                  value={draft.project_id}
                  onChange={(e) => setDraft({ ...draft, project_id: e.target.value })}
                />
              </label>
              <label>
                Organization ID · optional
                <input
                  aria-label="OpenAI organization ID"
                  maxLength={100}
                  placeholder="org-…"
                  value={draft.organization_id}
                  onChange={(e) => setDraft({ ...draft, organization_id: e.target.value })}
                />
              </label>
              <label className="checkbox">
                <input
                  type="checkbox"
                  disabled={legacyChat || draft.api_mode === 'chat'}
                  checked={draft.web_enabled && !legacyChat && draft.api_mode !== 'chat'}
                  onChange={(e) => setDraft({ ...draft, web_enabled: e.target.checked })}
                />{' '}
                Offer public web search for this connection
              </label>
            </>
          )}
          <details className="agent-context-settings">
            <summary>Conversation context settings</summary>
            <label>
              Context profile
              <select
                aria-label="Model context profile"
                value={draft.context_profile}
                onChange={(e) =>
                  setDraft({ ...draft, context_profile: e.target.value as 'auto' | 'compact' | 'expanded' })
                }>
                <option value="auto">Automatic / compact default</option>
                <option value="compact">Compact · smaller models</option>
                <option value="expanded">Expanded · larger models</option>
              </select>
            </label>
            <label>
              Configured context window (tokens)
              <input
                aria-label="Model context window"
                type="number"
                min={2048}
                max={262144}
                step={1024}
                value={draft.context_window}
                onChange={(e) => setDraft({ ...draft, context_window: Number(e.target.value) })}
              />
            </label>
            <p>
              Your configured window is used as the model limit. Below 8K, at most 10 recent tickets are sent;
              32K+ can retrieve up to 100, starting with 30. Oversized evidence is shortened automatically
              with a visible update. Expanded context sends more history and richer excerpts; it can use more
              memory and provider tokens. Conversation scope is saved independently of this window.
            </p>
          </details>
          <label>
            Thinking setting
            <select
              aria-label="Model thinking setting"
              disabled={legacyChat}
              value={legacyChat ? '' : draft.reasoning_effort}
              onChange={(e) => setDraft({ ...draft, reasoning_effort: e.target.value })}>
              <option value="">Model default</option>
              {draft.provider !== 'gemini' && <option value="none">Off · if supported</option>}
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
            </select>
          </label>
          <p className="small">
            {legacyChat
              ? 'GPT-3.5 Turbo uses Model default; reasoning controls and built-in web search are unavailable. Set the context window supported by your deployment.'
              : draft.provider === 'gemini'
                ? 'Use Model default to start. Gemini 3 models do not support turning thinking off.'
                : 'Choose a setting supported by your model. Qwen3 on Ollama supports thinking on/off; named levels enable it.'}
          </p>
          <button className="button primary" disabled={busy}>
            {busy ? <LoaderCircle size={14} className="spin" /> : <Check size={14} />}Save model connection
          </button>
          <p className="small">
            Keys are encrypted in this local server’s data volume and never returned to the browser. Hosted
            models receive retrieved ticket context when you send a chat message.
          </p>
        </form>
      )}
      {notice && (
        <p className="agent-connection-notice" role="status">
          {notice}
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
