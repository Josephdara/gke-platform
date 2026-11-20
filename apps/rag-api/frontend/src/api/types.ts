export type SourceLabel = `S${1 | 2 | 3 | 4 | 5}`;

export interface Source {
  label: SourceLabel;
  chunkId: string;
  title: string;
  headingPath: string;
  score: number;
  /** Saved conversations keep the passage text, so it survives the document being retired. */
  text?: string;
}

export interface SessionRequest { username: string; password: string }
export interface CurrentSession { username: string }
export type SessionResponse = void;
export type DeleteSessionResponse = void;
export type SessionError = { detail: 'invalid_credentials' | 'rate_limited' };
export type UnauthorizedError = { detail: 'unauthorized' };
export type NotFoundError = { detail: 'not_found' };

export interface StatusResponse {
  model: { runtime: string; alias: string; status: 'ok' | 'unavailable' };
  retrieval: { status: 'ok' | 'unavailable' | 'mismatch' | 'disabled' };
  promptVersion: string;
  admission: { active: number; limit: number };
}

export interface ConversationSummary { id: string; title: string; updatedAt: string }
export type ConversationsResponse = ConversationSummary[];
export interface ConversationRequest { id: string }
export type MessageStatus = 'complete' | 'length' | 'cancelled' | 'failed';
export interface Message {
  role: 'user' | 'assistant';
  content: string;
  status: MessageStatus;
  sources: Source[];
}
export interface ConversationResponse { id: string; title: string; messages: Message[] }
export type DeleteConversationRequest = ConversationRequest;
export type DeleteConversationResponse = void;
export interface SourceRequest { chunkId: string }
export interface SourceResponse {
  chunkId: string;
  documentTitle: string;
  headingPath: string;
  text: string;
  sourceUrl: string;
  license: string;
  attribution: string;
}

export interface ChatRequest { question: string; conversationId?: string }
export type ChatRejection =
  | { status: 422; body: { detail: 'question_too_long' | 'question_empty' } }
  | { status: 429; body: { detail: 'busy' | 'rate_limited' }; retryAfterSeconds: number }
  | { status: 503; body: { detail: 'model_unavailable' | 'retrieval_unavailable' | 'upstream_failed' } }
  | { status: 401; body?: UnauthorizedError };

export interface ChatMeta {
  requestId: string;
  promptVersion: string;
  model: string;
  conversationId: string;
  sources: Source[];
}
export interface ChatToken { text: string }
export interface ChatDone {
  status: 'complete' | 'length';
  usage: { promptTokens: number; completionTokens: number };
  timings: { ttftMs: number; totalMs: number };
  citations: { valid: string[]; invalid: string[] };
}
export interface ChatError {
  reason: 'upstream_failed' | 'stalled' | 'deadline' | 'model_unavailable';
  partial: boolean;
}
export type ChatEvent =
  | { event: 'meta'; data: ChatMeta }
  | { event: 'token'; data: ChatToken }
  | { event: 'done'; data: ChatDone }
  | { event: 'error'; data: ChatError };

export type ApiErrorDetail = 'network_error' | 'forbidden' | SessionError['detail'] | UnauthorizedError['detail'] |
  NotFoundError['detail'] | NonNullable<ChatRejection['body']>['detail'];

export const QUESTION_LIMIT = 2_000;
