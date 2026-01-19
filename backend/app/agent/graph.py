"""
LangGraph Agent Definition Module - CONVERSATIONAL AGENT
Defines the state graph for HIERARCHICAL + ADAPTIVE summarization
with automatic intent classification and retrieval-based responses.

GRAPH ARCHITECTURE (Summarization):
1. classify_page → extract_sections
2. extract_sections → process_section (loop)
3. process_section → [process_section | embed_source] (conditional)
4. embed_source → [embed_summary | synthesize_page] (optional summary embeddings)
5. synthesize_page → END

Conversational Flow:
- classify_intent → retrieve_sections → generate_response
"""

import logging
from typing import AsyncGenerator, Optional, TYPE_CHECKING
from .intent import UserIntent

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from .state import AgentState, create_initial_state, create_followup_state, PageType
from .nodes import (
    # New hierarchical nodes
    classify_page_node,
    extract_sections_node,
    process_section_node,
    embed_section_source_node,
    embed_section_summary_node,
    synthesize_page_node,
    handle_followup_node,
    # Streaming variants
    process_section_streaming,
    synthesize_page_streaming,
    handle_followup_streaming,
    # Conditional functions
    should_continue_processing,
    should_handle_followup,
    # Legacy compatibility
    chunk_content_node,
    summarize_chunk_node,
    merge_summary_node,
    embed_and_store_node,
    should_continue_summarizing,
    summarize_chunk_streaming,
    merge_summary_streaming,
)

logger = logging.getLogger(__name__)


def create_summarization_graph() -> StateGraph:
    """
    Creates the LangGraph StateGraph for HIERARCHICAL page summarization.
    
    GRAPH FLOW:
    1. classify_page → extract_sections
    2. extract_sections → process_section
    3. process_section → [process_section | embed_source] (loop until all done)
    4. embed_source → synthesize_page
    5. synthesize_page → END
    
    The process_section node handles ADAPTIVE chunking internally:
    - Small sections: summarize directly
    - Large sections: chunk → facts → summarize
    
    Returns:
        Configured StateGraph
    """
    graph = StateGraph(AgentState)
    
    # Add nodes
    graph.add_node("classify_page", classify_page_node)
    graph.add_node("extract_sections", extract_sections_node)
    graph.add_node("process_section", process_section_node)
    graph.add_node("embed_source", embed_section_source_node)
    graph.add_node("synthesize_page", synthesize_page_node)
    
    # Set entry point
    graph.set_entry_point("classify_page")
    
    # Linear edges
    graph.add_edge("classify_page", "extract_sections")
    graph.add_edge("extract_sections", "process_section")
    
    # Section processing loop (conditional)
    graph.add_conditional_edges(
        "process_section",
        should_continue_processing,
        {
            "continue": "process_section",  # More sections to process
            "embed": "embed_source"          # All sections done
        }
    )
    
    # After embedding, synthesize
    graph.add_edge("embed_source", "synthesize_page")
    
    # End edges
    graph.add_edge("synthesize_page", END)
    
    return graph


def create_followup_graph() -> StateGraph:
    """
    Creates a simpler graph for handling follow-up questions.
    
    FLOW:
    - handle_followup → END
    
    The handle_followup node:
    1. Embeds query using Pinecone hosted embeddings
    2. Retrieves SOURCE sections (embedding_type=source)
    3. Re-summarizes only retrieved sections
    4. Streams response
    
    Returns:
        Configured StateGraph for follow-ups
    """
    graph = StateGraph(AgentState)
    
    graph.add_node("handle_followup", handle_followup_node)
    graph.set_entry_point("handle_followup")
    graph.add_edge("handle_followup", END)
    
    return graph


