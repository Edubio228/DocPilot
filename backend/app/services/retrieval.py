"""
Retrieval Service Module
Combines Pinecone and Embeddings for semantic search.

RETRIEVAL ARCHITECTURE:
- PRIMARY: embedding_type="source" - Used for follow-up questions
- SECONDARY: embedding_type="summary" - Used for routing/previews

ALL follow-up question retrieval MUST use embedding_type="source".
"""

import logging
from typing import Optional, Literal
from functools import lru_cache

from .pinecone_client import PineconeClient, get_pinecone_client
from .embeddings import EmbeddingService, get_embedding_service
from ..config import settings

logger = logging.getLogger(__name__)


# Import EmbeddingType from state for type hints
EmbeddingTypeStr = Literal["source", "summary"]


class RetrievalService:
    """
    High-level service for semantic retrieval of page sections.
    Supports dual embedding types for different use cases.
    """
    
    def __init__(
        self,
        pinecone_client: Optional[PineconeClient] = None,
        embedding_service: Optional[EmbeddingService] = None
    ):
        """Initialize with optional dependency injection."""
        self.pinecone = pinecone_client or get_pinecone_client()
        self.embeddings = embedding_service or get_embedding_service()
        self.top_k = settings.top_k_retrieval
        self.threshold = settings.similarity_threshold
    
    # ============================================
    # NEW: Section-based methods
    # ============================================
    
    def store_sections(
        self,
        page_url: str,
        sections: list[dict],
        embedding_type: EmbeddingTypeStr = "source"
    ) -> int:
        """
        Embeds and stores sections with embedding_type metadata.
        
        Args:
            page_url: URL of the page
            sections: List of section dicts with section_id, heading, text, summary_text
            embedding_type: "source" for source text, "summary" for summary text
            
        Returns:
            Number of sections stored
        """
        if not sections:
            logger.warning(f"No sections to store for {page_url}")
            return 0
        
        # Determine which text to embed based on embedding_type
        if embedding_type == "source":
            texts = [s.get("text", "") for s in sections]
        else:  # summary
            texts = [s.get("summary_text", s.get("text", "")) for s in sections]
        
        logger.info(f"Generating {embedding_type} embeddings for {len(texts)} sections")
        embeddings = self.embeddings.embed_texts(texts)
        
        # Store in Pinecone with embedding_type metadata
        stored_count = self.pinecone.upsert_sections(
            page_url=page_url,
            sections=sections,
            embeddings=embeddings,
            embedding_type=embedding_type
        )
        
        logger.info(f"Stored {stored_count} {embedding_type} embeddings for {page_url}")
        return stored_count
    
    def retrieve_sections(
        self,
        page_url: str,
        query: str,
        embedding_type: EmbeddingTypeStr = "source",
        top_k: Optional[int] = None,
        score_threshold: Optional[float] = None
    ) -> list[dict]:
        """
        Retrieves relevant sections with embedding_type filtering.
        
        CRITICAL: Follow-up queries MUST use embedding_type="source".
        
        Args:
            page_url: URL of the page to search
            query: The user's search query
            embedding_type: "source" (default) or "summary"
            top_k: Number of results (default from settings)
            score_threshold: Minimum score (default from settings)
            
        Returns:
            List of matching sections sorted by relevance
        """
        top_k = top_k or self.top_k
        score_threshold = score_threshold or self.threshold
        
        logger.info(f"Retrieving {embedding_type} sections for: '{query[:50]}...'")
        
        # Generate query embedding (uses "query" input_type)
        query_embedding = self.embeddings.embed_query(query)
        
        # Search with embedding_type filter
        results = self.pinecone.search_sections(
            page_url=page_url,
            query_embedding=query_embedding,
            embedding_type=embedding_type,
            top_k=top_k,
            score_threshold=score_threshold
        )
        
        # Sort by score (highest first)
        results.sort(key=lambda x: x["score"], reverse=True)
        
        logger.info(f"Retrieved {len(results)} {embedding_type} sections")
        return results
    
    def build_context_from_sections(
        self,
        sections: list[dict],
        max_tokens: int = 2000
    ) -> str:
        """
        Builds a context string from retrieved sections for LLM input.
        
        Args:
            sections: List of section dicts
            max_tokens: Maximum tokens in output
            
        Returns:
            Formatted context string
        """
        if not sections:
            return ""
        
        context_parts = []
        current_length = 0
        
        for section in sections:
            heading = section.get("heading", "Section")
            text = section.get("text", "")
            score = section.get("score", 0)
            
            section_text = f"## {heading} (relevance: {score:.2f})\n{text}\n"
            
            # Token estimate
            section_tokens = len(section_text) // 4
            
            if current_length + section_tokens > max_tokens:
                remaining = max_tokens - current_length
                remaining_chars = remaining * 4
                if remaining_chars > 100:
                    section_text = section_text[:remaining_chars] + "..."
                    context_parts.append(section_text)
                break
            
            context_parts.append(section_text)
            current_length += section_tokens
        
        return "\n".join(context_parts)
    
    # ============================================
    # LEGACY: Chunk-based methods for backward compat
    # ============================================
    
    def store_page_chunks(
        self,
        page_url: str,
        chunks: list[dict]
    ) -> int:
        """[LEGACY] Use store_sections instead."""
        if not chunks:
            return 0
        
        texts = [chunk["text"] for chunk in chunks]
        embeddings = self.embeddings.embed_texts(texts)
        
        return self.pinecone.upsert_chunks(
            page_url=page_url,
            chunks=chunks,
            embeddings=embeddings
        )
    
    def retrieve_relevant_chunks(
        self,
        page_url: str,
        query: str,
        top_k: Optional[int] = None,
        score_threshold: Optional[float] = None
    ) -> list[dict]:
        """[LEGACY] Use retrieve_sections instead."""
        top_k = top_k or self.top_k
        score_threshold = score_threshold or self.threshold
        
        query_embedding = self.embeddings.embed_query(query)
        
        results = self.pinecone.search_similar(
            page_url=page_url,
            query_embedding=query_embedding,
            top_k=top_k,
            score_threshold=score_threshold
        )
        
        results.sort(key=lambda x: x["score"], reverse=True)
        return results
    
    def build_context_from_chunks(
        self,
        chunks: list[dict],
        max_tokens: int = 2000
    ) -> str:
        """[LEGACY] Use build_context_from_sections instead."""
        return self.build_context_from_sections(chunks, max_tokens)
    
    # ============================================
    # UTILITY METHODS
    # ============================================
    
    def check_page_indexed(self, page_url: str) -> bool:
        """Checks if a page has already been indexed."""
        return self.pinecone.check_page_exists(page_url)
    
    def get_page_info(self, page_url: str) -> dict:
        """Gets information about an indexed page."""
        return {
            "page_url": page_url,
            "namespace": self.pinecone.generate_namespace(page_url),
            "chunk_count": self.pinecone.get_page_chunk_count(page_url),
            "indexed": self.pinecone.check_page_exists(page_url)
        }
    
    def reindex_page(
        self,
        page_url: str,
        sections: list[dict]
    ) -> int:
        """Deletes existing vectors and re-indexes a page."""
        logger.info(f"Re-indexing page: {page_url}")
        self.pinecone.delete_page_vectors(page_url)
        return self.store_sections(page_url, sections, "source")


# Singleton instance
_retrieval_service: Optional[RetrievalService] = None


@lru_cache()
def get_retrieval_service() -> RetrievalService:
    """Returns a cached singleton instance of RetrievalService."""
    global _retrieval_service
    if _retrieval_service is None:
        _retrieval_service = RetrievalService()
    return _retrieval_service
