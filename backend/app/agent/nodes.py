"""
Agent Nodes Module - HIERARCHICAL + ADAPTIVE SUMMARIZATION
Contains all node functions for the LangGraph summarization agent.

NODE ARCHITECTURE:
1. classify_page_node - Detect page type
2. extract_sections_node - Parse page into logical sections
3. process_section_node - Adaptive: direct summary OR chunk→facts→summary
4. embed_section_source_node - Embed source text (PRIMARY)
5. embed_section_summary_node - Embed summary text (OPTIONAL)
6. synthesize_page_node - Create TL;DR + outline
7. handle_followup_node - Answer questions from source embeddings
"""

import logging
from typing import Any, AsyncGenerator

from .state import (
    AgentState, PageType, SectionData, ChunkData,
    RetrievedSection, EmbeddingType
)
from .prompts import prompt_builder, SYSTEM_PROMPTS
from ..services import (
    get_retrieval_service,
    get_llm_service,
)
from ..services.section_extractor import get_section_extractor
from ..config import settings

logger = logging.getLogger(__name__)


# ============================================
# NODE 1: PAGE CLASSIFICATION
# ============================================

async def classify_page_node(state: AgentState) -> dict[str, Any]:
    """
    Node 1: Classify the page type based on content.
    
    Analyzes page text to determine type:
    - docs: Technical documentation
    - api: API reference
    - blog: Blog post/article
    - readme: README file
    
    This classification affects summarization prompts and strategy.
    """
    logger.info("Classifying page type...")
    
    llm = get_llm_service()
    prompt = prompt_builder.build_classification_prompt(state.page_text)
    
    try:
        response = await llm.generate(
            prompt=prompt,
            system_prompt=SYSTEM_PROMPTS["classification"],
            max_tokens=20,
            temperature=0.1  # Low temperature for consistent classification
        )
        
        response_lower = response.strip().lower()
        
        if "api" in response_lower:
            page_type = PageType.API
        elif "blog" in response_lower:
            page_type = PageType.BLOG
        elif "readme" in response_lower:
            page_type = PageType.README
        elif "docs" in response_lower or "doc" in response_lower:
            page_type = PageType.DOCS
        else:
            page_type = PageType.UNKNOWN
        
        logger.info(f"Page classified as: {page_type.value}")
        
        return {
            "page_type": page_type,
            "current_status": f"classified as {page_type.value}"
        }
        
    except Exception as e:
        logger.error(f"Classification error: {e}")
        return {
            "page_type": PageType.UNKNOWN,
            "current_status": "classification failed, using default"
        }


# ============================================
# NODE 2: SECTION EXTRACTION
# ============================================

async def extract_sections_node(state: AgentState) -> dict[str, Any]:
    """
    Node 2: Extract logical sections from page content.
    
    EXTRACTION STRATEGY:
    - Parse H1-H3 headings
    - Content between headings = section
    - Calculate token_count for adaptive chunking decision
    - Mark sections as is_large if > threshold
    
    This replaces the old chunk_content_node with section-aware extraction.
    """
    logger.info("Extracting sections from page...")
    
    extractor = get_section_extractor()
    
    try:
        # Extract raw sections
        raw_sections = extractor.extract_sections(
            text=state.page_text,
            page_url=state.page_url
        )
        
        # Convert to SectionData with is_large flag
        sections = []
        for raw in raw_sections:
            is_large = extractor.is_large_section(raw.token_count)
            
            sections.append(SectionData(
                section_id=raw.section_id,
                heading=raw.heading,
                heading_level=raw.heading_level,
                raw_text=raw.raw_text,
                token_count=raw.token_count,
                is_large=is_large,
                chunks=[],
                merged_facts=None,
                summary_text=None,
                is_summarized=False,
                source_embedded=False,
                summary_embedded=False
            ))
        
        stats = extractor.get_section_stats(raw_sections)
        logger.info(f"Extracted {stats['count']} sections: "
                    f"{stats['small_sections']} small, {stats['large_sections']} large")
        
        return {
            "sections": sections,
            "current_section_index": 0,
            "current_status": f"extracted {len(sections)} sections"
        }
        
    except Exception as e:
        logger.error(f"Section extraction error: {e}")
        return {
            "error": f"Failed to extract sections: {str(e)}",
            "current_status": "extraction failed"
        }


