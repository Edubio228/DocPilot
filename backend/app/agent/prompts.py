"""
Prompt Templates Module
Contains all prompts for HIERARCHICAL + ADAPTIVE summarization.

PROMPT ARCHITECTURE:
1. Classification - Detect page type
2. Fact Extraction - Extract facts from chunks (large sections ONLY)
3. Section Summarization - Summarize sections directly or from facts
4. Page Synthesis - Create TL;DR and section outline
5. Follow-up - Answer questions using retrieved source text
"""

from typing import Optional

# ============================================
# SYSTEM PROMPTS
# ============================================

SYSTEM_PROMPTS = {
    "classification": """You are a page classifier. Analyze the content and classify it into one category.
Output ONLY the category name, nothing else.""",

    "fact_extraction": """You are a fact extraction agent.
Extract ONLY factual points and key concepts from the text.
DO NOT summarize, explain, or rewrite.
DO NOT add interpretations or generalizations.
Output bullet points of raw facts only.""",

    "section_summary": """You are a documentation summarizer for developers.
Summarize clearly and concisely.
Preserve important technical details.
Use bullet points for lists.
Assume the reader is a contributor who needs actionable information.""",

    "page_synthesis": """You are a documentation overview generator.
Create high-level page summaries that:
- Provide a TL;DR (5 bullet points max)
- Highlight relationships between sections
- Avoid repeating section-level details
- Help readers navigate the document quickly""",

    "followup": """You are a documentation assistant.
Answer questions ONLY using the provided context.
Be direct and specific.
If information is not in the context, say so clearly.
Cite specific sections when relevant."""
}

# ============================================
# PAGE TYPE INSTRUCTIONS
# ============================================

PAGE_TYPE_INSTRUCTIONS = {
    "docs": """Technical documentation for developers.
Focus on: core functionality, usage patterns, configuration, prerequisites.""",

    "blog": """Blog post or article.
Focus on: main arguments, key insights, conclusions, practical takeaways.""",

    "api": """API reference documentation.
Focus on: endpoints, request/response formats, parameters, authentication, errors.""",

    "readme": """README file or project description.
Focus on: project purpose, installation, quick start, key features.""",

    "unknown": """General web content.
Focus on: main topics, key information, actionable items."""
}


