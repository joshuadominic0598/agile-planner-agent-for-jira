export async function api<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api${url}`, options);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === 'string' ? body.detail : `Request failed (${response.status}). Please try again.`);
  }
  return response.json();
}

export function params(values: Record<string, string | number | null | undefined>) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) if (value != null && value !== '') query.set(key, String(value));
  return query.toString();
}

export type AgentEvent = { event: string; [key: string]: unknown };
export async function streamAgent<T>(url: string, body: unknown, onEvent: (event: AgentEvent) => void, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api${url}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal });
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(typeof error?.detail === 'string' ? error.detail : `Request failed (${response.status}).`);
  }
  if (!response.headers.get('content-type')?.includes('application/x-ndjson')) {
    const result = await response.json(); onEvent({ event: 'done', ...result }); return result;
  }
  if (!response.body) throw new Error('This browser cannot read the response stream.');
  const reader = response.body.getReader(); const decoder = new TextDecoder();
  let buffer = ''; let result: T | undefined;
  const consume = (line: string) => {
    if (!line.trim()) return;
    const event = JSON.parse(line) as AgentEvent;
    if (event.event === 'error') throw new Error(String(event.message || 'The response was interrupted.'));
    onEvent(event);
    if (event.event === 'done') result = event as T;
  };
  try {
    for (;;) {
      const { value, done } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      let newline: number;
      while ((newline = buffer.indexOf('\n')) >= 0) { const line = buffer.slice(0, newline); buffer = buffer.slice(newline + 1); consume(line); }
      if (buffer.length > 2_000_000) throw new Error('The response exceeded the stream limit.');
      if (done) break;
    }
    if (buffer.trim()) consume(buffer);
    if (!result) throw new Error('The response ended before completion. Your draft is available to retry.');
    return result;
  } finally { await reader.cancel().catch(() => undefined); reader.releaseLock(); }
}
