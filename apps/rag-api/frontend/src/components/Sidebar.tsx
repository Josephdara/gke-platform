import { isMock } from '../api';
import type { ConversationSummary } from '../api/types';

interface SidebarProps {
  conversations: ConversationSummary[];
  selectedId?: string;
  disabled: boolean;
  username: string;
  onNew: () => void;
  onSelect: (id: string) => void;
  onDelete: (conversation: ConversationSummary) => void;
}

export function Sidebar({ conversations, selectedId, disabled, username, onNew, onSelect, onDelete }: SidebarProps) {
  return <div className="sidebar-content">
    <button className="button new-conversation" onClick={onNew} disabled={disabled}><span aria-hidden="true">+</span> New conversation</button>
    <div className="sidebar-heading"><h2>Conversations</h2><span>{conversations.length}</span></div>
    <nav aria-label="Conversations" className="conversation-list">
      {conversations.length === 0 && <p className="muted small-text">Your conversations will appear here.</p>}
      {conversations.map((conversation) => <div key={conversation.id} className={`conversation-row ${conversation.id === selectedId ? 'selected' : ''}`}>
        <button className="conversation-select" aria-current={conversation.id === selectedId ? 'page' : undefined} disabled={disabled} onClick={() => onSelect(conversation.id)}>
          <span>{conversation.title}</span>
          <time dateTime={conversation.updatedAt}>{new Intl.DateTimeFormat('en', { month: 'short', day: 'numeric' }).format(new Date(conversation.updatedAt))}</time>
        </button>
        <button className="conversation-delete" disabled={disabled} onClick={() => onDelete(conversation)} aria-label={`Delete ${conversation.title}`} title={`Delete ${conversation.title}`}>
          <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 10v7M14 10v7" /></svg>
        </button>
      </div>)}
    </nav>
    {disabled && <p className="muted small-text sidebar-help">Finish or stop the current request to switch conversations.</p>}
    <div className="sidebar-footer"><span className="user-avatar" aria-hidden="true">{username.slice(0, 1).toUpperCase()}</span><div><strong>{username}</strong><small>Platform workspace</small></div>{isMock && <span className="mock-badge">DEMO</span>}</div>
  </div>;
}