class PromptBuilder:
    """
    Builder class for constructing prompts for hierarchical summarization.
    
    PROMPT FLOW:
    1. classify_page → determines page_type
    2. extract_chunk_facts → (large sections only) extracts raw facts
    3. summarize_section → direct or fact-based summarization
    4. synthesize_page → creates TL;DR + outline
    5. answer_followup → answers questions from source context
    """
    
    # ============================================
    # CLASSIFICATION
    # ============================================
    
    @staticmethod
    def build_classification_prompt(text_sample: str) -> str:
        """
        Builds prompt for page type classification.
        
        Args:
            text_sample: First ~1000 chars of page text
            
        Returns:
            Classification prompt
        """
        return f"""Analyze this content and classify the page type.

Content sample:
{text_sample[:1000]}

Categories:
- docs: Technical documentation, guides, tutorials
- api: API reference with endpoints or function signatures
- blog: Blog posts, articles, opinion pieces
- readme: README files, project descriptions

Respond with ONLY the category name (docs, api, blog, or readme):"""

    # ============================================
    # FACT EXTRACTION (Large Sections ONLY)
    # ============================================
    
    @staticmethod
    def build_chunk_fact_extraction_prompt(
        chunk_text: str,
        chunk_heading: str
    ) -> str:
        """
        Builds prompt for extracting facts from a chunk.
        Used ONLY for large sections that have been chunked.
        
        CRITICAL: This is NOT summarization. Extract raw facts only.
        
        Args:
            chunk_text: The chunk text
            chunk_heading: Parent section heading
            
        Returns:
            Fact extraction prompt
        """
        return f"""Section: {chunk_heading}

Text:
{chunk_text}

Extract factual points and key concepts only.
Do not summarize, explain, or rewrite.
Output as bullet points:"""

    # ============================================
    # SECTION SUMMARIZATION
    # ============================================
    
    @staticmethod
    def build_section_summary_prompt_direct(
        section_text: str,
        section_heading: str,
        page_type: str
    ) -> str:
        """
        Builds prompt for DIRECTLY summarizing a small section.
        Used when section.token_count <= threshold.
        
        Args:
            section_text: Raw section text
            section_heading: Section heading
            page_type: Detected page type
            
        Returns:
            Direct summarization prompt
        """
        type_instruction = PAGE_TYPE_INSTRUCTIONS.get(page_type, PAGE_TYPE_INSTRUCTIONS["unknown"])
        
        return f"""Summarize this documentation section clearly and concisely.
Assume the reader is a contributor.
Preserve important technical details.

Page Type: {page_type}
{type_instruction}

Section: {section_heading}

Content:
{section_text}

Summary (2-4 paragraphs, use bullet points for lists):"""

    @staticmethod
    def build_section_summary_prompt_from_facts(
        merged_facts: str,
        section_heading: str,
        page_type: str
    ) -> str:
        """
        Builds prompt for summarizing a section from extracted facts.
        Used when section was large and chunked → facts extracted.
        
        Args:
            merged_facts: Combined facts from all chunks
            section_heading: Section heading
            page_type: Detected page type
            
        Returns:
            Fact-based summarization prompt
        """
        type_instruction = PAGE_TYPE_INSTRUCTIONS.get(page_type, PAGE_TYPE_INSTRUCTIONS["unknown"])
        
        return f"""Summarize this documentation section using the extracted facts.
Assume the reader is a contributor.
Preserve important technical details.

Page Type: {page_type}
{type_instruction}

Section: {section_heading}

Extracted Facts:
{merged_facts}

Summary (2-4 paragraphs, synthesize the facts into a coherent summary):"""

    # ============================================
    # PAGE-LEVEL SYNTHESIS
    # ============================================
    
    @staticmethod
    def build_page_synthesis_prompt(
        section_summaries: dict[str, str],
        page_title: str,
        page_type: str
    ) -> str:
        """
        Builds prompt for page-level synthesis.
        Creates TL;DR (5 bullets) + section outline.
        
        CRITICAL: This does NOT replace section summaries.
        It provides a high-level overview for navigation.
        
        Args:
            section_summaries: Dict of section_id → summary
            page_title: Page title
            page_type: Detected page type
            
        Returns:
            Page synthesis prompt
        """
        # Format section summaries with headings
        summaries_text = ""
        for i, (section_id, summary) in enumerate(section_summaries.items(), 1):
            # Extract heading from summary if possible, or use section number
            summaries_text += f"\n**Section {i}:**\n{summary}\n"
        
        title_context = f"Page: {page_title}\n" if page_title else ""
        
        return f"""Create a high-level overview of this page.
Highlight relationships between sections.
Avoid repeating section-level details.

{title_context}Page Type: {page_type}

Section Summaries:
{summaries_text}

Generate:
1. **TL;DR** (5 bullet points max - the essential takeaways)
2. **Section Outline** (brief description of what each section covers)

Page Overview:"""

    # ============================================
    # FOLLOW-UP QUESTIONS
    # ============================================
    
    @staticmethod
    def build_followup_prompt(
        user_query: str,
        retrieved_context: str,
        page_title: str = ""
    ) -> str:
        """
        Builds prompt for answering follow-up questions.
        
        CRITICAL: Uses SOURCE text (embedding_type=source), NOT summaries.
        Adjusts verbosity based on query complexity.
        
        Args:
            user_query: The user's question
            retrieved_context: Retrieved source sections
            page_title: Optional page title
            
        Returns:
            Follow-up prompt
        """
        title_context = f"Document: {page_title}\n" if page_title else ""
        
        return f"""Answer the following question using ONLY the provided context.
Be precise and specific.
If the context doesn't contain enough information, say so clearly.

{title_context}
Relevant Context:
{retrieved_context}

Question: {user_query}

Provide a clear, direct answer. Cite specific sections when relevant.

Answer:"""

    @staticmethod
    def build_followup_resummary_prompt(
        user_query: str,
        retrieved_sections_text: str,
        page_type: str
    ) -> str:
        """
        Builds prompt for re-summarizing retrieved sections for follow-up.
        Used when user needs a focused summary of specific sections.
        
        Args:
            user_query: The user's question/intent
            retrieved_sections_text: Source text of retrieved sections
            page_type: Page type for context
            
        Returns:
            Re-summarization prompt
        """
        return f"""The user is asking about specific sections of this {page_type} page.
Re-summarize ONLY the relevant sections to directly address their question.

User Question: {user_query}

Relevant Sections:
{retrieved_sections_text}

Provide a focused summary that directly addresses the user's question.
Adjust verbosity based on question complexity (simple = brief, complex = detailed).

Focused Summary:"""

    # ============================================
    # STREAMING VARIANTS
    # ============================================
    
    @staticmethod
    def build_streaming_section_prompt(
        section_text: str,
        section_heading: str,
        page_type: str,
        is_from_facts: bool = False
    ) -> str:
        """
        Optimized prompt for streaming section summarization.
        
        Args:
            section_text: Section text or merged facts
            section_heading: Section heading
            page_type: Page type
            is_from_facts: Whether input is extracted facts
            
        Returns:
            Streaming-optimized prompt
        """
        content_label = "Extracted Facts" if is_from_facts else "Content"
        
        return f"""[{page_type.upper()}] Section: {section_heading}

{content_label}:
{section_text}

Summarize for developers (preserve technical details):"""


# ============================================
# LEGACY COMPATIBILITY
# ============================================

# Keep old prompt names working
prompt_builder = PromptBuilder()

# Legacy exports
PROMPTS = {
    "system": SYSTEM_PROMPTS,
    "page_types": PAGE_TYPE_INSTRUCTIONS,
}
