import type {
  ApiErrorDetail, ChatEvent, ChatRequest, CurrentSession, ConversationRequest, ConversationResponse,
  ConversationsResponse, DeleteConversationRequest, DeleteConversationResponse,
  DeleteSessionResponse, SessionRequest, SessionResponse, SourceRequest, SourceResponse,
  StatusResponse,
} from './types';

/** The HTTP adapter must send these headers on POST and DELETE, with same-origin cookies. */
export const MUTATION_HEADERS = { 'X-Assistant-Client': '1' } as const;

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: ApiErrorDetail,
    readonly retryAfterSeconds = 0,
  ) {
    super(detail);
    this.name = 'ApiError';
  }
}

/** Wire payloads stay unchanged. Transport failures reject with ApiError. */
export interface AssistantApi {
  /** GET /api/session: the signed-in user, or 401 when there is no valid session. */
  getSession(signal: AbortSignal): Promise<CurrentSession>;
  /** POST /api/session. A login 401 means invalid credentials. */
  createSession(request: SessionRequest, signal: AbortSignal): Promise<SessionResponse>;
  /** DELETE /api/session */
  deleteSession(signal: AbortSignal): Promise<DeleteSessionResponse>;
  /** GET /api/status */
  getStatus(signal: AbortSignal): Promise<StatusResponse>;
  /** GET /api/conversations */
  listConversations(signal: AbortSignal): Promise<ConversationsResponse>;
  /** GET /api/conversations/{id} */
  getConversation(request: ConversationRequest, signal: AbortSignal): Promise<ConversationResponse>;
  /** DELETE /api/conversations/{id} */
  deleteConversation(request: DeleteConversationRequest, signal: AbortSignal): Promise<DeleteConversationResponse>;
  /** GET /api/sources/{chunkId} */
  getSource(request: SourceRequest, signal: AbortSignal): Promise<SourceResponse>;
  /** POST /api/chat. Abort must cancel reading and close the underlying connection. */
  chat(request: ChatRequest, signal: AbortSignal): AsyncIterable<ChatEvent>;
}

export function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}