class SummarizationAgent:
    """
    High-level agent class wrapping the LangGraph workflow.
    Supports HIERARCHICAL + ADAPTIVE summarization with streaming.
    
    Features:
    - Section-based summarization (not whole-page)
    - Adaptive chunking for large sections
    - Dual embeddings (source + optional summary)
    - Real-time streaming for all outputs
    """
    
    def __init__(self):
        """Initialize the agent with compiled graphs."""
        self.summarization_graph = create_summarization_graph()
        self.followup_graph = create_followup_graph()
        
        # Compile graphs with checkpointing
        self.memory = MemorySaver()
        
        self.summarization_app = self.summarization_graph.compile(
            checkpointer=self.memory
        )
        self.followup_app = self.followup_graph.compile(
            checkpointer=self.memory
        )
        
        # Cache for page states
        self._page_states: dict[str, AgentState] = {}
        
        logger.info("SummarizationAgent initialized with hierarchical summarization")
    
    async def summarize_page(
        self,
        page_url: str,
        page_text: str,
        page_title: str = ""
    ) -> AgentState:
        """
        Summarizes a page using hierarchical section-based approach.
        Non-streaming version.
        
        Args:
            page_url: URL of the page
            page_text: Extracted page text
            page_title: Optional page title
            
        Returns:
            Final AgentState with section summaries and page synthesis
        """
        initial_state = create_initial_state(
            page_url=page_url,
            page_text=page_text,
            page_title=page_title
        )
        
        config = {"configurable": {"thread_id": page_url}}
        
        final_state = await self.summarization_app.ainvoke(
            initial_state.model_dump(),
            config=config
        )
        
        result = AgentState(**final_state)
        self._page_states[page_url] = result
        
        return result
    
    async def summarize_page_streaming(
        self,
        page_url: str,
        page_text: str,
        page_title: str = ""
    ) -> AsyncGenerator[dict, None]:
        """
        Summarizes a page with STREAMING output.
        
        STREAMING EVENTS:
        - status: Progress updates
        - section_start: Starting a section
        - token: Individual tokens
        - section_end: Section complete
        - synthesis_start: Starting page synthesis
        - synthesis_end: Synthesis complete
        - complete: All done
        
        Args:
            page_url: URL of the page
            page_text: Extracted page text
            page_title: Optional page title
            
        Yields:
            Dict with event type and data
        """
        # Initialize state
        state = create_initial_state(
            page_url=page_url,
            page_text=page_text,
            page_title=page_title
        )
        
        # Step 1: Classify page
        yield {"event": "status", "data": "analyzing page type"}
        result = await classify_page_node(state)
        state = state.model_copy(update=result)
        yield {"event": "status", "data": f"classified as {state.page_type.value}"}
        
        # Step 2: Extract sections
        yield {"event": "status", "data": "extracting sections"}
        result = await extract_sections_node(state)
        state = state.model_copy(update=result)
        yield {"event": "status", "data": f"found {len(state.sections)} sections"}
        
        # Step 3: Embed source text
        yield {"event": "status", "data": "embedding content"}
        result = await embed_section_source_node(state)
        state = state.model_copy(update=result)
        yield {"event": "status", "data": "embeddings saved"}
        
        # Step 4: Summarize each section with streaming
        section_summaries = {}
        for i, section in enumerate(state.sections):
            yield {
                "event": "status",
                "data": f"summarizing section {i + 1}/{len(state.sections)}: {section.heading}"
            }
            yield {
                "event": "section_start",
                "data": {
                    "index": i,
                    "heading": section.heading,
                    "is_large": section.is_large
                }
            }
            
            section_summary = ""
            async for token in process_section_streaming(state, i):
                section_summary += token
                yield {"event": "token", "data": token}
            
            section_summaries[section.section_id] = section_summary
            yield {"event": "section_end", "data": {"index": i}}
        
        # Update state with summaries
        state = state.model_copy(update={"section_summaries": section_summaries})
        
        # Step 5: Page synthesis with streaming
        if len(section_summaries) > 1:
            yield {"event": "status", "data": "creating page overview"}
            yield {"event": "synthesis_start", "data": {}}
            
            page_summary = ""
            async for token in synthesize_page_streaming(state):
                page_summary += token
                yield {"event": "token", "data": token}
            
            state = state.model_copy(update={
                "page_summary": page_summary,
                "final_summary": page_summary  # Legacy compat
            })
            yield {"event": "synthesis_end", "data": {}}
        else:
            # Single section - use section summary as page summary
            single_summary = list(section_summaries.values())[0] if section_summaries else ""
            state = state.model_copy(update={
                "page_summary": single_summary,
                "final_summary": single_summary
            })
        
        # Cache final state
        self._page_states[page_url] = state
        
        yield {"event": "status", "data": "complete"}
        yield {
            "event": "complete",
            "data": {
                "summary": state.page_summary,
                "section_count": len(state.sections),
                "section_summaries": section_summaries
            }
        }
    
    async def handle_followup(
        self,
        page_url: str,
        query: str
    ) -> AgentState:
        """
        Handles a follow-up question about a previously summarized page.
        Non-streaming version.
        
        CRITICAL: Retrieves using embedding_type=source, not summaries.
        
        Args:
            page_url: URL of the page
            query: User's follow-up question
            
        Returns:
            AgentState with followup_response
        """
        if page_url in self._page_states:
            base_state = self._page_states[page_url]
        else:
            base_state = AgentState(page_url=page_url)
        
        state = create_followup_state(base_state, query)
        
        config = {"configurable": {"thread_id": f"{page_url}:followup"}}
        
        final_state = await self.followup_app.ainvoke(
            state.model_dump(),
            config=config
        )
        
        return AgentState(**final_state)
    
    async def handle_followup_streaming(
        self,
        page_url: str,
        query: str
    ) -> AsyncGenerator[dict, None]:
        """
        Handles a follow-up question with streaming output.
        
        Args:
            page_url: URL of the page
            query: User's follow-up question
            
        Yields:
            Dict with event type and data
        """
        if page_url in self._page_states:
            base_state = self._page_states[page_url]
        else:
            base_state = AgentState(page_url=page_url)
        
        state = create_followup_state(base_state, query)
        
        yield {"event": "status", "data": "searching for relevant sections"}
        yield {"event": "followup_start", "data": {"query": query}}
        
        response = ""
        async for token in handle_followup_streaming(state):
            response += token
            yield {"event": "token", "data": token}
        
        yield {"event": "followup_end", "data": {}}
        yield {"event": "complete", "data": {"response": response}}
    
    # ============================================
    # NEW: CONVERSATIONAL CHAT METHODS
    # ============================================
    
    def is_page_indexed(self, page_url: str) -> bool:
        """
        Checks if a page has been indexed in Pinecone.
        Used to decide if we need to index before answering queries.
        """
        return page_url in self._page_states and self._page_states[page_url].embeddings_saved
    
    async def index_page_for_chat(
        self,
        page_url: str,
        page_text: str,
        page_title: str = ""
    ) -> None:
        """
        Silently indexes a page without streaming summaries.
        Used for chat queries when page hasn't been summarized yet.
        
        Only extracts sections and creates embeddings - no summarization.
        """
        logger.info(f"Indexing page for chat: {page_url}")
        
        from .state import create_initial_state
        
        state = create_initial_state(
            page_url=page_url,
            page_text=page_text,
            page_title=page_title
        )
        
        # Classify page
        result = await classify_page_node(state)
        state = state.model_copy(update=result)
        
        # Extract sections
        result = await extract_sections_node(state)
        state = state.model_copy(update=result)
        
        # Embed source text only (for retrieval)
        result = await embed_section_source_node(state)
        state = state.model_copy(update=result)
        
        # Cache state
        self._page_states[page_url] = state
        logger.info(f"Page indexed: {len(state.sections)} sections")
    
    async def handle_chat_query_streaming(
        self,
        page_url: str,
        query: str,
        intent: 'UserIntent',
        topic: Optional[str] = None,
        page_text: Optional[str] = None
    ) -> AsyncGenerator[dict, None]:
        """
        Handles a chat query with intent-based response generation.
        
        INTENT ROUTING:
        - SECTION_EXPLAIN: Retrieve + explain relevant sections
        - STEP_BY_STEP: Retrieve + rewrite as numbered steps
        - CLARIFICATION: Retrieve + extract conditions/consequences
        - GENERAL_QUESTION: Retrieve + answer based on context
        
        NEW: If no results found, automatically crawls relevant linked pages.
        
        Args:
            page_url: URL of the page
            query: User's query
            intent: Classified user intent
            topic: Extracted topic from query (if any)
            page_text: Raw page content (for link crawling)
            
        Yields:
            Dict with event type and data
        """
        from .intent import UserIntent
        from ..services import get_retrieval_service, get_llm_service
        from .prompts import prompt_builder
        
        # Get base state
        if page_url in self._page_states:
            base_state = self._page_states[page_url]
        else:
            base_state = AgentState(page_url=page_url)
        
        retrieval = get_retrieval_service()
        llm = get_llm_service()
        
        # Step 1: Retrieve relevant sections
        yield {"event": "status", "data": {"message": "searching relevant sections"}}
        
        # Use topic if available, otherwise full query
        search_query = topic if topic else query
        
        retrieved = retrieval.retrieve_sections(
            page_url=page_url,
            query=search_query,
            top_k=5,
            embedding_type="source"
        )
        
        # NEW: If no results, try crawling linked pages
        if not retrieved and page_text:
            yield {"event": "status", "data": {"message": "🔍 searching linked pages..."}}
            
            from ..services import get_link_crawler
            crawler = get_link_crawler()
            
            try:
                # Crawl relevant linked pages
                crawled_pages = await crawler.crawl_relevant_pages(
                    page_text=page_text,
                    base_url=page_url,
                    query=search_query
                )
                
                if crawled_pages:
                    yield {"event": "status", "data": {"message": f"📄 found {len(crawled_pages)} relevant pages, indexing..."}}
                    
                    # Index each crawled page
                    for page in crawled_pages:
                        if page.get("text") and len(page["text"]) > 50:
                            await self.index_page_for_chat(
                                page_url=page["url"],
                                page_text=page["text"],
                                page_title=page.get("title", "")
                            )
                    
                    # Try retrieval again across ALL indexed pages (not just current URL)
                    # For now, search each crawled page
                    all_retrieved = []
                    for page in crawled_pages:
                        page_results = retrieval.retrieve_sections(
                            page_url=page["url"],
                            query=search_query,
                            top_k=3,
                            embedding_type="source"
                        )
                        for result in page_results:
                            result["source_url"] = page["url"]
                            result["source_title"] = page.get("title", "")
                        all_retrieved.extend(page_results)
                    
                    # Sort by score and take top 5
                    all_retrieved.sort(key=lambda x: x.get("score", 0), reverse=True)
                    retrieved = all_retrieved[:5]
                    
                    if retrieved:
                        yield {"event": "status", "data": {"message": f"✅ found {len(retrieved)} sections from linked pages"}}
            
            except Exception as e:
                logger.error(f"Link crawling failed: {e}")
                # Continue with empty results
        
        if not retrieved:
            yield {"event": "token", "data": "I couldn't find relevant information on this page or linked pages. Try navigating to a more specific documentation page."}
            yield {"event": "complete", "data": {"response": "No relevant sections found"}}
            return
        
        yield {"event": "status", "data": {"message": f"found {len(retrieved)} relevant sections"}}
        
        # Build context from retrieved sections
        context_parts = []
        source_pages = set()  # Track if we used multiple pages
        for i, section in enumerate(retrieved, 1):
            heading = section.get("heading", section.get("section_id", f"Section {i}"))
            text = section.get("text", "")
            
            # Check if this came from a crawled page
            source_url = section.get("source_url", "")
            source_title = section.get("source_title", "")
            if source_url:
                source_pages.add(source_title or source_url)
                context_parts.append(f"[Section {i}: {heading} (from: {source_title or source_url})]\n{text}")
            else:
                context_parts.append(f"[Section {i}: {heading}]\n{text}")
        
        context = "\n\n".join(context_parts)
        
        # Step 2: Generate response based on intent
        yield {"event": "followup_start", "data": {"query": query, "intent": intent.value}}
        
        # Build intent-specific prompt - CONCISE but COMPLETE responses
        if intent == UserIntent.STEP_BY_STEP:
            system_prompt = """You are a documentation assistant. Give CONCISE, ACTIONABLE step-by-step guides.

CRITICAL FORMATTING RULES:
1. Code blocks MUST use triple backticks: ```bash ... ``` (NEVER single backtick)
2. Maximum 8 steps - focus on the essential ones
3. One code block per step maximum
4. Use **bold** for important terms
5. Use bullet points (-) not numbered lists inside steps
6. Keep explanations to 1-2 sentences per step"""
            
            prompt = f"""Create a step-by-step guide for: "{query}"

Context:
{context}

FORMAT (follow exactly):

## 🎯 [Task Name]

### Prerequisites
- Item 1
- Item 2

### Step 1: [Action Name]
Brief explanation.
```bash
command here
```

### Step 2: [Action Name]
Brief explanation.
```bash
command here
```

RULES:
- Max 8 steps
- Always close code blocks with ```
- Keep it concise"""

        elif intent == UserIntent.CLARIFICATION:
            system_prompt = """You are a documentation assistant. Give CLEAR, DIRECT answers.

CRITICAL FORMATTING RULES:
1. Code blocks MUST use triple backticks: ```bash ... ``` (NEVER single backtick)
2. Lead with the direct answer in **bold**
3. Use bullet points (-) for lists
4. Keep response under 300 words"""
            
            prompt = f"""Answer: {query}

Context:
{context}

FORMAT:

## 💡 Answer

**[Direct answer in 1-2 sentences]**

### Details
- Point 1
- Point 2

### Command (if applicable)
```bash
command here
```

Keep response focused and concise."""

        elif intent == UserIntent.SECTION_EXPLAIN:
            system_prompt = """You are a documentation assistant. Give CLEAR explanations.

CRITICAL FORMATTING RULES:
1. Code blocks MUST use triple backticks: ```bash ... ``` (NEVER single backtick)
2. Start with **TL;DR** in bold
3. Use ### for sections
4. Keep response under 400 words"""
            
            prompt = f"""Explain: {query}

Context:
{context}

FORMAT:

## 📌 [Topic]

**TL;DR:** [One sentence summary]

### How it works
- Point 1
- Point 2

### Example
```bash
example command or code
```

Keep response concise."""

        else:  # GENERAL_QUESTION
            system_prompt = """You are a documentation assistant. Give HELPFUL, ACCURATE responses.

CRITICAL FORMATTING RULES:
1. Code blocks MUST use triple backticks: ```bash ... ``` (NEVER single backtick)
2. Lead with the direct answer in **bold**
3. Use bullet points (-) for lists
4. Keep response under 300 words"""
            
            prompt = f"""Answer: {query}

Context:
{context}

FORMAT:

**[Direct answer]**

### Details
- Point 1
- Point 2

### Command (if applicable)
```bash
command here
```

Keep response focused."""
        
        # Stream the response
        response = ""
        async for token in llm.generate_stream(
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=1200,  # Reduced to prevent truncation
            temperature=0.2   # Lower for consistent formatting
        ):
            response += token
            yield {"event": "token", "data": token}
        
        yield {"event": "followup_end", "data": {}}
        yield {"event": "complete", "data": {"response": response}}
    
    def get_cached_state(self, page_url: str) -> Optional[AgentState]:
        """Returns the cached state for a page if available."""
        return self._page_states.get(page_url)
    
    def clear_cache(self, page_url: Optional[str] = None) -> None:
        """Clears cached page states."""
        if page_url:
            self._page_states.pop(page_url, None)
        else:
            self._page_states.clear()


# Singleton instance
_agent: Optional[SummarizationAgent] = None


def get_summarization_agent() -> SummarizationAgent:
    """Returns the singleton SummarizationAgent instance."""
    global _agent
    if _agent is None:
        _agent = SummarizationAgent()
    return _agent
