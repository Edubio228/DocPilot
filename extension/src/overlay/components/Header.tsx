/**
 * Header Component - PRODUCTION BUILD
 * Displays the overlay header with title and close button.
 * 
 * PRODUCTION FEATURES:
 * - Debounced close button to prevent double-clicks
 * - Proper accessibility attributes
 * - Keyboard support (Enter/Space)
 */

import React, { useCallback, useState, useRef, useEffect } from 'react';

interface HeaderProps {
  pageTitle: string;
  onClose: () => void;
}

const CLOSE_DEBOUNCE_MS = 300;

export const Header: React.FC<HeaderProps> = ({ pageTitle, onClose }) => {
  const [isClosing, setIsClosing] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  
  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);
  
  // Debounced close handler
  const handleClose = useCallback((e: React.MouseEvent | React.KeyboardEvent) => {
    e.preventDefault();
    e.stopPropagation();
    
    if (isClosing) return;
    
    setIsClosing(true);
    onClose();
    
    // Reset after debounce period
    timeoutRef.current = setTimeout(() => {
      setIsClosing(false);
    }, CLOSE_DEBOUNCE_MS);
  }, [isClosing, onClose]);
  
  // Keyboard support
  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      handleClose(e);
    }
  }, [handleClose]);
  
  return (
    <div className="docpilot-header" role="banner">
      <div className="docpilot-header-title">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
        </svg>
        <span>DocPilot</span>
      </div>
      <button 
        className="docpilot-close-btn" 
        onClick={handleClose}
        onKeyDown={handleKeyDown}
        disabled={isClosing}
        aria-label="Close DocPilot panel"
        title="Close (Esc)"
        type="button"
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <path d="M1 1l12 12M13 1L1 13" strokeLinecap="round" />
        </svg>
      </button>
    </div>
  );
};
