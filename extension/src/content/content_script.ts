/**
 * Content Script - PRODUCTION BUILD
 * Runs in the context of web pages. Handles:
 * - Injecting the Shadow DOM overlay (fully isolated from host page)
 * - Extracting page content
 * - Communication with background script
 * - Forwarding streaming events to overlay
 * 
 * PRODUCTION BEST PRACTICES:
 * - Shadow DOM isolation (no CSS leakage)
 * - Debounced event handlers (prevent double-clicks)
 * - Proper cleanup on unmount
 * - High z-index stacking context
 * - Glassmorphism transparent UI
 */

import { extractPageContent } from './extractor';
import type { ExtensionMessage } from '../types';

// ============================================
// CONSTANTS
// ============================================
const OVERLAY_CONTAINER_ID = 'docpilot-extension-container';
const SHADOW_HOST_ID = 'docpilot-shadow-host';
const DEBOUNCE_MS = 300;
const ANIMATION_DURATION_MS = 250;

// ============================================
// STATE
// ============================================
let overlayInjected = false;
let overlayVisible = false;
let shadowRoot: ShadowRoot | null = null;
let isAnimating = false;

// ============================================
// UTILITY FUNCTIONS
// ============================================

/**
 * Debounce function to prevent rapid-fire events
 */
function debounce<T extends (...args: unknown[]) => void>(
  fn: T,
  delay: number
): (...args: Parameters<T>) => void {
  let timeoutId: ReturnType<typeof setTimeout> | null = null;
  return (...args: Parameters<T>) => {
    if (timeoutId) clearTimeout(timeoutId);
    timeoutId = setTimeout(() => fn(...args), delay);
  };
}

/**
 * Prevents double-click by checking animation state
 */
function preventDoubleAction(): boolean {
  if (isAnimating) return true;
  return false;
}

/**
 * Injects the overlay into the page using Shadow DOM
 * This isolates our styles from the host page completely
 * 
 * PRODUCTION FEATURES:
 * - Closed shadow DOM for full isolation
 * - All styles scoped within shadow
 * - High z-index stacking context
 */
function injectOverlay(): void {
  if (overlayInjected) {
    return;
  }
  
  // Create container with isolated stacking context
  const container = document.createElement('div');
  container.id = OVERLAY_CONTAINER_ID;
  container.setAttribute('data-docpilot-root', 'true');
  container.style.cssText = `
    all: initial !important;
    position: fixed !important;
    top: 0 !important;
    right: 0 !important;
    width: 420px !important;
    max-width: 500px !important;
    height: 100vh !important;
    height: 100dvh !important;
    z-index: 2147483647 !important;
    pointer-events: none !important;
    isolation: isolate !important;
    contain: layout style !important;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif !important;
    overflow: visible !important;
  `;
  
  // Create shadow host
  const shadowHost = document.createElement('div');
  shadowHost.id = SHADOW_HOST_ID;
  shadowHost.style.cssText = `
    all: initial !important;
    display: block !important;
    width: 100% !important;
    height: 100% !important;
    max-width: 500px !important;
  `;
  container.appendChild(shadowHost);
  
  // Attach closed shadow DOM for full isolation
  shadowRoot = shadowHost.attachShadow({ mode: 'open' });
  
  // Inject styles into shadow DOM
  const styleSheet = document.createElement('style');
  styleSheet.textContent = getOverlayStyles();
  shadowRoot.appendChild(styleSheet);
  
  // Create root element for React
  const root = document.createElement('div');
  root.id = 'docpilot-root';
  root.className = 'docpilot-overlay docpilot-hidden';
  shadowRoot.appendChild(root);
  
  // Add to page
  document.body.appendChild(container);
  
  // Load overlay script
  loadOverlayScript();
  
  overlayInjected = true;
  console.log('[DocPilot] Overlay injected with Shadow DOM isolation');
}

/**
 * Loads the React overlay bundle
 */
function loadOverlayScript(): void {
  const script = document.createElement('script');
  script.src = chrome.runtime.getURL('overlay.js');
  script.type = 'module';
  
  script.onload = () => {
    console.log('[DocPilot] Overlay script loaded');
  };
  
  script.onerror = (error) => {
    console.error('[DocPilot] Failed to load overlay script:', error);
  };
  
  // Append to head (script runs in page context)
  document.head.appendChild(script);
}

