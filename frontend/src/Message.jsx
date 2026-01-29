/**
 * Message.jsx - Renders a chat message with optional Plotly visualization
 */

import { useEffect, useRef } from 'react';
import Plotly from 'plotly.js-dist';

export default function Message({ message }) {
  const chartRef = useRef(null);

  useEffect(() => {
    if (message.artifact_json && chartRef.current) {
      try {
        const plotData = JSON.parse(message.artifact_json);

        // Render the Plotly chart
        Plotly.newPlot(
          chartRef.current,
          plotData.data,
          {
            ...plotData.layout,
            autosize: true,
            margin: { l: 50, r: 30, t: 50, b: 50 },
          },
          {
            responsive: true,
            displayModeBar: true,
            displaylogo: false,
          }
        );
      } catch (e) {
        console.error('Failed to render Plotly chart:', e);
      }
    }

    // Cleanup on unmount
    return () => {
      if (chartRef.current) {
        Plotly.purge(chartRef.current);
      }
    };
  }, [message.artifact_json]);

  const isUser = message.role === 'user';

  return (
    <div className={`message ${isUser ? 'message-user' : 'message-assistant'}`}>
      <div className="message-header">
        <span className="message-role">{isUser ? 'You' : 'Assistant'}</span>
        {message.created_at && (
          <span className="message-time">
            {new Date(message.created_at).toLocaleTimeString()}
          </span>
        )}
      </div>

      <div className="message-content">
        {message.content}
      </div>

      {message.artifact_json && (
        <div className="message-chart">
          <div ref={chartRef} style={{ width: '100%', minHeight: '400px' }} />
        </div>
      )}

      {message.tool_calls && message.tool_calls.length > 0 && (
        <div className="message-tools">
          <small>
            Tools used: {message.tool_calls.map(tc => tc.tool).join(', ')}
          </small>
        </div>
      )}
    </div>
  );
}
