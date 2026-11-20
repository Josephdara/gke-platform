import { useCallback, useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { ApiError, isAbort } from './api/client';
import { isMock } from './api';
import type { AssistantApi } from './api/client';
import { QUESTION_LIMIT } from './api/types';
import type { ChatError, ConversationSummary, Source, StatusResponse } from './api/types';
import { Answer } from './components/Answer';
import type { ChatMessage } from './components/Answer';
import { Dialog } from './components/Dialog';
import { Passage } from './components/Passage';
import { Sidebar } from './components/Sidebar';
import { SignIn } from './components/SignIn';
import { useCountdown } from './hooks';

const suggestions = [
  { topic: 'WORKLOAD HEALTH', question: 'What happens when a liveness probe fails?' },
  { topic: 'NETWORK ISOLATION', question: 'How does the platform stop a model server from reaching the internet?' },
  { topic: 'NETWORK POLICIES', question: 'How do default-deny and allow policies work together?' },
  { topic: 'TROUBLESHOOTING', question: 'How are readiness and liveness probes different?' },
];

function errorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return 'The request could not be completed. Please try again.';
  switch (error.detail) {
    case 'question_empty': return 'Enter a question before sending.';
    case 'question_too_long': return 'Your question is too long. Keep it to 2,000 characters.';
    case 'model_unavailable': return 'The model is unavailable. Please try again later.';
    case 'retrieval_unavailable': return 'Documentation retrieval is unavailable. Please try again later.';
    case 'upstream_failed': return 'The model request failed before an answer could be returned.';
    case 'not_found': return 'This conversation is no longer available.';
    case 'busy':
    case 'rate_limited': return 'No answer was started. Wait for the countdown, then retry when you are ready.';
    default: return 'The request could not be completed. Please try again.';
  }
}

function streamErrorMessage(error: ChatError): string {
  const reason = error.reason === 'deadline' ? 'The answer exceeded its time limit.'
    : error.reason === 'stalled' ? 'The answer stream stalled.'
    : error.reason === 'model_unavailable' ? 'The model became unavailable.' : 'The answer stream failed.';
  return `${reason} ${error.partial ? 'The partial answer has been kept.' : 'No answer text was received.'} Retry only when you are ready.`;
}

export function App({ api }: { api: AssistantApi }) {
  const [username, setUsername] = useState<string | null>(null);
  const [checking, setChecking] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    void api.getSession(controller.signal)
      .then((session) => { if (!controller.signal.aborted) setUsername(session.username); })
      .catch(() => undefined)
      .finally(() => { if (!controller.signal.aborted) setChecking(false); });
    return () => controller.abort();
  }, [api]);
  const [notice, setNotice] = useState('');
  const [announcement, setAnnouncement] = useState('');
  const announce = useCallback((message: string) => setAnnouncement(message), []);
  const onUnauthorized = useCallback(() => {
    setUsername(null);
    setNotice('Your session has expired. Sign in to continue.');
    announce('Your session has expired. Sign in to continue.');
  }, [announce]);
  const onSignedOut = useCallback(() => {
    setUsername(null);
    setNotice('You have signed out.');
    announce('You have signed out.');
  }, [announce]);

  return <>
    <div className="sr-only" role="status" aria-live="polite" aria-atomic="true">{announcement}</div>
    {checking ? <div className="workspace-loading" aria-busy="true"><span className="thinking-indicator" aria-hidden="true" /><p>Loading...</p></div>
      : username === null
      ? <SignIn api={api} notice={notice} announce={announce} onSignedIn={(name) => { setNotice(''); setUsername(name); announce('Signed in. Your workspace is ready.'); }} />
      : <Workspace api={api} username={username} onUnauthorized={onUnauthorized} onSignedOut={onSignedOut} announce={announce} />}
  </>;
}

interface WorkspaceProps {
  api: AssistantApi;
  username: string;
  onUnauthorized: () => void;
  onSignedOut: () => void;
  announce: (message: string) => void;
}

