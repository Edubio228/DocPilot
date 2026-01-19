/**
 * FollowUp Component
 * Handles the chat-style follow-up questions interface.
 * Displays message history and input for new questions.
 */

import React, { useState, useRef, useEffect } from 'react';
import type { ChatMessage } from '../../types';

interface FollowUpProps {
  messages: ChatMessage[];
  isLoading: boolean;
  streamedResponse: string;
  onSubmit: (query: string) => void;
  disabled: boolean;
}

export const FollowUp: React.FC<FollowUpProps> = ({
  messages,
  isLoading,
  streamedResponse,
  onSubmit,
  disabled,
}) => {
  const [inputValue, setInputValue] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  
  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamedResponse]);
  
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!inputValue.trim() || disabled || isLoading) {
      return;
    }
    
    onSubmit(inputValue.trim());
    setInputValue('');
  };
  
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };
  
  return (
    <div className="flex flex-col h-full">
      {/* Messages area */}
      <div className="flex-1 overflow-y-auto p-4">
        {messages.length === 0 && !isLoading ? (
          <div className="text-center text-gray-500 py-8">
            <svg 
              className="w-12 h-12 mx-auto mb-3 opacity-50"
              viewBox="0 0 24 24" 
              fill="none" 
              stroke="currentColor" 
              strokeWidth="1.5"
            >
              <path d="M8 10h8M8 14h4M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              <path d="M21 12c0 4.97-4.03 9-9 9-1.5 0-2.91-.37-4.15-1.02L3 21l1.02-4.85A8.96 8.96 0 013 12c0-4.97 4.03-9 9-9s9 4.03 9 9z" />
            </svg>
            <p className="text-sm">Ask a follow-up question about this page</p>
          </div>
        ) : (
          <div className="docpilot-messages">
            {messages.map((message) => (
              <div
                key={message.id}
                className={`docpilot-message ${message.role}`}
              >
                {renderMessageContent(message.content)}
              </div>
            ))}
            
            {/* Streaming response */}
            {isLoading && streamedResponse && (
              <div className="docpilot-message assistant">
                {renderMessageContent(streamedResponse)}
                <span className="docpilot-cursor" />
              </div>
            )}
            
            {/* Loading indicator */}
            {isLoading && !streamedResponse && (
              <div className="docpilot-message assistant">
                <div className="flex items-center gap-2">
                  <div className="docpilot-spinner" style={{ width: 16, height: 16 }} />
                  <span className="text-gray-500">Thinking...</span>
                </div>
              </div>
            )}
            
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>
      
      {/* Input area */}
      <div className="docpilot-input-area">
        <form onSubmit={handleSubmit} className="docpilot-input-wrapper">
          <input
            ref={inputRef}
            type="text"
            className="docpilot-input"
            placeholder="Ask a follow-up question..."
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={disabled || isLoading}
          />
          <button
            type="submit"
            className="docpilot-send-btn"
            disabled={!inputValue.trim() || disabled || isLoading}
          >
            {isLoading ? (
              <div className="docpilot-spinner" style={{ width: 16, height: 16, borderColor: 'rgba(255,255,255,0.3)', borderTopColor: 'white' }} />
            ) : (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            )}
          </button>
        </form>
      </div>
    </div>
  );
};

/**
 * Renders message content with basic formatting
 */
function renderMessageContent(content: string): JSX.Element {
  // Split by code blocks
  const parts = content.split(/(```[\s\S]*?```)/g);
  
  return (
    <>
      {parts.map((part, index) => {
        if (part.startsWith('```') && part.endsWith('```')) {
          // Code block
          const code = part.slice(3, -3).replace(/^\w+\n/, ''); // Remove language tag
          return (
            <pre key={index} className="bg-gray-800 text-gray-100 p-3 rounded-lg text-sm overflow-x-auto my-2">
              <code>{code}</code>
            </pre>
          );
        }
        
        // Regular text with inline code
        const inlineCodeParts = part.split(/(`[^`]+`)/g);
        return (
          <span key={index}>
            {inlineCodeParts.map((codePart, codeIndex) => {
              if (codePart.startsWith('`') && codePart.endsWith('`')) {
                return (
                  <code 
                    key={codeIndex} 
                    className="bg-gray-200 px-1.5 py-0.5 rounded text-sm font-mono"
                  >
                    {codePart.slice(1, -1)}
                  </code>
                );
              }
              return codePart;
            })}
          </span>
        );
      })}
    </>
  );
}