# ============================================
# NODE 3: PROCESS SECTION (ADAPTIVE)
# ============================================

async def process_section_node(state: AgentState) -> dict[str, Any]:
    """
    Node 3: Process current section with ADAPTIVE strategy.
    
    ADAPTIVE LOGIC:
    - Small section (token_count <= threshold): summarize directly
    - Large section (token_count > threshold): chunk → extract facts → summarize
    
    This node is called in a loop for each section.
    """
    idx = state.current_section_index
    
    if idx >= len(state.sections):
        logger.info("All sections processed")
        return {"current_status": "all sections processed"}
    
    section = state.sections[idx]
    logger.info(f"Processing section {idx + 1}/{len(state.sections)}: {section.heading} "
                f"({section.token_count} tokens, large={section.is_large})")
    
    llm = get_llm_service()
    
    try:
        if section.is_large:
            # LARGE SECTION: chunk → extract facts → summarize from facts
            summary = await _process_large_section(section, state.page_type.value, llm)
        else:
            # SMALL SECTION: summarize directly
            summary = await _process_small_section(section, state.page_type.value, llm)
        
        # Update section summaries dict
        updated_summaries = dict(state.section_summaries)
        updated_summaries[section.section_id] = summary
        
        # Update sections list with summarized flag
        updated_sections = list(state.sections)
        updated_sections[idx] = section.model_copy(update={
            "summary_text": summary,
            "is_summarized": True
        })
        
        return {
            "sections": updated_sections,
            "section_summaries": updated_summaries,
            "current_section_index": idx + 1,
            "current_status": f"summarized section {idx + 1}/{len(state.sections)}"
        }
        
    except Exception as e:
        logger.error(f"Section processing error for {section.heading}: {e}")
        
        # Update with error placeholder
        updated_summaries = dict(state.section_summaries)
        updated_summaries[section.section_id] = f"[Error summarizing: {section.heading}]"
        
        return {
            "section_summaries": updated_summaries,
            "current_section_index": idx + 1,
            "current_status": f"error on section {idx + 1}"
        }


async def _process_small_section(
    section: SectionData,
    page_type: str,
    llm
) -> str:
    """
    Process a small section: summarize directly from raw text.
    
    Args:
        section: The section to summarize
        page_type: Page type for prompt context
        llm: LLM service instance
        
    Returns:
        Section summary
    """
    prompt = prompt_builder.build_section_summary_prompt_direct(
        section_text=section.raw_text,
        section_heading=section.heading,
        page_type=page_type
    )
    
    return await llm.generate(
        prompt=prompt,
        system_prompt=SYSTEM_PROMPTS["section_summary"],
        max_tokens=512,
        temperature=0.5
    )


async def _process_large_section(
    section: SectionData,
    page_type: str,
    llm
) -> str:
    """
    Process a large section: chunk → extract facts → summarize from facts.
    
    HIERARCHICAL STRATEGY:
    1. Split section into chunks (max 512 tokens each)
    2. Extract facts from each chunk (NO summarization)
    3. Merge facts
    4. Summarize from merged facts
    
    Args:
        section: The large section to process
        page_type: Page type for prompt context
        llm: LLM service instance
        
    Returns:
        Section summary
    """
    # Step 1: Split into chunks
    chunks = _split_section_into_chunks(section)
    logger.debug(f"Split large section into {len(chunks)} chunks")
    
    # Step 2: Extract facts from each chunk
    all_facts = []
    for chunk in chunks:
        prompt = prompt_builder.build_chunk_fact_extraction_prompt(
            chunk_text=chunk.text,
            chunk_heading=section.heading
        )
        
        facts = await llm.generate(
            prompt=prompt,
            system_prompt=SYSTEM_PROMPTS["fact_extraction"],
            max_tokens=300,
            temperature=0.3  # Low temperature for factual extraction
        )
        all_facts.append(facts)
    
    # Step 3: Merge facts
    merged_facts = "\n".join(all_facts)
    
    # Step 4: Summarize from merged facts
    prompt = prompt_builder.build_section_summary_prompt_from_facts(
        merged_facts=merged_facts,
        section_heading=section.heading,
        page_type=page_type
    )
    
    return await llm.generate(
        prompt=prompt,
        system_prompt=SYSTEM_PROMPTS["section_summary"],
        max_tokens=512,
        temperature=0.5
    )


