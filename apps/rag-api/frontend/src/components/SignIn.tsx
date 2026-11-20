import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { ApiError, isAbort } from '../api/client';
import type { AssistantApi } from '../api/client';
import { isMock } from '../api';
import { useCountdown } from '../hooks';

interface SignInProps {
  api: AssistantApi;
  notice: string;
  onSignedIn: (username: string) => void;
  announce: (message: string) => void;
}

export function SignIn({ api, notice, onSignedIn, announce }: SignInProps) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [retryAt, setRetryAt] = useState(0);
  const remaining = useCountdown(retryAt);
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending || remaining > 0) return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    const username = String(fields.get('username') ?? '').trim();
    const credentials = { username, password: String(fields.get('password') ?? '') };
    // The password is uncontrolled, cleared on submit, and never persisted or logged.
    const input = form.elements.namedItem('password');
    if (input instanceof HTMLInputElement) input.value = '';
    fields.delete('password');
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setPending(true);
    setError('');
    announce('');
    try {
      await api.createSession(credentials, controller.signal);
      if (!controller.signal.aborted) onSignedIn(username);
    } catch (failure) {
      if (controller.signal.aborted || isAbort(failure)) return;
      const message = failure instanceof ApiError && failure.status === 401
        ? 'That username or password is incorrect. Please try again.'
        : failure instanceof ApiError && failure.status === 429
          ? 'Too many sign-in attempts.' : 'Sign-in could not be completed. Please try again.';
      if (failure instanceof ApiError && failure.status === 429) {
        setRetryAt(Date.now() + failure.retryAfterSeconds * 1_000);
      }
      setError(message);
      announce(message);
      if (input instanceof HTMLInputElement) window.requestAnimationFrame(() => input.focus());
    } finally {
      credentials.password = '';
      if (!controller.signal.aborted) setPending(false);
    }
  }

  return <main className="sign-in-page">
    <div className="sign-in-brand"><span className="brand-mark" aria-hidden="true">P</span><span>Platform Assistant</span></div>
    <section className="sign-in-card" aria-labelledby="sign-in-title">
      <span className="eyebrow">YOUR PLATFORM KNOWLEDGE, TOGETHER</span>
      <h1 id="sign-in-title">A clearer view of<br />your platform.</h1>
      <p className="intro">Ask a question. Explore the answer. See the documentation behind it.</p>
      <div className="section-rule" />
      <h2>Sign in to your workspace</h2>
      {notice && <p className="notice">{notice}</p>}
      <form onSubmit={(event) => { void submit(event); }}>
        <label htmlFor="username">Username</label>
        <input id="username" name="username" autoComplete="username" required autoCapitalize="none" spellCheck={false} disabled={pending} />
        <label htmlFor="password">Password</label>
        <input id="password" name="password" type="password" autoComplete="current-password" required disabled={pending} aria-describedby={error ? 'login-error' : undefined} />
        {error && <p id="login-error" className="error-text">{error}</p>}
        {remaining > 0 && <p className="notice">Try again in {remaining} seconds.</p>}
        <button type="submit" className="button primary sign-in-submit" disabled={pending || remaining > 0}>{pending ? 'Signing in...' : 'Sign in'}</button>
      </form>
      {isMock && <p className="demo-credentials">Demo access: <code>platform</code> / <code>platform-demo</code></p>}
    </section>
    {isMock && <p className="sign-in-footer"><span className="small-label">MOCK WORKSPACE</span> Sample answers and sources. No backend connection.</p>}
  </main>;
}
