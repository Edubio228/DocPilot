/**
 * Background Service Worker
 * Handles extension button clicks, manages connections to backend,
 * and coordinates communication between content scripts and overlay UI.
 */

import type {
  ExtensionMessage,
  StreamEvent,
  SummarizeRequest,
  FollowupRequest,
} from '../types';

// Configuration
const BACKEND_URL = 'http://localhost:8000';

// Track overlay state per tab
const tabStates = new Map<number, { isOverlayOpen: boolean }>();

/**
 * Handles extension icon click - toggles the overlay
 */
chrome.action.onClicked.addListener(async (tab) => {
  if (!tab.id || !tab.url) return;
  
  // Skip chrome:// and other restricted URLs
  if (tab.url.startsWith('chrome://') || tab.url.startsWith('chrome-extension://')) {
    console.log('Cannot run on restricted pages');
    return;
  }
  
  const tabId = tab.id;
  const currentState = tabStates.get(tabId) || { isOverlayOpen: false };
  
  try {
    // Send toggle message to content script
    await chrome.tabs.sendMessage(tabId, { type: 'TOGGLE_OVERLAY' });
    
    // Update state
    tabStates.set(tabId, { isOverlayOpen: !currentState.isOverlayOpen });
  } catch (error) {
    console.error('Error toggling overlay:', error);
    
    // Content script might not be injected yet, try injecting it
    try {
      await chrome.scripting.executeScript({
        target: { tabId },
        files: ['content.js'],
      });
      
      // Wait a bit for script to initialize
      await new Promise(resolve => setTimeout(resolve, 100));
      
      // Try again
      await chrome.tabs.sendMessage(tabId, { type: 'TOGGLE_OVERLAY' });
      tabStates.set(tabId, { isOverlayOpen: true });
    } catch (injectError) {
      console.error('Failed to inject content script:', injectError);
    }
  }
});

/**
 * Listen for messages from content scripts
 */
chrome.runtime.onMessage.addListener((message: ExtensionMessage, sender, sendResponse) => {
  const tabId = sender.tab?.id;
  
  switch (message.type) {
    case 'CHAT_REQUEST':
      // NEW: Unified chat handler - backend will classify intent
      handleChat(message.payload, tabId);
      sendResponse({ status: 'started' });
      break;
      
    case 'SUMMARIZE_PAGE':
      // Legacy: still supported for backward compat
      handleSummarize(message.payload, tabId);
      sendResponse({ status: 'started' });
      break;
      
    case 'FOLLOWUP_QUERY':
      // Legacy: still supported for backward compat
      handleFollowup(message.payload, tabId);
      sendResponse({ status: 'started' });
      break;
      
    case 'OVERLAY_READY':
      console.log('Overlay ready in tab', tabId);
      sendResponse({ status: 'acknowledged' });
      break;
      
    case 'CLOSE_OVERLAY':
      if (tabId) {
        tabStates.set(tabId, { isOverlayOpen: false });
      }
      sendResponse({ status: 'closed' });
      break;
      
    default:
      sendResponse({ status: 'unknown message type' });
  }
  
  return true; // Keep message channel open for async response
});

/**
 * Handles page summarization with SSE streaming
 */
async function handleSummarize(
  payload: { pageUrl: string; pageText: string; pageTitle: string },
  tabId?: number
) {
  if (!tabId) {
    console.error('No tab ID for summarize request');
    return;
  }
  
  const request: SummarizeRequest = {
    page_url: payload.pageUrl,
    page_text: payload.pageText,
    page_title: payload.pageTitle,
  };
  
  try {
    // Start SSE connection
    const response = await fetch(`${BACKEND_URL}/api/summarize`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
    });
    
    if (!response.ok) {
      throw new Error(`HTTP error: ${response.status}`);
    }
    
    if (!response.body) {
      throw new Error('No response body');
    }
    
    // Read SSE stream
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    
    // eslint-disable-next-line no-constant-condition
    while (true) {
      const { done, value } = await reader.read();
      
      if (done) {
        break;
      }
      
      buffer += decoder.decode(value, { stream: true });
      
      // Parse SSE events from buffer
      const events = parseSSEEvents(buffer);
      buffer = events.remaining;
      
      // Forward events to content script
      for (const event of events.parsed) {
        await sendStreamEvent(tabId, event);
      }
    }
    
  } catch (error) {
    console.error('Summarization error:', error);
    await sendStreamEvent(tabId, {
      event: 'error',
      data: { error: error instanceof Error ? error.message : 'Unknown error' },
    });
  }
}