def _split_section_into_chunks(section: SectionData) -> list[ChunkData]:
    """
    Splits a large section into chunks for fact extraction.
    
    Args:
        section: The section to split
        
    Returns:
        List of ChunkData objects
    """
    max_chunk_tokens = settings.chunk_max_tokens  # 512
    text = section.raw_text
    
    # Simple sentence-based splitting
    sentences = text.replace('\n', ' ').split('. ')
    
    chunks = []
    current_chunk = []
    current_tokens = 0
    
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        
        # Estimate tokens (1.3 tokens per word)
        sentence_tokens = int(len(sentence.split()) * 1.3)
        
        if current_tokens + sentence_tokens > max_chunk_tokens and current_chunk:
            # Save current chunk
            chunks.append(ChunkData(
                index=len(chunks),
                text='. '.join(current_chunk) + '.',
                heading=section.heading,
                section_id=section.section_id,
                token_count=current_tokens
            ))
            current_chunk = [sentence]
            current_tokens = sentence_tokens
        else:
            current_chunk.append(sentence)
            current_tokens += sentence_tokens
    
    # Don't forget the last chunk
    if current_chunk:
        chunks.append(ChunkData(
            index=len(chunks),
            text='. '.join(current_chunk) + '.' if current_chunk else '',
            heading=section.heading,
            section_id=section.section_id,
            token_count=current_tokens
        ))
    
    return chunks


# ============================================
# NODE 4: EMBED SECTION SOURCE
# ============================================

async def embed_section_source_node(state: AgentState) -> dict[str, Any]:
    """
    Node 4: Embed section SOURCE text for semantic retrieval.
    
    CRITICAL: This is the PRIMARY embedding used for follow-up queries.
    - Embeds cleaned section source text (chunk-merged if large)
    - Sets embedding_type = "source" in metadata
    
    All retrieval for follow-up questions uses source embeddings.
    """
    logger.info("Embedding section source text...")
    
    retrieval_service = get_retrieval_service()
    
    try:
        # Check if already indexed
        if retrieval_service.check_page_indexed(state.page_url):
            logger.info("Page already indexed, skipping source embedding")
            return {
                "embeddings_saved": True,
                "current_status": "using cached source embeddings"
            }
        
        # Prepare sections for embedding
        sections_for_embedding = []
        for section in state.sections:
            sections_for_embedding.append({
                "section_id": section.section_id,
                "heading": section.heading,
                "text": section.raw_text,  # Source text
                "summary_text": section.summary_text or "",
                "embedding_type": "source"  # PRIMARY
            })
        
        # Store embeddings
        stored_count = retrieval_service.store_sections(
            page_url=state.page_url,
            sections=sections_for_embedding,
            embedding_type=EmbeddingType.SOURCE
        )
        
        # Update sections with embedded flag
        updated_sections = [
            s.model_copy(update={"source_embedded": True})
            for s in state.sections
        ]
        
        logger.info(f"Stored {stored_count} source embeddings")
        
        return {
            "sections": updated_sections,
            "embeddings_saved": True,
            "current_status": f"embedded {stored_count} sections"
        }
        
    except Exception as e:
        logger.error(f"Source embedding error: {e}")
        return {
            "embeddings_saved": False,
            "current_status": "embedding skipped (error)"
        }


# ============================================
# NODE 5: EMBED SECTION SUMMARY (OPTIONAL)
# ============================================

