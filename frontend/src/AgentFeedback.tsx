import { useState } from 'react';
import { ThumbsDown, ThumbsUp, MessageSquare } from 'lucide-react';
import { api } from './api';

type Feedback = { vote?: number; note?: string };
export default function AgentFeedback({ runId, initial }: { runId?: string; initial?: Feedback }) {
  const [value, setValue] = useState<Feedback>(initial || {});
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState(initial?.note || '');
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');
  if (!runId) return null;
  const submit = async (change: Feedback) => {
    setBusy(true);
    setStatus('');
    try {
      const result = await api<{ feedback: Feedback }>(`/agent/runs/${runId}/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(change),
      });
      setValue(result.feedback);
      setEditing(false);
      setStatus('Feedback saved');
    } catch (e) {
      setStatus((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="agent-feedback" aria-label="Response feedback">
      <div>
        <span role="status">{status}</span>
        <button
          type="button"
          aria-label="Helpful response"
          title="Helpful response"
          aria-pressed={value.vote === 1}
          disabled={busy}
          onClick={() => void submit({ vote: value.vote === 1 ? 0 : 1 })}>
          <ThumbsUp size={14} />
        </button>
        <button
          type="button"
          aria-label="Unhelpful response"
          title="Unhelpful response"
          aria-pressed={value.vote === -1}
          disabled={busy}
          onClick={() => void submit({ vote: value.vote === -1 ? 0 : -1 })}>
          <ThumbsDown size={14} />
        </button>
        <button
          type="button"
          title="Add an error report or feedback"
          disabled={busy}
          onClick={() => setEditing(!editing)}>
          <MessageSquare size={14} /> Respond
        </button>
      </div>
      {editing && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void submit({ note });
          }}>
          <label>
            Feedback or error report
            <input
              autoFocus
              aria-label="Response feedback note"
              maxLength={300}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="What could be improved? Press Enter to save."
            />
          </label>
          <small>{note.length}/300</small>
          <button type="submit" disabled={busy || !note.trim()}>
            {busy ? 'Saving…' : 'Save feedback'}
          </button>
        </form>
      )}
    </div>
  );
}
