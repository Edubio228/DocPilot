"""
Embeddings Service Module
Handles text embedding generation using Pinecone's hosted embedding model.
Uses Pinecone Inference API - NO local model loading required.

Architecture:
- Embeddings: Pinecone Inference API (llama-text-embed-v2)
- LLM: Ollama (Mistral) - for text generation only
"""

import logging
from typing import Optional
from functools import lru_cache

from pinecone import Pinecone

from ..config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    Service for generating text embeddings using Pinecone Inference API.
    Uses llama-text-embed-v2 which produces 1024-dimensional vectors.
    
    Benefits of this approach:
    - No local model loading (faster startup, ~0 memory overhead)
    - No GPU requirements for embeddings
    - Consistent embeddings between indexing and querying
    - Optimized for retrieval with separate passage/query input types
    """
    
    def __init__(self):
        """
        Initialize the Pinecone client for embedding generation.
        Uses the same API key as the vector database.
        """
        self.client = Pinecone(api_key=settings.pinecone_api_key)
        self.model_name = settings.pinecone_embedding_model
        self._dimension = settings.pinecone_dimension
        
        logger.info(f"Embedding service initialized with Pinecone model: {self.model_name}")
        logger.info(f"Embedding dimension: {self._dimension}")
    
    @property
    def dimension(self) -> int:
        """
        Returns the embedding dimension for this model.
        llama-text-embed-v2 produces 1024-dimensional vectors.
        """
        return self._dimension
    
    def embed_text(self, text: str) -> list[float]:
        """
        Generates an embedding for a single text string using Pinecone Inference API.
        Uses 'passage' input_type for documents/content being indexed.
        
        Args:
            text: The text to embed
            
        Returns:
            A list of floats representing the embedding vector (1024 dimensions)
        """
        try:
            response = self.client.inference.embed(
                model=self.model_name,
                inputs=[text],
                parameters={"input_type": "passage"}
            )
            
            # Extract embedding from response
            embedding = response.data[0].values
            return list(embedding)
            
        except Exception as e:
            logger.error(f"Pinecone embedding error: {e}")
            raise
    
    def embed_texts(self, texts: list[str], batch_size: int = 96) -> list[list[float]]:
        """
        Generates embeddings for multiple texts using Pinecone Inference API.
        Batches requests for efficiency (Pinecone supports up to 96 inputs per request).
        
        Args:
            texts: List of texts to embed
            batch_size: Number of texts per API call (max 96 for Pinecone)
            
        Returns:
            List of embedding vectors
        """
        if not texts:
            return []
        
        logger.info(f"Embedding {len(texts)} texts using Pinecone Inference API")
        
        all_embeddings = []
        
        # Process in batches (Pinecone limit is ~96 per request)
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            
            try:
                response = self.client.inference.embed(
                    model=self.model_name,
                    inputs=batch,
                    parameters={"input_type": "passage"}
                )
                
                # Extract embeddings from response
                batch_embeddings = [list(item.values) for item in response.data]
                all_embeddings.extend(batch_embeddings)
                
                logger.debug(f"Embedded batch {i // batch_size + 1}, total: {len(all_embeddings)}")
                
            except Exception as e:
                logger.error(f"Pinecone embedding error for batch {i // batch_size + 1}: {e}")
                raise
        
        return all_embeddings
    
    def embed_query(self, query: str) -> list[float]:
        """
        Generates an embedding optimized for search queries.
        Uses 'query' input_type for better retrieval performance.
        
        The distinction between 'passage' and 'query' input types helps
        the model optimize embeddings for asymmetric retrieval tasks.
        
        Args:
            query: The search query to embed
            
        Returns:
            The query embedding vector (1024 dimensions)
        """
        try:
            response = self.client.inference.embed(
                model=self.model_name,
                inputs=[query],
                parameters={"input_type": "query"}
            )
            
            embedding = response.data[0].values
            return list(embedding)
            
        except Exception as e:
            logger.error(f"Pinecone query embedding error: {e}")
            raise
    
    def compute_similarity(self, embedding1: list[float], embedding2: list[float]) -> float:
        """
        Computes cosine similarity between two embeddings.
        
        Args:
            embedding1: First embedding vector
            embedding2: Second embedding vector
            
        Returns:
            Cosine similarity score between -1 and 1
        """
        import numpy as np
        
        vec1 = np.array(embedding1)
        vec2 = np.array(embedding2)
        
        # Normalize and compute dot product for cosine similarity
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return float(np.dot(vec1, vec2) / (norm1 * norm2))


# Singleton instance
_embedding_service: Optional[EmbeddingService] = None


@lru_cache()
def get_embedding_service() -> EmbeddingService:
    """
    Returns a cached singleton instance of EmbeddingService.
    Unlike local models, Pinecone client is lightweight and fast to initialize.
    """
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
