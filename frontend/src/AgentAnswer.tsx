import { Children, type ReactNode } from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export type AgentSource = { key: string; summary: string; reason: string; status: string; excerpt: string };
export type AgentChart = {
  title: string;
  unit: string;
  scope: { project?: string; sprint?: string };
  data: { label: string; value: number }[];
};

export function AnswerText({
  content,
  sources = [],
  onTicket,
}: {
  content: string;
  sources?: AgentSource[];
  onTicket: (key: string) => void;
}) {
  const verified = new Set(sources.map((s) => s.key));
  const linkText = (children: ReactNode): ReactNode =>
    Children.map(children, (child) => {
      if (typeof child !== 'string') return child;
      const parts: ReactNode[] = [];
      let position = 0;
      for (const match of child.matchAll(/\b[A-Za-z][A-Za-z0-9_]*-\d+\b/g)) {
        if (!verified.has(match[0])) continue;
        parts.push(child.slice(position, match.index));
        parts.push(
          <button className="agent-inline-ticket" key={match.index} onClick={() => onTicket(match[0])}>
            {match[0]}
          </button>
        );
        position = match.index + match[0].length;
      }
      parts.push(child.slice(position));
      return parts;
    });
  // Some local models escape emphasis markers even when asked for Markdown. Keep code intact.
  const text = content
    .split(/(```[\s\S]*?(?:```|$))/g)
    .map((part, i) => (i % 2 ? part : part.replace(/\\\*\\\*/g, '**')))
    .join('');
  const cell = ({ children }: { children?: ReactNode }) => <td>{linkText(children)}</td>;
  return (
    <Markdown
      remarkPlugins={[remarkGfm]}
      skipHtml
      components={{
        p: ({ children }) => <p>{linkText(children)}</p>,
        li: ({ children }) => <li>{linkText(children)}</li>,
        strong: ({ children }) => <strong>{linkText(children)}</strong>,
        em: ({ children }) => <em>{linkText(children)}</em>,
        td: cell,
        code: ({ children, className }) => {
          const key = typeof children === 'string' ? children.trim() : '';
          return verified.has(key) && !className ? (
            <button className="agent-inline-ticket" onClick={() => onTicket(key)}>
              {key}
            </button>
          ) : (
            <code className={className}>{children}</code>
          );
        },
        table: ({ children }) => (
          <div className="agent-markdown-table">
            <table>{children}</table>
          </div>
        ),
        a: ({ href, children }) =>
          href?.startsWith('ticket:') && verified.has(href.slice(7)) ? (
            <button className="agent-inline-ticket" onClick={() => onTicket(href.slice(7))}>
              {children}
            </button>
          ) : /^https?:\/\//i.test(href || '') ? (
            <a href={href} target="_blank" rel="noreferrer">
              {children}
            </a>
          ) : (
            <span>{children}</span>
          ),
        img: () => null,
      }}>
      {text}
    </Markdown>
  );
}

export function AgentVisuals({ charts }: { charts: AgentChart[] }) {
  return (
    <div className="agent-visuals">
      {charts.map((chart, i) => {
        const max = Math.max(1, ...chart.data.map((d) => d.value));
        return (
          <figure key={i} className="agent-chart" aria-label={chart.title}>
            <figcaption>
              {chart.title}
              <span>
                {chart.scope.project} · {chart.scope.sprint}
              </span>
            </figcaption>
            <div role="img" aria-label={chart.data.map((d) => `${d.label}: ${d.value}`).join(', ')}>
              {chart.data.map((d) => (
                <div className="agent-chart-row" key={d.label}>
                  <span title={d.label}>{d.label}</span>
                  <i>
                    <b
                      style={{
                        width: `${Math.max(d.value ? 1 : 0, (d.value / max) * 100)}%`,
                        background:
                          (
                            { 'to do': '#0c66e4', 'in progress': '#e7791a', done: '#1f845a' } as Record<
                              string,
                              string
                            >
                          )[d.label.toLowerCase()] || '#579dff',
                      }}
                    />
                  </i>
                  <strong>{d.value.toLocaleString()}</strong>
                </div>
              ))}
            </div>
          </figure>
        );
      })}
    </div>
  );
}
