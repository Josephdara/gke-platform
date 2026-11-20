import { useEffect, useState } from 'react';
import { ApiError, isAbort } from '../api/client';
import type { AssistantApi } from '../api/client';
import type { Source, SourceResponse } from '../api/types';
import { Dialog } from './Dialog';

interface PassageProps {
  api: AssistantApi;
  source: Source;
  onClose: () => void;
  onUnauthorized: () => void;
  announce: (message: string) => void;
}

function externalUrl(value: string): string | undefined {
  try {
    const url = new URL(value);
    return (url.protocol === 'https:' || url.protocol === 'http:') && !url.username && !url.password ? url.href : undefined;
  } catch { return undefined; }
}

export function Passage({ api, source, onClose, onUnauthorized, announce }: PassageProps) {
  const [passage, setPassage] = useState<SourceResponse | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setPassage(null);
    setError('');
    void api.getSource({ chunkId: source.chunkId }, controller.signal).then((result) => {
      if (!controller.signal.aborted) setPassage(result);
    }).catch((failure: unknown) => {
      if (controller.signal.aborted || isAbort(failure)) return;
      if (failure instanceof ApiError && failure.status === 401) { onUnauthorized(); return; }
      const message = failure instanceof ApiError && failure.status === 404
        ? source.text
          ? 'This passage is no longer in the corpus. Below is the text saved with this answer.'
          : 'This passage is no longer in the corpus. The saved answer may refer to an older document.'
        : 'The passage could not be loaded. You can try again.';
      setError(message);
      announce(message);
    });
    return () => controller.abort();
  }, [api, source.chunkId, source.text, attempt, onUnauthorized, announce]);
  const url = passage ? externalUrl(passage.sourceUrl) : undefined;

  return <Dialog title="Source passage" drawer onClose={onClose}>
    <div className="passage-label"><span className="source-label">{source.label}</span><span>RETRIEVED DOCUMENTATION</span></div>
    {!passage && !error && <p className="loading-text">Loading passage...</p>}
    {error && <div className="notice"><p>{error}</p>{!source.text && <button className="button secondary" onClick={() => setAttempt((value) => value + 1)}>Try loading again</button>}</div>}
    {error && source.text && <>
      <h3 className="passage-title">{source.title}</h3>
      <p className="muted passage-heading">{source.headingPath}</p>
      <div className="passage-text">{source.text}</div>
    </>}
    {passage && <>
      <h3 className="passage-title">{passage.documentTitle}</h3>
      <p className="muted passage-heading">{passage.headingPath}</p>
      <div className="passage-text">{passage.text}</div>
      <dl className="attribution">
        <dt>License</dt><dd>{passage.license}</dd>
        <dt>Attribution</dt><dd>{passage.attribution}</dd>
      </dl>
      {url ? <a className="button secondary source-link" href={url} target="_blank" rel="noopener noreferrer">View source<span className="sr-only"> (opens in a new tab)</span></a>
        : <p className="notice">The source link is unavailable because its URL is not a safe web address.</p>}
    </>}
  </Dialog>;
}
