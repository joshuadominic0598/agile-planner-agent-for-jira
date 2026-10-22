import { ExternalLink } from 'lucide-react';
import type { AgentSource } from './AgentAnswer';

type Evidence = {
  context_description?: string;
  scope?: { project: string; sprint: string };
  snapshot_metrics?: boolean;
  sources?: AgentSource[];
  tools?: { tool: string }[];
  web_sources?: { title: string; url: string }[];
};

export default function AgentResponseFooter({
  message,
  onTicket,
}: {
  message: Evidence;
  onTicket: (key: string) => void;
}) {
  const { scope, sources = [], tools = [], web_sources = [] } = message;
  const web = web_sources.filter((source) => /^https?:\/\//i.test(source.url));
  const counts = tools.reduce<Record<string, number>>((all, tool) => {
    all[tool.tool] = (all[tool.tool] || 0) + 1;
    return all;
  }, {});
  if (!scope && !message.context_description && !sources.length && !tools.length && !web.length) return null;
  const label = [scope?.project || 'All projects', scope?.sprint || 'All issues'].join(' · ');
  return (
    <details className="agent-response-footer">
      <summary aria-label="Response details">
        <span className="agent-footer-scope" title={label}>
          {label}
        </span>
        <span>
          {sources.length} {sources.length === 1 ? 'ticket' : 'tickets'} · {tools.length} tool{' '}
          {tools.length === 1 ? 'call' : 'calls'}
          {web.length ? ` · ${web.length} links` : ''}
        </span>
      </summary>
      <div className="agent-footer-content">
        <p className="agent-evidence-note">
          CSV snapshot{message.snapshot_metrics ? ' · Counts cover all tickets in the requested scope.' : ''}
        </p>
        {message.context_description && (
          <p className="agent-evidence-note">Conversation scope: {message.context_description}</p>
        )}
        {!!sources.length && (
          <section aria-label="Ticket sources">
            <h4>Ticket sources</h4>
            {sources.map((source) => (
              <button
                key={source.key}
                className="agent-source"
                title={source.excerpt}
                onClick={() => onTicket(source.key)}>
                <span>
                  {source.key} <ExternalLink size={12} />
                </span>
                <strong>{source.summary}</strong>
                <small>
                  {source.reason} · {source.status}
                </small>
              </button>
            ))}
          </section>
        )}
        {!!tools.length && (
          <section aria-label="Tools used">
            <h4>Tools used</h4>
            <div className="agent-footer-tools">
              {Object.entries(counts).map(([name, count]) => (
                <span key={name}>
                  {name.replaceAll('_', ' ')} ×{count}
                </span>
              ))}
            </div>
          </section>
        )}
        {!!web.length && (
          <section className="agent-web-sources" aria-label="Web sources">
            <h4>Web sources</h4>
            {web.map((source, i) => (
              <a key={i} href={source.url} target="_blank" rel="noreferrer">
                {source.title} <ExternalLink size={12} />
              </a>
            ))}
          </section>
        )}
      </div>
    </details>
  );
}
