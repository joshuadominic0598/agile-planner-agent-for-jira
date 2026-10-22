import { useEffect, useLayoutEffect, useRef, useState, type FormEvent } from 'react';
import {
  Bot,
  ChevronDown,
  LoaderCircle,
  MessageSquarePlus,
  Paperclip,
  Send,
  Settings2,
  History,
  X,
  Maximize2,
  Minimize2,
} from 'lucide-react';
import { api, params, streamAgent } from './api';
import './agent.css';
import { AnswerText, AgentVisuals, type AgentChart } from './AgentAnswer';
import AgentHistory from './AgentHistory';
import AgentResponseFooter from './AgentResponseFooter';
import AgentProgress from './AgentProgress';
import { useAgentWindow, type ResizeEdge } from './useAgentWindow';
import AgentProjectContext from './AgentProjectContext';
import { useAgentBack } from './useAgentBack';
import AgentFeedback from './AgentFeedback';
import AgentConnections, { type ModelChoice } from './AgentConnections';
import EmbeddingChoice from './EmbeddingChoice';

type AgentStatus = {
  status: string;
  progress: number;
  message: string;
  metadata: {
    tickets?: number;
    chunks?: number;
    edges?: number;
    embedding_model?: string;
    chunk_characters?: number;
    chunk_overlap?: number;
  };
  model: { available: boolean; provider: string; name: string; web_available: boolean };
  choices: ModelChoice[];
  embedding: { provider: string; model: string; preset?: string; private_local?: boolean };
  note: string;
};
type Source = { key: string; summary: string; reason: string; status: string; excerpt: string };
type Message = {
  client_id?: string;
  run_id?: string;
  feedback?: { vote?: number; note?: string };
  details_markdown?: string;
  id?: number;
  context_description?: string;
  context_inherited?: boolean;
  context_usage?: { profile: string; context_window: number; history_messages: number };
  charts?: AgentChart[];
  activity?: { message: string; tool?: string; ok?: boolean }[];
  skill?: string;
  page_hint?: { project: string; sprint: string; view: string; ticket?: string };
  model?: string;
  connection_id?: string;
  role: 'user' | 'assistant';
  content: string;
  attachments?: string[];
  mode?: string;
  sources?: Source[];
  tools?: { tool: string; ok: boolean; result_count: number }[];
  snapshot_metrics?: boolean;
  web_sources?: { title: string; url: string; start_index?: number; end_index?: number }[];
  scope?: { project: string; sprint: string };
};
type PendingMessage = {
  id: string;
  text: string;
  attachments: { key: string; title: string }[];
  request: Record<string, unknown>;
};
type ActiveRun = {
  id: string;
  answerId: string;
  original: PendingMessage;
  steered: PendingMessage[];
  reserved: number;
  failed?: boolean;
  traceId?: string;
  canSteer: Promise<boolean>;
  activate: (started: boolean) => void;
};
type Reply = Message & { session_id: string };
type HistoryPage = {
  session_id: string;
  messages: Message[];
  has_more?: boolean;
  before_id?: number;
  context_description?: string;
};
export type Attachment = { key: string; title: string; sequence: number };
const read = (key: string) => {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
};
const save = (key: string, value: string) => {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* Chat works without browser storage. */
  }
};

function useAgentStatus(dataset?: string) {
  const [status, setStatus] = useState<AgentStatus | null>(null);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (!dataset) return;
    let live = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const result = await api<AgentStatus>(`/datasets/${dataset}/agent/status`);
        if (live) {
          setStatus(result);
          setError('');
          timer = setTimeout(poll, result.status === 'building' ? 1500 : 15000);
        }
      } catch (e) {
        if (live) {
          setError((e as Error).message);
          timer = setTimeout(poll, 15000);
        }
      }
    };
    void poll();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [dataset, revision]);
  return { status, error, refresh: () => setRevision((i) => i + 1) };
}