async def embed_section_summary_node(state: AgentState) -> dict[str, Any]:
    """
    Node 5: Embed section SUMMARY text (OPTIONAL).
    
    Used for:
    - Routing
    - Previews
    - Overview queries
    
    NOT used for follow-up question retrieval.
    """
    logger.info("Embedding section summaries (optional)...")
    
    retrieval_service = get_retrieval_service()
    
    try:
        # Prepare summaries for embedding
        summaries_for_embedding = []
        for section in state.sections:
            if section.summary_text:
                summaries_for_embedding.append({
                    "section_id": f"{section.section_id}_summary",
                    "heading": section.heading,
                    "text": section.summary_text,  # Summary text
                    "summary_text": section.summary_text,
                    "embedding_type": "summary"  # SECONDARY
                })
        
        if not summaries_for_embedding:
            return {
                "summary_embeddings_saved": False,
                "current_status": "no summaries to embed"
            }
        
        # Store embeddings
        stored_count = retrieval_service.store_sections(
            page_url=state.page_url,
            sections=summaries_for_embedding,
            embedding_type=EmbeddingType.SUMMARY
        )
        
        # Update sections with embedded flag
        updated_sections = [
            s.model_copy(update={"summary_embedded": True})
            for s in state.sections
        ]
        
        logger.info(f"Stored {stored_count} summary embeddings")
        
        return {
            "sections": updated_sections,
            "summary_embeddings_saved": True,
            "current_status": f"embedded {stored_count} summaries"
        }
        
    except Exception as e:
        logger.error(f"Summary embedding error: {e}")
        return {
            "summary_embeddings_saved": False,
            "current_status": "summary embedding skipped"
        }


# ============================================
# NODE 6: SYNTHESIZE PAGE SUMMARY
# ============================================

async def synthesize_page_node(state: AgentState) -> dict[str, Any]:
    """
    Node 6: Generate page-level synthesis (TL;DR + outline).
    
    CRITICAL: This does NOT replace section summaries.
    It provides a high-level overview for quick navigation.
    
    Output:
    - TL;DR (5 bullet points max)
    - Section outline
    """
    logger.info("Synthesizing page overview...")
    
    if not state.section_summaries:
        logger.warning("No section summaries to synthesize")
        return {
            "page_summary": "No content was summarized.",
            "current_status": "complete"
        }
    
    # If only one section, use it as page summary
    if len(state.section_summaries) == 1:
        only_summary = list(state.section_summaries.values())[0]
        return {
            "page_summary": only_summary,
            "final_summary": only_summary,  # Legacy compat
            "current_status": "complete"
        }
    
    llm = get_llm_service()
    
    try:
        prompt = prompt_builder.build_page_synthesis_prompt(
            section_summaries=state.section_summaries,
            page_title=state.page_title,
            page_type=state.page_type.value
        )
        
        page_summary = await llm.generate(
            prompt=prompt,
            system_prompt=SYSTEM_PROMPTS["page_synthesis"],
            max_tokens=800,
            temperature=0.5
        )
        
        return {
            "page_summary": page_summary,
            "final_summary": page_summary,  # Legacy compat
            "current_status": "complete"
        }
        
    except Exception as e:
        logger.error(f"Page synthesis error: {e}")
        # Fallback: concatenate section summaries
        fallback = "\n\n---\n\n".join(state.section_summaries.values())
        return {
            "page_summary": fallback,
            "final_summary": fallback,
            "current_status": "complete (synthesis failed)"
        }


# ============================================
# NODE 7: HANDLE FOLLOW-UP QUERY
# ============================================

async def handle_followup_node(state: AgentState) -> dict[str, Any]:
    """
    Node 7: Handle follow-up questions using semantic retrieval.
    
    CRITICAL FLOW:
    1. Embed query using Pinecone hosted embeddings
    2. Retrieve top-k relevant SECTIONS (embedding_type=source)
    3. Re-summarize ONLY the retrieved sections
    4. Adjust verbosity based on user intent
    
    DO NOT re-run full-page summarization.
    """
    if not state.user_query:
        logger.warning("No user query provided")
        return {
            "error": "No query provided",
            "current_status": "error"
        }
    
    logger.info(f"Handling follow-up: {state.user_query[:50]}...")
    
    retrieval_service = get_retrieval_service()
    llm = get_llm_service()
    
    try:
        # Retrieve relevant sections (SOURCE embeddings only)
        results = retrieval_service.retrieve_sections(
            page_url=state.page_url,
            query=state.user_query,
            embedding_type=EmbeddingType.SOURCE  # CRITICAL: source only
        )
        
        # Convert to RetrievedSection objects
        retrieved = [
            RetrievedSection(
                section_id=r["section_id"],
                heading=r["heading"],
                text=r["text"],
                summary_text=r.get("summary_text"),
                score=r["score"],
                embedding_type=EmbeddingType.SOURCE
            )
            for r in results
        ]
        
        if not retrieved:
            return {
                "retrieved_sections": [],
                "followup_response": "I couldn't find relevant information to answer that question.",
                "current_status": "complete"
            }
        
        # Build context from retrieved sections
        context = retrieval_service.build_context_from_sections(results)
        
        # Generate answer
        prompt = prompt_builder.build_followup_prompt(
            user_query=state.user_query,
            retrieved_context=context,
            page_title=state.page_title
        )
        
        response = await llm.generate(
            prompt=prompt,
            system_prompt=SYSTEM_PROMPTS["followup"],
            max_tokens=512,
            temperature=0.3  # Lower temperature for factual answers
        )
        
        return {
            "retrieved_sections": retrieved,
            "followup_response": response,
            "current_status": "complete"
        }
        
    except Exception as e:
        logger.error(f"Follow-up error: {e}")
        return {
            "error": f"Failed to answer question: {str(e)}",
            "current_status": "error"
        }


