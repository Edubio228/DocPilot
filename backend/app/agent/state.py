"""
Agent State Module - CONVERSATIONAL AGENT
Defines the state schema for the LangGraph conversational agent.
Implements HIERARCHICAL + ADAPTIVE summarization with intent-based routing.

STATE ARCHITECTURE:
- Sections are the PRIMARY unit of summarization
- Chunks are ONLY created for large sections (> threshold)
- State tracks both section-level and page-level summaries
- Embeddings track both source text and summary text
- Conversation history enables multi-turn interactions
"""

from typing import Optional, Literal, Annotated, List
from enum import Enum
from dataclasses import dataclass, field
from pydantic import BaseModel, Field
import operator


class PageType(str, Enum):
    """Enumeration of supported page types for specialized summarization."""
    DOCS = "docs"
    BLOG = "blog"
    API = "api"
    README = "readme"
    UNKNOWN = "unknown"


class EmbeddingType(str, Enum):
    """Type of embedding stored in Pinecone - critical for retrieval filtering."""
    SOURCE = "source"   # PRIMARY - used for follow-up retrieval
    SUMMARY = "summary"  # SECONDARY - used for routing/previews only


class ConversationMessage(BaseModel):
    """Represents a message in the conversation history."""
    role: Literal["user", "assistant"]
    content: str
    intent: Optional[str] = None  # For user messages, the detected intent


class ChunkData(BaseModel):
    """
    Represents a chunk WITHIN a large section.
    Chunks are created ONLY when section.token_count > threshold.
    
    Chunks are used for:
    - Fact extraction (not summarization)
    - Breaking down large sections for processing
    """
    index: int
    text: str
    heading: str  # Parent section heading
    section_id: str  # Reference to parent section
    token_count: int = 0
    extracted_facts: Optional[str] = None  # Facts extracted from this chunk


class SectionData(BaseModel):
    """
    Represents a logical section of the page (PRIMARY summarization unit).
    
    HIERARCHICAL SUMMARIZATION:
    - Small sections (token_count <= threshold): summarize directly
    - Large sections (token_count > threshold): chunk → extract facts → summarize
    
    Each section produces:
    - summary_text: The final section summary
    - source_text: Cleaned source (chunk-merged if large section)
    """
    section_id: str  # Unique identifier for this section
    heading: str  # Section heading (H1-H3)
    heading_level: int  # 1, 2, or 3
    raw_text: str  # Original section text
    token_count: int  # Token count for adaptive chunking decision
    
    # Chunking state (ONLY for large sections)
    is_large: bool = False  # True if token_count > threshold
    chunks: list[ChunkData] = Field(default_factory=list)
    merged_facts: Optional[str] = None  # Combined facts from all chunks
    
    # Summarization state
    summary_text: Optional[str] = None
    is_summarized: bool = False
    
    # Embedding state
    source_embedded: bool = False  # SOURCE text embedded
    summary_embedded: bool = False  # SUMMARY text embedded (optional)


class RetrievedSection(BaseModel):
    """Represents a section retrieved via similarity search."""
    section_id: str
    heading: str
    text: str  # Source text (what was embedded)
    summary_text: Optional[str] = None
    score: float
    embedding_type: EmbeddingType = EmbeddingType.SOURCE


