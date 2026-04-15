/**
 * Chat.jsx - Main chat interface component
 */

import { useState, useRef, useEffect } from 'react';
import Message from './Message';
import { sendMessage } from './api';

export default function Chat({
  conversation,
  messages,
  onNewMessage,
  onConversationCreated
}) {
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const messagesEndRef = useRef(null);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userMessage = input.trim();
    setInput('');
    setError(null);
    setIsLoading(true);

    // Optimistically add user message
    const tempUserMsg = {
      id: Date.now(),
      role: 'user',
      content: userMessage,
      created_at: new Date().toISOString(),
    };
    onNewMessage(tempUserMsg);

    try {
      const result = await sendMessage(userMessage, conversation?.id);

      // If this created a new conversation, notify parent
      if (!conversation && result.thread_id) {
        onConversationCreated(result.thread_id, userMessage);
      }

      // Add assistant response
      const assistantMsg = {
        id: Date.now() + 1,
        role: 'assistant',
        content: result.response,
        artifact_json: result.artifact_json,
        artifact_path: result.artifact_path,
        tool_calls: result.tool_calls,
        created_at: new Date().toISOString(),
      };
      onNewMessage(assistantMsg);

    } catch (err) {
      setError(err.message);
      console.error('Chat error:', err);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="chat">
      <div className="chat-messages">
        {messages.length === 0 ? (
          <div className="chat-empty">
            <h2>City Growth AI</h2>
            <p>Ask questions about employment and wages in US cities.</p>
            <p className="chat-examples">
              Try: "Show wage trends in Austin" or "Compare employment growth in Austin vs Dallas"
            </p>
          </div>
        ) : (
          messages.map((msg, index) => (
            <Message key={msg.id || index} message={msg} />
          ))
        )}

        {isLoading && (
          <div className="message message-assistant">
            <div className="message-header">
              <span className="message-role">Assistant</span>
            </div>
            <div className="message-content loading">
              Thinking...
            </div>
          </div>
        )}

        {error && (
          <div className="chat-error">
            Error: {error}
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <form className="chat-input-form" onSubmit={handleSubmit}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about employment and wages..."
          disabled={isLoading}
          className="chat-input"
        />
        <button
          type="submit"
          disabled={isLoading || !input.trim()}
          className="chat-submit"
        >
          {isLoading ? '...' : 'Send'}
        </button>
      </form>
    </div>
  );
}