# ============================================
# STREAMING VARIANTS
# ============================================

async def process_section_streaming(
    state: AgentState,
    section_index: int
) -> AsyncGenerator[str, None]:
    """
    Streaming version of section processing.
    Yields tokens as they're generated for real-time UI.
    """
    if section_index >= len(state.sections):
        return
    
    section = state.sections[section_index]
    llm = get_llm_service()
    
    if section.is_large:
        # For large sections, we can't easily stream fact extraction
        # So we do facts first, then stream the summary
        chunks = _split_section_into_chunks(section)
        all_facts = []
        
        for chunk in chunks:
            prompt = prompt_builder.build_chunk_fact_extraction_prompt(
                chunk_text=chunk.text,
                chunk_heading=section.heading
            )
            facts = await llm.generate(
                prompt=prompt,
                system_prompt=SYSTEM_PROMPTS["fact_extraction"],
                max_tokens=300,
                temperature=0.3
            )
            all_facts.append(facts)
        
        merged_facts = "\n".join(all_facts)
        
        prompt = prompt_builder.build_streaming_section_prompt(
            section_text=merged_facts,
            section_heading=section.heading,
            page_type=state.page_type.value,
            is_from_facts=True
        )
    else:
        prompt = prompt_builder.build_streaming_section_prompt(
            section_text=section.raw_text,
            section_heading=section.heading,
            page_type=state.page_type.value,
            is_from_facts=False
        )
    
    async for token in llm.generate_stream(
        prompt=prompt,
        system_prompt=SYSTEM_PROMPTS["section_summary"],
        max_tokens=512,
        temperature=0.5
    ):
        yield token


async def synthesize_page_streaming(state: AgentState) -> AsyncGenerator[str, None]:
    """
    Streaming version of page synthesis.
    """
    if not state.section_summaries:
        yield "No content was summarized."
        return
    
    if len(state.section_summaries) == 1:
        yield list(state.section_summaries.values())[0]
        return
    
    llm = get_llm_service()
    
    prompt = prompt_builder.build_page_synthesis_prompt(
        section_summaries=state.section_summaries,
        page_title=state.page_title,
        page_type=state.page_type.value
    )
    
    async for token in llm.generate_stream(
        prompt=prompt,
        system_prompt=SYSTEM_PROMPTS["page_synthesis"],
        max_tokens=800,
        temperature=0.5
    ):
        yield token


async def handle_followup_streaming(state: AgentState) -> AsyncGenerator[str, None]:
    """
    Streaming version of follow-up handling.
    """
    if not state.user_query:
        yield "No query provided."
        return
    
    retrieval_service = get_retrieval_service()
    llm = get_llm_service()
    
    # Retrieve relevant sections
    results = retrieval_service.retrieve_sections(
        page_url=state.page_url,
        query=state.user_query,
        embedding_type=EmbeddingType.SOURCE
    )
    
    if not results:
        yield "I couldn't find relevant information to answer that question."
        return
    
    # Build context
    context = retrieval_service.build_context_from_sections(results)
    
    # Build prompt
    prompt = prompt_builder.build_followup_prompt(
        user_query=state.user_query,
        retrieved_context=context,
        page_title=state.page_title
    )
    
    # Stream response
    async for token in llm.generate_stream(
        prompt=prompt,
        system_prompt=SYSTEM_PROMPTS["followup"],
        max_tokens=512,
        temperature=0.3
    ):
        yield token


