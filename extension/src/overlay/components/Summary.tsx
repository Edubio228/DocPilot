/**
 * Summary Component
 * Displays the streaming summary content with proper formatting.
 * Shows loading state and handles markdown-like content.
 */

import React, { useEffect, useRef } from 'react';

interface SummaryProps {
  content: string;
  isLoading: boolean;
  showCursor: boolean;
  currentSection?: {
    index: number;
    heading: string;
  } | null;
}

export const Summary: React.FC<SummaryProps> = ({
  content,
  isLoading,
  showCursor,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  currentSection,
}) => {
  const contentRef = useRef<HTMLDivElement>(null);
  
  // Auto-scroll to bottom as content streams
  useEffect(() => {
    if (contentRef.current && isLoading) {
      contentRef.current.scrollTop = contentRef.current.scrollHeight;
    }
  }, [content, isLoading]);
  
  if (!content && isLoading) {
    return (
      <div className="docpilot-loading">
        <div className="docpilot-spinner" />
        <span>Analyzing page content...</span>
      </div>
    );
  }
  
  if (!content) {
    return (
      <div className="docpilot-empty">
        <svg className="docpilot-empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M9 12h6M9 16h6M9 8h6M5 3h14a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2z" />
        </svg>
        <p>Click the extension icon to summarize this page</p>
      </div>
    );
  }
  
  // Simple markdown-like rendering
  const renderContent = (text: string) => {
    const lines = text.split('\n');
    const elements: JSX.Element[] = [];
    let key = 0;
    
    for (const line of lines) {
      // Headings
      if (line.startsWith('## ')) {
        elements.push(
          <h2 key={key++} className="text-lg font-semibold text-gray-900 mt-4 mb-2">
            {line.slice(3)}
          </h2>
        );
      } else if (line.startsWith('### ')) {
        elements.push(
          <h3 key={key++} className="text-base font-semibold text-gray-800 mt-3 mb-2">
            {line.slice(4)}
          </h3>
        );
      } else if (line.startsWith('# ')) {
        elements.push(
          <h1 key={key++} className="text-xl font-bold text-gray-900 mt-4 mb-2">
            {line.slice(2)}
          </h1>
        );
      }
      // Bullet points
      else if (line.startsWith('- ') || line.startsWith('* ')) {
        elements.push(
          <li key={key++} className="ml-4 text-gray-700">
            {line.slice(2)}
          </li>
        );
      }
      // Numbered lists
      else if (/^\d+\.\s/.test(line)) {
        const match = line.match(/^\d+\.\s(.*)$/);
        if (match) {
          elements.push(
            <li key={key++} className="ml-4 text-gray-700 list-decimal">
              {match[1]}
            </li>
          );
        }
      }
      // Code blocks (simplified)
      else if (line.startsWith('```')) {
        // Skip code fence markers
        continue;
      }
      // Bold text
      else if (line.includes('**')) {
        const parts = line.split(/\*\*(.+?)\*\*/g);
        elements.push(
          <p key={key++} className="text-gray-700 mb-2">
            {parts.map((part, i) => 
              i % 2 === 1 ? <strong key={i}>{part}</strong> : part
            )}
          </p>
        );
      }
      // Regular paragraphs
      else if (line.trim()) {
        elements.push(
          <p key={key++} className="text-gray-700 mb-2">
            {line}
          </p>
        );
      }
      // Empty lines
      else {
        elements.push(<div key={key++} className="h-2" />);
      }
    }
    
    return elements;
  };
  
  return (
    <div ref={contentRef} className="docpilot-summary">
      {renderContent(content)}
      {showCursor && isLoading && <span className="docpilot-cursor" />}
    </div>
  );
};
