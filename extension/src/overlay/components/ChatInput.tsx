/**
 * ChatInput Component - PRODUCTION BUILD
 * Single text input for the conversational interface.
 * 
 * PRODUCTION FEATURES:
 * - Debounced submit to prevent double-clicks
 * - Proper keyboard handling
 * - Focus management
 * - Accessibility (aria labels)
 * 
 * NO mode buttons - user types naturally and agent infers intent.
 */

import React, { useRef, useEffect, useCallback, useState } from 'react';

interface ChatInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (value: string) => void;
  disabled?: boolean;
  placeholder?: string;
}

// Debounce delay in ms
const SUBMIT_DEBOUNCE_MS = 300;

export const ChatInput: React.FC<ChatInputProps> = ({
  value,
  onChange,
  onSubmit,
  disabled = false,
  placeholder = 'Ask anything about this page…',
}) => {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const submitTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  
  // Focus input on mount
  useEffect(() => {
    const timer = setTimeout(() => {
      inputRef.current?.focus();
    }, 300);
    return () => clearTimeout(timer);
  }, []);
  
  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (submitTimeoutRef.current) {
        clearTimeout(submitTimeoutRef.current);
      }
    };
  }, []);
  
  // Debounced submit handler to prevent double-clicks
  const handleSubmit = useCallback((e: React.FormEvent) => {
    e.preventDefault();
    e.stopPropagation();
    
    if (!value.trim() || disabled || isSubmitting) {
      return;
    }
    
    // Set submitting state to prevent double-clicks
    setIsSubmitting(true);
    
    // Submit the value
    onSubmit(value.trim());
    
    // Reset submitting state after debounce period
    submitTimeoutRef.current = setTimeout(() => {
      setIsSubmitting(false);
    }, SUBMIT_DEBOUNCE_MS);
  }, [value, disabled, isSubmitting, onSubmit]);
  
  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  }, [handleSubmit]);
  
  const handleChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    onChange(e.target.value);
  }, [onChange]);
  
  const isDisabled = disabled || isSubmitting;
  const canSubmit = !isDisabled && value.trim().length > 0;
  
  return (
    <div className="docpilot-input-area">
      <form onSubmit={handleSubmit} className="docpilot-input-wrapper">
        <input
          ref={inputRef}
          type="text"
          className="docpilot-input"
          value={value}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={isDisabled}
          autoComplete="off"
          autoCorrect="off"
          autoCapitalize="off"
          spellCheck="false"
          aria-label="Ask a question about this page"
        />
        <button
          type="submit"
          className="docpilot-send-btn"
          disabled={!canSubmit}
          aria-label="Send message"
          aria-busy={isSubmitting}
        >
          <svg 
            width="20" 
            height="20" 
            viewBox="0 0 24 24" 
            fill="none" 
            stroke="currentColor" 
            strokeWidth="2"
            strokeLinecap="round" 
            strokeLinejoin="round"
          >
            <line x1="22" y1="2" x2="11" y2="13" />
            <polygon points="22 2 15 22 11 13 2 9 22 2" />
          </svg>
        </button>
      </form>
    </div>
  );
};

export default ChatInput;