class AgentState(BaseModel):
    """
    The state object passed between all nodes in the LangGraph agent.
    
    HIERARCHICAL SUMMARIZATION STATE:
    - sections[]: All extracted sections with their state
    - current_section_index: Tracks section loop progress
    - section_summaries{}: Map of section_id → summary (for synthesis)
    - page_summary: Final page-level synthesis (TL;DR + outline)
    
    The state is immutable - nodes return new state dicts that get merged.
    """
    
    # Page identification
    page_url: str = Field(default="", description="URL of the page being processed")
    page_title: str = Field(default="", description="Title of the page")
    
    # Original content
    page_text: str = Field(default="", description="Full extracted text from the page")
    
    # Page classification
    page_type: PageType = Field(
        default=PageType.UNKNOWN,
        description="Detected type of the page (docs/api/blog/readme)"
    )
    
    # ============================================
    # HIERARCHICAL SUMMARIZATION STATE
    # ============================================
    
    # Section extraction state
    sections: list[SectionData] = Field(
        default_factory=list,
        description="List of extracted sections with metadata"
    )
    
    # Section processing loop state
    current_section_index: int = Field(
        default=0,
        description="Index of section currently being processed"
    )
    
    # Section summaries (accumulates as sections are processed)
    # Using dict for direct access by section_id
    section_summaries: dict[str, str] = Field(
        default_factory=dict,
        description="Map of section_id → summary text"
    )
    
    # Page-level synthesis (generated AFTER all sections are summarized)
    page_summary: str = Field(
        default="",
        description="Page-level TL;DR and section outline"
    )
    
    # Legacy compatibility (for backward compat with old code)
    chunks: list[ChunkData] = Field(
        default_factory=list,
        description="[DEPRECATED] Use sections instead"
    )
    summaries: Annotated[list[str], operator.add] = Field(
        default_factory=list,
        description="[DEPRECATED] Use section_summaries instead"
    )
    final_summary: str = Field(
        default="",
        description="[DEPRECATED] Use page_summary instead"
    )
    
    # ============================================
    # EMBEDDING STATE
    # ============================================
    
    embeddings_saved: bool = Field(
        default=False,
        description="Whether all source embeddings have been stored"
    )
    summary_embeddings_saved: bool = Field(
        default=False,
        description="Whether summary embeddings have been stored (optional)"
    )
    
    # ============================================
    # FOLLOW-UP QUERY STATE
    # ============================================
    
    user_query: Optional[str] = Field(
        default=None,
        description="Current user query (any intent)"
    )
    user_intent: Optional[str] = Field(
        default=None,
        description="Detected intent for current query"
    )
    retrieved_sections: list[RetrievedSection] = Field(
        default_factory=list,
        description="Sections retrieved for follow-up (embedding_type=source)"
    )
    followup_response: str = Field(
        default="",
        description="Response to the user's follow-up question"
    )
    
    # ============================================
    # CONVERSATION HISTORY (NEW)
    # ============================================
    
    conversation_history: list[ConversationMessage] = Field(
        default_factory=list,
        description="Full conversation history for multi-turn chat"
    )
    last_user_query: Optional[str] = Field(
        default=None,
        description="Most recent user query"
    )
    
    # ============================================
    # PROGRESS TRACKING
    # ============================================
    
    current_status: str = Field(
        default="initializing",
        description="Current processing status for UI updates"
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if processing failed"
    )
    
    # Streaming state
    is_streaming: bool = Field(
        default=False,
        description="Whether we're currently streaming tokens"
    )
    stream_buffer: str = Field(
        default="",
        description="Buffer for accumulated streaming tokens"
    )
    
    class Config:
        """Pydantic config for the state model."""
        arbitrary_types_allowed = True


def create_initial_state(
    page_url: str,
    page_text: str,
    page_title: str = ""
) -> AgentState:
    """
    Factory function to create initial agent state for page summarization.
    
    Args:
        page_url: URL of the page
        page_text: Extracted page text
        page_title: Optional page title
        
    Returns:
        Initialized AgentState
    """
    return AgentState(
        page_url=page_url,
        page_text=page_text,
        page_title=page_title,
        current_status="reading page"
    )


def create_followup_state(
    existing_state: AgentState,
    user_query: str
) -> AgentState:
    """
    Creates state for processing a follow-up question.
    Preserves existing page data and summaries.
    
    IMPORTANT: Follow-up queries retrieve using embedding_type=source
    and only re-summarize the RETRIEVED sections, not the whole page.
    
    Args:
        existing_state: Previous state with page data
        user_query: The user's follow-up question
        
    Returns:
        Updated AgentState for follow-up processing
    """
    return existing_state.model_copy(
        update={
            "user_query": user_query,
            "retrieved_sections": [],
            "followup_response": "",
            "current_status": "processing query",
            "error": None
        }
    )
