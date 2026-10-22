import { useEffect, useState } from 'react';
import { Copy, ChevronLeft, ChevronRight } from 'lucide-react';
import { api, params } from './api';

type Ticket = { key: string; summary: string; reporter: string; assignee: string; status: string };
type Pair = { id: string; left: Ticket; right: Ticket; exact: boolean; similarity: number; reason: string };
type Result = {
  ready: boolean;
  message?: string;
  eligible_tickets?: number;
  total: number;
  pairs: Pair[];
  method?: string;
  definition?: string;
};
export default function DuplicateTickets({
  dataset,
  project,
  onOpen,
}: {
  dataset: string;
  project: string;
  onOpen: (key: string) => void;
}) {
  const [data, setData] = useState<Result | null>(null);
  const [error, setError] = useState('');
  const [page, setPage] = useState(1);
  const [threshold, setThreshold] = useState('0.88');
  useEffect(() => {
    setPage(1);
  }, [project, threshold]);
  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout>;
    setData(null);
    setError('');
    const load = async () => {
      try {
        const result = await api<Result>(
          `/datasets/${dataset}/duplicates?${params({ project, page, threshold })}`
        );
        if (live) {
          setData(result);
          if (!result.ready) timer = setTimeout(load, 15000);
        }
      } catch (e) {
        if (live) setError((e as Error).message);
      }
    };
    void load();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [dataset, project, page, threshold]);
  return (
    <section className="card duplicate-tickets" aria-label="Potential duplicate tickets">
      <div className="card-heading">
        <div>
          <h2>
            <Copy size={18} /> Similar To Do tickets
          </h2>
          <p className="card-subtitle">
            Spot overlapping work before you plan it. Completed and in-progress tickets are excluded.
          </p>
        </div>
        <label>
          Minimum similarity
          <select
            aria-label="Duplicate similarity threshold"
            value={threshold}
            onChange={(e) => setThreshold(e.target.value)}>
            <option value="0.88">88%</option>
            <option value="0.95">95%</option>
            <option value="1">Exact content only</option>
          </select>
        </label>
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {!data && !error && <p className="muted">Comparing indexed ticket content…</p>}
      {data && !data.ready && (
        <p className="muted">{data.message} Prepare the index in Sprint Agent → Configure.</p>
      )}
      {data?.ready && (
        <>
          <p className="small muted">
            {data.eligible_tickets} To Do tickets checked · {data.total} potential pairs. {data.method}
          </p>
          {!data.total && <p>No matching To Do tickets above this threshold.</p>}
          {data.pairs.map((pair) => (
            <article className="duplicate-pair" key={pair.id}>
              <header>
                <strong>
                  {pair.exact ? 'Same title & description' : `${Math.round(pair.similarity * 100)}% similar`}
                </strong>
                <span>{pair.reason}</span>
              </header>
              <div>
                {[pair.left, pair.right].map((ticket) => (
                  <button key={ticket.key} onClick={() => onOpen(ticket.key)}>
                    <strong>
                      {ticket.key} · {ticket.summary}
                    </strong>
                    <small>
                      {ticket.status} · Reported by {ticket.reporter || 'Not provided'} · Assigned to{' '}
                      {ticket.assignee || 'Unassigned'}
                    </small>
                  </button>
                ))}
              </div>
            </article>
          ))}
          {data.total > 5 && (
            <div className="pagination">
              <span>
                Page {page} of {Math.ceil(data.total / 5)}
              </span>
              <div>
                <button
                  className="icon-button"
                  aria-label="Previous duplicate pairs"
                  disabled={page === 1}
                  onClick={() => setPage(page - 1)}>
                  <ChevronLeft size={16} />
                </button>
                <button
                  className="icon-button"
                  aria-label="Next duplicate pairs"
                  disabled={page * 5 >= data.total}
                  onClick={() => setPage(page + 1)}>
                  <ChevronRight size={16} />
                </button>
              </div>
            </div>
          )}
          <p className="small muted">
            Similarity is a review signal. Check requirements and relationships before marking anything as a
            duplicate.
          </p>
        </>
      )}
    </section>
  );
}