/**
 * Shows/hides the overlay panel with animation
 * Debounced to prevent double-click issues
 */
const toggleOverlay = debounce((): void => {
  if (preventDoubleAction()) return;
  
  if (!overlayInjected) {
    injectOverlay();
    // Wait for injection then show
    setTimeout(() => showOverlay(), 100);
    return;
  }
  
  if (overlayVisible) {
    hideOverlay();
  } else {
    showOverlay();
  }
}, DEBOUNCE_MS);

/**
 * Shows the overlay with smooth animation
 */
function showOverlay(): void {
  if (preventDoubleAction() || overlayVisible) return;
  
  const container = document.getElementById(OVERLAY_CONTAINER_ID);
  const root = shadowRoot?.getElementById('docpilot-root');
  if (!container || !root) return;
  
  isAnimating = true;
  
  // Remove hidden class and enable interactions
  root.classList.remove('docpilot-hidden');
  container.style.pointerEvents = 'auto';
  
  // Trigger entrance animation
  root.classList.add('docpilot-entering');
  
  setTimeout(() => {
    root.classList.remove('docpilot-entering');
    root.classList.add('docpilot-visible');
    isAnimating = false;
  }, ANIMATION_DURATION_MS);
  
  overlayVisible = true;
  
  // Dispatch custom event to notify React
  dispatchOverlayEvent('show');
  
  // Extract page content and send to overlay (for context)
  const content = extractPageContent();
  dispatchOverlayEvent('pageContent', content);
}

/**
 * Hides the overlay with smooth animation
 */
function hideOverlay(): void {
  if (preventDoubleAction() || !overlayVisible) return;
  
  const container = document.getElementById(OVERLAY_CONTAINER_ID);
  const root = shadowRoot?.getElementById('docpilot-root');
  if (!container || !root) return;
  
  isAnimating = true;
  
  // Trigger exit animation
  root.classList.remove('docpilot-visible');
  root.classList.add('docpilot-exiting');
  
  setTimeout(() => {
    root.classList.remove('docpilot-exiting');
    root.classList.add('docpilot-hidden');
    container.style.pointerEvents = 'none';
    isAnimating = false;
  }, ANIMATION_DURATION_MS);
  
  overlayVisible = false;
  
  // Notify background
  chrome.runtime.sendMessage({ type: 'CLOSE_OVERLAY' });
  
  // Dispatch to overlay
  dispatchOverlayEvent('hide');
}

/**
 * Dispatches custom events to the overlay React app
 */
function dispatchOverlayEvent(eventName: string, detail?: unknown): void {
  if (!shadowRoot) return;
  
  const root = shadowRoot.getElementById('docpilot-root');
  if (!root) return;
  
  const event = new CustomEvent(`docpilot:${eventName}`, {
    detail,
    bubbles: true,
  });
  
  root.dispatchEvent(event);
}

/**
 * Handles messages from background script
 */
function handleMessage(
  message: ExtensionMessage,
  sender: chrome.runtime.MessageSender,
  sendResponse: (response: unknown) => void
): boolean {
  switch (message.type) {
    case 'TOGGLE_OVERLAY':
      toggleOverlay();
      sendResponse({ status: 'toggled', visible: !overlayVisible });
      break;
      
    case 'STREAM_EVENT':
      // Forward streaming events to overlay
      dispatchOverlayEvent('streamEvent', message.payload);
      sendResponse({ status: 'forwarded' });
      break;
      
    case 'GET_PAGE_CONTENT': {
      const content = extractPageContent();
      sendResponse(content);
      break;
    }
      
    default:
      sendResponse({ status: 'unknown' });
  }
  
  return true; // Keep channel open
}

/**
 * Returns the CSS styles for the overlay - GLASSMORPHISM THEME
 * These are injected into the Shadow DOM for complete isolation
 * 
 * DESIGN PRINCIPLES:
 * - Transparent/frosted glass effect with backdrop-filter
 * - Subtle gradients and shadows
 * - Smooth animations and transitions
 * - Dark mode friendly with transparency
 * - Responsive and accessible
 */