function Workspace({ api, username, onUnauthorized, onSignedOut, announce }: WorkspaceProps) {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string>();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [banner, setBanner] = useState('');
  const [bootstrapAttempt, setBootstrapAttempt] = useState(0);
  const [rateLimit, setRateLimit] = useState<{ kind: 'busy' | 'rate_limited'; until: number } | null>(null);
  const remaining = useCountdown(rateLimit?.until ?? 0);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<ConversationSummary | null>(null);
  const [retryQuestion, setRetryQuestion] = useState<string | null>(null);
  const [source, setSource] = useState<Source | null>(null);
  const stream = useRef<AbortController | null>(null);
  const mounted = useRef(false);
  const requests = useRef(new Set<AbortController>());
  const navigation = useRef<AbortController | null>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const newChatFocus = useRef<HTMLButtonElement>(null);
  const scrollPane = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const blocked = loading || historyLoading || signingOut || deleting;
  const selectedTitle = conversations.find((entry) => entry.id === selectedId)?.title ?? 'New conversation';

  useEffect(() => {
    mounted.current = true;
    const activeRequests = requests.current;
    return () => {
      mounted.current = false;
      activeRequests.forEach((controller) => controller.abort());
      stream.current?.abort();
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setBanner('');
    void Promise.all([api.getStatus(controller.signal), api.listConversations(controller.signal)])
      .then(([nextStatus, list]) => {
        if (controller.signal.aborted) return;
        setStatus(nextStatus);
        setConversations(list);
      }).catch((error: unknown) => {
        if (controller.signal.aborted || isAbort(error)) return;
        if (error instanceof ApiError && error.status === 401) { onUnauthorized(); return; }
        const message = 'The workspace could not be loaded. Try loading it again.';
        setBanner(message);
        announce(message);
      }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [api, onUnauthorized, announce, bootstrapAttempt]);

  useEffect(() => {
    const pane = scrollPane.current;
    if (pane && stickToBottom.current) pane.scrollTop = pane.scrollHeight;
  }, [messages]);

  function newRequest() {
    const controller = new AbortController();
    requests.current.add(controller);
    return controller;
  }

  function handleFailure(error: unknown) {
    if (isAbort(error)) return;
    if (error instanceof ApiError && error.status === 401) { onUnauthorized(); return; }
    const message = errorMessage(error);
    setBanner(message);
    announce(message);
  }

  function updateAnswer(id: string, update: (message: ChatMessage) => ChatMessage) {
    setMessages((current) => current.map((message) => message.id === id ? update(message) : message));
  }

  function newConversation() {
    if (stream.current || blocked) return;
    navigation.current?.abort();
    setSelectedId(undefined);
    setMessages([]);
    setQuestion('');
    setBanner('');
    setMobileOpen(false);
    stickToBottom.current = true;
    // Runs after the native drawer has restored focus to its trigger.
    window.requestAnimationFrame(() => composer.current?.focus());
  }

  async function openConversation(id: string) {
    if (stream.current || blocked) return;
    navigation.current?.abort();
    const controller = newRequest();
    navigation.current = controller;
    setMobileOpen(false);
    setHistoryLoading(true);
    setBanner('');
    try {
      const conversation = await api.getConversation({ id }, controller.signal);
      if (controller.signal.aborted) return;
      setSelectedId(conversation.id);
      setQuestion('');
      stickToBottom.current = true;
      setMessages(conversation.messages.map((message) => ({ ...message, id: crypto.randomUUID(), phase: 'finished' })));
      announce(`Loaded conversation: ${conversation.title}.`);
    } catch (error) { if (!controller.signal.aborted) handleFailure(error); }
    finally { requests.current.delete(controller); if (!controller.signal.aborted) setHistoryLoading(false); }
  }

  async function refreshList() {
    const controller = newRequest();
    try {
      const list = await api.listConversations(controller.signal);
      if (!controller.signal.aborted && !stream.current) setConversations(list);
    } catch (error) { if (!controller.signal.aborted) handleFailure(error); }
    finally { requests.current.delete(controller); }
  }

  async function send(raw: string) {
    if (stream.current || blocked || !status || remaining > 0 || !raw.trim() || raw.length > QUESTION_LIMIT) return;
    const text = raw.trim();
    const controller = new AbortController();
    stream.current = controller;
    const answerId = crypto.randomUUID();
    setQuestion('');
    setStreaming(true);
    setBanner('');
    setRateLimit(null);
    announce('');
    stickToBottom.current = true;
    setMessages((current) => [...current,
      { id: crypto.randomUUID(), role: 'user', content: text, sources: [], status: 'complete' },
      { id: answerId, role: 'assistant', content: '', sources: [], status: 'complete', phase: 'waiting' },
    ]);
    let terminal = false;
    let answerText = '';
    let sessionExpired = false;
    try {
      for await (const event of api.chat({ question: text, ...(selectedId ? { conversationId: selectedId } : {}) }, controller.signal)) {
        controller.signal.throwIfAborted();
        if (event.event === 'meta') {
          setSelectedId(event.data.conversationId);
          updateAnswer(answerId, (message) => ({ ...message, sources: event.data.sources }));
          setConversations((current) => {
            const existing = current.find((entry) => entry.id === event.data.conversationId);
            return [{ id: event.data.conversationId, title: existing?.title ?? text.slice(0, 64), updatedAt: new Date().toISOString() },
              ...current.filter((entry) => entry.id !== event.data.conversationId)];
          });
        } else if (event.event === 'token') {
          answerText += event.data.text;
          updateAnswer(answerId, (message) => ({ ...message, content: message.content + event.data.text, phase: 'streaming' }));
        } else if (event.event === 'done') {
          terminal = true;
          updateAnswer(answerId, (message) => ({ ...message, phase: 'finished', status: event.data.status, done: event.data }));
          announce(`${event.data.status === 'length' ? 'Answer reached its length limit.' : 'Answer complete.'} ${answerText}`);
          break;
        } else {
          terminal = true;
          const message = streamErrorMessage(event.data);
          updateAnswer(answerId, (answer) => ({ ...answer, phase: 'finished', status: 'failed', error: message, retryQuestion: text }));
          announce(message);
          break;
        }
      }
      if (!terminal) throw new Error('Stream ended without a terminal event');
    } catch (error) {
      if (!mounted.current) return;
      if (controller.signal.aborted || isAbort(error)) {
        updateAnswer(answerId, (answer) => ({ ...answer, phase: 'finished', status: 'cancelled', retryQuestion: text }));
        announce('Answer stopped. Any partial answer has been kept.');
      } else if (error instanceof ApiError && error.status === 401) {
        sessionExpired = true;
        onUnauthorized();
      } else {
        if (error instanceof ApiError && error.status === 429) {
          setRateLimit({ kind: error.detail === 'busy' ? 'busy' : 'rate_limited', until: Date.now() + error.retryAfterSeconds * 1_000 });
        }
        const message = errorMessage(error);
        updateAnswer(answerId, (answer) => ({ ...answer, phase: 'finished', status: 'failed', error: message, retryQuestion: text }));
        announce(message);
      }
    } finally {
      if (mounted.current && stream.current === controller) {
        stream.current = null;
        setStreaming(false);
        if (!sessionExpired) void refreshList();
      }
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); void send(question); }

  async function deleteConversation() {
    if (!deleteTarget || deleting) return;
    const target = deleteTarget;
    const controller = newRequest();
    setDeleting(true);
    try {
      await api.deleteConversation({ id: target.id }, controller.signal);
      if (controller.signal.aborted) return;
      setConversations((current) => current.filter((entry) => entry.id !== target.id));
      if (selectedId === target.id) { setSelectedId(undefined); setMessages([]); setQuestion(''); }
      setDeleteTarget(null);
      announce(`Deleted conversation: ${target.title}.`);
    } catch (error) { if (!controller.signal.aborted) { setDeleteTarget(null); handleFailure(error); } }
    finally { requests.current.delete(controller); if (!controller.signal.aborted) setDeleting(false); }
  }

  async function signOut() {
    if (signingOut) return;
    const activeStream = stream.current;
    stream.current = null;
    activeStream?.abort();
    const controller = newRequest();
    setSigningOut(true);
    try {
      await api.deleteSession(controller.signal);
      if (!controller.signal.aborted) onSignedOut();
    } catch (error) { if (!controller.signal.aborted) handleFailure(error); }
    finally {
      requests.current.delete(controller);
      if (!controller.signal.aborted) { setSigningOut(false); setStreaming(false); }
    }
  }

  const sidebarProps = {
    conversations, selectedId, disabled: streaming || blocked, username,
    onNew: newConversation,
    onSelect: (id: string) => { void openConversation(id); },
    onDelete: (target: ConversationSummary) => { setMobileOpen(false); setDeleteTarget(target); },
  };
  const retrievalLabel = status?.retrieval.status === 'ok' ? 'Connected'
    : status?.retrieval.status === 'mismatch' ? 'Index mismatch'
    : status?.retrieval.status === 'disabled' ? 'Disabled' : status?.retrieval.status === 'unavailable' ? 'Unavailable' : 'Loading';

  return <div className="workspace">
    <a className="skip-link" href="#question">Skip to question</a>
    <header className="app-header">
      <a className="brand" href="#question"><span className="brand-mark" aria-hidden="true">P</span><span>Platform Assistant</span></a>
      <span className="workspace-type">Documentation workspace</span>
      <div className="system-status" aria-label="Platform status">
        <span className={`status-item ${status?.model.status === 'ok' ? 'healthy' : ''}`}><i aria-hidden="true" />Model: {status ? status.model.status === 'ok' ? 'Ready' : 'Unavailable' : 'Loading'}</span>
        <span className={`status-item ${status?.retrieval.status === 'ok' ? 'healthy' : ''}`}><i aria-hidden="true" />Retrieval: {retrievalLabel}</span>
      </div>
      <button className="button quiet sign-out" disabled={signingOut} onClick={() => { void signOut(); }}>{signingOut ? 'Signing out...' : 'Sign out'}</button>
    </header>
    <aside className="desktop-sidebar"><Sidebar {...sidebarProps} /></aside>
    <main className="chat-main" aria-labelledby="conversation-title">
      <div className="chat-toolbar">
        <button type="button" ref={newChatFocus} className="button secondary mobile-menu" onClick={() => setMobileOpen(true)}>Conversations</button>
        <div><span className="small-label toolbar-label">WORKSPACE</span><h1 id="conversation-title">{selectedTitle}</h1></div>
        {isMock && <span className="mock-badge toolbar-demo">MOCK DATA</span>}
      </div>
      <div className="notices">
        {banner && <div className="notice error-notice"><p>{banner}</p>{!status && <button className="text-button" onClick={() => setBootstrapAttempt((value) => value + 1)}>Reload workspace</button>}</div>}
        {rateLimit && <p className="notice rate-notice">{remaining > 0
          ? rateLimit.kind === 'busy' ? `All answer slots are in use, try again in ${remaining} seconds.` : `You have reached the request limit. Try again in ${remaining} seconds.`
          : 'You can try again now. Your question will only be sent when you choose Retry answer or Send.'}</p>}
        {status?.retrieval.status === 'mismatch' && <p className="notice">The retrieval index does not match the configured embedding model. Grounded answers are unavailable.</p>}
        {status?.retrieval.status === 'disabled' && <p className="notice">Documentation retrieval is disabled. Answers will have no retrieved sources.</p>}
      </div>
      <div className="chat-scroll" ref={scrollPane} onScroll={() => {
        const pane = scrollPane.current;
        if (pane) stickToBottom.current = pane.scrollHeight - pane.scrollTop - pane.clientHeight < 100;
      }}>
        {loading || historyLoading ? <div className="workspace-loading"><span className="thinking-indicator" aria-hidden="true" /><p>{historyLoading ? 'Loading conversation...' : 'Loading your workspace...'}</p></div>
          : messages.length === 0 ? <section className="empty-state" aria-labelledby="welcome-title">
            <div className="empty-kicker"><span className="eyebrow">BUILT ON YOUR DOCUMENTATION</span><span className="short-rule" /></div>
            <h2 id="welcome-title">Your platform,<br /><span>explained.</span></h2>
            <p className="intro">From probes to policies, get answers grounded in platform documentation. Follow the sources to see how it all fits together.</p>
            <p className="suggestion-heading">A few good places to start</p>
            <div className="suggestion-grid">{suggestions.map((suggestion) => <button type="button" key={suggestion.topic} className="suggestion" disabled={blocked || !status || remaining > 0} onClick={() => { void send(suggestion.question); }}><span>{suggestion.topic}</span><strong>{suggestion.question}</strong></button>)}</div>
            <p className="empty-note">{isMock ? 'Sample documentation. Clear sources. You stay in control.' : 'Every answer lists the passages it drew on. You stay in control.'}</p>
          </section>
            : <div className="messages">{messages.map((message) => message.role === 'user'
              ? <article key={message.id} className="user-message" aria-label="Your question"><span>You</span><p>{message.content}</p></article>
              : <Answer key={message.id} message={message} onSource={setSource} onRetry={setRetryQuestion} retryDisabled={streaming || blocked || remaining > 0} announce={announce} />)}</div>}
      </div>
      <div className="composer-area">
        <form className={`composer ${question.length > QUESTION_LIMIT ? 'over-limit' : ''}`} onSubmit={submit}>
          <label htmlFor="question">Ask about your platform</label>
          <textarea ref={composer} id="question" name="question" placeholder="What would you like to understand?" value={question} rows={2} disabled={blocked || !status}
            aria-describedby="question-help question-count" aria-invalid={question.length > QUESTION_LIMIT}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                void send(question);
              }
            }} />
          <div className="composer-bottom"><span id="question-help" className="muted small-text">Enter to send <span aria-hidden="true">·</span> Shift+Enter for a new line</span>
            <span id="question-count" className={`character-count ${question.length >= 1800 ? 'near-limit' : ''}`}>{question.length.toLocaleString('en')} / 2,000{question.length > QUESTION_LIMIT && <span className="sr-only">: question is too long</span>}</span>
            {streaming ? <button type="button" className="button secondary stop-button" onClick={() => stream.current?.abort()}><span className="stop-mark" aria-hidden="true" />Stop</button>
              : <button type="submit" className="button primary" disabled={blocked || !status || !question.trim() || question.length > QUESTION_LIMIT || remaining > 0}>Send</button>}
          </div>
        </form>
        <p className="composer-footnote">Answers can be incomplete. Check the sources before changing your platform.{isMock && <span>Mock workspace · No backend requests</span>}</p>
      </div>
    </main>
    {mobileOpen && <Dialog title="Conversations" drawer onClose={() => setMobileOpen(false)}><Sidebar {...sidebarProps} /></Dialog>}
    {source && <Passage key={source.chunkId} api={api} source={source} onClose={() => setSource(null)} onUnauthorized={onUnauthorized} announce={announce} />}
    {deleteTarget && <Dialog title="Delete conversation?" onClose={() => setDeleteTarget(null)} fallbackFocus={() => { composer.current?.focus(); }}>
      <p>Delete “{deleteTarget.title}” and its messages? This cannot be undone.</p>
      <div className="dialog-actions"><button className="button secondary" onClick={() => setDeleteTarget(null)}>Cancel</button><button className="button danger" disabled={deleting} onClick={() => { void deleteConversation(); }}>{deleting ? 'Deleting...' : 'Delete conversation'}</button></div>
    </Dialog>}
    {retryQuestion !== null && <Dialog title="Send this question again?" onClose={() => setRetryQuestion(null)}>
      <p>This starts a new answer and counts as another request. Your previous answer will be kept.</p><blockquote className="retry-preview">{retryQuestion}</blockquote>
      <div className="dialog-actions"><button className="button secondary" onClick={() => setRetryQuestion(null)}>Cancel</button><button className="button primary" disabled={streaming || blocked || remaining > 0} onClick={() => { const text = retryQuestion; setRetryQuestion(null); void send(text); }}>Send again</button></div>
    </Dialog>}
  </div>;
}
