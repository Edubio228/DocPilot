/**
 * Main Overlay App Component - PRODUCTION BUILD
 * 
 * REFACTORED: Single chat-style interface replacing tabs.
 * User types in a single text box, agent infers intent automatically.
 * 
 * PRODUCTION FEATURES:
 * - Keyboard shortcuts (Escape to close)
 * - Proper focus management
 * - Debounced handlers
 * - Accessibility improvements
 * 
 * UX REQUIREMENTS:
 * - Single chat-style text input with placeholder "Ask anything about this page…"
 * - Scrollable response area above input
 * - NO buttons for summary/follow-up
 * - NO mode selectors
 * - Streaming responses in real-time
 */

import React, { useState, useCallback, useRef, useEffect } from 'react';
import { Header } from './components/Header';
import { StatusBar } from './components/StatusBar';
import { ChatMessage } from './components/ChatMessage';
import { ChatInput } from './components/ChatInput';
import { useStreaming } from './hooks/useStreaming';

export const App: React.FC = () => {
  const { state, addUserMessage, setOverlayOpen } = useStreaming();
  const [inputValue, setInputValue] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  
  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [state.messages, state.streamedContent]);
  
  /**
   * Handles overlay close request
   */
  const handleClose = useCallback(() => {
    setOverlayOpen(false);
    window.dispatchEvent(new CustomEvent('docpilot:requestClose'));
  }, [setOverlayOpen]);
  
  /**
   * Keyboard shortcuts handler
   */
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Escape to close
      if (e.key === 'Escape') {
        e.preventDefault();
        handleClose();
      }
    };
    
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleClose]);
  
  /**
   * Handles user message submission
   * Agent will automatically infer intent (summary, explain, clarify, etc.)
   */
  const handleSubmit = useCallback((query: string) => {
    if (!query.trim() || state.isLoading) return;
    
    // Add user message to chat
    addUserMessage(query);
    
    // Send chat request via custom event (chrome.runtime not available in page context)
    // The backend will classify intent automatically from the query
    window.dispatchEvent(new CustomEvent('docpilot:chatRequest', {
      detail: {
        pageUrl: state.pageUrl,
        pageText: state.pageText || '',  // Include page text for first-time processing
        pageTitle: state.pageTitle || '',
        query: query,
      },
    }));
    
    setInputValue('');
  }, [addUserMessage, state.pageUrl, state.pageText, state.pageTitle, state.isLoading]);
  
  /**
   * Determines if we have any content to display
   */
  const hasContent = state.messages.length > 0 || state.streamedContent;
  
  /**
   * Streaming response indicator
   */
  const isStreaming = state.isLoading && state.streamedContent;
  
  return (
    <div 
      ref={containerRef}
      className="docpilot-overlay"
      role="dialog"
      aria-label="DocPilot Assistant"
      aria-modal="false"
    >
      {/* Header */}
      <Header 
        pageTitle={state.pageTitle || 'DocPilot'} 
        onClose={handleClose} 
      />
      
      {/* Status bar */}
      <StatusBar 
        status={state.status}
        isLoading={state.isLoading}
        isError={!!state.error}
      />
      
      {/* Error display */}
      {state.error && (
        <div className="docpilot-error mx-4 mt-4" role="alert">
          <strong>Error:</strong> {state.error}
        </div>
      )}
      
      {/* Chat messages area - scrollable */}
      <div className="docpilot-content docpilot-messages-container" role="log" aria-live="polite">
        {!hasContent ? (
          /* Empty state - prompt user to ask */
          <div className="docpilot-empty" aria-label="Welcome message">
            <svg 
              className="docpilot-empty-icon" 
              viewBox="0 0 24 24" 
              fill="none" 
              stroke="currentColor" 
              strokeWidth="2"
              aria-hidden="true"
            >
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
            </svg>
            <p>Ask anything about this page…</p>
            <p className="docpilot-hint">
              Try &quot;Summarize this page&quot; or ask a specific question
            </p>
          </div>
        ) : (
          /* Chat messages */
          <div className="docpilot-messages">
            {state.messages.map((message) => (
              <ChatMessage
                key={message.id}
                role={message.role}
                content={message.content}
              />
            ))}
            
            {/* Streaming response */}
            {isStreaming && (
              <ChatMessage
                role="assistant"
                content={state.streamedContent}
                isStreaming={true}
              />
            )}
            
            {/* Loading indicator when waiting for response */}
            {state.isLoading && !state.streamedContent && state.messages.length > 0 && (
              <div className="docpilot-loading" role="status" aria-label="Loading response">
                <div className="docpilot-spinner" aria-hidden="true" />
                <span>{state.status || 'Thinking...'}</span>
              </div>
            )}
            
            <div ref={messagesEndRef} aria-hidden="true" />
          </div>
        )}
      </div>
      
      {/* Single chat input - NO mode buttons */}
      <ChatInput
        value={inputValue}
        onChange={setInputValue}
        onSubmit={handleSubmit}
        disabled={state.isLoading}
        placeholder="Ask anything about this page…"
      />
    </div>
  );
};

export default App;
