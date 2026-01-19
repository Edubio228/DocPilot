"""
Pinecone Client Module
Handles all interactions with Pinecone vector database.

EMBEDDING ARCHITECTURE:
- PRIMARY: embedding_type="source" - Section source text for follow-up retrieval
- SECONDARY: embedding_type="summary" - Section summaries for routing/previews

All follow-up question retrieval MUST use embedding_type="source".
"""

import hashlib
import logging
from typing import Optional, Literal
from functools import lru_cache

from pinecone import Pinecone, ServerlessSpec

from ..config import settings

logger = logging.getLogger(__name__)


# Type alias for embedding types
EmbeddingTypeStr = Literal["source", "summary"]


class PineconeClient:
    """
    Client for interacting with Pinecone vector database.
    Supports dual embedding types (source/summary) with proper filtering.
    """
    
    def __init__(self):
        """Initialize Pinecone client with API key from settings."""
        self.pc = Pinecone(api_key=settings.pinecone_api_key)
        self.index_name = settings.pinecone_index_name
        self.dimension = settings.pinecone_dimension
        self._index = None
        
        self._ensure_index_exists()
    
    def _ensure_index_exists(self) -> None:
        """Creates the Pinecone index if it doesn't exist."""
        existing_indexes = [idx.name for idx in self.pc.list_indexes()]
        
        if self.index_name not in existing_indexes:
            logger.info(f"Creating Pinecone index: {self.index_name}")
            self.pc.create_index(
                name=self.index_name,
                dimension=self.dimension,
                metric="cosine",
                spec=ServerlessSpec(
                    cloud="aws",
                    region=settings.pinecone_environment
                )
            )
            logger.info(f"Index {self.index_name} created successfully")
        else:
            logger.info(f"Index {self.index_name} already exists")
    
    @property
    def index(self):
        """Lazily loads and caches the Pinecone index reference."""
        if self._index is None:
            self._index = self.pc.Index(self.index_name)
        return self._index
    
    @staticmethod
    def generate_namespace(page_url: str) -> str:
        """
        Generates a unique namespace for a page URL.
        
        Args:
            page_url: The full URL of the page
            
        Returns:
            A hashed namespace string
        """
        return hashlib.md5(page_url.encode()).hexdigest()[:16]
    
    @staticmethod
    def generate_section_id(
        page_url: str,
        section_id: str,
        embedding_type: EmbeddingTypeStr
    ) -> str:
        """
        Generates a unique ID for a section embedding.
        Includes embedding_type to differentiate source vs summary.
        
        Args:
            page_url: The full URL of the page
            section_id: The section identifier
            embedding_type: "source" or "summary"
            
        Returns:
            A unique vector identifier
        """
        content = f"{page_url}:{section_id}:{embedding_type}"
        return hashlib.md5(content.encode()).hexdigest()
    
    # ============================================
    # LEGACY: Chunk-based methods for backward compat
    # ============================================
    
    @staticmethod
    def generate_chunk_id(page_url: str, chunk_index: int, heading: str) -> str:
        """[LEGACY] Generates a unique ID for a chunk."""
        content = f"{page_url}:{chunk_index}:{heading}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def upsert_chunks(
        self,
        page_url: str,
        chunks: list[dict],
        embeddings: list[list[float]]
    ) -> int:
        """[LEGACY] Upserts chunks with embeddings. Use upsert_sections instead."""
        namespace = self.generate_namespace(page_url)
        vectors = []
        
        for chunk, embedding in zip(chunks, embeddings):
            chunk_id = self.generate_chunk_id(
                page_url, 
                chunk["index"], 
                chunk.get("heading", "")
            )
            
            metadata = {
                "chunk_id": chunk_id,
                "page_url": page_url,
                "heading": chunk.get("heading", ""),
                "text": chunk["text"][:1000],
                "chunk_index": chunk["index"],
                "full_text": chunk["text"],
                "embedding_type": "source"  # Default to source
            }
            
            vectors.append({
                "id": chunk_id,
                "values": embedding,
                "metadata": metadata
            })
        
        return self._batch_upsert(vectors, namespace)
    
    # ============================================
    # NEW: Section-based methods with embedding_type
    # ============================================
    
    def upsert_sections(
        self,
        page_url: str,
        sections: list[dict],
        embeddings: list[list[float]],
        embedding_type: EmbeddingTypeStr = "source"
    ) -> int:
        """
        Upserts section embeddings with embedding_type metadata.
        
        CRITICAL METADATA:
        - embedding_type: "source" (PRIMARY) or "summary" (SECONDARY)
        - section_id: Unique section identifier
        - section_text: Source text (for retrieval context)
        - summary_text: Summary text (if available)
        
        Args:
            page_url: URL of the page
            sections: List of section dicts with section_id, heading, text, summary_text
            embeddings: Embedding vectors for each section
            embedding_type: "source" for source text, "summary" for summary text
            
        Returns:
            Number of vectors upserted
        """
        namespace = self.generate_namespace(page_url)
        vectors = []
        
        for section, embedding in zip(sections, embeddings):
            vector_id = self.generate_section_id(
                page_url,
                section["section_id"],
                embedding_type
            )
            
            # CRITICAL: Include embedding_type in metadata for filtering
            metadata = {
                "vector_id": vector_id,
                "page_url": page_url,
                "section_id": section["section_id"],
                "heading": section.get("heading", ""),
                "text": section.get("text", "")[:1000],  # Truncate for metadata limit
                "section_text": section.get("text", ""),  # Full source text
                "summary_text": section.get("summary_text", ""),
                "embedding_type": embedding_type  # CRITICAL: source or summary
            }
            
            vectors.append({
                "id": vector_id,
                "values": embedding,
                "metadata": metadata
            })
        
        stored = self._batch_upsert(vectors, namespace)
        logger.info(f"Upserted {stored} {embedding_type} embeddings to namespace {namespace}")
        return stored
    
    def search_sections(
        self,
        page_url: str,
        query_embedding: list[float],
        embedding_type: EmbeddingTypeStr = "source",
        top_k: int = 5,
        score_threshold: float = 0.35
    ) -> list[dict]:
        """
        Searches for similar sections with embedding_type filtering.
        
        CRITICAL: Follow-up queries MUST use embedding_type="source".
        
        Args:
            page_url: URL of the page to search within
            query_embedding: Embedding vector of the query
            embedding_type: "source" (default for retrieval) or "summary"
            top_k: Number of results to return
            score_threshold: Minimum similarity score
            
        Returns:
            List of matching sections with scores and metadata
        """
        namespace = self.generate_namespace(page_url)
        
        # Filter by embedding_type in the query
        results = self.index.query(
            vector=query_embedding,
            top_k=top_k,
            namespace=namespace,
            include_metadata=True,
            filter={"embedding_type": {"$eq": embedding_type}}  # CRITICAL FILTER
        )
        
        filtered_results = []
        for match in results.matches:
            if match.score >= score_threshold:
                filtered_results.append({
                    "section_id": match.metadata.get("section_id", match.id),
                    "score": match.score,
                    "text": match.metadata.get("section_text", match.metadata.get("text", "")),
                    "heading": match.metadata.get("heading", ""),
                    "summary_text": match.metadata.get("summary_text", ""),
                    "embedding_type": match.metadata.get("embedding_type", "source")
                })
        
        logger.info(f"Found {len(filtered_results)} {embedding_type} sections "
                    f"above threshold {score_threshold}")
        return filtered_results
    
    # Legacy method for backward compatibility
    def search_similar(
        self,
        page_url: str,
        query_embedding: list[float],
        top_k: int = 5,
        score_threshold: float = 0.35
    ) -> list[dict]:
        """[LEGACY] Searches for similar chunks. Use search_sections instead."""
        namespace = self.generate_namespace(page_url)
        
        results = self.index.query(
            vector=query_embedding,
            top_k=top_k,
            namespace=namespace,
            include_metadata=True
        )
        
        filtered_results = []
        for match in results.matches:
            if match.score >= score_threshold:
                filtered_results.append({
                    "chunk_id": match.id,
                    "score": match.score,
                    "text": match.metadata.get("section_text", 
                            match.metadata.get("full_text", 
                            match.metadata.get("text", ""))),
                    "heading": match.metadata.get("heading", ""),
                    "chunk_index": match.metadata.get("chunk_index", 0),
                    "section_id": match.metadata.get("section_id", "")
                })
        
        logger.info(f"Found {len(filtered_results)} chunks above threshold {score_threshold}")
        return filtered_results
    
    def _batch_upsert(self, vectors: list[dict], namespace: str) -> int:
        """Upserts vectors in batches for efficiency."""
        batch_size = 100
        total_upserted = 0
        
        for i in range(0, len(vectors), batch_size):
            batch = vectors[i:i + batch_size]
            self.index.upsert(vectors=batch, namespace=namespace)
            total_upserted += len(batch)
            logger.debug(f"Upserted batch {i // batch_size + 1}, total: {total_upserted}")
        
        return total_upserted
    
    def delete_page_vectors(self, page_url: str) -> None:
        """Deletes all vectors for a specific page."""
        namespace = self.generate_namespace(page_url)
        self.index.delete(delete_all=True, namespace=namespace)
        logger.info(f"Deleted all vectors in namespace {namespace}")
    
    def check_page_exists(self, page_url: str) -> bool:
        """Checks if a page has already been indexed."""
        namespace = self.generate_namespace(page_url)
        stats = self.index.describe_index_stats()
        namespaces = stats.get("namespaces", {})
        
        if namespace in namespaces:
            vector_count = namespaces[namespace].get("vector_count", 0)
            return vector_count > 0
        
        return False
    
    def get_page_chunk_count(self, page_url: str) -> int:
        """Returns the number of vectors indexed for a page."""
        namespace = self.generate_namespace(page_url)
        stats = self.index.describe_index_stats()
        namespaces = stats.get("namespaces", {})
        
        if namespace in namespaces:
            return namespaces[namespace].get("vector_count", 0)
        
        return 0


# Singleton instance
_pinecone_client: Optional[PineconeClient] = None


@lru_cache()
def get_pinecone_client() -> PineconeClient:
    """Returns a cached singleton instance of PineconeClient."""
    global _pinecone_client
    if _pinecone_client is None:
        _pinecone_client = PineconeClient()
    return _pinecone_client