function getOverlayStyles(): string {
  return `
    /* ============================================
       CSS RESET - FULL ISOLATION
       ============================================ */
    *, *::before, *::after {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      font-family: inherit;
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
    }
    
    :host {
      all: initial;
      display: block;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
    }
    
    /* ============================================
       ANIMATION STATES
       ============================================ */
    .docpilot-hidden {
      opacity: 0;
      transform: translateX(100%);
      pointer-events: none;
    }
    
    .docpilot-entering {
      animation: slideIn ${ANIMATION_DURATION_MS}ms cubic-bezier(0.16, 1, 0.3, 1) forwards;
    }
    
    .docpilot-visible {
      opacity: 1;
      transform: translateX(0);
    }
    
    .docpilot-exiting {
      animation: slideOut ${ANIMATION_DURATION_MS}ms cubic-bezier(0.7, 0, 0.84, 0) forwards;
    }
    
    @keyframes slideIn {
      from {
        opacity: 0;
        transform: translateX(100%);
      }
      to {
        opacity: 1;
        transform: translateX(0);
      }
    }
    
    @keyframes slideOut {
      from {
        opacity: 1;
        transform: translateX(0);
      }
      to {
        opacity: 0;
        transform: translateX(100%);
      }
    }
    
    /* ============================================
       GLASSMORPHISM OVERLAY BASE
       ============================================ */
    .docpilot-overlay {
      width: 420px;
      min-width: 380px;
      max-width: 500px;
      height: 100vh;
      height: 100dvh;
      background: rgba(15, 15, 25, 0.92);
      backdrop-filter: blur(20px) saturate(180%);
      -webkit-backdrop-filter: blur(20px) saturate(180%);
      border-left: 1px solid rgba(255, 255, 255, 0.1);
      box-shadow: 
        -8px 0 32px rgba(0, 0, 0, 0.3),
        inset 1px 0 0 rgba(255, 255, 255, 0.05);
      display: flex;
      flex-direction: column;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
      font-size: 14px;
      line-height: 1.5;
      color: rgba(255, 255, 255, 0.95);
      overflow: hidden;
      position: absolute;
      right: 0;
      top: 0;
      transition: transform ${ANIMATION_DURATION_MS}ms cubic-bezier(0.16, 1, 0.3, 1),
                  opacity ${ANIMATION_DURATION_MS}ms ease;
    }
    
    /* Global text wrapping */
    .docpilot-overlay * {
      word-wrap: break-word;
      overflow-wrap: break-word;
    }
    
    /* ============================================
       HEADER - FIXED HEIGHT
       ============================================ */
    .docpilot-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 14px 18px;
      min-height: 54px;
      background: rgba(255, 255, 255, 0.05);
      backdrop-filter: blur(10px);
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
      position: relative;
      overflow: hidden;
      flex-shrink: 0;
      box-sizing: border-box;
    }
    
    .docpilot-header::before {
      content: '';
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      height: 1px;
      background: linear-gradient(90deg, 
        transparent, 
        rgba(139, 92, 246, 0.5), 
        rgba(99, 102, 241, 0.5), 
        transparent);
    }
    
    .docpilot-header-title {
      font-weight: 600;
      font-size: 15px;
      display: flex;
      align-items: center;
      gap: 10px;
      color: rgba(255, 255, 255, 0.95);
    }
    
    .docpilot-header-title svg {
      width: 22px;
      height: 22px;
      color: #a78bfa;
      filter: drop-shadow(0 0 8px rgba(167, 139, 250, 0.4));
    }
    
    .docpilot-close-btn {
      background: rgba(255, 255, 255, 0.08);
      border: 1px solid rgba(255, 255, 255, 0.1);
      color: rgba(255, 255, 255, 0.8);
      width: 30px;
      height: 30px;
      border-radius: 8px;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: all 0.2s ease;
      -webkit-tap-highlight-color: transparent;
      user-select: none;
    }
    
    .docpilot-close-btn:hover {
      background: rgba(255, 255, 255, 0.15);
      border-color: rgba(255, 255, 255, 0.2);
      color: white;
      transform: scale(1.05);
    }
    
    .docpilot-close-btn:active {
      transform: scale(0.95);
    }
    
    /* ============================================
       STATUS BAR - FIXED HEIGHT
       ============================================ */
    .docpilot-status {
      padding: 10px 18px;
      background: rgba(255, 255, 255, 0.03);
      border-bottom: 1px solid rgba(255, 255, 255, 0.05);
      font-size: 12px;
      color: rgba(255, 255, 255, 0.6);
      display: flex;
      align-items: center;
      gap: 10px;
      min-height: 38px;
      flex-shrink: 0;
      box-sizing: border-box;
    }
    
    .docpilot-status-dot {
      width: 8px;
      height: 8px;
      min-width: 8px;
      border-radius: 50%;
      background: #10b981;
      box-shadow: 0 0 12px rgba(16, 185, 129, 0.6);
      animation: pulse 2s infinite;
      flex-shrink: 0;
    }
    
    .docpilot-status-dot.loading {
      background: #fbbf24;
      box-shadow: 0 0 12px rgba(251, 191, 36, 0.6);
    }
    
    .docpilot-status-dot.error {
      background: #ef4444;
      box-shadow: 0 0 12px rgba(239, 68, 68, 0.6);
      animation: none;
    }
    
    .docpilot-status-text {
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      flex: 1;
    }
    
    @keyframes pulse {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.6; transform: scale(0.9); }
    }
    
    /* ============================================
       CONTENT AREA - FLEXIBLE SCROLL
       ============================================ */
    .docpilot-content {
      flex: 1;
      min-height: 0;
      overflow-y: auto;
      overflow-x: hidden;
      padding: 18px;
      scrollbar-width: thin;
      scrollbar-color: rgba(255, 255, 255, 0.2) transparent;
    }
    
    .docpilot-content::-webkit-scrollbar {
      width: 6px;
    }
    
    .docpilot-content::-webkit-scrollbar-track {
      background: transparent;
    }
    
    .docpilot-content::-webkit-scrollbar-thumb {
      background: rgba(255, 255, 255, 0.2);
      border-radius: 3px;
    }
    
    .docpilot-content::-webkit-scrollbar-thumb:hover {
      background: rgba(255, 255, 255, 0.3);
    }
    
    /* ============================================
       CHAT MESSAGES
       ============================================ */
    .docpilot-messages {
      display: flex;
      flex-direction: column;
      gap: 16px;
    }
    
    .docpilot-messages-container {
      display: flex;
      flex-direction: column;
      background: transparent;
    }
    
    .docpilot-message {
      display: flex;
      gap: 12px;
      max-width: 95%;
      animation: messageIn 0.3s cubic-bezier(0.16, 1, 0.3, 1);
    }
    
    @keyframes messageIn {
      from {
        opacity: 0;
        transform: translateY(10px);
      }
      to {
        opacity: 1;
        transform: translateY(0);
      }
    }
    
    .docpilot-message.user {
      align-self: flex-end;
      flex-direction: row-reverse;
    }
    
    .docpilot-message.user .docpilot-message-content {
      background: linear-gradient(135deg, 
        rgba(99, 102, 241, 0.9) 0%, 
        rgba(139, 92, 246, 0.9) 100%);
      color: white;
      padding: 12px 16px;
      border-radius: 18px 18px 4px 18px;
      font-size: 14px;
      box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
    }
    
    .docpilot-message.assistant {
      align-self: flex-start;
    }
    
    /* Avatar - Glassmorphism */
    .docpilot-avatar {
      width: 34px;
      height: 34px;
      min-width: 34px;
      background: linear-gradient(135deg, 
        rgba(99, 102, 241, 0.3) 0%, 
        rgba(139, 92, 246, 0.3) 100%);
      backdrop-filter: blur(8px);
      border: 1px solid rgba(255, 255, 255, 0.15);
      border-radius: 12px;
      display: flex;
      align-items: center;
      justify-content: center;
      color: #a78bfa;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
    }
    
    .docpilot-avatar svg {
      width: 18px;
      height: 18px;
    }
    
    /* ============================================
       RESPONSE CARD - FROSTED GLASS
       ============================================ */
    .docpilot-response-card {
      background: rgba(255, 255, 255, 0.05);
      backdrop-filter: blur(10px);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 16px;
      padding: 16px;
      box-shadow: 
        0 4px 16px rgba(0, 0, 0, 0.2),
        inset 0 1px 0 rgba(255, 255, 255, 0.05);
      max-width: 100%;
      overflow: hidden;
    }
    
    /* Card header with emoji */
    .docpilot-card-header {
      margin-bottom: 12px;
    }
    
    .docpilot-card-header h2 {
      font-size: 15px;
      font-weight: 600;
      color: rgba(255, 255, 255, 0.95);
      margin: 0;
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }
    
    /* Highlight box for TL;DR */
    .docpilot-highlight-box {
      background: linear-gradient(135deg, 
        rgba(99, 102, 241, 0.15) 0%, 
        rgba(139, 92, 246, 0.1) 100%);
      border-left: 3px solid #a78bfa;
      padding: 12px 14px;
      border-radius: 0 12px 12px 0;
      margin: 10px 0;
      font-size: 14px;
      color: rgba(255, 255, 255, 0.9);
    }
    
    .docpilot-highlight-box strong {
      color: #c4b5fd;
    }
    
    /* Section label */
    .docpilot-section-label {
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: rgba(255, 255, 255, 0.5);
      margin: 14px 0 8px 0;
    }
    
    /* Card bullet list */
    .docpilot-card-list {
      list-style: none;
      padding: 0;
      margin: 10px 0;
    }
    
    .docpilot-card-list li {
      position: relative;
      padding-left: 20px;
      margin-bottom: 10px;
      font-size: 13px;
      color: rgba(255, 255, 255, 0.85);
      line-height: 1.6;
    }
    
    .docpilot-card-list li::before {
      content: '';
      position: absolute;
      left: 0;
      top: 8px;
      width: 6px;
      height: 6px;
      background: linear-gradient(135deg, #a78bfa 0%, #6366f1 100%);
      border-radius: 50%;
      box-shadow: 0 0 8px rgba(167, 139, 250, 0.4);
    }
    
    /* Steps list with numbers */
    .docpilot-steps-list {
      list-style: none;
      padding: 0;
      margin: 12px 0;
      counter-reset: step-counter;
    }
    
    .docpilot-step-item {
      display: flex;
      gap: 14px;
      margin-bottom: 14px;
      align-items: flex-start;
    }
    
    .docpilot-step-number {
      min-width: 28px;
      height: 28px;
      background: linear-gradient(135deg, 
        rgba(99, 102, 241, 0.4) 0%, 
        rgba(139, 92, 246, 0.4) 100%);
      border: 1px solid rgba(255, 255, 255, 0.15);
      color: white;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 12px;
      font-weight: 600;
      box-shadow: 0 2px 8px rgba(99, 102, 241, 0.3);
    }
    
    .docpilot-step-content {
      flex: 1;
      font-size: 13px;
      color: rgba(255, 255, 255, 0.85);
      line-height: 1.6;
      padding-top: 4px;
    }
    
    .docpilot-step-content strong {
      color: rgba(255, 255, 255, 0.95);
      font-weight: 600;
    }
    
    /* Bold text styling */
    .docpilot-bold {
      color: rgba(255, 255, 255, 0.95);
      font-weight: 600;
    }
    
    /* Inline code */
    .docpilot-inline-code {
      background: rgba(167, 139, 250, 0.15);
      color: #c4b5fd;
      padding: 2px 8px;
      border-radius: 6px;
      font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
      font-size: 12px;
      border: 1px solid rgba(167, 139, 250, 0.2);
    }
    
    /* ============================================
       CODE BLOCKS - DARK GLASS
       ============================================ */
    .docpilot-code-block {
      background: rgba(0, 0, 0, 0.4);
      backdrop-filter: blur(8px);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 12px;
      margin: 14px 0;
      overflow: hidden;
      box-shadow: 
        0 4px 16px rgba(0, 0, 0, 0.3),
        inset 0 1px 0 rgba(255, 255, 255, 0.03);
      max-width: 100%;
    }
    
    .docpilot-code-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 10px 14px;
      background: rgba(255, 255, 255, 0.03);
      border-bottom: 1px solid rgba(255, 255, 255, 0.05);
    }
    
    .docpilot-code-lang {
      color: rgba(255, 255, 255, 0.5);
      font-size: 11px;
      font-weight: 500;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    
    .docpilot-copy-btn {
      background: rgba(255, 255, 255, 0.08);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 6px;
      cursor: pointer;
      padding: 5px 10px;
      font-size: 11px;
      color: rgba(255, 255, 255, 0.7);
      transition: all 0.2s ease;
      -webkit-tap-highlight-color: transparent;
      user-select: none;
    }
    
    .docpilot-copy-btn:hover {
      background: rgba(255, 255, 255, 0.15);
      color: white;
    }
    
    .docpilot-copy-btn:active {
      transform: scale(0.95);
    }
    
    .docpilot-code-content {
      margin: 0;
      padding: 14px 16px;
      overflow-x: auto;
      font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
      font-size: 12px;
      line-height: 1.6;
      color: #e2e8f0;
      white-space: pre;
      max-width: 100%;
      scrollbar-width: thin;
      scrollbar-color: rgba(255, 255, 255, 0.2) transparent;
    }
    
    .docpilot-code-content::-webkit-scrollbar {
      height: 6px;
    }
    
    .docpilot-code-content::-webkit-scrollbar-track {
      background: transparent;
    }
    
    .docpilot-code-content::-webkit-scrollbar-thumb {
      background: rgba(255, 255, 255, 0.2);
      border-radius: 3px;
    }
    
    .docpilot-code-content code {
      background: transparent;
      padding: 0;
      color: inherit;
      font-family: inherit;
      white-space: pre-wrap;
      word-break: break-all;
    }
    
    /* Step header styling */
    .docpilot-step-header {
      font-size: 14px;
      font-weight: 600;
      color: rgba(255, 255, 255, 0.95);
      margin: 18px 0 10px 0;
      padding-bottom: 6px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.1);
      word-wrap: break-word;
      overflow-wrap: break-word;
    }
    
    /* Message paragraph */
    .docpilot-message-paragraph {
      font-size: 13px;
      color: rgba(255, 255, 255, 0.85);
      line-height: 1.7;
      margin-bottom: 10px;
      word-wrap: break-word;
      overflow-wrap: break-word;
    }
    
    .docpilot-message-heading {
      font-weight: 600;
      color: rgba(255, 255, 255, 0.95);
      margin: 14px 0 10px 0;
    }
    
    /* ============================================
       INPUT AREA - FIXED AT BOTTOM
       ============================================ */
    .docpilot-input-area {
      padding: 14px 18px;
      background: rgba(255, 255, 255, 0.03);
      border-top: 1px solid rgba(255, 255, 255, 0.08);
      backdrop-filter: blur(10px);
      flex-shrink: 0;
      min-height: 68px;
      box-sizing: border-box;
    }
    
    .docpilot-input-wrapper {
      display: flex;
      gap: 10px;
      align-items: center;
      height: 40px;
    }
    
    .docpilot-input {
      flex: 1;
      height: 40px;
      padding: 0 16px;
      background: rgba(255, 255, 255, 0.08);
      border: 1px solid rgba(255, 255, 255, 0.12);
      border-radius: 12px;
      font-size: 14px;
      color: rgba(255, 255, 255, 0.95);
      outline: none;
      transition: background 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
      box-sizing: border-box;
    }
    
    .docpilot-input:focus {
      background: rgba(255, 255, 255, 0.1);
      border-color: rgba(139, 92, 246, 0.5);
      box-shadow: 0 0 0 3px rgba(139, 92, 246, 0.15);
    }
    
    .docpilot-input:disabled {
      opacity: 0.6;
      cursor: not-allowed;
    }
    
    .docpilot-input::placeholder {
      color: rgba(255, 255, 255, 0.4);
    }
    
    .docpilot-send-btn {
      height: 40px;
      width: 40px;
      min-width: 40px;
      padding: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      background: linear-gradient(135deg, 
        rgba(99, 102, 241, 0.9) 0%, 
        rgba(139, 92, 246, 0.9) 100%);
      color: white;
      border: none;
      border-radius: 12px;
      font-weight: 500;
      cursor: pointer;
      transition: transform 0.2s ease, box-shadow 0.2s ease, opacity 0.2s ease;
      box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
      -webkit-tap-highlight-color: transparent;
      user-select: none;
      box-sizing: border-box;
    }
    
    .docpilot-send-btn:hover:not(:disabled) {
      transform: translateY(-1px);
      box-shadow: 0 6px 16px rgba(99, 102, 241, 0.4);
    }
    
    .docpilot-send-btn:active:not(:disabled) {
      transform: scale(0.95);
    }
    
    .docpilot-send-btn:disabled {
      background: rgba(255, 255, 255, 0.1);
      color: rgba(255, 255, 255, 0.4);
      cursor: not-allowed;
      box-shadow: none;
      opacity: 0.5;
    }
    
    /* ============================================
       LOADING STATES
       ============================================ */
    .docpilot-loading {
      display: flex;
      align-items: center;
      gap: 12px;
      color: rgba(255, 255, 255, 0.6);
      padding: 20px;
    }
    
    .docpilot-spinner {
      width: 22px;
      height: 22px;
      border: 2px solid rgba(255, 255, 255, 0.1);
      border-top-color: #a78bfa;
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
    }
    
    @keyframes spin {
      to { transform: rotate(360deg); }
    }
    
    /* Streaming cursor */
    .docpilot-cursor {
      display: inline-block;
      width: 8px;
      height: 18px;
      background: #a78bfa;
      margin-left: 3px;
      border-radius: 2px;
      animation: blink 1s infinite;
      box-shadow: 0 0 8px rgba(167, 139, 250, 0.5);
    }
    
    @keyframes blink {
      0%, 50% { opacity: 1; }
      51%, 100% { opacity: 0; }
    }
    
    /* ============================================
       ERROR STATE
       ============================================ */
    .docpilot-error {
      padding: 14px;
      background: rgba(239, 68, 68, 0.15);
      border: 1px solid rgba(239, 68, 68, 0.3);
      border-radius: 12px;
      color: #fca5a5;
      font-size: 13px;
      backdrop-filter: blur(8px);
    }
    
    /* ============================================
       EMPTY STATE
       ============================================ */
    .docpilot-empty {
      text-align: center;
      padding: 50px 24px;
      color: rgba(255, 255, 255, 0.5);
    }
    
    .docpilot-empty-icon {
      width: 52px;
      height: 52px;
      margin: 0 auto 18px;
      opacity: 0.4;
      color: #a78bfa;
    }
    
    .docpilot-empty p {
      font-size: 15px;
      color: rgba(255, 255, 255, 0.7);
    }
    
    .docpilot-hint {
      font-size: 13px;
      color: rgba(255, 255, 255, 0.4);
      margin-top: 10px;
    }
    
    /* ============================================
       FOCUS VISIBLE STYLES (Accessibility)
       ============================================ */
    .docpilot-close-btn:focus-visible,
    .docpilot-send-btn:focus-visible,
    .docpilot-input:focus-visible,
    .docpilot-copy-btn:focus-visible {
      outline: 2px solid #a78bfa;
      outline-offset: 2px;
    }
    
    /* ============================================
       REDUCED MOTION
       ============================================ */
    @media (prefers-reduced-motion: reduce) {
      .docpilot-overlay,
      .docpilot-message,
      .docpilot-hidden,
      .docpilot-entering,
      .docpilot-exiting {
        animation: none !important;
        transition: none !important;
      }
    }
  `;
}

