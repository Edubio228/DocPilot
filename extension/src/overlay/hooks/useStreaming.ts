/**
 * useStreaming Hook - CONVERSATIONAL UI
 * 
 * Manages SSE streaming state and event handling for the overlay UI.
 * REFACTORED for single chat-style interface with automatic intent detection.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import type { 
  StreamEvent, 
  OverlayState, 
  ChatMessage,
  StreamEventType,
  StatusEventData,
  ChunkStartEventData,
  CompleteEventData,
  ErrorEventData,
} from '../../types';

const initialState: OverlayState = {
  isOpen: false,
  isLoading: false,
  status: 'Ready',
  pageUrl: '',
  pageTitle: '',
  pageText: '',  // Store page text for chat requests
  pageType: null,
  currentSection: null,
  streamedContent: '',
  finalSummary: '',
  followupResponse: '',
  error: null,
  messages: [],
  pageIndexed: false,  // Track if page has been indexed
};

export function useStreaming() {
  const [state, setState] = useState<OverlayState>(initialState);
  const streamBufferRef = useRef<string>('');
  const messageIdRef = useRef<number>(0);
  const pendingResponseRef = useRef<boolean>(false);  // Track if we're building a response
  
  /**
   * Resets the streaming state
   */
  const resetState = useCallback(() => {
    streamBufferRef.current = '';
    pendingResponseRef.current = false;
    setState(prev => ({
      ...initialState,
      isOpen: prev.isOpen,
      pageUrl: prev.pageUrl,
      pageTitle: prev.pageTitle,
      pageText: prev.pageText,
      messages: prev.messages,
    }));
  }, []);
  
  /**
   * Handles incoming stream events from the background script
   * REFACTORED for conversational UI - accumulates tokens into assistant messages
   */
  const handleStreamEvent = useCallback((event: StreamEvent) => {
    const eventType = event.event as StreamEventType;
    const data = event.data;
    
    switch (eventType) {
      case 'connected':
        setState(prev => ({
          ...prev,
          isLoading: true,
          status: 'Connected to server',
          error: null,
        }));
        break;
        
      case 'status': {
        const statusData = data as StatusEventData;
        setState(prev => ({
          ...prev,
          status: statusData.message || statusData.toString(),
        }));
        break;
      }
        
      case 'chunk_start': {
        const chunkData = data as ChunkStartEventData;
        setState(prev => ({
          ...prev,
          currentSection: {
            index: chunkData.index,
            heading: chunkData.heading,
          },
          status: `Summarizing: ${chunkData.heading}`,
        }));
        // Add section header to streamed content
        streamBufferRef.current += `\n\n## ${chunkData.heading}\n\n`;
        setState(prev => ({
          ...prev,
          streamedContent: streamBufferRef.current,
        }));
        break;
      }
        
      case 'chunk_end':
        setState(prev => ({
          ...prev,
          currentSection: null,
        }));
        break;
        
      case 'final_start':
        setState(prev => ({
          ...prev,
          status: 'Creating final summary',
          streamedContent: '',
        }));
        streamBufferRef.current = '';
        break;
        
      case 'final_end':
        setState(prev => ({
          ...prev,
          finalSummary: streamBufferRef.current,
        }));
        break;
        
      case 'token': {
        // Append token to buffer
        const token = typeof data === 'string' ? data : '';
        streamBufferRef.current += token;
        setState(prev => ({
          ...prev,
          streamedContent: streamBufferRef.current,
        }));
        break;
      }
        
      case 'followup_start':
        // Start building assistant response
        pendingResponseRef.current = true;
        setState(prev => ({
          ...prev,
          isLoading: true,
          status: 'Generating response',
          streamedContent: '',
        }));
        streamBufferRef.current = '';
        break;
        
      case 'followup_end': {
        // Finalize assistant message and add to chat
        if (streamBufferRef.current) {
          const assistantMessage: ChatMessage = {
            id: `msg-${++messageIdRef.current}`,
            role: 'assistant',
            content: streamBufferRef.current,
            timestamp: Date.now(),
          };
          setState(prev => ({
            ...prev,
            messages: [...prev.messages, assistantMessage],
            streamedContent: '',  // Clear streaming content
          }));
        }
        pendingResponseRef.current = false;
        break;
      }
        
      case 'synthesis_start':
        // Page summary synthesis starting - treat as assistant response
        pendingResponseRef.current = true;
        setState(prev => ({
          ...prev,
          status: 'Creating overview',
        }));
        streamBufferRef.current = '';
        break;
        
      case 'synthesis_end': {
        // Page summary complete - add as assistant message
        if (streamBufferRef.current) {
          const summaryMessage: ChatMessage = {
            id: `msg-${++messageIdRef.current}`,
            role: 'assistant',
            content: streamBufferRef.current,
            timestamp: Date.now(),
          };
          setState(prev => ({
            ...prev,
            messages: [...prev.messages, summaryMessage],
            finalSummary: streamBufferRef.current,
            streamedContent: '',
          }));
        }
        pendingResponseRef.current = false;
        break;
      }
        
      case 'complete': {
        const completeData = data as CompleteEventData;
        // If there's still buffered content that wasn't added as a message, add it now
        if (streamBufferRef.current && pendingResponseRef.current) {
          const finalMessage: ChatMessage = {
            id: `msg-${++messageIdRef.current}`,
            role: 'assistant',
            content: streamBufferRef.current,
            timestamp: Date.now(),
          };
          setState(prev => ({
            ...prev,
            messages: [...prev.messages, finalMessage],
            isLoading: false,
            status: 'Complete',
            streamedContent: '',
            finalSummary: completeData.summary || prev.finalSummary,
          }));
        } else {
          setState(prev => ({
            ...prev,
            isLoading: false,
            status: 'Complete',
            finalSummary: completeData.summary || prev.finalSummary,
          }));
        }
        pendingResponseRef.current = false;
        streamBufferRef.current = '';
        break;
      }
        
      case 'error': {
        const errorData = data as ErrorEventData;
        pendingResponseRef.current = false;
        setState(prev => ({
          ...prev,
          isLoading: false,
          status: 'Error',
          error: errorData.error || 'An error occurred',
        }));
        break;
      }
        
      case 'ping':
        // Heartbeat, ignore
        break;
        
      default:
        console.log('Unknown event type:', eventType, data);
    }
  }, []);
  
  /**
   * Sets page content info
   */
  const setPageContent = useCallback((content: { url: string; title: string; text: string }) => {
    setState(prev => ({
      ...prev,
      pageUrl: content.url,
      pageTitle: content.title,
      pageText: content.text,  // Store for chat requests
      status: 'Ready to chat',
    }));
  }, []);
  
  /**
   * Adds a user message and triggers follow-up
   */
  const addUserMessage = useCallback((query: string) => {
    const userMessage: ChatMessage = {
      id: `msg-${++messageIdRef.current}`,
      role: 'user',
      content: query,
      timestamp: Date.now(),
    };
    
    setState(prev => ({
      ...prev,
      messages: [...prev.messages, userMessage],
      isLoading: true,
      status: 'Processing your question',
    }));
    
    streamBufferRef.current = '';
    
    return userMessage;
  }, []);
  
  /**
   * Sets overlay visibility
   */
  const setOverlayOpen = useCallback((isOpen: boolean) => {
    setState(prev => ({
      ...prev,
      isOpen,
    }));
  }, []);
  
  /**
   * Clears chat messages
   */
  const clearMessages = useCallback(() => {
    setState(prev => ({
      ...prev,
      messages: [],
    }));
  }, []);
  
  // Listen for custom events from content script
  useEffect(() => {
    const handleShowEvent = () => {
      setOverlayOpen(true);
    };
    
    const handleHideEvent = () => {
      setOverlayOpen(false);
    };
    
    const handlePageContentEvent = (e: CustomEvent) => {
      setPageContent(e.detail);
    };
    
    const handleStreamEventWrapper = (e: CustomEvent<StreamEvent>) => {
      handleStreamEvent(e.detail);
    };
    
    // Get the root element - check shadow DOM first, then fallback to document
    const shadowHost = document.getElementById('docpilot-shadow-host');
    const root = shadowHost?.shadowRoot?.getElementById('docpilot-root') 
      || document.getElementById('docpilot-root');
    
    if (root) {
      root.addEventListener('docpilot:show', handleShowEvent);
      root.addEventListener('docpilot:hide', handleHideEvent);
      root.addEventListener('docpilot:pageContent', handlePageContentEvent as EventListener);
      root.addEventListener('docpilot:streamEvent', handleStreamEventWrapper as EventListener);
      
      return () => {
        root.removeEventListener('docpilot:show', handleShowEvent);
        root.removeEventListener('docpilot:hide', handleHideEvent);
        root.removeEventListener('docpilot:pageContent', handlePageContentEvent as EventListener);
        root.removeEventListener('docpilot:streamEvent', handleStreamEventWrapper as EventListener);
      };
    }
  }, [setOverlayOpen, setPageContent, handleStreamEvent]);
  
  return {
    state,
    handleStreamEvent,
    setPageContent,
    addUserMessage,
    setOverlayOpen,
    clearMessages,
    resetState,
  };
}
