"""
LLM Service Module
Handles interaction with Groq API for text generation.
Uses llama-3.1-8b-instant for ALL generation tasks (summarization, explanation, follow-up).

ARCHITECTURE NOTE:
- LLM is used ONLY for text generation (summarization, explanation, follow-up answers)
- LLM is NOT used for embeddings, retrieval, or storage
- Embeddings are handled by Pinecone Inference API (see embeddings.py)
"""

import logging
import json
import asyncio
from typing import AsyncGenerator, Optional
from functools import lru_cache

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

# Retry configuration for rate limits
MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0  # seconds
MAX_BACKOFF = 10.0  # seconds


class LLMService:
    """
    Service for interacting with Groq API for text generation.
    Uses llama-3.1-8b-instant model for all generation tasks.
    Supports both streaming and non-streaming responses.
    
    Key Features:
    - Real-time streaming for UI token-by-token updates
    - OpenAI-compatible API (Groq uses OpenAI format)
    - Optimized for low-latency inference
    """
    
    def __init__(self):
        """
        Initialize the LLM service with Groq API configuration.
        """
        self.api_key = settings.groq_api_key
        self.model = settings.groq_model
        self.base_url = settings.groq_base_url
        self.chat_url = f"{self.base_url}/chat/completions"
        
        # Validate API key is set
        if not self.api_key:
            logger.warning("GROQ_API_KEY not set - LLM generation will fail")
        
        logger.info(f"LLM Service initialized with model: {self.model}")
    
    def _get_headers(self) -> dict:
        """Returns headers for Groq API requests."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
    
    async def check_api_available(self) -> bool:
        """
        Checks if the Groq API is reachable and the API key is valid.
        
        Returns:
            True if API is available and key is valid
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/models",
                    headers=self._get_headers(),
                    timeout=10.0
                )
                return response.status_code == 200
        except Exception as e:
            logger.error(f"Error checking API availability: {e}")
        return False
    
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7
    ) -> str:
        """
        Generates a complete response (non-streaming) with retry logic.
        Used for classification and short generation tasks.
        
        Args:
            prompt: The user prompt
            system_prompt: Optional system instructions
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (lower = more focused)
            
        Returns:
            The complete generated text
        """
        messages = []
        
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        messages.append({"role": "user", "content": prompt})
        
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False
        }
        
        # Retry with exponential backoff
        backoff = INITIAL_BACKOFF
        last_error = None
        
        for attempt in range(MAX_RETRIES):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        self.chat_url,
                        headers=self._get_headers(),
                        json=payload,
                        timeout=120.0
                    )
                    response.raise_for_status()
                    
                    data = response.json()
                    return data["choices"][0]["message"]["content"]
                    
            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code == 429:
                    # Rate limit - retry with backoff
                    logger.warning(f"Rate limited (429), attempt {attempt + 1}/{MAX_RETRIES}, waiting {backoff}s...")
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, MAX_BACKOFF)
                    continue
                else:
                    logger.error(f"Groq API HTTP error: {e.response.status_code} - {e.response.text}")
                    raise
            except Exception as e:
                logger.error(f"LLM generation error: {e}")
                raise
        
        # All retries exhausted
        logger.error(f"All {MAX_RETRIES} retries exhausted for Groq API")
        raise last_error or Exception("Failed to generate after retries")
    
    async def generate_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7
    ) -> AsyncGenerator[str, None]:
        """
        Generates a streaming response with retry logic for rate limits.
        This is the PRIMARY method for real-time summarization and follow-up answers.
        
        STREAMING ARCHITECTURE:
        - Groq uses Server-Sent Events (SSE) format
        - Each chunk contains a delta with partial content
        - UI receives tokens in real-time for progressive display
        - Retries with exponential backoff on 429 rate limit errors
        
        Args:
            prompt: The user prompt
            system_prompt: Optional system instructions
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            
        Yields:
            Individual tokens/chunks as they're generated
        """
        messages = []
        
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        messages.append({"role": "user", "content": prompt})
        
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True  # Enable streaming
        }
        
        # Retry with exponential backoff
        backoff = INITIAL_BACKOFF
        
        for attempt in range(MAX_RETRIES):
            try:
                async with httpx.AsyncClient() as client:
                    async with client.stream(
                        "POST",
                        self.chat_url,
                        headers=self._get_headers(),
                        json=payload,
                        timeout=120.0
                    ) as response:
                        # Check for rate limit before streaming
                        if response.status_code == 429:
                            raise httpx.HTTPStatusError(
                                f"Rate limited",
                                request=response.request,
                                response=response
                            )
                        
                        response.raise_for_status()
                        
                        # Process SSE stream
                        async for line in response.aiter_lines():
                            if line.startswith("data: "):
                                data_str = line[6:]  # Remove "data: " prefix
                                
                                # Handle stream end
                                if data_str.strip() == "[DONE]":
                                    return  # Successfully completed
                                
                                try:
                                    data = json.loads(data_str)
                                    
                                    # Extract content delta from the response
                                    choices = data.get("choices", [])
                                    if choices:
                                        delta = choices[0].get("delta", {})
                                        content = delta.get("content", "")
                                        
                                        if content:
                                            yield content
                                            
                                except json.JSONDecodeError:
                                    # Skip malformed JSON chunks
                                    continue
                        
                        # Stream completed successfully
                        return
                                
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    # Rate limit - retry with backoff
                    logger.warning(f"Rate limited (429), attempt {attempt + 1}/{MAX_RETRIES}, waiting {backoff}s...")
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, MAX_BACKOFF)
                    continue
                else:
                    logger.error(f"Groq streaming error: {e.response.status_code}")
                    yield f"[Error: API returned {e.response.status_code}]"
                    return
            except Exception as e:
                logger.error(f"LLM streaming error: {e}")
                yield f"[Error: {str(e)}]"
                return
        
        # All retries exhausted
        logger.error(f"All {MAX_RETRIES} retries exhausted for Groq streaming API")
        yield "[Error: Rate limit exceeded. Please try again in a moment.]"
    
    async def generate_with_context(
        self,
        prompt: str,
        context: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.5
    ) -> str:
        """
        Generates a response with provided context (for follow-up questions).
        Non-streaming version.
        
        Args:
            prompt: The user's question
            context: Retrieved context to ground the response
            system_prompt: System instructions
            max_tokens: Maximum tokens
            temperature: Sampling temperature (lower for factual answers)
            
        Returns:
            Generated response
        """
        full_prompt = f"""Context:
{context}

Question: {prompt}

Answer based ONLY on the provided context. Be specific and cite relevant sections."""
        
        return await self.generate(
            prompt=full_prompt,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature
        )
    
    async def generate_with_context_stream(
        self,
        prompt: str,
        context: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.5
    ) -> AsyncGenerator[str, None]:
        """
        Streaming version of generate_with_context for follow-up questions.
        
        Args:
            prompt: The user's question
            context: Retrieved context
            system_prompt: System instructions
            max_tokens: Maximum tokens
            temperature: Sampling temperature
            
        Yields:
            Tokens as they're generated
        """
        full_prompt = f"""Context:
{context}

Question: {prompt}

Answer based ONLY on the provided context. Be specific and cite relevant sections."""
        
        async for token in self.generate_stream(
            prompt=full_prompt,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature
        ):
            yield token


# Singleton instance
_llm_service: Optional[LLMService] = None


@lru_cache()
def get_llm_service() -> LLMService:
    """
    Returns a cached singleton instance of LLMService.
    """
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service
