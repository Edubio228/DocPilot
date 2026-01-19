"""
Chunking Service Module
Handles intelligent text chunking for page content.
Chunks by headings and respects token limits.
"""

import re
import logging
from typing import Optional
from functools import lru_cache
from dataclasses import dataclass

from ..config import settings

logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    """Represents a text chunk with metadata."""
    index: int
    text: str
    heading: str
    start_pos: int
    end_pos: int
    token_count: int


class ChunkingService:
    """
    Service for chunking page content intelligently.
    Respects heading structure and token limits.
    """
    
    def __init__(self):
        """
        Initialize chunking service with configuration.
        """
        self.chunk_size = settings.chunk_size
        self.chunk_overlap = settings.chunk_overlap
        self.max_chunks = settings.max_chunks_per_page
        
        # Heading patterns for different content types
        self.heading_patterns = [
            r'^#{1,6}\s+(.+)$',  # Markdown headings
            r'^(.+)\n[=\-]{3,}$',  # Underline-style headings
            r'<h[1-6][^>]*>(.+?)</h[1-6]>',  # HTML headings
        ]
        
        logger.info(f"Chunking service initialized: size={self.chunk_size}, overlap={self.chunk_overlap}")
    
    def estimate_tokens(self, text: str) -> int:
        """
        Estimates token count for text.
        Uses rough approximation of 4 characters per token.
        
        Args:
            text: Text to estimate
            
        Returns:
            Estimated token count
        """
        # More accurate estimation considering whitespace and punctuation
        words = len(text.split())
        chars = len(text)
        
        # Average of word-based and char-based estimates
        return max(1, (words + chars // 4) // 2)
    
    def extract_headings(self, text: str) -> list[dict]:
        """
        Extracts all headings from text with their positions.
        
        Args:
            text: The full page text
            
        Returns:
            List of heading dicts with 'text', 'start', 'end', 'level'
        """
        headings = []
        
        # Markdown headings (# to ######)
        for match in re.finditer(r'^(#{1,6})\s+(.+)$', text, re.MULTILINE):
            level = len(match.group(1))
            headings.append({
                "text": match.group(2).strip(),
                "start": match.start(),
                "end": match.end(),
                "level": level
            })
        
        # Sort by position
        headings.sort(key=lambda x: x["start"])
        
        return headings
    
    def chunk_by_headings(self, text: str) -> list[Chunk]:
        """
        Chunks text by heading structure.
        Each section under a heading becomes a chunk (if within size limits).
        
        Args:
            text: The full page text
            
        Returns:
            List of Chunk objects
        """
        headings = self.extract_headings(text)
        chunks = []
        
        if not headings:
            # No headings found, use simple chunking
            return self.chunk_by_size(text, "Content")
        
        # Process each section
        for i, heading in enumerate(headings):
            section_start = heading["end"] + 1
            section_end = headings[i + 1]["start"] if i + 1 < len(headings) else len(text)
            
            section_text = text[section_start:section_end].strip()
            
            if not section_text:
                continue
            
            section_tokens = self.estimate_tokens(section_text)
            
            if section_tokens <= self.chunk_size:
                # Section fits in one chunk
                chunks.append(Chunk(
                    index=len(chunks),
                    text=section_text,
                    heading=heading["text"],
                    start_pos=section_start,
                    end_pos=section_end,
                    token_count=section_tokens
                ))
            else:
                # Section too large, split further
                sub_chunks = self.chunk_by_size(section_text, heading["text"])
                for sub_chunk in sub_chunks:
                    sub_chunk.index = len(chunks)
                    chunks.append(sub_chunk)
        
        # Handle content before first heading
        if headings and headings[0]["start"] > 0:
            intro_text = text[:headings[0]["start"]].strip()
            if intro_text:
                intro_chunks = self.chunk_by_size(intro_text, "Introduction")
                # Prepend intro chunks
                for i, chunk in enumerate(intro_chunks):
                    chunk.index = i
                for chunk in chunks:
                    chunk.index += len(intro_chunks)
                chunks = intro_chunks + chunks
        
        # Limit total chunks
        if len(chunks) > self.max_chunks:
            logger.warning(f"Truncating chunks from {len(chunks)} to {self.max_chunks}")
            chunks = chunks[:self.max_chunks]
        
        return chunks
    
    def chunk_by_size(self, text: str, heading: str = "Content") -> list[Chunk]:
        """
        Chunks text by size with overlap.
        Used when no heading structure is available or for large sections.
        
        Args:
            text: Text to chunk
            heading: Heading to assign to all chunks
            
        Returns:
            List of Chunk objects
        """
        chunks = []
        
        # Split into sentences for cleaner boundaries
        sentences = self._split_into_sentences(text)
        
        current_chunk = []
        current_tokens = 0
        chunk_start = 0
        
        for sentence in sentences:
            sentence_tokens = self.estimate_tokens(sentence)
            
            if current_tokens + sentence_tokens > self.chunk_size and current_chunk:
                # Save current chunk
                chunk_text = " ".join(current_chunk)
                chunks.append(Chunk(
                    index=len(chunks),
                    text=chunk_text,
                    heading=heading,
                    start_pos=chunk_start,
                    end_pos=chunk_start + len(chunk_text),
                    token_count=current_tokens
                ))
                
                # Start new chunk with overlap
                overlap_tokens = 0
                overlap_sentences = []
                
                for s in reversed(current_chunk):
                    s_tokens = self.estimate_tokens(s)
                    if overlap_tokens + s_tokens <= self.chunk_overlap:
                        overlap_sentences.insert(0, s)
                        overlap_tokens += s_tokens
                    else:
                        break
                
                current_chunk = overlap_sentences
                current_tokens = overlap_tokens
                chunk_start += len(chunk_text) - len(" ".join(overlap_sentences))
            
            current_chunk.append(sentence)
            current_tokens += sentence_tokens
        
        # Don't forget the last chunk
        if current_chunk:
            chunk_text = " ".join(current_chunk)
            chunks.append(Chunk(
                index=len(chunks),
                text=chunk_text,
                heading=heading,
                start_pos=chunk_start,
                end_pos=chunk_start + len(chunk_text),
                token_count=current_tokens
            ))
        
        return chunks
    
    def _split_into_sentences(self, text: str) -> list[str]:
        """
        Splits text into sentences using multiple delimiters.
        
        Args:
            text: Text to split
            
        Returns:
            List of sentences
        """
        # Handle common sentence boundaries
        # This regex splits on . ! ? followed by space or newline
        sentences = re.split(r'(?<=[.!?])\s+', text)
        
        # Filter empty sentences and clean up
        sentences = [s.strip() for s in sentences if s.strip()]
        
        # Handle very long "sentences" (likely code blocks or lists)
        final_sentences = []
        for sentence in sentences:
            if self.estimate_tokens(sentence) > self.chunk_size // 2:
                # Split long sentences by newlines
                parts = sentence.split('\n')
                final_sentences.extend([p.strip() for p in parts if p.strip()])
            else:
                final_sentences.append(sentence)
        
        return final_sentences
    
    def chunk_page(self, page_text: str) -> list[dict]:
        """
        Main method to chunk a page's text content.
        Returns chunks in the format expected by other services.
        
        Args:
            page_text: The full extracted page text
            
        Returns:
            List of chunk dictionaries with 'text', 'heading', 'index'
        """
        # Clean the text
        cleaned_text = self._clean_text(page_text)
        
        if not cleaned_text:
            logger.warning("No text content to chunk")
            return []
        
        # Try heading-based chunking first
        chunks = self.chunk_by_headings(cleaned_text)
        
        logger.info(f"Created {len(chunks)} chunks from page content")
        
        # Convert to dict format
        return [
            {
                "index": chunk.index,
                "text": chunk.text,
                "heading": chunk.heading,
                "token_count": chunk.token_count
            }
            for chunk in chunks
        ]
    
    def _clean_text(self, text: str) -> str:
        """
        Cleans text by removing excessive whitespace and normalizing.
        
        Args:
            text: Raw text
            
        Returns:
            Cleaned text
        """
        # Normalize line endings
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        
        # Remove excessive blank lines (more than 2)
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # Remove excessive spaces
        text = re.sub(r' {3,}', '  ', text)
        
        # Strip leading/trailing whitespace
        text = text.strip()
        
        return text


# Singleton instance
_chunking_service: Optional[ChunkingService] = None


@lru_cache()
def get_chunking_service() -> ChunkingService:
    """
    Returns a cached singleton instance of ChunkingService.
    """
    global _chunking_service
    if _chunking_service is None:
        _chunking_service = ChunkingService()
    return _chunking_service
