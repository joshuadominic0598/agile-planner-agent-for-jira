import { useEffect, useState } from 'react';
import { ChevronRight, LoaderCircle, X } from 'lucide-react';
import { api, params } from './api';

type Conversation = { session_id: string; title: string; preview: string; updated_at: string; message_count: number; dataset_id: string; filename: string };
export default function AgentHistory({ dataset, current, onResume, onClose }: { dataset: string; current: string | null; onResume: (id: string, dataset: string) => void; onClose: () => void }) {
  const [items, setItems] = useState<Conversation[]>([]);
  const [allImports, setAllImports] = useState(false);
  const [offset, setOffset] = useState(0);
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    let live = true; setLoading(true); setError('');
    api<{ sessions: Conversation[]; has_more: boolean; next_offset: number }>(`${allImports ? '/agent/conversations' : `/datasets/${dataset}/agent/sessions`}?${params({ offset, limit: 20 })}`).then(data => {
      if (live) { setItems(old => offset ? [...old, ...data.sessions] : data.sessions); setMore(data.has_more); }
    }).catch(e => { if (live) setError(e.message); }).finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [dataset, offset, allImports]);
  return <section className="agent-history" aria-label="Conversation history">
    <header><div><h3>Conversations</h3><p>Saved chats for this CSV. Open any chat to view or continue it.</p></div><button type="button" className="agent-history-close" aria-label="Close conversation history" onClick={onClose}><X size={18} /></button></header>
    <label className="checkbox"><input type="checkbox" aria-label="Include conversations from all CSV imports" checked={allImports} onChange={e => { setOffset(0); setAllImports(e.target.checked); }} /> Include all CSV imports</label>
    {items.map(item => <button type="button" key={item.session_id} className="agent-history-item" aria-current={item.session_id === current ? 'true' : undefined} onClick={() => onResume(item.session_id,item.dataset_id)}><strong>{item.title}</strong><small>{item.filename} · {new Date(item.updated_at).toLocaleString()} · {item.message_count} messages</small><span>{item.preview}</span><ChevronRight size={16} /></button>)}
    {!loading && !items.length && <p>No saved conversations yet. Your first completed exchange saves the chat.</p>}
    {loading && <p role="status"><LoaderCircle size={15} className="spin" /> Loading conversations…</p>}
    {error && <p role="alert" className="error">{error}</p>}
    {more && <button className="button secondary" disabled={loading} onClick={() => setOffset(items.length)}>Load more conversations</button>}
  </section>;
}
