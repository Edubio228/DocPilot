/**
 * Type definitions for DocPilot extension
 * Shared types between background, content, and overlay scripts
 */

// Message types for communication between scripts
export type MessageType =
  | 'TOGGLE_OVERLAY'
  | 'SUMMARIZE_PAGE'
  | 'FOLLOWUP_QUERY'
  | 'CHAT_REQUEST'  // NEW: Unified chat request
  | 'STREAM_EVENT'
  | 'GET_PAGE_CONTENT'
  | 'PAGE_CONTENT'
  | 'OVERLAY_READY'
  | 'CLOSE_OVERLAY'
  | 'ERROR';

export interface BaseMessage {
  type: MessageType;
}

export interface ToggleOverlayMessage extends BaseMessage {
  type: 'TOGGLE_OVERLAY';
}

export interface SummarizePageMessage extends BaseMessage {
  type: 'SUMMARIZE_PAGE';
  payload: {
    pageUrl: string;
    pageText: string;
    pageTitle: string;
  };
}

// NEW: Unified chat request message
export interface ChatRequestMessage extends BaseMessage {
  type: 'CHAT_REQUEST';
  payload: {
    pageUrl: string;
    pageText: string;
    pageTitle: string;
    query: string;
  };
}

export interface FollowupQueryMessage extends BaseMessage {
  type: 'FOLLOWUP_QUERY';
  payload: {
    pageUrl: string;
    query: string;
  };
}

export interface StreamEventMessage extends BaseMessage {
  type: 'STREAM_EVENT';
  payload: StreamEvent;
}

export interface PageContentMessage extends BaseMessage {
  type: 'PAGE_CONTENT';
  payload: {
    url: string;
    title: string;
    text: string;
  };
}

export interface ErrorMessage extends BaseMessage {
  type: 'ERROR';
  payload: {
    message: string;
    details?: string;
  };
}

export type ExtensionMessage =
  | ToggleOverlayMessage
  | SummarizePageMessage
  | ChatRequestMessage  // NEW: Unified chat
  | FollowupQueryMessage
  | StreamEventMessage
  | PageContentMessage
  | ErrorMessage
  | { type: 'GET_PAGE_CONTENT' }
  | { type: 'OVERLAY_READY' }
  | { type: 'CLOSE_OVERLAY' };

// Streaming event types from backend
export type StreamEventType =
  | 'connected'
  | 'status'
  | 'progress'
  | 'chunk_start'
  | 'chunk_end'
  | 'section_start'
  | 'section_end'
  | 'synthesis_start'
  | 'synthesis_end'
  | 'final_start'
  | 'final_end'
  | 'token'
  | 'followup_start'
  | 'followup_end'
  | 'complete'
  | 'error'
  | 'ping';

export interface StreamEvent {
  event: StreamEventType;
  data: unknown;
  id?: string;
}

export interface StatusEventData {
  message: string;
}

export interface ChunkStartEventData {
  index: number;
  heading: string;
}

export interface ChunkEndEventData {
  index: number;
}

export interface CompleteEventData {
  summary?: string;
  response?: string;
}

export interface ErrorEventData {
  error: string;
}

// Page types from backend
export type PageType = 'docs' | 'blog' | 'api' | 'readme' | 'unknown';

// Overlay state
export interface OverlayState {
  isOpen: boolean;
  isLoading: boolean;
  status: string;
  pageUrl: string;
  pageTitle: string;
  pageText: string;  // Store page text for chat requests
  pageType: PageType | null;
  currentSection: {
    index: number;
    heading: string;
  } | null;
  streamedContent: string;
  finalSummary: string;
  followupResponse: string;
  error: string | null;
  messages: ChatMessage[];
  pageIndexed: boolean;  // Track if page has been indexed
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
}

// Backend API types
export interface SummarizeRequest {
  page_url: string;
  page_text: string;
  page_title?: string;
}

export interface FollowupRequest {
  page_url: string;
  user_query: string;
}

// Configuration
export interface ExtensionConfig {
  backendUrl: string;
  streamingEnabled: boolean;
  maxRetries: number;
  retryDelay: number;
}

export const DEFAULT_CONFIG: ExtensionConfig = {
  backendUrl: 'http://localhost:8000',
  streamingEnabled: true,
  maxRetries: 3,
  retryDelay: 1000,
};