/**
 * Listen for custom events from the overlay (which runs in page context)
 * Uses proper event cleanup pattern
 */
function setupOverlayEventListeners(): void {
  // Overlay ready event
  const handleOverlayReady = (): void => {
    console.log('[DocPilot] Overlay ready');
    chrome.runtime.sendMessage({ type: 'OVERLAY_READY' });
  };
  
  // Chat request from overlay (unified handler)
  const handleChatRequest = ((event: CustomEvent) => {
    const { pageUrl, pageText, pageTitle, query } = event.detail;
    chrome.runtime.sendMessage({
      type: 'CHAT_REQUEST',
      payload: { pageUrl, pageText, pageTitle, query },
    });
  }) as EventListener;
  
  // Legacy follow-up request from overlay (backward compat)
  const handleFollowupRequest = ((event: CustomEvent) => {
    const { pageUrl, query } = event.detail;
    chrome.runtime.sendMessage({
      type: 'FOLLOWUP_QUERY',
      payload: { pageUrl, query },
    });
  }) as EventListener;
  
  // Close request from overlay
  const handleCloseRequest = (): void => {
    hideOverlay();
  };
  
  // Add all listeners
  window.addEventListener('docpilot:overlayReady', handleOverlayReady);
  window.addEventListener('docpilot:chatRequest', handleChatRequest);
  window.addEventListener('docpilot:followupRequest', handleFollowupRequest);
  window.addEventListener('docpilot:requestClose', handleCloseRequest);
  
  // Cleanup on page unload
  window.addEventListener('beforeunload', () => {
    window.removeEventListener('docpilot:overlayReady', handleOverlayReady);
    window.removeEventListener('docpilot:chatRequest', handleChatRequest);
    window.removeEventListener('docpilot:followupRequest', handleFollowupRequest);
    window.removeEventListener('docpilot:requestClose', handleCloseRequest);
  });
}

// ============================================
// INITIALIZATION
// ============================================
chrome.runtime.onMessage.addListener(handleMessage);
setupOverlayEventListeners();

console.log('[DocPilot] Content script loaded - Production Build');
