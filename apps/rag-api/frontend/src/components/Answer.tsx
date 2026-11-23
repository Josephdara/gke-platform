import { useState } from 'react';
import type { ChatDone, Message } from '../api/types';
import { Markdown } from './Markdown';
import { Sources } from './Sources';

export interface ChatMessage extends Message {
  id: string;
  phase?: 'waiting' | 'streaming' | 'finished';
  done?: ChatDone;
  error?: string;
  retryQuestion?: string;
}

interface AnswerProps {
  message: ChatMessage;
  onRetry: (question: string) => void;
  retryDisabled: boolean;
  announce: (message: string) => void;
}

export function Answer({ message, onRetry, retryDisabled, announce }: AnswerProps) {
  const [copied, setCopied] = useState(false);
  const finished = message.phase !== 'waiting' && message.phase !== 'streaming';
  // A saved answer that finished has no citation check of its own; its stored labels stand in.
  // A stopped or failed answer was never checked, so its citations stay plain text.
  const checked = finished && (message.status === 'complete' || message.status === 'length');
  const valid = message.done?.citations.valid ?? (checked ? message.sources.map((source) => source.label) : []);
  const invalid = message.done?.citations.invalid ?? [];
  const status = message.status === 'cancelled' ? 'Stopped' : message.status === 'failed' ? 'Incomplete'
    : message.status === 'length' ? 'Length limit reached' : 'Complete';
  const unshownInvalid = invalid.filter((label) => !message.content.includes(`[${label}]`));
  const mode = message.sources.length > 0 ? 'From your documentation' : 'General answer';
  // A withheld answer was already streamed; once the policy result arrives, it is replaced.
  const withheld = message.done?.policy?.withheld ?? false;
  async function copy() {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      announce('Answer copied to clipboard.');
    } catch { announce('Copy failed. Select the answer text to copy it manually.'); }
  }

  return <article className="answer" aria-label="Assistant answer">
    <div className="answer-heading"><span className="assistant-avatar" aria-hidden="true">P</span><span>Platform Assistant</span>
      {message.content && <span className={`answer-tag ${message.sources.length ? '' : 'general'}`}>{mode}</span>}</div>
    {message.phase === 'waiting' && <div className="thinking"><span className="thinking-indicator" aria-hidden="true" /><p>Searching the documentation, then thinking...</p><span className="muted">This can take a few seconds.</span></div>}
    {withheld && <p className="notice">This answer was withheld because it did not pass the content policy.</p>}
    {message.content && !withheld && <Markdown content={message.content} sources={message.sources} valid={valid} invalid={invalid} />}
    {message.phase === 'streaming' && <span className="stream-indicator" aria-label="Answer is streaming" />}
    {unshownInvalid.map((label) => <p key={label} className="unverified">{label}: unverified citation</p>)}
    {finished && !withheld && message.sources.length > 0 && <Sources sources={message.sources} cited={valid.filter((label) => message.content.includes(`[${label}]`))} />}
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
