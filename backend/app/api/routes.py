"""
API Routes Module - CONVERSATIONAL AGENT
Defines FastAPI endpoints for the unified chat interface.

MAIN ENDPOINT: /api/chat
- Single endpoint for all user queries
- Backend classifies intent automatically
- Supports: summary, explain, step-by-step, clarification, questions

All streaming endpoints use Server-Sent Events (SSE).
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, HttpUrl

from .streaming_utils import create_sse_response, format_sse_event, StreamingEventType
from ..agent.graph import get_summarization_agent
from ..agent.intent import classify_intent, UserIntent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


# Request/Response Models

class ChatRequest(BaseModel):
    """
    Unified chat request model.
    Agent automatically classifies intent from query.
    """
    page_url: str = Field(..., description="URL of the page")
    page_text: str = Field(default="", description="Extracted text content (for first request)")
    page_title: Optional[str] = Field(default="", description="Title of the page")
    query: str = Field(..., description="User's natural language query")
    
    class Config:
        json_schema_extra = {
            "example": {
                "page_url": "https://docs.example.com/guide",
                "page_text": "# Getting Started\n\nThis guide shows you how to...",
                "page_title": "Getting Started Guide",
                "query": "Summarize this page"
            }
        }


class SummarizeRequest(BaseModel):
    """Request model for page summarization (legacy support)."""
    page_url: str = Field(..., description="URL of the page to summarize")
    page_text: str = Field(..., description="Extracted text content of the page")
    page_title: Optional[str] = Field(default="", description="Title of the page")
    
    class Config:
        json_schema_extra = {
            "example": {
                "page_url": "https://docs.example.com/guide",
                "page_text": "# Getting Started\n\nThis guide shows you how to...",
                "page_title": "Getting Started Guide"
            }
        }


class FollowUpRequest(BaseModel):
    """Request model for follow-up questions."""
    page_url: str = Field(..., description="URL of the previously summarized page")
    user_query: str = Field(..., description="The follow-up question")
    
    class Config:
        json_schema_extra = {
            "example": {
                "page_url": "https://docs.example.com/guide",
                "user_query": "How do I configure authentication?"
            }
        }


class HealthResponse(BaseModel):
    """Response model for health check."""
    status: str
    services: dict


class SummaryResponse(BaseModel):
    """Non-streaming summary response."""
    page_url: str
    page_type: str
    summary: str
    chunk_count: int


class FollowUpResponse(BaseModel):
    """Non-streaming follow-up response."""
    page_url: str
    query: str
    response: str
    sources_count: int


# Endpoints

@router.get("/health")
async def health_check() -> HealthResponse:
    """
    Health check endpoint.
    Verifies all required services are operational.
    """
    from ..services import get_llm_service, get_embedding_service
    
    services = {
        "llm": False,
        "embeddings": False,
        "pinecone": False
    }
    
    # Check LLM service (Groq API)
    try:
        llm = get_llm_service()
        services["llm"] = await llm.check_api_available()
    except Exception as e:
        logger.error(f"LLM health check failed: {e}")
    
    # Check embedding service
    try:
        embeddings = get_embedding_service()
        # Quick test embedding
        _ = embeddings.embed_text("test")
        services["embeddings"] = True
    except Exception as e:
        logger.error(f"Embeddings health check failed: {e}")
    
    # Check Pinecone
    try:
        from ..services import get_pinecone_client
        pinecone = get_pinecone_client()
        _ = pinecone.index.describe_index_stats()
        services["pinecone"] = True
    except Exception as e:
        logger.error(f"Pinecone health check failed: {e}")
    
    all_healthy = all(services.values())
    
    return HealthResponse(
        status="healthy" if all_healthy else "degraded",
        services=services
    )


# ============================================
# MAIN UNIFIED CHAT ENDPOINT
# ============================================

@router.post("/chat")
async def chat_streaming(request: ChatRequest):
    """
    UNIFIED CHAT ENDPOINT - Single entry point for all user queries.
    
    The agent automatically classifies user intent:
    - PAGE_SUMMARY: "summarize", "overview", "TL;DR"
    - SECTION_EXPLAIN: explain a specific topic/concept
    - STEP_BY_STEP: "step by step", "walk me through"
    - CLARIFICATION: "what if", "what happens if"
    - GENERAL_QUESTION: any other question
    
    Returns SSE stream with real-time tokens.
    """
    logger.info(f"Chat request for: {request.page_url}")
    logger.info(f"Query: {request.query}")
    
    if not request.query or len(request.query.strip()) < 2:
        raise HTTPException(
            status_code=400,
            detail="Query is too short"
        )
    
    agent = get_summarization_agent()
    
    async def event_generator():
        try:
            # Step 1: Classify intent
            yield {"event": "status", "data": {"message": "understanding your question"}}
            
            intent_result = await classify_intent(request.query)
            
            yield {
                "event": "status",
                "data": {"message": f"intent: {intent_result.intent.value}"}
            }
            
            # Step 2: Route based on intent
            if intent_result.intent == UserIntent.PAGE_SUMMARY:
                # Page-level summary request
                if not request.page_text or len(request.page_text.strip()) < 50:
                    yield {"event": "error", "data": {"error": "Page content not available"}}
                    return
                
                # Use existing streaming summarization
                async for event in agent.summarize_page_streaming(
                    page_url=request.page_url,
                    page_text=request.page_text,
                    page_title=request.page_title or ""
                ):
                    yield event
            else:
                # For all other intents, use retrieval-based response
                # First ensure page is indexed
                if request.page_text and len(request.page_text.strip()) >= 50:
                    # Check if page needs indexing
                    if not agent.is_page_indexed(request.page_url):
                        yield {"event": "status", "data": {"message": "indexing page content"}}
                        # Index silently (no streaming)
                        await agent.index_page_for_chat(
                            page_url=request.page_url,
                            page_text=request.page_text,
                            page_title=request.page_title or ""
                        )
                
                # Handle query with appropriate response style
                async for event in agent.handle_chat_query_streaming(
                    page_url=request.page_url,
                    query=request.query,
                    intent=intent_result.intent,
                    topic=intent_result.extracted_topic,
                    page_text=request.page_text  # Pass for link crawling
                ):
                    yield event
                    
        except Exception as e:
            logger.error(f"Chat error: {e}")
            yield {"event": "error", "data": {"error": str(e)}}
    
    return StreamingResponse(
        create_sse_response(event_generator()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


# ============================================
# LEGACY ENDPOINTS (kept for backward compat)
# ============================================

@router.post("/summarize")
async def summarize_page_streaming(request: SummarizeRequest):
    """
    Summarizes a page with real-time streaming output.
    
    Returns Server-Sent Events (SSE) stream with:
    - status: Progress updates ("reading page", "chunking", etc.)
    - token: Individual tokens as they're generated
    - chunk_start/chunk_end: Section boundaries
    - complete: Final summary
    
    The stream format follows SSE spec:
    ```
    event: status
    data: {"message": "reading page"}
    
    event: token
    data: "The"
    
    event: token
    data: " documentation"
    ```
    """
    logger.info(f"Summarize request for: {request.page_url}")
    
    if not request.page_text or len(request.page_text.strip()) < 50:
        raise HTTPException(
            status_code=400,
            detail="Page text is too short to summarize"
        )
    
    agent = get_summarization_agent()
    
    async def event_generator():
        try:
            async for event in agent.summarize_page_streaming(
                page_url=request.page_url,
                page_text=request.page_text,
                page_title=request.page_title or ""
            ):
                yield event
        except Exception as e:
            logger.error(f"Summarization error: {e}")
            yield {"event": "error", "data": {"error": str(e)}}
    
    return StreamingResponse(
        create_sse_response(event_generator()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


@router.post("/summarize/sync", response_model=SummaryResponse)
async def summarize_page_sync(request: SummarizeRequest) -> SummaryResponse:
    """
    Summarizes a page synchronously (non-streaming).
    Returns the complete summary after processing.
    
    Use this endpoint when streaming is not needed.
    """
    logger.info(f"Sync summarize request for: {request.page_url}")
    
    if not request.page_text or len(request.page_text.strip()) < 50:
        raise HTTPException(
            status_code=400,
            detail="Page text is too short to summarize"
        )
    
    agent = get_summarization_agent()
    
    try:
        result = await agent.summarize_page(
            page_url=request.page_url,
            page_text=request.page_text,
            page_title=request.page_title or ""
        )
        
        return SummaryResponse(
            page_url=request.page_url,
            page_type=result.page_type.value,
            summary=result.final_summary,
            chunk_count=len(result.chunks)
        )
    except Exception as e:
        logger.error(f"Summarization error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/followup")
async def handle_followup_streaming(request: FollowUpRequest):
    """
    Handles a follow-up question with streaming output.
    
    Uses vector similarity search to find relevant chunks
    from the previously indexed page, then generates an answer.
    
    Returns SSE stream with:
    - status: Progress updates
    - token: Answer tokens
    - complete: Final response
    """
    logger.info(f"Follow-up request for: {request.page_url}")
    logger.info(f"Query: {request.user_query}")
    
    if not request.user_query or len(request.user_query.strip()) < 3:
        raise HTTPException(
            status_code=400,
            detail="Query is too short"
        )
    
    agent = get_summarization_agent()
    
    async def event_generator():
        try:
            async for event in agent.handle_followup_streaming(
                page_url=request.page_url,
                query=request.user_query
            ):
                yield event
        except Exception as e:
            logger.error(f"Follow-up error: {e}")
            yield {"event": "error", "data": {"error": str(e)}}
    
    return StreamingResponse(
        create_sse_response(event_generator()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.post("/followup/sync", response_model=FollowUpResponse)
async def handle_followup_sync(request: FollowUpRequest) -> FollowUpResponse:
    """
    Handles a follow-up question synchronously.
    Returns the complete answer after processing.
    """
    logger.info(f"Sync follow-up for: {request.page_url}")
    
    if not request.user_query or len(request.user_query.strip()) < 3:
        raise HTTPException(
            status_code=400,
            detail="Query is too short"
        )
    
    agent = get_summarization_agent()
    
    try:
        result = await agent.handle_followup(
            page_url=request.page_url,
            query=request.user_query
        )
        
        return FollowUpResponse(
            page_url=request.page_url,
            query=request.user_query,
            response=result.followup_response,
            sources_count=len(result.retrieved_chunks)
        )
    except Exception as e:
        logger.error(f"Follow-up error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/page/{page_url:path}/status")
async def get_page_status(page_url: str):
    """
    Gets the processing status for a page.
    
    Returns information about whether the page has been
    indexed and summarized, including cached data.
    """
    from ..services import get_retrieval_service
    
    agent = get_summarization_agent()
    retrieval = get_retrieval_service()
    
    cached_state = agent.get_cached_state(page_url)
    page_info = retrieval.get_page_info(page_url)
    
    return {
        "page_url": page_url,
        "indexed": page_info["indexed"],
        "chunk_count": page_info["chunk_count"],
        "has_cached_summary": cached_state is not None,
        "cached_summary": cached_state.final_summary if cached_state else None
    }


@router.delete("/page/{page_url:path}/cache")
async def clear_page_cache(page_url: str):
    """
    Clears the cached data for a page.
    
    Useful when the page content has changed and
    needs to be re-processed.
    """
    from ..services import get_pinecone_client
    
    agent = get_summarization_agent()
    pinecone = get_pinecone_client()
    
    # Clear agent cache
    agent.clear_cache(page_url)
    
    # Clear Pinecone vectors
    pinecone.delete_page_vectors(page_url)
    
    return {"status": "cleared", "page_url": page_url}