function IndexControls({
  dataset,
  status,
  refresh,
}: {
  dataset: string;
  status: AgentStatus | null;
  refresh: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [embeddingPreset, setEmbeddingPreset] = useState('');
  useEffect(() => {
    setEmbeddingPreset(status?.embedding.preset || (status?.embedding.provider === 'local' ? 'lexical' : ''));
  }, [dataset, status?.embedding.preset, status?.embedding.provider]);
  const build = async () => {
    setBusy(true);
    setError('');
    try {
      await api(`/datasets/${dataset}/agent/index`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(embeddingPreset ? { embedding_preset: embeddingPreset } : {}),
      });
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="agent-index">
      <strong>{status?.status === 'ready' ? 'Ticket context is ready' : 'Prepare ticket context'}</strong>
      <p>{status?.message || 'Checking the local ticket index…'}</p>
      {status?.status === 'building' && (
        <progress aria-label="Agent index progress" max={100} value={status.progress || undefined} />
      )}
      {status?.status === 'ready' && (
        <p className="small muted">
          {status.metadata.tickets?.toLocaleString()} tickets · {status.metadata.chunks?.toLocaleString()}{' '}
          chunks · {status.metadata.edges?.toLocaleString()} graph connections
          <br />
          Vectors: {status.metadata.embedding_model}
          {status.metadata.chunk_characters && (
            <>
              {' '}
              · max {status.metadata.chunk_characters.toLocaleString()} characters ·{' '}
              {status.metadata.chunk_overlap} overlap
            </>
          )}
        </p>
      )}
      <EmbeddingChoice
        value={embeddingPreset}
        onChange={setEmbeddingPreset}
        disabled={!status || busy || status.status === 'building'}
      />
      <p className="small muted">
        Changing the model or chunk size rebuilds this import’s index. Other imports keep their own choice.
      </p>
      <button
        className="button secondary"
        disabled={!status || busy || status.status === 'building'}
        onClick={build}>
        {busy || status?.status === 'building' ? (
          <LoaderCircle className="spin" size={15} />
        ) : (
          <Settings2 size={15} />
        )}
        {status?.status === 'ready' ? 'Rebuild ticket index' : 'Prepare agent index'}
      </button>
      {status?.status === 'ready' && (
        <p className="small muted">
          Saved with this import · reused in every conversation and after refresh.
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export function AgentSetup({ dataset }: { dataset: string }) {
  const { status, error, refresh } = useAgentStatus(dataset);
  return (
    <section className="card agent-setup" aria-label="Sprint Agent setup">
      <div>
        <span className="eyebrow">SPRINT AGENT · OPTIONAL SETUP</span>
        <h2>Give your project a conversation.</h2>
        <p>Index ticket details and exported relationships now, or prepare the agent later from the chat.</p>
      </div>
      <IndexControls dataset={dataset} status={status} refresh={refresh} />
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <p className="small muted">
        {status?.model.available
          ? `AI connection: ${status.model.name}. Retrieved context goes to your configured provider when you send a question.`
          : 'Connect an AI model in the chat’s Configure menu to start a conversation.'}{' '}
        {status?.embedding.private_local
          ? 'Private semantic indexing runs in local Ollama. Ticket text stays on this device.'
          : status?.embedding.provider !== 'local' && status
            ? 'Semantic indexing sends ticket text to the configured embedding provider.'
            : 'The default keyword, vector and graph index stays on this server.'}
      </p>
    </section>
  );
}

export default function AgentChat({
  dataset,
  openRequest = 0,
  project = '',
  sprint = '',
  activeSprint = '',
  page = '',
  pageTicket = '',
  attachment,
  onOpenTicket,
  onResumeConversation,
}: {
  dataset?: string;
  openRequest?: number;
  project?: string;
  sprint?: string;
  activeSprint?: string;
  page?: string;
  pageTicket?: string;
  attachment?: Attachment;
  onOpenTicket?: (key: string) => void;
  onResumeConversation?: (dataset: string, session: string) => Promise<void>;
}) {
  const windowState = useAgentWindow();
  const panel = useRef<HTMLElement | null>(null);
  const jump = useRef<'answer' | 'latest' | null>(null);
  const [expandedAnswers, setExpandedAnswers] = useState<Record<number, boolean>>({});
  const [open, setOpen] = useState(() => read('sprintlens.chat.open') === dataset);
  const [settings, setSettings] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  useEffect(() => {
    if (openRequest) {
      setOpen(true);
      setSettings(false);
      setShowHistory(false);
    }
  }, [openRequest]);
  const [contextDescription, setContextDescription] = useState('');
  const [resetContext, setResetContext] = useState(false);
  const [contextOptions, setContextOptions] = useState(false);
  const [effort, setEffort] = useState<'low' | 'standard' | 'high'>(() => {
    const value = read('agileplanner.agent.effort');
    return value === 'low' || value === 'high' ? value : 'standard';
  });
  const [usePageContext, setUsePageContext] = useState(
    () => read('sprintlens.agent.pageContext') !== 'false'
  );
  const [useConversationContext, setUseConversationContext] = useState(
    () => read('sprintlens.agent.conversationContext') !== 'false'
  );
  const [hasOlder, setHasOlder] = useState(false);
  const [beforeId, setBeforeId] = useState<number>();
  const [loadingOlder, setLoadingOlder] = useState(false);
  const body = useRef<HTMLDivElement | null>(null);
  const scrollRestore = useRef<{ height: number; top: number } | null>(null);
  const [draft, setDraft] = useState('');
  const [attached, setAttached] = useState<{ key: string; title: string }[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [session, setSession] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const activeRun = useRef<ActiveRun | null>(null);
  const [deliveryMode, setDeliveryMode] = useState<'queue' | 'steer'>(() =>
    read('agileplanner.agent.deliveryMode') === 'steer' ? 'steer' : 'queue'
  );
  const pendingKey = `agileplanner.pending.${dataset || 'none'}`;
  const [queued, setQueued] = useState<PendingMessage[]>(() => {
    try {
      const saved = JSON.parse(read(pendingKey) || '[]');
      return Array.isArray(saved)
        ? saved.filter(
            (m) =>
              typeof m.id === 'string' &&
              typeof m.text === 'string' &&
              m.request &&
              Array.isArray(m.attachments)
          )
        : [];
    } catch {
      return [];
    }
  });
  const queueRef = useRef<PendingMessage[]>(queued);
  const [queuePaused, setQueuePaused] = useState(queued.length > 0);
  const pausedRef = useRef(queued.length > 0);
  const [steerCount, setSteerCount] = useState(0);
  const [steerSending, setSteerSending] = useState(false);
  const [notice, setNotice] = useState<{ title: string; message: string; configure?: boolean } | null>(null);
  const noticeButton = useRef<HTMLButtonElement>(null);
  const mounted = useRef(true);
  const runNext = useRef<(item: PendingMessage) => Promise<void>>(async () => {});
  const sessionRef = useRef(session);
  sessionRef.current = session;
  const updateQueue = (items: PendingMessage[]) => {
    queueRef.current = items;
    setQueued(items);
    const running = activeRun.current;
    const retained = running && busyRef.current ? [running.original, ...running.steered, ...items] : items;
    save(pendingKey, JSON.stringify([...new Map(retained.map((m) => [m.id, m])).values()]));
  };
  const pauseQueue = (value: boolean) => {
    pausedRef.current = value;
    setQueuePaused(value);
  };
  const changeDeliveryMode = (value: 'queue' | 'steer') => {
    setDeliveryMode(value);
    save('agileplanner.agent.deliveryMode', value);
  };
  useEffect(() => {
    if (notice) noticeButton.current?.focus();
  }, [notice]);
  const [elapsed, setElapsed] = useState(0);
  const [restoring, setRestoring] = useState(false);
  const [error, setError] = useState(
    queued.length ? 'Pending messages restored. Resume or edit them when ready.' : ''
  );
  const [failedRun, setFailedRun] = useState<string>();
  const [web, setWeb] = useState(false);
  const [connection, setConnection] = useState(() => read('sprintlens.agent.connection') || '');
  const { status, error: statusError, refresh } = useAgentStatus(dataset);
  const storageKey = `sprintlens.chat.${dataset}`;
  const controller = useRef<AbortController | null>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const composer = useRef<HTMLFormElement>(null);
  const launcher = useRef<HTMLButtonElement>(null);
  const backWithinAgent = () => {
    if (contextOptions) setContextOptions(false);
    else if (settings) setSettings(false);
    else if (showHistory) setShowHistory(false);
  };
  useAgentBack(open, backWithinAgent, panel);
  useEffect(() => {
    if (!busy) return;
    const start = Date.now();
    setElapsed(0);
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [busy]);
  useEffect(() => {
    if (!open || !windowState.full) return;
    const dock = panel.current?.closest('.agent-dock');
    const siblings = Array.from(dock?.parentElement?.children || []).filter(
      (el) => el !== dock
    ) as HTMLElement[];
    const previous = siblings.map((el) => el.inert);
    siblings.forEach((el) => {
      el.inert = true;
    });
    return () =>
      siblings.forEach((el, i) => {
        el.inert = previous[i];
      });
  }, [open, windowState.full]);
  const choices = status?.choices || [];
  const selectedConnection = choices.find((c) => c.id === connection) || choices[0];
  const selectConnection = (id: string) => {
    setConnection(id);
    save('sprintlens.agent.connection', id);
    setWeb(false);
  };
  const ready = !!dataset && status?.status === 'ready' && !!selectedConnection;

  useEffect(() => {
    const stored = read(storageKey);
    const id =
      stored === null
        ? read(`sprintlens.chat.${dataset}.${read(`sprintlens.project.${dataset}`) || project}`)
        : stored;
    if (!dataset || !id) return;
    let live = true;
    setRestoring(true);
    api<HistoryPage>(`/datasets/${dataset}/agent/sessions/${id}?${params({ project })}`)
      .then((data) => {
        if (live) {
          jump.current = 'latest';
          setMessages(data.messages);
          setSession(data.session_id);
          setContextDescription(data.context_description || '');
          setHasOlder(!!data.has_more);
          setBeforeId(data.before_id);
          save(storageKey, data.session_id);
        }
      })
      .catch((e) => {
        if (live) {
          setError(`Could not restore chat: ${e.message}`);
          save(storageKey, '');
        }
      })
      .finally(() => {
        if (live) setRestoring(false);
      });
    return () => {
      live = false;
    };
  }, [dataset, storageKey]);
  useEffect(() => {
    if (!attachment) return;
    setAttached((previous) => [...previous.filter((i) => i.key !== attachment.key), attachment].slice(-8));
    setOpen(true);
  }, [attachment]);
  useEffect(() => {
    if (open) {
      input.current?.focus({ preventScroll: true });
      save('sprintlens.chat.open', '');
    }
  }, [open]);
  useLayoutEffect(() => {
    const el = body.current;
    if (!el || !open || showHistory) return;
    el.style.setProperty('--agent-reading-height', `${Math.max(150, el.clientHeight - 24)}px`);
    if (scrollRestore.current) {
      el.scrollTop = scrollRestore.current.top + el.scrollHeight - scrollRestore.current.height;
      scrollRestore.current = null;
    } else if (jump.current) {
      if (jump.current === 'latest') el.scrollTop = el.scrollHeight;
      else {
        const article = el.querySelector('.agent-message:last-child');
        if (article)
          el.scrollTop += article.getBoundingClientRect().top - el.getBoundingClientRect().top - 12;
      }
      jump.current = null;
    }
  }, [messages, open, showHistory, windowState.frame.height, windowState.full]);
  useLayoutEffect(() => {
    if (!open || !body.current) return;
    body.current.scrollTop = settings || showHistory ? 0 : body.current.scrollHeight;
  }, [open, settings, showHistory]);
  useEffect(() => {
    if (!contextOptions) return;
    composer.current
      ?.querySelector<HTMLButtonElement>('[aria-label="Close message context"]')
      ?.focus({ preventScroll: true });
    const dismiss = (event: PointerEvent) => {
      if (!composer.current?.contains(event.target as Node)) setContextOptions(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        setContextOptions(false);
        composer.current?.querySelector<HTMLButtonElement>('[aria-label="Message context"]')?.focus();
      }
    };
    document.addEventListener('pointerdown', dismiss);
    document.addEventListener('keydown', escape, true);
    return () => {
      document.removeEventListener('pointerdown', dismiss);
      document.removeEventListener('keydown', escape, true);
    };
  }, [contextOptions]);
  const close = () => {
    windowState.setFull(false);
    setOpen(false);
    launcher.current?.focus();
  };
  const newChat = () => {
    updateQueue([]);
    pauseQueue(false);
    sessionRef.current = null;
    setMessages([]);
    setExpandedAnswers({});
    setSession(null);
    setError('');
    setDraft('');
    setAttached([]);
    setContextDescription('');
    setResetContext(false);
    setHasOlder(false);
    setBeforeId(undefined);
    setShowHistory(false);
    setSettings(false);
    save(storageKey, '');
  };
  const resume = async (id: string, targetDataset = dataset) => {
    if (!dataset || busy || restoring || loadingOlder) return;
    setRestoring(true);
    setError('');
    try {
      if (targetDataset && targetDataset !== dataset && onResumeConversation) {
        await onResumeConversation(targetDataset, id);
        return;
      }
      const data = await api<HistoryPage>(`/datasets/${dataset}/agent/sessions/${id}`);
      jump.current = 'latest';
      setMessages(data.messages);
      setSession(id);
      save(storageKey, id);
      setContextDescription(data.context_description || '');
      setResetContext(false);
      setHasOlder(!!data.has_more);
      setBeforeId(data.before_id);
      setDraft('');
      setAttached([]);
      setShowHistory(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRestoring(false);
    }
  };
  const older = async () => {
    if (!dataset || !session || !beforeId || loadingOlder || busy) return;
    setLoadingOlder(true);
    try {
      const data = await api<HistoryPage>(
        `/datasets/${dataset}/agent/sessions/${session}?${params({ before_id: beforeId })}`
      );
      if (body.current)
        scrollRestore.current = { height: body.current.scrollHeight, top: body.current.scrollTop };
      setMessages((previous) => [...data.messages, ...previous]);
      setHasOlder(!!data.has_more);
      setBeforeId(data.before_id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoadingOlder(false);
    }
  };
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      controller.current?.abort();
    };
  }, []);
  const readinessNotice = () => {
    if (!dataset)
      return {
        title: 'Import tickets first',
        message: 'Load your Jira export before messaging Sprint Agent.',
      };
    if (status?.status !== 'ready')
      return {
        title: 'Agent index is not ready',
        message:
          'Ticket search is still being prepared or needs to be built. Open Configure to check the index, then try again.',
        configure: true,
      };
    return {
      title: 'AI model is not configured',
      message: 'Add or select an AI model connection in Configure before sending a message.',
      configure: true,
    };
  };
  const run = async (item: PendingMessage) => {
    if (busyRef.current || !mounted.current) return;
    let activate = (_started: boolean) => {};
    const canSteer = new Promise<boolean>((resolve) => {
      activate = resolve;
    });
    const current: ActiveRun = {
      id: crypto.randomUUID(),
      answerId: crypto.randomUUID(),
      original: item,
      steered: [],
      reserved: 0,
      canSteer,
      activate,
    };
    save(pendingKey, JSON.stringify([item, ...queueRef.current]));
    activeRun.current = current;
    busyRef.current = true;
    setBusy(true);
    setSteerCount(0);
    setFailedRun(undefined);
    setError('');
    jump.current = 'answer';
    setMessages((previous) => [
      ...previous,
      {
        client_id: item.id,
        role: 'user',
        content: item.text,
        attachments: item.attachments.map((a) => a.key),
      },
      {
        client_id: current.answerId,
        role: 'assistant',
        content: '',
        mode: 'ai',
        model: selectedConnection?.model,
        activity: [],
        charts: [],
      },
    ]);
    const previousContextDescription = contextDescription;
    const abort = new AbortController();
    controller.current = abort;
    try {
      const reply = await streamAgent<Reply>(
        `/datasets/${dataset}/agent/chat`,
        {
          ...item.request,
          message: item.text,
          request_id: current.id,
          session_id: sessionRef.current,
          attachments: item.attachments.map((a) => a.key),
          stream: true,
        },
        (event) => {
          if (event.event === 'run') {
            current.traceId = event.run_id as string | undefined;
            current.activate(true);
            return;
          }
          if (event.event === 'heartbeat') return;
          if (event.event === 'context') {
            setContextDescription(String(event.context_description || ''));
            return;
          }
          setMessages((previous) => {
            const answer = previous.find((m) => m.client_id === current.answerId);
            if (!answer) return previous;
            const next = { ...answer };
            if (event.event === 'steering') {
              next.content = '';
              next.charts = [];
              next.tools = [];
              next.activity = [{ message: String(event.message || 'Applying your steering messages.') }];
              return [...previous.filter((m) => m.client_id !== current.answerId), next];
            }
            if (event.event === 'text_delta') next.content += String(event.text || '');
            if (event.event === 'activity')
              next.activity = [
                ...(next.activity || []),
                {
                  message: String(event.message || ''),
                  tool: event.tool as string | undefined,
                  ok: event.ok as boolean | undefined,
                },
              ];
            if (event.event === 'tool_usage') next.tools = event.tools as Message['tools'];
            if (event.event === 'chart')
              next.charts = [...(next.charts || []), event as unknown as AgentChart];
            if (event.event === 'done')
              Object.assign(next, event, { role: 'assistant', client_id: current.answerId });
            return previous.map((m) => (m.client_id === current.answerId ? next : m));
          });
        },
        abort.signal
      );
      sessionRef.current = reply.session_id;
      setSession(reply.session_id);
      save(storageKey, reply.session_id);
      save(pendingKey, JSON.stringify(queueRef.current));
      setContextDescription(reply.context_description || '');
      setResetContext(false);
      setMessages((previous) =>
        previous.map((m) =>
          m.client_id === current.answerId ? { ...reply, role: 'assistant', client_id: current.answerId } : m
        )
      );
    } catch (e) {
      current.failed = true;
      setFailedRun(current.traceId);
      pauseQueue(true);
      setContextDescription(previousContextDescription);
      const ids = new Set([item.id, current.answerId, ...current.steered.map((m) => m.id)]);
      setMessages((previous) => previous.filter((m) => !ids.has(m.client_id || '')));
      // Keep newly typed drafts and preserve failed requests for an explicit retry.
      updateQueue([item, ...current.steered, ...queueRef.current]);
      const problem = (e as Error).message;
      if (/ticket index|index settings|preparing ticket|preparing the agent index/i.test(problem)) {
        setNotice({ title: 'Agent index is not ready', message: problem, configure: true });
        refresh();
      } else if (/connect an AI model|AI model unavailable|model.*not configured/i.test(problem)) {
        setNotice({ title: 'AI model is not configured', message: problem, configure: true });
        refresh();
      }
      setError(
        (e as Error).name === 'AbortError'
          ? 'Generation stopped. Pending messages are kept below; resume when ready.'
          : (e as Error).message
      );
    } finally {
      current.activate(false);
      controller.current = null;
      activeRun.current = null;
      busyRef.current = false;
      if (mounted.current) {
        setBusy(false);
        setSteerCount(0);
        input.current?.focus({ preventScroll: true });
      }
    }
  };
  runNext.current = run;
  useEffect(() => {
    if (busy || queuePaused || !queued.length || restoring || loadingOlder || steerSending) return;
    const timer = setTimeout(() => {
      if (busyRef.current || pausedRef.current || !queueRef.current.length) return;
      if (!ready) {
        pauseQueue(true);
        setNotice(readinessNotice());
        return;
      }
      const [next, ...rest] = queueRef.current;
      // Retain the active item until it succeeds, so refresh can recover it.
      queueRef.current = rest;
      setQueued(rest);
      void runNext.current(next);
    }, 0);
    return () => clearTimeout(timer);
  }, [busy, queued, queuePaused, ready, restoring, loadingOlder, steerSending]);
  const send = async (event: FormEvent) => {
    event.preventDefault();
    if (!draft.trim() || restoring || loadingOlder || steerSending) return;
    setContextOptions(false);
    if (!ready) {
      setNotice(readinessNotice());
      return;
    }
    const current = activeRun.current;
    if (current && deliveryMode === 'steer' && current.reserved >= 4) {
      setNotice({
        title: 'Please wait for responses',
        message:
          'You can add up to four steering messages to one response. Wait for the agent to finish before sending more.',
      });
      return;
    }
    const item: PendingMessage = {
      id: crypto.randomUUID(),
      text: draft.trim(),
      attachments: [...attached],
      request: {
        project,
        sprint,
        page,
        page_ticket: pageTicket,
        active_sprint: activeSprint,
        mode: 'ai',
        allow_web: web,
        effort,
        connection_id: selectedConnection?.id,
        reset_context: busyRef.current ? false : resetContext,
        use_page_context: usePageContext,
        use_conversation_context: useConversationContext,
      },
    };
    setDraft('');
    setAttached([]);
    if (current && deliveryMode === 'steer') {
      current.reserved += 1;
      setSteerSending(true);
      try {
        if (!(await current.canSteer)) {
          updateQueue([...queueRef.current, item]);
          return;
        }
        const response = await fetch(`/api/datasets/${dataset}/agent/chat/${current.id}/steer`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            id: item.id,
            message: item.text,
            attachments: item.attachments.map((a) => a.key),
          }),
        });
        if (response.status === 409) {
          updateQueue([...queueRef.current, item]);
        } else if (!response.ok) {
          const data = await response.json().catch(() => null);
          throw new Error(data?.detail || 'Could not send the steering message. Try again.');
        } else {
          if (current.failed) {
            updateQueue([...queueRef.current, item]);
            pauseQueue(true);
            return;
          }
          current.steered.push(item);
          save(pendingKey, JSON.stringify([current.original, ...current.steered, ...queueRef.current]));
          if (activeRun.current === current) setSteerCount(current.reserved);
          setMessages((previous) => {
            const user: Message = {
              client_id: item.id,
              role: 'user',
              content: item.text,
              attachments: item.attachments.map((a) => a.key),
            };
            const position = previous.findIndex((m) => m.client_id === current.answerId);
            return position < 0
              ? [...previous, user]
              : [...previous.slice(0, position), user, ...previous.slice(position)];
          });
        }
      } catch (e) {
        current.reserved -= 1;
        // Failed deliveries stay visible without overwriting a newer draft.
        updateQueue([...queueRef.current, item]);
        pauseQueue(true);
        setNotice({ title: 'Message was not sent', message: (e as Error).message });
      } finally {
        setSteerSending(false);
        input.current?.focus({ preventScroll: true });
      }
    } else if (busyRef.current || queueRef.current.length) {
      updateQueue([...queueRef.current, item]);
    } else {
      pauseQueue(false);
      void run(item);
    }
  };
  return (
    <div className={`agent-dock${open && windowState.full ? ' agent-dock-full' : ''}`}>
      {open && (
        <section
          ref={panel}
          className={`agent-panel${windowState.full ? ' agent-fullscreen' : ''}`}
          style={
            windowState.full
              ? undefined
              : {
                  left: windowState.frame.x,
                  top: windowState.frame.y,
                  width: windowState.frame.width,
                  height: windowState.frame.height,
                }
          }
          role={windowState.full ? 'dialog' : 'region'}
          aria-modal={windowState.full || undefined}
          aria-label="Sprint Agent chat"
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.stopPropagation();
              if (contextOptions || settings || showHistory) backWithinAgent();
              else if (windowState.full) windowState.setFull(false);
              else close();
            }
            if (e.key === 'Tab' && windowState.full) {
              const nodes = Array.from(
                panel.current?.querySelectorAll<HTMLElement>(
                  'button:not(:disabled),select:not(:disabled),textarea:not(:disabled),input:not(:disabled),summary,a[href]'
                ) || []
              ).filter((n) => n.getClientRects().length);
              const first = nodes[0],
                last = nodes.at(-1);
              if (e.shiftKey && document.activeElement === first) {
                e.preventDefault();
                last?.focus();
              } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault();
                first?.focus();
              }
            }
          }}>
          <header
            className={`agent-header${windowState.full ? '' : ' agent-move'}`}
            tabIndex={windowState.full ? undefined : 0}
            aria-label="Move agent chat"
            {...windowState.controls('move')}>
            <span className="agent-avatar">
              <Bot size={22} />
            </span>
            <div>
              <h2>Sprint Agent</h2>
              <span>{selectedConnection ? selectedConnection.model : 'Connect a model'}</span>
            </div>
            <button
              className="agent-header-button agent-configure"
              aria-label="Configure agent"
              title="Configure model and agent"
              aria-expanded={settings}
              onClick={() => {
                setSettings(!settings);
                setShowHistory(false);
              }}>
              <Settings2 size={18} />
              <span>Configure</span>
            </button>
            <button
              className="agent-header-button"
              aria-label="Conversation history"
              title="View conversation history"
              disabled={!dataset || busy || restoring || loadingOlder || !!queued.length}
              onClick={() => {
                setShowHistory(!showHistory);
                setSettings(false);
              }}>
              <History size={18} />
            </button>
            <button
              className="agent-header-button"
              aria-label="New chat"
              title="Start a new chat"
              disabled={busy || restoring || loadingOlder}
              onClick={newChat}>
              <MessageSquarePlus size={18} />
            </button>
            <button
              className="agent-header-button"
              aria-label={windowState.full ? 'Exit full screen' : 'Full screen chat'}
              title={windowState.full ? 'Exit full screen' : 'Expand chat to full screen'}
              aria-pressed={windowState.full}
              onClick={() => windowState.setFull(!windowState.full)}>
              {windowState.full ? <Minimize2 size={17} /> : <Maximize2 size={17} />}
            </button>
            <button
              className="agent-header-button"
              aria-label="Close Sprint Agent"
              title="Minimize chat"
              onClick={close}>
              <ChevronDown size={20} />
            </button>
          </header>
          <div className="agent-body" ref={body}>
            {settings && dataset ? (
              <div className="agent-settings">
                <div className="agent-settings-title">
                  <h3>Configure agent</h3>
                  <button
                    type="button"
                    className="icon-button"
                    aria-label="Close agent configuration"
                    onClick={() => setSettings(false)}>
                    <X size={16} />
                  </button>
                </div>
                <label>
                  Model
                  <select
                    aria-label="Agent model"
                    value={selectedConnection?.id || ''}
                    disabled={busy || restoring}
                    onChange={(e) => selectConnection(e.target.value)}>
                    {!choices.length && <option value="">No AI connection configured</option>}
                    {choices.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Messages during a response
                  <select
                    aria-label="Message delivery mode"
                    value={deliveryMode}
                    onChange={(e) => changeDeliveryMode(e.target.value as 'queue' | 'steer')}>
                    <option value="queue">Queue · answer new messages in order</option>
                    <option value="steer">Steer · update the current response</option>
                  </select>
                </label>
                <p>
                  Queue is the default. Steer reconsiders up to four new messages at the next model or tool
                  boundary. The current provider request finishes first.
                </p>
                {selectedConnection && (
                  <details className="agent-context-settings">
                    <summary>Model context capacity</summary>
                    <p>
                      {selectedConnection.context_profile || 'compact'} profile ·{' '}
                      {(selectedConnection.context_window || 32768).toLocaleString()} token window.
                      Conversation and page preferences are beside the message box.
                    </p>
                  </details>
                )}
                <IndexControls dataset={dataset} status={status} refresh={refresh} />
                <p>
                  {selectedConnection
                    ? `Model connection: ${selectedConnection.provider}. Retrieved ticket context is sent to this provider in AI mode.`
                    : 'Connect a model to start chatting. Every answer is written by the model after it investigates your question.'}
                </p>
                <p>
                  {status?.embedding.private_local
                    ? `Private local embeddings: ${status.embedding.model}. Ticket text stays on this device for indexing and search.`
                    : status?.embedding.provider === 'local'
                      ? 'Narrative TF-IDF + keyword search; metadata and graph are queried separately.'
                      : `Semantic embeddings: ${status?.embedding.model || 'checking…'}. Ticket text is sent to your embedding provider.`}
                </p>
                {selectedConnection?.web_available && (
                  <label className="checkbox">
                    <input type="checkbox" checked={web} onChange={(e) => setWeb(e.target.checked)} /> Allow
                    public web search for this chat
                  </label>
                )}
                <details className="agent-retrieval-contract">
                  <summary>How retrieval works</summary>
                  <ol>
                    <li>Ticket keys and people/status/sprint filters query MongoDB directly.</li>
                    <li>
                      SQLite stores the search vectors and keyword index for ticket titles, descriptions,
                      acceptance criteria, comments and attachment references. Attachment contents are not
                      included. Metadata is attached from MongoDB after retrieval.
                    </li>
                    <li>
                      Graph traversal follows exported hierarchy, issue links, labels, components and
                      versions.
                    </li>
                    <li>
                      Conversation context comes first, followed by the current page when enabled, then search
                      across the export; ambiguous matches require clarification.
                    </li>
                    <li>
                      Full-scope aggregates and calculator results generate the charts. Search samples never
                      establish totals.
                    </li>
                  </ol>
                  <span>Search vectors: {status?.metadata.embedding_model || 'Not prepared'}</span>
                </details>
                <AgentProjectContext dataset={dataset} project={project} />
                <AgentConnections
                  selected={selectedConnection?.id || ''}
                  onChanged={(id) => {
                    if (id) selectConnection(id);
                    refresh();
                  }}
                />
              </div>
            ) : showHistory && dataset ? (
              <AgentHistory
                dataset={dataset}
                current={session}
                onResume={(id, source) => void resume(id, source)}
                onClose={() => setShowHistory(false)}
              />
            ) : (
              <>
                {!dataset ? (
                  <div className="agent-empty">
                    <Bot size={32} />
                    <h3>Agent unavailable</h3>
                    <p>Upload a Jira CSV first. Then prepare its ticket index to ask about your project.</p>
                  </div>
                ) : (
                  <>
                    {status?.status !== 'ready' && (
                      <div className="agent-settings">
                        <IndexControls dataset={dataset} status={status} refresh={refresh} />
                      </div>
                    )}
                    {!selectedConnection && status?.status === 'ready' && !settings && (
                      <p className="agent-preview-note">
                        Connect a model using Configure above to ask questions. The agent will investigate and
                        stream its answer; automatic reports are disabled.
                      </p>
                    )}
                    {restoring && (
                      <p role="status">
                        <LoaderCircle size={16} className="spin" /> Restoring your conversation…
                      </p>
                    )}
                    {!messages.length && !restoring && (
                      <div className="agent-welcome">
                        <Bot size={30} />
                        <h3>Your project, in conversation.</h3>
                        <p>
                          Find a ticket by its number, explore related work, or ask about the selected sprint.
                        </p>
                        <div className="agent-prompts">
                          {[
                            'Summarize this sprint',
                            'Give me a project overview',
                            'Review the backlog',
                            'Analyze employee ',
                          ].map((text) => (
                            <button
                              key={text}
                              disabled={!ready}
                              onClick={() => {
                                setDraft(text);
                                input.current?.focus();
                              }}>
                              {text.trim()}
                            </button>
                          ))}
                        </div>
                        <p className="small muted">
                          Attach a ticket using “Ask Sprint Agent” in its details. Answers use the imported
                          CSV snapshot.
                        </p>
                      </div>
                    )}
                    {hasOlder && (
                      <button
                        className="button secondary agent-load-older"
                        disabled={loadingOlder || busy || restoring}
                        onClick={() => void older()}>
                        {loadingOlder ? 'Loading…' : 'Load older messages'}
                      </button>
                    )}
                    <div className="agent-messages" aria-live="polite" aria-relevant="additions">
                      {messages.map((message, i) => (
                        <article
                          key={message.client_id || message.id || i}
                          className={`agent-message agent-${message.role}`}>
                          <span className="agent-message-label">
                            {message.role === 'user'
                              ? 'You'
                              : message.mode === 'retrieval'
                                ? 'Retrieval preview'
                                : `Sprint Agent${message.model ? ' · ' + message.model : ''}`}
                          </span>
                          {message.role === 'user' && !!message.attachments?.length && (
                            <div className="agent-attachments">
                              {message.attachments.map((key) => (
                                <span key={key}>
                                  <Paperclip size={12} />
                                  {key}
                                </span>
                              ))}
                            </div>
                          )}
                          {message.role === 'assistant' && (
                            <AgentProgress
                              responding={!!message.content.trim()}
                              tools={message.tools}
                              activity={message.activity || []}
                              working={busy && message.client_id === activeRun.current?.answerId}
                            />
                          )}
                          {message.skill && (
                            <span className="agent-skill-label">{message.skill} analysis</span>
                          )}
                          <div
                            className={`agent-message-text${message.role === 'assistant' && message.content.length > 2800 && !expandedAnswers[i] ? ' agent-answer-collapsed' : ''}`}>
                            {message.role === 'assistant' ? (
                              <AnswerText
                                content={message.content}
                                sources={message.sources}
                                onTicket={(key) => {
                                  close();
                                  onOpenTicket?.(key);
                                }}
                              />
                            ) : (
                              message.content
                            )}
                          </div>
                          {message.role === 'assistant' && message.content.length > 2800 && (
                            <button
                              className="agent-expand-answer"
                              aria-expanded={!!expandedAnswers[i]}
                              onClick={() => setExpandedAnswers((old) => ({ ...old, [i]: !old[i] }))}>
                              {expandedAnswers[i] ? 'Collapse answer' : 'Read full answer'}
                            </button>
                          )}
                          {message.details_markdown && (
                            <details className="agent-report-details">
                              <summary>More details</summary>
                              <AnswerText
                                content={message.details_markdown}
                                sources={message.sources}
                                onTicket={(key) => {
                                  close();
                                  onOpenTicket?.(key);
                                }}
                              />
                            </details>
                          )}
                          {!!message.charts?.length && <AgentVisuals charts={message.charts.slice(0, 2)} />}
                          {message.role === 'assistant' && (
                            <AgentResponseFooter
                              message={message}
                              onTicket={(key) => {
                                close();
                                onOpenTicket?.(key);
                              }}
                            />
                          )}
                          {message.role === 'assistant' &&
                            message.content &&
                            !(busy && message.client_id === activeRun.current?.answerId) && (
                              <AgentFeedback runId={message.run_id} initial={message.feedback} />
                            )}
                        </article>
                      ))}
                    </div>
                    {busy && (
                      <div className="agent-thinking">
                        <LoaderCircle size={16} className="spin" /> Responding… {elapsed}s{' '}
                        <button
                          type="button"
                          className="text-button"
                          onClick={() => {
                            pauseQueue(true);
                            controller.current?.abort();
                          }}>
                          Stop generating
                        </button>
                      </div>
                    )}
                  </>
                )}
                {(error || statusError) && (
                  <div className="error" role="alert">
                    {error || statusError}
                    {error && !!queued.length && (
                      <div className="agent-retry-actions">
                        <button
                          type="button"
                          className="button secondary"
                          disabled={busy}
                          onClick={() => {
                            const [last, ...rest] = queueRef.current;
                            updateQueue([
                              {
                                ...last,
                                request: { ...last.request, connection_id: selectedConnection?.id, effort },
                              },
                              ...rest,
                            ]);
                            setError('');
                            pauseQueue(false);
                          }}>
                          Retry last message
                        </button>
                        <button
                          type="button"
                          className="text-button"
                          disabled={busy || !!draft.trim()}
                          onClick={() => {
                            const [last, ...rest] = queueRef.current;
                            setDraft(last.text);
                            setAttached(last.attachments);
                            updateQueue(rest);
                            setError('');
                            input.current?.focus();
                          }}>
                          Edit last message
                        </button>
                      </div>
                    )}
                    <AgentFeedback runId={failedRun} />
                  </div>
                )}
              </>
            )}
          </div>
          {!windowState.full &&
            (['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'] as ResizeEdge[]).map((edge) => (
              <button
                key={edge}
                className={`agent-resize agent-resize-${edge}`}
                aria-label={
                  edge === 'se'
                    ? 'Resize agent chat'
                    : `Resize agent chat ${{ n: 'top', s: 'bottom', e: 'right', w: 'left', ne: 'top right', nw: 'top left', sw: 'bottom left' }[edge]}`
                }
                {...windowState.controls('resize', edge)}
              />
            ))}
          <form className="agent-composer" ref={composer} onSubmit={send}>
            <div
              className="agent-context-popover"
              role="dialog"
              aria-label="Message context and memory"
              id="agent-message-context"
              hidden={!contextOptions}>
              <div className="agent-settings-title">
                <h3>Context & memory</h3>
                <button
                  type="button"
                  className="icon-button"
                  aria-label="Close message context"
                  onClick={() => setContextOptions(false)}>
                  <X size={15} />
                </button>
              </div>
              <div className="agent-conversation-scope">
                <span>
                  {resetContext || !useConversationContext
                    ? 'Your next question won’t reuse earlier people, sprint or filters. Messages stay in chat history.'
                    : contextDescription
                      ? `Remembering: ${contextDescription}`
                      : 'No people, tickets or filters remembered yet.'}
                </span>
                {useConversationContext && contextDescription && (
                  <button
                    type="button"
                    disabled={busy || restoring}
                    onClick={() => setResetContext(!resetContext)}
                    aria-label={
                      resetContext ? 'Keep conversation context' : 'Clear context for next message'
                    }>
                    {resetContext ? 'Undo' : 'Start fresh'}
                  </button>
                )}
              </div>
              <fieldset className="agent-context-options">
                <legend>Context for your next message</legend>
                <label>
                  Investigation effort
                  <select
                    aria-label="Investigation effort"
                    value={effort}
                    disabled={busy || restoring}
                    onChange={(e) => {
                      const value = e.target.value as typeof effort;
                      setEffort(value);
                      save('agileplanner.agent.effort', value);
                    }}>
                    <option value="low">Low · quicker, fewer evidence checks</option>
                    <option value="standard">Standard · balanced investigation</option>
                    <option value="high">High · more batches and follow-up checks</option>
                  </select>
                </label>
                <p>
                  Controls search depth and model requests, independently of model thinking. Large searches
                  use your selected model for bounded evidence checks and reranking, then the final answer.
                  Higher effort can use more provider tokens.
                </p>
                <label>
                  <input
                    type="checkbox"
                    aria-label="Use conversation history"
                    checked={useConversationContext}
                    disabled={busy || restoring}
                    onChange={(e) => {
                      setUseConversationContext(e.target.checked);
                      save('sprintlens.agent.conversationContext', String(e.target.checked));
                    }}
                  />
                  Use conversation history
                </label>
                <p>Keep the people, tickets and filters you’ve been discussing for follow-up questions.</p>
                <label>
                  <input
                    type="checkbox"
                    aria-label="Use current page"
                    checked={usePageContext}
                    disabled={busy || restoring}
                    onChange={(e) => {
                      setUsePageContext(e.target.checked);
                      save('sprintlens.agent.pageContext', String(e.target.checked));
                    }}
                  />
                  Use current page
                </label>
                <p>
                  {page === 'sprint' ? 'Sprint explorer' : 'Overview'} · {project || 'All projects'} ·{' '}
                  {sprint === '__unscheduled__' ? 'Unscheduled issues' : sprint || 'All issues'}. A starting
                  hint, never a search limit.
                  {pageTicket && (
                    <>
                      {' '}
                      Open ticket: <strong>{pageTicket}</strong>.{' '}
                      {usePageContext
                        ? '“This ticket” uses this open panel.'
                        : 'Excluded while page context is off.'}
                    </>
                  )}
                </p>
                <p>
                  Your question takes priority, then conversation context, then the page if enabled. Search
                  can reach the entire export. Existing conversation filters stay in effect until you change
                  them or start fresh.
                </p>
              </fieldset>
            </div>

            {!!queued.length && (
              <div className="agent-pending" aria-label="Pending messages">
                <div>
                  <strong>
                    {queued.length} {queuePaused ? 'pending' : 'queued'}
                  </strong>
                  {queuePaused && (
                    <button
                      type="button"
                      className="text-button"
                      disabled={busy}
                      onClick={() => {
                        pauseQueue(false);
                        setError('');
                      }}>
                      Resume pending messages
                    </button>
                  )}
                </div>
                <ol>
                  {queued.map((item) => (
                    <li key={item.id}>
                      <span title={item.text}>{item.text}</span>
                      <button
                        type="button"
                        className="icon-button"
                        aria-label={`Remove queued message: ${item.text}`}
                        onClick={() => updateQueue(queueRef.current.filter((m) => m.id !== item.id))}>
                        <X size={13} />
                      </button>
                    </li>
                  ))}
                </ol>
              </div>
            )}
            {busy && steerCount > 0 && (
              <p className="agent-steer-status" role="status">
                {steerCount}/4 steering messages added to this response
              </p>
            )}
            {!!attached.length && (
              <div className="agent-draft-attachments">
                {attached.map((item) => (
                  <span key={item.key} title={item.title}>
                    <Paperclip size={13} />
                    {item.key}
                    <button
                      type="button"
                      aria-label={`Remove attached ${item.key}`}
                      onClick={() => setAttached((previous) => previous.filter((i) => i.key !== item.key))}>
                      <X size={13} />
                    </button>
                  </span>
                ))}
              </div>
            )}
            <div className="agent-compose-row">
              <textarea
                ref={input}
                aria-label="Message Sprint Agent"
                placeholder={
                  !selectedConnection
                    ? 'Connect a model in Configure to start…'
                    : ready
                      ? 'Ask about a ticket, topic, or sprint…'
                      : 'Prepare ticket context to start…'
                }
                maxLength={4000}
                rows={2}
                value={draft}
                disabled={restoring || loadingOlder || showHistory || settings}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault();
                    e.currentTarget.form?.requestSubmit();
                  }
                }}
              />
              <div className="agent-compose-actions">
                <button
                  type="button"
                  className="agent-context-button"
                  aria-label="Message context"
                  title="View remembered context and message settings"
                  aria-expanded={contextOptions}
                  aria-controls="agent-message-context"
                  onClick={() => setContextOptions(!contextOptions)}>
                  <Settings2 size={14} /> Context
                  {(resetContext || !useConversationContext) && (
                    <span className="agent-context-fresh">Fresh</span>
                  )}
                </button>
                <button
                  type="submit"
                  aria-label="Send message"
                  disabled={
                    !draft.trim() || steerSending || restoring || loadingOlder || showHistory || settings
                  }>
                  <Send size={18} />
                </button>
              </div>
            </div>
            <span>
              {busy
                ? deliveryMode === 'queue'
                  ? 'Queue mode · New messages wait for this response.'
                  : 'Steer mode · New messages apply at the next model or tool stop point.'
                : 'Read-only · Verify ticket sources · Shift + Enter for a new line'}
            </span>
          </form>
        </section>
      )}
      {notice && (
        <div
          className="agent-notice-overlay"
          onKeyDown={(e) => {
            e.stopPropagation();
            if (e.key === 'Escape') {
              setNotice(null);
              input.current?.focus();
            }
            if (e.key === 'Tab') {
              const buttons = Array.from(e.currentTarget.querySelectorAll('button'));
              const next =
                (buttons.indexOf(document.activeElement as HTMLButtonElement) +
                  (e.shiftKey ? -1 : 1) +
                  buttons.length) %
                buttons.length;
              e.preventDefault();
              buttons[next]?.focus();
            }
          }}>
          <div
            className="agent-notice"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="agent-notice-title"
            aria-describedby="agent-notice-message">
            <h3 id="agent-notice-title">{notice.title}</h3>
            <p id="agent-notice-message">{notice.message}</p>
            <div>
              {notice.configure && (
                <button
                  className="button secondary"
                  onClick={() => {
                    setNotice(null);
                    setSettings(true);
                    setShowHistory(false);
                  }}>
                  Open Configure
                </button>
              )}
              <button
                ref={noticeButton}
                className="button"
                onClick={() => {
                  setNotice(null);
                  input.current?.focus();
                }}>
                OK
              </button>
            </div>
          </div>
        </div>
      )}
      <button
        ref={launcher}
        style={open && windowState.full ? { display: 'none' } : undefined}
        className="agent-launcher"
        aria-label={open ? 'Minimize Sprint Agent' : 'Open Sprint Agent'}
        aria-expanded={open}
        onClick={() => (open ? close() : setOpen(true))}>
        {open ? <ChevronDown size={21} /> : <Bot size={23} />}
        <span>Sprint Agent</span>
        {ready && <i />}
      </button>
    </div>
  );
}
