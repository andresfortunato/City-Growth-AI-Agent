/**
 * api.js - WebSocket and REST client for City Growth AI
 */

const API_BASE = 'http://localhost:8001';
const WS_BASE = 'ws://localhost:8001';

/**
 * Send a chat message via REST API (non-streaming)
 */
export async function sendMessage(message, threadId = null) {
  const response = await fetch(`${API_BASE}/api/chat/message`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      message,
      thread_id: threadId,
    }),
  });

  if (!response.ok) {
    throw new Error(`API error: ${response.status}`);
  }

  return response.json();
}

/**
 * Get list of conversations
 */
export async function getConversations(limit = 50, offset = 0) {
  const response = await fetch(
    `${API_BASE}/api/chat/conversations?limit=${limit}&offset=${offset}`
  );

  if (!response.ok) {
    throw new Error(`API error: ${response.status}`);
  }

  return response.json();
}

/**
 * Get a single conversation with messages
 */
export async function getConversation(conversationId) {
  const response = await fetch(
    `${API_BASE}/api/chat/conversations/${conversationId}`
  );

  if (!response.ok) {
    if (response.status === 404) {
      return null;
    }
    throw new Error(`API error: ${response.status}`);
  }

  return response.json();
}

/**
 * Delete a conversation
 */
export async function deleteConversation(conversationId) {
  const response = await fetch(
    `${API_BASE}/api/chat/conversations/${conversationId}`,
    { method: 'DELETE' }
  );

  if (!response.ok) {
    throw new Error(`API error: ${response.status}`);
  }

  return response.json();
}

/**
 * WebSocket connection manager for streaming chat
 */
export class ChatWebSocket {
  constructor(onMessage, onError, onClose) {
    this.ws = null;
    this.onMessage = onMessage;
    this.onError = onError || console.error;
    this.onClose = onClose || (() => {});
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 5;
    this.pingInterval = null;
  }

  connect() {
    if (this.ws?.readyState === WebSocket.OPEN) {
      return;
    }

    this.ws = new WebSocket(`${WS_BASE}/api/chat/ws`);

    this.ws.onopen = () => {
      console.log('WebSocket connected');
      this.reconnectAttempts = 0;

      // Start ping interval for keepalive
      this.pingInterval = setInterval(() => {
        if (this.ws?.readyState === WebSocket.OPEN) {
          this.ws.send(JSON.stringify({ type: 'ping' }));
        }
      }, 30000);
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type !== 'pong') {
          this.onMessage(data);
        }
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e);
      }
    };

    this.ws.onerror = (error) => {
      console.error('WebSocket error:', error);
      this.onError(error);
    };

    this.ws.onclose = () => {
      console.log('WebSocket closed');
      clearInterval(this.pingInterval);
      this.onClose();

      // Attempt to reconnect
      if (this.reconnectAttempts < this.maxReconnectAttempts) {
        this.reconnectAttempts++;
        const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
        console.log(`Reconnecting in ${delay}ms...`);
        setTimeout(() => this.connect(), delay);
      }
    };
  }

  send(message, threadId = null) {
    if (this.ws?.readyState !== WebSocket.OPEN) {
      this.connect();
      // Wait for connection then send
      setTimeout(() => this.send(message, threadId), 500);
      return;
    }

    this.ws.send(JSON.stringify({
      type: 'message',
      content: message,
      thread_id: threadId,
    }));
  }

  disconnect() {
    clearInterval(this.pingInterval);
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }
}
