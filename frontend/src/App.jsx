/**
 * App.jsx - Main application component
 */

import { useState, useCallback } from 'react';
import Sidebar from './Sidebar';
import Chat from './Chat';
import { getConversation } from './api';
import './App.css';

export default function App() {
  const [currentConversation, setCurrentConversation] = useState(null);
  const [messages, setMessages] = useState([]);
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  const handleSelectConversation = useCallback(async (conversation) => {
    setCurrentConversation(conversation);

    // Load full conversation with messages
    try {
      const fullConversation = await getConversation(conversation.id);
      if (fullConversation) {
        setMessages(fullConversation.messages || []);
      }
    } catch (err) {
      console.error('Failed to load conversation:', err);
      setMessages([]);
    }
  }, []);

  const handleNewChat = useCallback(() => {
    setCurrentConversation(null);
    setMessages([]);
  }, []);

  const handleNewMessage = useCallback((message) => {
    setMessages(prev => [...prev, message]);
  }, []);

  const handleConversationCreated = useCallback((threadId, firstMessage) => {
    // Create a temporary conversation object
    const newConversation = {
      id: threadId,
      title: firstMessage.substring(0, 100),
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      message_count: 2,
    };
    setCurrentConversation(newConversation);

    // Trigger sidebar refresh
    setRefreshTrigger(prev => prev + 1);
  }, []);

  return (
    <div className="app">
      <Sidebar
        currentConversation={currentConversation}
        onSelectConversation={handleSelectConversation}
        onNewChat={handleNewChat}
        refreshTrigger={refreshTrigger}
      />
      <Chat
        conversation={currentConversation}
        messages={messages}
        onNewMessage={handleNewMessage}
        onConversationCreated={handleConversationCreated}
      />
    </div>
  );
}
