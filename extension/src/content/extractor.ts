/**
 * Page Text Extractor
 * Extracts readable content from web pages while filtering out
 * navigation, footers, ads, and other non-content elements.
 */

/**
 * Elements to exclude from text extraction
 * These typically contain navigation, ads, or other non-content
 */
const EXCLUDED_SELECTORS = [
  'nav',
  'header',
  'footer',
  'aside',
  '.nav',
  '.navbar',
  '.navigation',
  '.menu',
  '.sidebar',
  '.footer',
  '.header',
  '.advertisement',
  '.ad',
  '.ads',
  '.social-share',
  '.social-links',
  '.comments',
  '.comment-section',
  '.related-posts',
  '.recommended',
  '.cookie-notice',
  '.cookie-banner',
  '.popup',
  '.modal',
  '[role="navigation"]',
  '[role="banner"]',
  '[role="contentinfo"]',
  '[aria-hidden="true"]',
  'script',
  'style',
  'noscript',
  'iframe',
  'svg',
  'canvas',
];

/**
 * Elements that typically contain main content
 * Ordered by specificity - more specific selectors first
 */
const CONTENT_SELECTORS = [
  // Documentation sites
  '.docs-content',
  '.documentation',
  '.doc-content',
  '[data-docs]',
  '.prose',  // Tailwind prose class - common in docs
  '.markdown-body',
  
  // Article/blog content
  'article',
  '.article-content',
  '.post-content',
  '.entry-content',
  
  // Generic content areas
  'main',
  '[role="main"]',
  '.content',
  '.main-content',
  '.page-content',
  '#content',
  '#main',
  '#article',
  
  // Fallback - look for large text containers
  '[class*="content"]',
  '[class*="body"]',
];

/**
 * Extracts the main text content from the current page
 */
export function extractPageContent(): {
  title: string;
  text: string;
  url: string;
} {
  const url = window.location.href;
  const title = document.title || '';
  
  // Try to find main content container
  let contentElement = findContentElement();
  
  if (!contentElement) {
    // Fallback to body
    contentElement = document.body;
  }
  
  // Clone to avoid modifying the actual DOM
  const clonedContent = contentElement.cloneNode(true) as HTMLElement;
  
  // Remove excluded elements
  removeExcludedElements(clonedContent);
  
  // Extract text with structure
  const text = extractStructuredText(clonedContent);
  
  return { title, text, url };
}

/**
 * Finds the most likely main content container
 */
function findContentElement(): HTMLElement | null {
  // Try each content selector
  for (const selector of CONTENT_SELECTORS) {
    const element = document.querySelector<HTMLElement>(selector);
    if (element && hasSubstantialContent(element)) {
      return element;
    }
  }
  
  // Try to find by content density
  return findByContentDensity();
}

/**
 * Checks if an element has substantial text content
 */
function hasSubstantialContent(element: HTMLElement): boolean {
  const text = element.textContent || '';
  const words = text.trim().split(/\s+/).length;
  return words > 50; // At least 50 words (lowered for docs pages with code blocks)
}

/**
 * Finds the element with the highest text content density
 */
function findByContentDensity(): HTMLElement | null {
  const candidates = document.querySelectorAll<HTMLElement>('div, section, article, main');
  let bestElement: HTMLElement | null = null;
  let bestScore = 0;
  
  candidates.forEach(element => {
    // Skip excluded elements
    if (EXCLUDED_SELECTORS.some(sel => {
      try {
        return element.matches(sel);
      } catch {
        return false;
      }
    })) {
      return;
    }
    
    // Skip very small elements
    const rect = element.getBoundingClientRect();
    if (rect.width < 200 || rect.height < 100) {
      return;
    }
    
    const text = element.textContent || '';
    const textLength = text.trim().length;
    const htmlLength = element.innerHTML.length;
    
    // Content density = text length / HTML length
    // Higher ratio means more text, less markup
    const density = textLength / (htmlLength || 1);
    const score = density * textLength;
    
    // Must have minimum content (lowered threshold)
    if (textLength > 200 && score > bestScore) {
      bestScore = score;
      bestElement = element;
    }
  });
  
  return bestElement;
}

