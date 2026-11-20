import { ApiError, MUTATION_HEADERS, isAbort } from './client';
import type { AssistantApi } from './client';
import type {
  ApiErrorDetail, ChatEvent, ChatRequest, ConversationRequest, CurrentSession, ConversationResponse,
  ConversationSummary, SessionRequest, SourceRequest, SourceResponse, StatusResponse,
} from './types';

const EVENTS = new Set(['meta', 'token', 'done', 'error']);

/** The real adapter: same-origin requests to rag-api, with its session cookie. */
export class HttpAssistantApi implements AssistantApi {
  private async send(method: 'GET' | 'POST' | 'DELETE', path: string, signal: AbortSignal, body?: unknown): Promise<Response> {
    const headers: Record<string, string> = { Accept: method === 'POST' && path === '/api/chat' ? 'text/event-stream' : 'application/json' };
    if (method !== 'GET') Object.assign(headers, MUTATION_HEADERS);
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    let response: Response;
    try {
      response = await fetch(path, {
        method, headers, signal, credentials: 'same-origin', cache: 'no-store',
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (error) {
      if (isAbort(error)) throw error;
      throw new ApiError(0, 'network_error');
    }
    if (response.ok) return response;
    let detail: ApiErrorDetail = response.status === 401 ? 'unauthorized' : response.status === 404 ? 'not_found' : 'upstream_failed';
    try {
      const parsed: unknown = await response.json();
      if (parsed && typeof parsed === 'object' && 'detail' in parsed && typeof parsed.detail === 'string') {
        detail = parsed.detail as ApiErrorDetail;
      }
    } catch { /* A body that is not JSON keeps the status-based detail. */ }
    const retryAfter = Number.parseInt(response.headers.get('Retry-After') ?? '', 10);
    throw new ApiError(response.status, detail, Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : 0);
  }

  private async json<T>(path: string, signal: AbortSignal): Promise<T> {
    return await (await this.send('GET', path, signal)).json() as T;
  }

  getSession(signal: AbortSignal): Promise<CurrentSession> {
    return this.json('/api/session', signal);
  }

  async createSession(request: SessionRequest, signal: AbortSignal): Promise<void> {
    await this.send('POST', '/api/session', signal, request);
  }

  async deleteSession(signal: AbortSignal): Promise<void> {
    await this.send('DELETE', '/api/session', signal);
  }

  getStatus(signal: AbortSignal): Promise<StatusResponse> {
    return this.json('/api/status', signal);
  }

  listConversations(signal: AbortSignal): Promise<ConversationSummary[]> {
    return this.json('/api/conversations', signal);
  }

  getConversation({ id }: ConversationRequest, signal: AbortSignal): Promise<ConversationResponse> {
    return this.json(`/api/conversations/${encodeURIComponent(id)}`, signal);
  }

  async deleteConversation({ id }: ConversationRequest, signal: AbortSignal): Promise<void> {
    await this.send('DELETE', `/api/conversations/${encodeURIComponent(id)}`, signal);
  }

  getSource({ chunkId }: SourceRequest, signal: AbortSignal): Promise<SourceResponse> {
    return this.json(`/api/sources/${encodeURIComponent(chunkId)}`, signal);
  }

  async *chat(request: ChatRequest, signal: AbortSignal): AsyncIterable<ChatEvent> {
    const response = await this.send('POST', '/api/chat', signal, request);
    if (!response.body || !(response.headers.get('Content-Type') ?? '').startsWith('text/event-stream')) {
      throw new ApiError(response.status, 'upstream_failed');
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let boundary = buffer.indexOf('\n\n');
        while (boundary !== -1) {
          const block = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          const event = parseEvent(block);
          if (event) yield event;
          boundary = buffer.indexOf('\n\n');
        }
      }
    } finally {
      // Cancelling the reader closes the connection, which stops generation on the server.
      await reader.cancel().catch(() => undefined);
    }
  }
}

function parseEvent(block: string): ChatEvent | null {
  let name = '';
  const data: string[] = [];
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) name = line.slice(6).trim();
    else if (line.startsWith('data:')) data.push(line.slice(5).trimStart());
  }
  if (!EVENTS.has(name) || data.length === 0) return null;
  try {
    return { event: name, data: JSON.parse(data.join('\n')) } as ChatEvent;
  } catch {
    throw new ApiError(200, 'upstream_failed');
  }
}