# ============================================
# CONDITIONAL EDGE FUNCTIONS
# ============================================

def should_continue_processing(state) -> str:
    """
    Determines if more sections need processing.
    
    Handles both dict and AgentState inputs from LangGraph.
    
    Returns:
        "continue" if more sections, "embed" if done
    """
    # LangGraph passes state as dict
    if isinstance(state, dict):
        current_index = state.get("current_section_index", 0)
        sections = state.get("sections", [])
    else:
        current_index = state.current_section_index
        sections = state.sections
    
    if current_index < len(sections):
        return "continue"
    return "embed"


def should_handle_followup(state) -> str:
    """
    Routes between summarization and follow-up.
    
    Handles both dict and AgentState inputs from LangGraph.
    
    Returns:
        "followup" if there's a query, "summarize" otherwise
    """
    # LangGraph passes state as dict
    if isinstance(state, dict):
        user_query = state.get("user_query", "")
    else:
        user_query = state.user_query
    
    if user_query:
        return "followup"
    return "summarize"


# ============================================
# LEGACY COMPATIBILITY
# ============================================

# Keep old function names working
async def chunk_content_node(state: AgentState) -> dict[str, Any]:
    """[DEPRECATED] Use extract_sections_node instead."""
    return await extract_sections_node(state)


async def summarize_chunk_node(state: AgentState) -> dict[str, Any]:
    """[DEPRECATED] Use process_section_node instead."""
    return await process_section_node(state)


async def merge_summary_node(state: AgentState) -> dict[str, Any]:
    """[DEPRECATED] Use synthesize_page_node instead."""
    return await synthesize_page_node(state)


async def embed_and_store_node(state: AgentState) -> dict[str, Any]:
    """[DEPRECATED] Use embed_section_source_node instead."""
    return await embed_section_source_node(state)


def should_continue_summarizing(state: AgentState) -> str:
    """[DEPRECATED] Use should_continue_processing instead."""
    return should_continue_processing(state)


async def summarize_chunk_streaming(
    state: AgentState,
    chunk_index: int
) -> AsyncGenerator[str, None]:
    """[DEPRECATED] Use process_section_streaming instead."""
    async for token in process_section_streaming(state, chunk_index):
        yield token


async def merge_summary_streaming(state: AgentState) -> AsyncGenerator[str, None]:
    """[DEPRECATED] Use synthesize_page_streaming instead."""
    async for token in synthesize_page_streaming(state):
        yield token


async def handle_followup_streaming(
    state: AgentState
) -> AsyncGenerator[str, None]:
    """
    Streaming version of follow-up handling.
    
    Args:
        state: Current agent state with user_query
        
    Yields:
        Tokens as they're generated
    """
    if not state.user_query:
        yield "No query provided."
        return
    
    retrieval_service = get_retrieval_service()
    llm = get_llm_service()
    
    # Retrieve relevant chunks
    results = retrieval_service.retrieve_relevant_chunks(
        page_url=state.page_url,
        query=state.user_query
    )
    
    if not results:
        yield "I couldn't find relevant information to answer that question."
        return
    
    # Build context
    context = retrieval_service.build_context_from_chunks(results)
    
    # Build prompt
    prompt = prompt_builder.build_followup_prompt(
        user_query=state.user_query,
        retrieved_context=context,
        page_title=state.page_title
    )
    
    # Stream response
    async for token in llm.generate_stream(
        prompt=prompt,
        system_prompt=SYSTEM_PROMPTS["followup"],
        max_tokens=512,
        temperature=0.3
    ):
        yield token


def should_continue_summarizing(state: AgentState) -> str:
    """
    Conditional edge function to determine if more chunks need summarization.
    
    Args:
        state: Current agent state
        
    Returns:
        "continue" if more chunks, "merge" if done
    """
    if state.current_chunk_index < len(state.chunks):
        return "continue"
    return "merge"


def should_handle_followup(state: AgentState) -> str:
    """
    Conditional edge function to route between summarization and follow-up.
    
    Args:
        state: Current agent state
        
    Returns:
        "followup" if there's a query, "summarize" otherwise
    """
    if state.user_query:
        return "followup"
    return "summarize"
