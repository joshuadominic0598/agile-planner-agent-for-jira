import { useEffect, useLayoutEffect, useState } from 'react';
import { ChevronDown, LoaderCircle } from 'lucide-react';

export type Activity = { message: string; tool?: string; ok?: boolean };
export default function AgentProgress({
  activity,
  working,
  responding,
  tools = [],
}: {
  activity: Activity[];
  working: boolean;
  responding: boolean;
  tools?: { tool: string; ok: boolean }[];
}) {
  const [expanded, setExpanded] = useState(working && !responding);
  const [age, setAge] = useState(0);
  const steps = activity.filter((item) => typeof item.message === 'string' && item.message.trim());
  const last = steps.at(-1)?.message || 'Reading your question';
  const usage = tools.length ? tools : steps.filter((item) => item.tool && item.ok !== undefined);
  const counts = usage.reduce<Record<string, number>>((all, item) => {
    if (item.tool) all[item.tool] = (all[item.tool] || 0) + 1;
    return all;
  }, {});
  const timeline = steps.filter((item) => item.tool !== 'calculator');
  const live = working && !responding;
  useLayoutEffect(() => {
    if (responding) setExpanded(false);
  }, [responding]);
  useEffect(() => {
    setAge(0);
    if (!live) return;
    const start = Date.now();
    const timer = setInterval(() => setAge(Math.floor((Date.now() - start) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [live, last]);
  if (!steps.length && !tools.length && !working) return null;
  const waiting = /analyzing|connecting|preparing.*answer/i.test(last);
  const label =
    live && waiting && age >= 8
      ? ['Reviewing retrieved context…', 'Considering your question…', 'Still waiting for the model…'][
          Math.floor((age - 8) / 8) % 3
        ]
      : last;
  return (
    <div className="agent-progress">
      <button
        type="button"
        className="agent-progress-toggle"
        aria-label={expanded ? 'Collapse agent activity' : 'Show agent activity'}
        aria-expanded={expanded}
        onClick={() => setExpanded(!expanded)}>
        {live && <LoaderCircle size={12} className="spin" />}
        <span>
          {live ? 'Working' : 'Actions'} ·{' '}
          {usage.length
            ? `${usage.length} tool ${usage.length === 1 ? 'call' : 'calls'}`
            : `${steps.length} ${steps.length === 1 ? 'update' : 'updates'}`}
        </span>
        <ChevronDown size={12} className={expanded ? 'agent-chevron-open' : ''} />
      </button>
      {expanded && (
        <div className="agent-activity-content">
          {!!Object.keys(counts).length && (
            <div className="agent-footer-tools" aria-label="Tool usage summary">
              {Object.entries(counts).map(([name, count]) => (
                <span key={name}>
                  {name.replaceAll('_', ' ')} ×{count}
                </span>
              ))}
            </div>
          )}
          {live ? (
            <div className="agent-flow" role="log" aria-label="Agent activity">
              {timeline.slice(-4, -1).map((step, i) => (
                <p className="agent-flow-message" key={i}>
                  {step.message}
                </p>
              ))}
              <p className="agent-flow-message agent-progress-current" role="status">
                {label}
                {age >= 8 && <small> · {age}s since last step</small>}
              </p>
            </div>
          ) : (
            <ol className="agent-activity-log" aria-label="Agent activity">
              {timeline.map((step, i) => (
                <li key={i} className={step.ok === false ? 'activity-unavailable' : ''}>
                  {step.message}
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </div>
  );
}