/**
 * Handles follow-up questions with SSE streaming
 */
async function handleFollowup(
  payload: { pageUrl: string; query: string },
  tabId?: number
) {
  if (!tabId) {
    console.error('No tab ID for followup request');
    return;
  }
  
  const request: FollowupRequest = {
    page_url: payload.pageUrl,
    user_query: payload.query,
  };
  
  try {
    const response = await fetch(`${BACKEND_URL}/api/followup`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
    });
    
    if (!response.ok) {
      throw new Error(`HTTP error: ${response.status}`);
    }
    
    if (!response.body) {
      throw new Error('No response body');
    }
    
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    
    // eslint-disable-next-line no-constant-condition
    while (true) {
      const { done, value } = await reader.read();
      
      if (done) {
        break;
      }
      
      buffer += decoder.decode(value, { stream: true });
      
      const events = parseSSEEvents(buffer);
      buffer = events.remaining;
      
      for (const event of events.parsed) {
        await sendStreamEvent(tabId, event);
      }
    }
    
  } catch (error) {
    console.error('Followup error:', error);
    await sendStreamEvent(tabId, {
      event: 'error',
      data: { error: error instanceof Error ? error.message : 'Unknown error' },
    });
  }
}

/**
 * NEW: Unified chat handler with automatic intent classification
 * Backend will determine if this is a summary request, follow-up, explanation, etc.
 */
async function handleChat(
  payload: { pageUrl: string; pageText: string; pageTitle: string; query: string },
  tabId?: number
) {
  if (!tabId) {
    console.error('No tab ID for chat request');
    return;
  }
  
  const request = {
    page_url: payload.pageUrl,
    page_text: payload.pageText,
    page_title: payload.pageTitle,
    query: payload.query,
  };
  
  try {
    // Call unified /api/chat endpoint - backend handles intent classification
    const response = await fetch(`${BACKEND_URL}/api/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
    });
    
    if (!response.ok) {
      throw new Error(`HTTP error: ${response.status}`);
    }
    
    if (!response.body) {
      throw new Error('No response body');
    }
    
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    
    // eslint-disable-next-line no-constant-condition
    while (true) {
      const { done, value } = await reader.read();
      
      if (done) {
        break;
      }
      
      buffer += decoder.decode(value, { stream: true });
      
      const events = parseSSEEvents(buffer);
      buffer = events.remaining;
      
      for (const event of events.parsed) {
        await sendStreamEvent(tabId, event);
      }
    }
    
  } catch (error) {
    console.error('Chat error:', error);
    await sendStreamEvent(tabId, {
      event: 'error',
      data: { error: error instanceof Error ? error.message : 'Unknown error' },
    });
  }
}

/**
 * Parses SSE events from a text buffer
 */
function parseSSEEvents(buffer: string): { parsed: StreamEvent[]; remaining: string } {
  const events: StreamEvent[] = [];
  const lines = buffer.split('\n');
  
  let currentEvent: Partial<StreamEvent> = {};
  let remaining = '';
  let lastCompleteIndex = -1;
  
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    
    if (line === '') {
      // Empty line marks end of event
      if (currentEvent.event && currentEvent.data !== undefined) {
        events.push(currentEvent as StreamEvent);
        lastCompleteIndex = i;
      }
      currentEvent = {};
      continue;
    }
    
    if (line.startsWith('event:')) {
      currentEvent.event = line.slice(6).trim() as StreamEvent['event'];
    } else if (line.startsWith('data:')) {
      const dataStr = line.slice(5).trim();
      try {
        currentEvent.data = JSON.parse(dataStr);
      } catch {
        currentEvent.data = dataStr;
      }
    } else if (line.startsWith('id:')) {
      currentEvent.id = line.slice(3).trim();
    }
  }
  
  // Keep incomplete event data in the buffer
  if (lastCompleteIndex >= 0) {
    remaining = lines.slice(lastCompleteIndex + 1).join('\n');
  } else {
    remaining = buffer;
  }
  
  return { parsed: events, remaining };
}

/**
 * Sends a stream event to the content script
 */
async function sendStreamEvent(tabId: number, event: StreamEvent): Promise<void> {
  try {
    await chrome.tabs.sendMessage(tabId, {
      type: 'STREAM_EVENT',
      payload: event,
    });
  } catch (error) {
    console.error('Failed to send stream event:', error);
  }
}

// Clean up tab states when tabs are closed
chrome.tabs.onRemoved.addListener((tabId) => {
  tabStates.delete(tabId);
});

console.log('DocPilot background service worker initialized');
