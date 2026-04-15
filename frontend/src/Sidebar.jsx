/**
 * Sidebar.jsx - Conversation history sidebar
 */

import { useState, useEffect } from 'react';
import { getConversations, deleteConversation } from './api';

export default function Sidebar({
  currentConversation,
  onSelectConversation,
  onNewChat,
  refreshTrigger
}) {
  const [conversations, setConversations] = useState([]);
  const [loading, setLoading] = useState(true);

  const loadConversations = async () => {
    try {
      const data = await getConversations();
      setConversations(data.conversations || []);
    } catch (err) {
      console.error('Failed to load conversations:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadConversations();
  }, [refreshTrigger]);

  const handleDelete = async (e, conversationId) => {
    e.stopPropagation();
    if (!confirm('Delete this conversation?')) return;

    try {
      await deleteConversation(conversationId);
      setConversations(prev => prev.filter(c => c.id !== conversationId));

      // If we deleted the current conversation, start new chat
      if (currentConversation?.id === conversationId) {
        onNewChat();
      }
    } catch (err) {
      console.error('Failed to delete conversation:', err);
    }
  };

  const formatDate = (dateStr) => {
    const date = new Date(dateStr);
    const now = new Date();
    const diff = now - date;

    // Today
    if (diff < 24 * 60 * 60 * 1000 && date.getDate() === now.getDate()) {
      return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }

    // Yesterday
    if (diff < 48 * 60 * 60 * 1000) {
      return 'Yesterday';
    }

    // This week
    if (diff < 7 * 24 * 60 * 60 * 1000) {
      return date.toLocaleDateString([], { weekday: 'short' });
    }

    // Older
    return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
  };

  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <h1>City Growth AI</h1>
        <button className="new-chat-btn" onClick={onNewChat}>
          + New Chat
        </button>
      </div>

      <div className="sidebar-conversations">
        {loading ? (
          <div className="sidebar-loading">Loading...</div>
        ) : conversations.length === 0 ? (
          <div className="sidebar-empty">No conversations yet</div>
        ) : (
          conversations.map((conv) => (
            <div
              key={conv.id}
              className={`conversation-item ${
                currentConversation?.id === conv.id ? 'active' : ''
              }`}
              onClick={() => onSelectConversation(conv)}
            >
              <div className="conversation-title">
                {conv.title.length > 40
                  ? conv.title.substring(0, 40) + '...'
                  : conv.title}
              </div>
              <div className="conversation-meta">
                <span className="conversation-date">
                  {formatDate(conv.updated_at)}
                </span>
                <button
                  className="conversation-delete"
                  onClick={(e) => handleDelete(e, conv.id)}
                  title="Delete conversation"
                >
                  x
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
