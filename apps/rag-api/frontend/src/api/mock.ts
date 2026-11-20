import { ApiError } from './client';
import type { AssistantApi } from './client';
import { networkAnswer, passages, probeAnswer, probeSources, seedConversations, sources } from './fixtures';
import { QUESTION_LIMIT } from './types';
import type {
  ChatEvent, ChatRequest, ConversationRequest, CurrentSession, ConversationResponse, ConversationSummary,
  Message, SessionRequest, SourceRequest, StatusResponse,
} from './types';

export const scenarios = [
  'default', 'loading', 'no-sources', 'unauthorized', 'rate-limited', 'busy',
  'model-unavailable', 'retrieval-unavailable', 'length', 'partial-failure',
  'stream-failure', 'stream-model-unavailable', 'deadline', 'stalled', 'retired-source', 'invalid-citations',
  'sign-in-rate-limited', 'retrieval-mismatch', 'retrieval-disabled', 'upstream-failed',
  'question-empty', 'question-too-long', 'conversation-not-found', 'unsafe-source',
  'unauthorized-source', 'unauthorized-history', 'unauthorized-delete',
  'unauthorized-signout', 'unauthorized-status', 'unauthorized-list',
] as const;
type Scenario = typeof scenarios[number];

function delay(ms: number, signal: AbortSignal): Promise<void> {
  signal.throwIfAborted();
  return new Promise((resolve, reject) => {
    const finish = () => {
      signal.removeEventListener('abort', abort);
      resolve();
    };
    const timer = window.setTimeout(finish, ms);
    const abort = () => {
      window.clearTimeout(timer);
      signal.removeEventListener('abort', abort);
      reject(new DOMException('Aborted', 'AbortError'));
    };
    signal.addEventListener('abort', abort, { once: true });
  });
}

/** All mock state is private to this instance and disappears on reload/sign-out. */
export class MockAssistantApi implements AssistantApi {
  private readonly scenario: Scenario;
  private authenticated = false;
  private loginAvailableAt: number | undefined;
  private chatAvailableAt: number | undefined;
  private conversations = new Map<string, ConversationResponse>();
  private summaries: ConversationSummary[] = [];

  constructor(scenario: string | null) {
    this.scenario = scenarios.find((value) => value === scenario) ?? 'default';
    this.resetConversations();
  }

  private resetConversations() {
    const seed = structuredClone(seedConversations());
    this.summaries = seed.summaries;
    this.conversations = new Map(seed.conversations.map((conversation) => [conversation.id, conversation]));
  }

  private requireSession(endpoint: string) {
    if (!this.authenticated || this.scenario === `unauthorized-${endpoint}`) {
      this.authenticated = false;
      throw new ApiError(401, 'unauthorized');
    }
  }

  async getSession(signal: AbortSignal): Promise<CurrentSession> {
    await delay(50, signal);
    if (!this.authenticated) throw new ApiError(401, 'unauthorized');
    return { username: 'platform' };
  }

  async createSession(request: SessionRequest, signal: AbortSignal): Promise<void> {
    const valid = request.username === 'platform' && request.password === 'platform-demo';
    await delay(450, signal);
    if (this.scenario === 'sign-in-rate-limited') {
      this.loginAvailableAt ??= Date.now() + 5_000;
      if (Date.now() < this.loginAvailableAt) {
        throw new ApiError(429, 'rate_limited', Math.ceil((this.loginAvailableAt - Date.now()) / 1_000));
      }
    }
    if (!valid) throw new ApiError(401, 'invalid_credentials');
    this.authenticated = true;
  }

  async deleteSession(signal: AbortSignal): Promise<void> {
    await delay(250, signal);
    this.requireSession('signout');
    this.authenticated = false;
    this.resetConversations();
  }

  async getStatus(signal: AbortSignal): Promise<StatusResponse> {
    await delay(this.scenario === 'loading' ? 1_500 : 250, signal);
    this.requireSession('status');
    const retrieval = this.scenario === 'retrieval-unavailable' ? 'unavailable'
      : this.scenario === 'retrieval-mismatch' ? 'mismatch'
      : this.scenario === 'retrieval-disabled' ? 'disabled' : 'ok';
    return {
      model: { runtime: 'llama.cpp', alias: 'Qwen2.5-1.5B-Instruct', status: this.scenario === 'model-unavailable' ? 'unavailable' : 'ok' },
      retrieval: { status: retrieval }, promptVersion: 'platform-v1',
      admission: { active: this.scenario === 'busy' ? 3 : 0, limit: 3 },
    };
  }

