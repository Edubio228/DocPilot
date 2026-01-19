/**
 * ChatMessage Component - PRODUCTION BUILD
 * Renders a single chat message (user or assistant).
 * Supports streaming indicator for in-progress responses.
 * Enhanced with card-based UI for high-level responses.
 * 
 * PRODUCTION FEATURES:
 * - Debounced copy button
 * - Accessibility improvements
 * - Proper event handling
 */

import React, { useCallback, useState } from 'react';

interface ChatMessageProps {
  role: 'user' | 'assistant';
  content: string;
  isStreaming?: boolean;
}

/**
 * Copy to clipboard with feedback
 */
function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  
  const handleCopy = useCallback(async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    
    if (copied) return;
    
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('[DocPilot] Failed to copy:', err);
    }
  }, [text, copied]);
  
  return (
    <button 
      className="docpilot-copy-btn"
      onClick={handleCopy}
      title={copied ? 'Copied!' : 'Copy code'}
      aria-label={copied ? 'Code copied to clipboard' : 'Copy code to clipboard'}
      type="button"
    >
      {copied ? '✓' : '📋'}
    </button>
  );
}

/**
 * Renders content with enhanced markdown formatting and cards
 */
function formatContent(content: string): React.ReactNode {
  if (!content) return null;
  
  const elements: React.ReactNode[] = [];
  
  // First, extract code blocks to protect them
  const codeBlockRegex = /```(\w*)\n?([\s\S]*?)```/g;
  const segments: Array<{type: 'text' | 'code', content: string, lang?: string}> = [];
  let lastIndex = 0;
  let match;
  
  while ((match = codeBlockRegex.exec(content)) !== null) {
    // Add text before code block
    if (match.index > lastIndex) {
      segments.push({
        type: 'text',
        content: content.slice(lastIndex, match.index)
      });
    }
    // Add code block
    segments.push({
      type: 'code',
      content: match[2].trim(),
      lang: match[1] || 'bash'
    });
    lastIndex = match.index + match[0].length;
  }
  // Add remaining text
  if (lastIndex < content.length) {
    segments.push({
      type: 'text',
      content: content.slice(lastIndex)
    });
  }
  
  // Process each segment
  segments.forEach((segment, segIndex) => {
    if (segment.type === 'code') {
      elements.push(
        <div key={`code-${segIndex}`} className="docpilot-code-block" role="region" aria-label={`Code block: ${segment.lang}`}>
          <div className="docpilot-code-header">
            <span className="docpilot-code-lang">{segment.lang}</span>
            <CopyButton text={segment.content} />
          </div>
          <pre className="docpilot-code-content">
            <code>{segment.content}</code>
          </pre>
        </div>
      );
    } else {
      // Process text content
      const paragraphs = segment.content.split(/\n\n+/);
      
      paragraphs.forEach((paragraph, pIndex) => {
        if (!paragraph.trim()) return;
        
        const key = `${segIndex}-${pIndex}`;
        
        // Check for h3 headers (### Step X:)
        if (paragraph.startsWith('### ')) {
          const headerText = paragraph.slice(4);
          elements.push(
            <h3 key={key} className="docpilot-step-header">
              {formatInlineElements(headerText)}
            </h3>
          );
          return;
        }
        
        // Check for h2 headers with emoji (card headers)
        if (paragraph.startsWith('## ')) {
          const headerText = paragraph.slice(3);
          elements.push(
            <div key={key} className="docpilot-card-header">
              <h2>{headerText}</h2>
            </div>
          );
          return;
        }
        
        // Check for bullet lists
        if (paragraph.includes('\n- ') || paragraph.startsWith('- ')) {
          const items = paragraph.split('\n').filter(line => line.trim().startsWith('-'));
          elements.push(
            <ul key={key} className="docpilot-card-list" role="list">
              {items.map((item, iIndex) => (
                <li key={iIndex} role="listitem">{formatInlineElements(item.replace(/^-\s*/, ''))}</li>
              ))}
            </ul>
          );
          return;
        }
        
        // Check for TL;DR or key answer (bold start)
        if (paragraph.startsWith('**TL;DR:**') || paragraph.startsWith('**')) {
          elements.push(
            <div key={key} className="docpilot-highlight-box" role="note">
              {formatInlineElements(paragraph)}
            </div>
          );
          return;
        }
        
        // Regular paragraph - handle line by line
        const lines = paragraph.split('\n').filter(l => l.trim());
        if (lines.length > 0) {
          elements.push(
            <p key={key} className="docpilot-message-paragraph">
              {lines.map((line, lIndex) => (
                <React.Fragment key={lIndex}>
                  {lIndex > 0 && <br />}
                  {formatInlineElements(line)}
                </React.Fragment>
              ))}
            </p>
          );
        }
      });
    }
  });
  
  return elements;
}

/**
 * Formats inline elements: code, bold, emoji
 */
function formatInlineElements(text: string): React.ReactNode {
  // Handle inline code (single backticks)
  const parts = text.split(/(`[^`]+`)/);
  
  return parts.map((part, index) => {
    if (part.startsWith('`') && part.endsWith('`')) {
      return (
        <code key={index} className="docpilot-inline-code">
          {part.slice(1, -1)}
        </code>
      );
    }
    // Handle bold
    const boldParts = part.split(/(\*\*[^*]+\*\*)/);
    return boldParts.map((bp, bi) => {
      if (bp.startsWith('**') && bp.endsWith('**')) {
        return <strong key={`${index}-${bi}`} className="docpilot-bold">{bp.slice(2, -2)}</strong>;
      }
      return <span key={`${index}-${bi}`}>{bp}</span>;
    });
  });
}

export const ChatMessage: React.FC<ChatMessageProps> = ({
  role,
  content,
  isStreaming = false,
}) => {
  const isUser = role === 'user';
  
  return (
    <div 
      className={`docpilot-message ${isUser ? 'user' : 'assistant'}`}
      role="article"
      aria-label={`${isUser ? 'Your message' : 'DocPilot response'}`}
    >
      {!isUser && (
        <div className="docpilot-avatar" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
          </svg>
        </div>
      )}
      <div className={`docpilot-message-content ${!isUser ? 'docpilot-response-card' : ''}`}>
        {isUser ? (
          content
        ) : (
          <>
            {formatContent(content)}
            {isStreaming && <span className="docpilot-cursor" aria-label="Loading..." />}
          </>
        )}
      </div>
    </div>
  );
};

export default ChatMessage;
