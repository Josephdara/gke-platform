import { useState } from 'react';
import type { ChatDone, Message, Source } from '../api/types';

export interface ChatMessage extends Message {
  id: string;
  phase?: 'waiting' | 'streaming' | 'finished';
  done?: ChatDone;
  error?: string;
  retryQuestion?: string;
}

interface AnswerProps {
  message: ChatMessage;
  onSource: (source: Source) => void;
  onRetry: (question: string) => void;
  retryDisabled: boolean;
  announce: (message: string) => void;
}

function AnswerText({ message, onSource }: Pick<AnswerProps, 'message' | 'onSource'>) {
  const stored = message.sources.map((source) => source.label);
  const valid = message.done?.citations.valid ?? (message.phase === 'finished' && !message.done ? stored : []);
  const invalid = message.done?.citations.invalid ?? [];
  return <div className="answer-text">{message.content.split(/(\[S\d+\])/g).map((part, index) => {
    const match = /^\[(S\d+)\]$/.exec(part);
    const label = match?.[1];
    if (!label) return part;
    if (invalid.includes(label)) return <span key={index} className="unverified">[{label}: unverified citation]</span>;
    const source = message.sources.find((entry) => entry.label === label);
    if (source && valid.includes(label)) return <button key={index} className="citation" onClick={() => onSource(source)} aria-label={`Open citation ${label}`}>{label}</button>;
    return part;
  })}</div>;
}

export function Answer({ message, onSource, onRetry, retryDisabled, announce }: AnswerProps) {
  const [copied, setCopied] = useState(false);
  const finished = message.phase !== 'waiting' && message.phase !== 'streaming';
  const status = message.status === 'cancelled' ? 'Stopped' : message.status === 'failed' ? 'Incomplete'
    : message.status === 'length' ? 'Length limit reached' : 'Complete';
  const unshownInvalid = message.done?.citations.invalid.filter((label) => !message.content.includes(`[${label}]`)) ?? [];
  async function copy() {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      announce('Answer copied to clipboard.');
    } catch { announce('Copy failed. Select the answer text to copy it manually.'); }
  }

  return <article className="answer" aria-label="Assistant answer">
    <div className="answer-heading"><span className="assistant-avatar" aria-hidden="true">P</span><span>Platform Assistant</span><span className="answer-tag">DOCUMENTATION</span></div>
    {message.phase === 'waiting' && <div className="thinking"><span className="thinking-indicator" aria-hidden="true" /><p>Searching the documentation, then thinking...</p><span className="muted">This can take a few seconds.</span></div>}
    {message.content && <AnswerText message={message} onSource={onSource} />}
    {message.phase === 'streaming' && <span className="stream-indicator" aria-label="Answer is streaming" />}
    {unshownInvalid.map((label) => <p key={label} className="unverified">{label}: unverified citation</p>)}
    {message.sources.length > 0 && <section className="sources" aria-label="Answer sources">
      <h3>Sources <span>{message.sources.length}</span></h3>
      <div className="source-grid">{message.sources.map((source) => <button type="button" className="source-card" key={source.chunkId} onClick={() => onSource(source)} aria-label={`Open source ${source.label}: ${source.title}`}>
        <span className="source-label">{source.label}</span><span><strong>{source.title}</strong><small>{source.headingPath}</small></span>
      </button>)}</div>
    </section>}
    {finished && message.sources.length === 0 && message.status === 'complete' && <p className="notice">No sources found for this answer.</p>}
    {finished && <div className="answer-footer">
      <span className={message.status === 'complete' ? 'completion' : 'completion attention'}>{status}</span>
      {message.content && <button type="button" className="text-button" onClick={() => { void copy(); }}>{copied ? 'Copied' : 'Copy answer'}</button>}
      {message.retryQuestion && <button type="button" className="text-button" disabled={retryDisabled} onClick={() => onRetry(message.retryQuestion ?? '')}>Retry answer</button>}
    </div>}
    {finished && message.status === 'length' && <p className="notice">The answer reached its output length limit. Ask a narrower follow-up question to continue.</p>}
    {finished && message.status === 'cancelled' && <p className="muted small-text">{message.content ? 'Your partial answer has been kept.' : 'Stopped before any answer text arrived.'}</p>}
    {message.error && <p className="error-text">{message.error}</p>}
  </article>;
}