  async listConversations(signal: AbortSignal): Promise<ConversationSummary[]> {
    await delay(this.scenario === 'loading' ? 1_500 : 250, signal);
    this.requireSession('list');
    return structuredClone([...this.summaries].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)));
  }

  async getConversation({ id }: ConversationRequest, signal: AbortSignal): Promise<ConversationResponse> {
    await delay(350, signal);
    this.requireSession('history');
    const conversation = this.conversations.get(id);
    if (!conversation || this.scenario === 'conversation-not-found') throw new ApiError(404, 'not_found');
    return structuredClone(conversation);
  }

  async deleteConversation({ id }: ConversationRequest, signal: AbortSignal): Promise<void> {
    await delay(350, signal);
    this.requireSession('delete');
    if (!this.conversations.has(id)) throw new ApiError(404, 'not_found');
    this.conversations.delete(id);
    this.summaries = this.summaries.filter((conversation) => conversation.id !== id);
  }

  async getSource({ chunkId }: SourceRequest, signal: AbortSignal) {
    await delay(450, signal);
    this.requireSession('source');
    const passage = passages[chunkId];
    if (!passage || this.scenario === 'retired-source') throw new ApiError(404, 'not_found');
    return structuredClone(this.scenario === 'unsafe-source'
      ? { ...passage, sourceUrl: 'javascript:alert("untrusted")' } : passage);
  }

  async *chat(request: ChatRequest, signal: AbortSignal): AsyncIterable<ChatEvent> {
    await delay(200, signal);
    this.requireSession('chat');
    if (this.scenario === 'unauthorized') {
      this.authenticated = false;
      throw new ApiError(401, 'unauthorized');
    }
    if (!request.question.trim() || this.scenario === 'question-empty') throw new ApiError(422, 'question_empty');
    if (request.question.length > QUESTION_LIMIT || this.scenario === 'question-too-long') throw new ApiError(422, 'question_too_long');
    if (this.scenario === 'busy' || this.scenario === 'rate-limited') {
      this.chatAvailableAt ??= Date.now() + 5_000;
      if (Date.now() < this.chatAvailableAt) {
        throw new ApiError(429, this.scenario === 'busy' ? 'busy' : 'rate_limited',
          Math.ceil((this.chatAvailableAt - Date.now()) / 1_000));
      }
    }
    if (this.scenario === 'model-unavailable') throw new ApiError(503, 'model_unavailable');
    if (this.scenario === 'retrieval-unavailable' || this.scenario === 'retrieval-mismatch') throw new ApiError(503, 'retrieval_unavailable');
    if (this.scenario === 'upstream-failed') throw new ApiError(503, 'upstream_failed');

    const startedAt = performance.now();
    const id = request.conversationId ?? crypto.randomUUID();
    let conversation = this.conversations.get(id);
    if (!conversation) {
      conversation = { id, title: request.question.slice(0, 64), messages: [] };
      this.conversations.set(id, conversation);
      this.summaries.push({ id, title: conversation.title, updatedAt: new Date().toISOString() });
    }
    const isProbe = /liveness|readiness|probe/i.test(request.question);
    const noSources = this.scenario === 'no-sources' || this.scenario === 'retrieval-disabled';
    const selectedSources = structuredClone(noSources ? [] : isProbe ? probeSources : sources);
    const assistant: Message = { role: 'assistant', content: '', status: 'cancelled', sources: selectedSources };
    conversation.messages.push({ role: 'user', content: request.question, status: 'complete', sources: [] }, assistant);
    const summary = this.summaries.find((entry) => entry.id === id);
    if (summary) summary.updatedAt = new Date().toISOString();

    let terminal = false;
    try {
      yield { event: 'meta', data: {
        requestId: crypto.randomUUID(), promptVersion: 'platform-v1', model: 'Qwen2.5-1.5B-Instruct',
        conversationId: id, sources: selectedSources,
      } };
      await delay(this.scenario === 'loading' ? 7_600 : 3_200, signal);
      if (this.scenario === 'stream-failure') {
        assistant.status = 'failed';
        terminal = true;
        yield { event: 'error', data: { reason: 'upstream_failed', partial: false } };
        return;
      }
      const answer = noSources
        ? 'I could not find a supporting passage for this question. Try asking about liveness probes or inference network isolation. I cannot provide a grounded answer without a matching source.'
        : (isProbe ? probeAnswer : networkAnswer) + (this.scenario === 'invalid-citations'
          ? '\n\nUnverified example: a guarantee that is not supported by these sources. [S9]\nLiteral model text: <script>alert("demo")</script>' : '');
      const tokens = answer.match(/\S+\s*/g) ?? [];
      const ttftMs = Math.round(performance.now() - startedAt);
      const interrupted = ['partial-failure', 'deadline', 'stalled', 'stream-model-unavailable'].includes(this.scenario);
      let sent = 0;
      for (const token of tokens) {
        await delay(40, signal);
        assistant.content += token;
        sent += 1;
        yield { event: 'token', data: { text: token } };
        if (interrupted && sent === 18) {
          assistant.status = 'failed';
          terminal = true;
          yield { event: 'error', data: {
            reason: this.scenario === 'deadline' ? 'deadline' : this.scenario === 'stalled' ? 'stalled'
              : this.scenario === 'stream-model-unavailable' ? 'model_unavailable' : 'upstream_failed',
            partial: true,
          } };
          return;
        }
        if (this.scenario === 'length' && sent === 28) break;
      }
      assistant.status = this.scenario === 'length' ? 'length' : 'complete';
      terminal = true;
      const cited = [...new Set(assistant.content.match(/S\d+(?=\])/g) ?? [])];
      yield { event: 'done', data: {
        status: assistant.status,
        usage: { promptTokens: 920, completionTokens: sent },
        timings: { ttftMs, totalMs: Math.round(performance.now() - startedAt) },
        citations: {
          valid: cited.filter((label) => selectedSources.some((source) => source.label === label)),
          invalid: cited.filter((label) => !selectedSources.some((source) => source.label === label)),
        },
      } };
    } finally {
      if (!terminal) assistant.status = 'cancelled';
    }
  }
}
