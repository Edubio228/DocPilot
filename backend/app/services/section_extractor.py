"""
Section Extractor Service Module
Parses page content into logical sections based on heading structure.

ARCHITECTURE:
- Sections are the PRIMARY unit for hierarchical summarization
- Each section contains: section_id, heading, raw_text, token_count
- Section size determines adaptive chunking strategy
"""

import re
import hashlib
import logging
from typing import Optional
from functools import lru_cache
from dataclasses import dataclass

from ..config import settings

logger = logging.getLogger(__name__)


@dataclass
class ExtractedSection:
    """Raw section data before conversion to SectionData model."""
    section_id: str
    heading: str
    heading_level: int
    raw_text: str
    start_pos: int
    end_pos: int
    token_count: int


class SectionExtractor:
    """
    Service for extracting logical sections from page content.
    
    EXTRACTION STRATEGY:
    1. Parse headings (H1-H3 in Markdown/HTML)
    2. Extract text between headings as sections
    3. Calculate token counts for adaptive chunking decisions
    4. Handle content before first heading as "Introduction"
    """
    
    def __init__(self):
        """Initialize section extractor with configuration."""
        self.small_threshold = settings.section_small_threshold  # 400 tokens
        self.max_sections = settings.max_sections_per_page  # 30 sections
        
        # Heading patterns for extraction
        self.md_heading_pattern = re.compile(
            r'^(#{1,3})\s+(.+)$',
            re.MULTILINE
        )
        self.html_heading_pattern = re.compile(
            r'<h([1-3])[^>]*>(.+?)</h\1>',
            re.IGNORECASE | re.DOTALL
        )
        
        logger.info(f"Section extractor initialized: threshold={self.small_threshold} tokens")
    
    def estimate_tokens(self, text: str) -> int:
        """
        Estimates token count for text.
        Uses word-based approximation (more accurate than char/4).
        
        Args:
            text: Text to estimate
            
        Returns:
            Estimated token count
        """
        if not text:
            return 0
        
        # More accurate: ~1.3 tokens per word for English
        words = len(text.split())
        return max(1, int(words * 1.3))
    
    def generate_section_id(self, page_url: str, heading: str, index: int) -> str:
        """
        Generates a unique, stable section ID.
        
        Args:
            page_url: URL of the page
            heading: Section heading
            index: Section index within page
            
        Returns:
            Unique section identifier
        """
        content = f"{page_url}:section:{index}:{heading}"
        return hashlib.md5(content.encode()).hexdigest()[:12]
    
    def extract_headings(self, text: str) -> list[dict]:
        """
        Extracts all H1-H3 headings with positions.
        
        Args:
            text: Full page text
            
        Returns:
            List of heading dicts with text, level, start, end positions
        """
        headings = []
        
        # Extract Markdown headings (# to ###)
        for match in self.md_heading_pattern.finditer(text):
            level = len(match.group(1))
            if level <= 3:  # Only H1-H3
                headings.append({
                    "text": match.group(2).strip(),
                    "level": level,
                    "start": match.start(),
                    "end": match.end()
                })
        
        # Extract HTML headings if no Markdown found
        if not headings:
            for match in self.html_heading_pattern.finditer(text):
                level = int(match.group(1))
                headings.append({
                    "text": match.group(2).strip(),
                    "level": level,
                    "start": match.start(),
                    "end": match.end()
                })
        
        # Sort by position
        headings.sort(key=lambda x: x["start"])
        
        return headings
    
    def extract_sections(
        self,
        text: str,
        page_url: str
    ) -> list[ExtractedSection]:
        """
        Extracts logical sections from page text.
        
        EXTRACTION LOGIC:
        1. Find all H1-H3 headings
        2. Content between headings becomes a section
        3. Content before first heading is "Introduction"
        4. Calculate token count for each section
        
        Args:
            text: Full page text
            page_url: URL for generating stable section IDs
            
        Returns:
            List of ExtractedSection objects
        """
        headings = self.extract_headings(text)
        sections = []
        section_index = 0
        
        # Handle content before first heading
        if headings and headings[0]["start"] > 0:
            intro_text = text[:headings[0]["start"]].strip()
            if intro_text and len(intro_text) > 50:  # Minimum content threshold
                token_count = self.estimate_tokens(intro_text)
                sections.append(ExtractedSection(
                    section_id=self.generate_section_id(page_url, "Introduction", section_index),
                    heading="Introduction",
                    heading_level=1,
                    raw_text=intro_text,
                    start_pos=0,
                    end_pos=headings[0]["start"],
                    token_count=token_count
                ))
                section_index += 1
        
        # Process each heading and its content
        for i, heading in enumerate(headings):
            # Section content starts after heading
            section_start = heading["end"] + 1
            
            # Section ends at next heading or end of text
            if i + 1 < len(headings):
                section_end = headings[i + 1]["start"]
            else:
                section_end = len(text)
            
            # Extract and clean section text
            section_text = text[section_start:section_end].strip()
            
            # Skip empty sections
            if not section_text or len(section_text) < 20:
                continue
            
            token_count = self.estimate_tokens(section_text)
            
            sections.append(ExtractedSection(
                section_id=self.generate_section_id(page_url, heading["text"], section_index),
                heading=heading["text"],
                heading_level=heading["level"],
                raw_text=section_text,
                start_pos=section_start,
                end_pos=section_end,
                token_count=token_count
            ))
            section_index += 1
        
        # If no headings found, treat whole content as single section
        if not sections and text.strip():
            token_count = self.estimate_tokens(text)
            sections.append(ExtractedSection(
                section_id=self.generate_section_id(page_url, "Content", 0),
                heading="Content",
                heading_level=1,
                raw_text=text.strip(),
                start_pos=0,
                end_pos=len(text),
                token_count=token_count
            ))
        
        # Limit sections to prevent excessive processing
        if len(sections) > self.max_sections:
            logger.warning(f"Truncating sections from {len(sections)} to {self.max_sections}")
            sections = sections[:self.max_sections]
        
        logger.info(f"Extracted {len(sections)} sections from page")
        return sections
    
    def is_large_section(self, token_count: int) -> bool:
        """
        Determines if a section needs chunking based on token count.
        
        ADAPTIVE CHUNKING RULE:
        - token_count <= threshold: summarize directly
        - token_count > threshold: needs chunking
        
        Args:
            token_count: Section token count
            
        Returns:
            True if section needs chunking
        """
        return token_count > self.small_threshold
    
    def get_section_stats(self, sections: list[ExtractedSection]) -> dict:
        """
        Returns statistics about extracted sections.
        Useful for debugging and monitoring.
        
        Args:
            sections: List of extracted sections
            
        Returns:
            Dict with section statistics
        """
        if not sections:
            return {"count": 0, "total_tokens": 0, "large_sections": 0, "small_sections": 0}
        
        total_tokens = sum(s.token_count for s in sections)
        large_count = sum(1 for s in sections if self.is_large_section(s.token_count))
        
        return {
            "count": len(sections),
            "total_tokens": total_tokens,
            "avg_tokens": total_tokens // len(sections),
            "large_sections": large_count,
            "small_sections": len(sections) - large_count
        }


# Singleton instance
_section_extractor: Optional[SectionExtractor] = None


@lru_cache()
def get_section_extractor() -> SectionExtractor:
    """Returns a cached singleton instance of SectionExtractor."""
    global _section_extractor
    if _section_extractor is None:
        _section_extractor = SectionExtractor()
    return _section_extractor