/**
 * Removes excluded elements from a cloned DOM tree
 */
function removeExcludedElements(root: HTMLElement): void {
  EXCLUDED_SELECTORS.forEach(selector => {
    try {
      const elements = root.querySelectorAll(selector);
      elements.forEach(el => el.remove());
    } catch {
      // Invalid selector, skip
    }
  });
}

/**
 * Extracts text with markdown-like structure from an element
 */
function extractStructuredText(element: HTMLElement): string {
  const parts: string[] = [];
  
  function processNode(node: Node, depth: number = 0): void {
    if (node.nodeType === Node.TEXT_NODE) {
      const text = node.textContent?.trim();
      if (text) {
        parts.push(text);
      }
      return;
    }
    
    if (node.nodeType !== Node.ELEMENT_NODE) {
      return;
    }
    
    const el = node as HTMLElement;
    const tagName = el.tagName.toLowerCase();
    
    // Handle headings
    if (/^h[1-6]$/.test(tagName)) {
      const level = parseInt(tagName[1]);
      const prefix = '#'.repeat(level);
      const text = el.textContent?.trim();
      if (text) {
        parts.push(`\n\n${prefix} ${text}\n`);
      }
      return;
    }
    
    // Handle paragraphs
    if (tagName === 'p') {
      const text = el.textContent?.trim();
      if (text) {
        parts.push(`\n${text}\n`);
      }
      return;
    }
    
    // Handle lists
    if (tagName === 'ul' || tagName === 'ol') {
      parts.push('\n');
      const items = el.querySelectorAll(':scope > li');
      items.forEach((li, index) => {
        const prefix = tagName === 'ol' ? `${index + 1}.` : '-';
        const text = li.textContent?.trim();
        if (text) {
          parts.push(`${prefix} ${text}\n`);
        }
      });
      return;
    }
    
    // Handle code blocks
    if (tagName === 'pre' || tagName === 'code') {
      const text = el.textContent?.trim();
      if (text) {
        parts.push(`\n\`\`\`\n${text}\n\`\`\`\n`);
      }
      return;
    }
    
    // Handle blockquotes
    if (tagName === 'blockquote') {
      const text = el.textContent?.trim();
      if (text) {
        const quoted = text.split('\n').map(line => `> ${line}`).join('\n');
        parts.push(`\n${quoted}\n`);
      }
      return;
    }
    
    // Handle line breaks
    if (tagName === 'br') {
      parts.push('\n');
      return;
    }
    
    // Handle horizontal rules
    if (tagName === 'hr') {
      parts.push('\n---\n');
      return;
    }
    
    // Recursively process children for other elements
    el.childNodes.forEach(child => processNode(child, depth + 1));
  }
  
  processNode(element);
  
  // Clean up the text
  let text = parts.join(' ');
  
  // Normalize whitespace
  text = text.replace(/\n{3,}/g, '\n\n');  // Max 2 consecutive newlines
  text = text.replace(/[ \t]+/g, ' ');      // Normalize spaces
  text = text.replace(/\n +/g, '\n');       // Remove leading spaces after newlines
  text = text.trim();
  
  return text;
}

/**
 * Observes DOM changes to detect dynamic content loading
 */
export function observeDOMChanges(
  callback: (mutations: MutationRecord[]) => void
): MutationObserver {
  const observer = new MutationObserver(callback);
  
  observer.observe(document.body, {
    childList: true,
    subtree: true,
    characterData: false,
    attributes: false,
  });
  
  return observer;
}

/**
 * Gets a summary of the page structure for debugging
 */
export function getPageStructure(): {
  headings: string[];
  sections: number;
  wordCount: number;
} {
  const headings: string[] = [];
  document.querySelectorAll('h1, h2, h3, h4, h5, h6').forEach(h => {
    const text = h.textContent?.trim();
    if (text) {
      const level = h.tagName.toLowerCase();
      headings.push(`${level}: ${text}`);
    }
  });
  
  const sections = document.querySelectorAll('section, article').length;
  const bodyText = document.body.textContent || '';
  const wordCount = bodyText.trim().split(/\s+/).length;
  
  return { headings, sections, wordCount };
}
