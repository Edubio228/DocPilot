"""
Configuration module for DocPilot backend.
Loads environment variables and provides centralized config management.
"""

import os
from typing import Optional
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    Uses pydantic-settings for validation and type coercion.
    """
    
    # Application
    app_name: str = "DocPilot"
    debug: bool = False
    
    # Pinecone Configuration
    pinecone_api_key: str = ""
    pinecone_environment: str = "us-east-1"
    pinecone_index_name: str = "docpilot-pages"
    pinecone_dimension: int = 1024  # llama-text-embed-v2 dimension
    
    # Pinecone Embedding Model (hosted - no local inference)
    pinecone_embedding_model: str = "llama-text-embed-v2"
    
    # LLM Configuration (Groq API - for text generation only)
    # Model: llama-3.1-8b-instant for ALL text generation
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    
    # Summarization Configuration
    # Controls adaptive chunking thresholds for hierarchical summarization
    section_small_threshold: int = 400  # tokens - sections <= this are summarized directly
    chunk_max_tokens: int = 512  # max tokens per chunk when splitting large sections
    
    # Chunking Configuration
    chunk_size: int = 512  # tokens
    chunk_overlap: int = 50  # tokens
    max_chunks_per_page: int = 50
    max_sections_per_page: int = 30  # limit sections to prevent excessive API calls
    
    # Retrieval Configuration
    top_k_retrieval: int = 5
    similarity_threshold: float = 0.35  # Lowered from 0.7 - LLama embeddings typically score 0.3-0.6 for good matches
    
    # Streaming Configuration
    stream_delay_ms: int = 10  # Delay between tokens for smoother streaming
    
    # CORS
    cors_origins: list[str] = ["chrome-extension://*", "http://localhost:*"]
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    """
    Returns cached settings instance.
    Uses lru_cache to avoid repeated .env file reads.
    """
    return Settings()


# Export commonly used settings
settings = get_settings()
