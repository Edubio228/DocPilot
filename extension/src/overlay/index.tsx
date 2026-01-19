/**
 * Overlay Entry Point
 * Initializes React and renders the overlay app.
 * This runs in the context of the page via Shadow DOM.
 */

import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import '../styles/tailwind.css';

/**
 * Finds the Shadow DOM root and mounts the React app
 */
function initializeOverlay(): void {
  // The overlay is injected into a Shadow DOM by the content script
  // We need to find our root element within the shadow DOM
  
  // First, try to find the shadow host
  const shadowHost = document.getElementById('docpilot-shadow-host');
  
  if (shadowHost && shadowHost.shadowRoot) {
    const root = shadowHost.shadowRoot.getElementById('docpilot-root');
    if (root) {
      mountApp(root);
      return;
    }
  }
  
  // Fallback: try direct mount (for development/testing)
  const directRoot = document.getElementById('docpilot-root');
  if (directRoot) {
    mountApp(directRoot);
    return;
  }
  
  // If not found, wait and retry
  console.log('DocPilot: Waiting for root element...');
  setTimeout(initializeOverlay, 100);
}

/**
 * Mounts the React application to the given element
 */
function mountApp(container: HTMLElement): void {
  try {
    const root = createRoot(container);
    root.render(
      <React.StrictMode>
        <App />
      </React.StrictMode>
    );
    
    console.log('DocPilot overlay mounted successfully');
    
    // Notify content script that we're ready via custom event
    // (chrome.runtime is not available in page context)
    window.dispatchEvent(new CustomEvent('docpilot:overlayReady'));
    
  } catch (error) {
    console.error('Failed to mount DocPilot overlay:', error);
  }
}

// Handle close request from content script
document.addEventListener('docpilot:requestClose', () => {
  // This event is dispatched when the user clicks close
  // The content script will handle actually hiding the overlay
});

// Initialize when the script loads
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initializeOverlay);
} else {
  initializeOverlay();
}
