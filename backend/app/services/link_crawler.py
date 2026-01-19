"""
Link Crawler Service Module
Fetches content from linked pages when current page doesn't have answers.

ARCHITECTURE:
- Extracts relevant links from page content
- Fetches and indexes linked pages on-demand
- Used when retrieval returns no good matches
"""

import re
import logging
import asyncio
import aiohttp
from typing import Optional
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

from ..config import settings

logger = logging.getLogger(__name__)


class LinkCrawler:
    """
    Service for crawling linked pages to find relevant content.
    
    CRAWL STRATEGY:
    1. Extract links from current page content
    2. Score links by relevance to query (link text matching)
    3. Fetch top N most relevant linked pages
    4. Return combined content for indexing
    """
    
    def __init__(self, max_pages: int = 3, timeout: int = 10):
        """
        Initialize link crawler.
        
        Args:
            max_pages: Maximum number of linked pages to fetch
            timeout: HTTP request timeout in seconds
        """
        self.max_pages = max_pages
        self.timeout = timeout
        self.session: Optional[aiohttp.ClientSession] = None
        
        logger.info(f"Link crawler initialized: max_pages={max_pages}")
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                headers={
                    "User-Agent": "DocPilot/1.0 (Documentation Assistant)"
                }
            )
        return self.session
    
    async def close(self):
        """Close the session."""
        if self.session and not self.session.closed:
            await self.session.close()
    
    def extract_links(self, page_text: str, base_url: str) -> list[dict]:
        """
        Extract all links from page content.
        
        Args:
            page_text: Raw HTML or markdown content
            base_url: Base URL for resolving relative links
            
        Returns:
            List of dicts with 'url', 'text', 'context'
        """
        links = []
        
        # Try HTML parsing first
        try:
            soup = BeautifulSoup(page_text, 'html.parser')
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href']
                text = a_tag.get_text(strip=True)
                
                # Skip empty, anchors, external, or non-doc links
                if not href or href.startswith('#') or href.startswith('javascript:'):
                    continue
                if href.startswith('mailto:') or href.startswith('tel:'):
                    continue
                    
                # Resolve relative URLs
                full_url = urljoin(base_url, href)
                
                # Only include same-domain links
                if urlparse(full_url).netloc != urlparse(base_url).netloc:
                    continue
                
                # Get surrounding context
                parent = a_tag.parent
                context = parent.get_text(strip=True)[:200] if parent else ""
                
                links.append({
                    "url": full_url,
                    "text": text,
                    "context": context
                })
        except Exception as e:
            logger.warning(f"HTML parsing failed: {e}")
        
        # Also try markdown link pattern
        md_link_pattern = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
        for match in md_link_pattern.finditer(page_text):
            text, href = match.groups()
            
            if href.startswith('#') or href.startswith('http://') and urlparse(href).netloc != urlparse(base_url).netloc:
                continue
                
            full_url = urljoin(base_url, href)
            
            # Get context around the link
            start = max(0, match.start() - 100)
            end = min(len(page_text), match.end() + 100)
            context = page_text[start:end]
            
            # Avoid duplicates
            if not any(l['url'] == full_url for l in links):
                links.append({
                    "url": full_url,
                    "text": text,
                    "context": context
                })
        
        logger.info(f"Extracted {len(links)} links from page")
        return links
    
    def score_links_for_query(self, links: list[dict], query: str) -> list[dict]:
        """
        Score links by relevance to the user's query.
        
        Args:
            links: List of link dicts
            query: User's search query
            
        Returns:
            Links sorted by relevance score (highest first)
        """
        query_words = set(query.lower().split())
        
        scored_links = []
        for link in links:
            text_lower = link['text'].lower()
            context_lower = link['context'].lower()
            
            # Score based on word overlap
            text_words = set(text_lower.split())
            context_words = set(context_lower.split())
            
            text_overlap = len(query_words & text_words)
            context_overlap = len(query_words & context_words)
            
            # Bonus for key documentation terms
            doc_keywords = {'setup', 'install', 'guide', 'tutorial', 'getting', 'started', 
                          'development', 'environment', 'configuration', 'wsl', 'windows',
                          'linux', 'mac', 'docker', 'vagrant', 'prerequisites'}
            
            keyword_bonus = len(query_words & doc_keywords & (text_words | context_words))
            
            score = (text_overlap * 3) + context_overlap + (keyword_bonus * 2)
            
            if score > 0:
                scored_links.append({
                    **link,
                    "relevance_score": score
                })
        
        # Sort by score
        scored_links.sort(key=lambda x: x["relevance_score"], reverse=True)
        
        logger.info(f"Scored {len(scored_links)} relevant links for query")
        return scored_links
    
    async def fetch_page_content(self, url: str) -> Optional[dict]:
        """
        Fetch content from a URL.
        
        Args:
            url: URL to fetch
            
        Returns:
            Dict with 'url', 'title', 'text' or None if failed
        """
        try:
            session = await self._get_session()
            
            async with session.get(url) as response:
                if response.status != 200:
                    logger.warning(f"Failed to fetch {url}: HTTP {response.status}")
                    return None
                
                html = await response.text()
                
                # Parse with BeautifulSoup
                soup = BeautifulSoup(html, 'html.parser')
                
                # Get title
                title = ""
                title_tag = soup.find('title')
                if title_tag:
                    title = title_tag.get_text(strip=True)
                
                # Remove script, style, nav elements
                for element in soup(['script', 'style', 'nav', 'header', 'footer', 'aside']):
                    element.decompose()
                
                # Get main content
                main = soup.find('main') or soup.find('article') or soup.find('div', class_='content')
                if main:
                    text = main.get_text(separator='\n', strip=True)
                else:
                    text = soup.get_text(separator='\n', strip=True)
                
                # Clean up excessive whitespace
                text = re.sub(r'\n{3,}', '\n\n', text)
                text = re.sub(r' {2,}', ' ', text)
                
                logger.info(f"Fetched {url}: {len(text)} chars")
                
                return {
                    "url": url,
                    "title": title,
                    "text": text,
                    "html": html  # Keep HTML for link extraction
                }
                
        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching {url}")
            return None
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return None
    
    async def crawl_relevant_pages(
        self, 
        page_text: str, 
        base_url: str, 
        query: str
    ) -> list[dict]:
        """
        Crawl pages linked from current page that are relevant to query.
        
        Args:
            page_text: Current page content (HTML or text)
            base_url: Current page URL
            query: User's search query
            
        Returns:
            List of fetched page contents
        """
        # Extract and score links
        links = self.extract_links(page_text, base_url)
        scored_links = self.score_links_for_query(links, query)
        
        if not scored_links:
            logger.info("No relevant links found to crawl")
            return []
        
        # Fetch top N pages
        top_links = scored_links[:self.max_pages]
        logger.info(f"Crawling {len(top_links)} relevant pages: {[l['text'] for l in top_links]}")
        
        # Fetch in parallel
        tasks = [self.fetch_page_content(link['url']) for link in top_links]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter successful results
        pages = []
        for result in results:
            if isinstance(result, dict) and result is not None:
                pages.append(result)
        
        logger.info(f"Successfully crawled {len(pages)} pages")
        return pages


# Singleton instance
_link_crawler: Optional[LinkCrawler] = None


def get_link_crawler() -> LinkCrawler:
    """Get or create the link crawler singleton."""
    global _link_crawler
    if _link_crawler is None:
        _link_crawler = LinkCrawler(
            max_pages=3,
            timeout=10
        )
    return _link_crawler
