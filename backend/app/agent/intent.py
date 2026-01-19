"""
Intent Classification Module - CONVERSATIONAL AGENT
Classifies user intent from natural language input.

INTENT CATEGORIES:
1. PAGE_SUMMARY - "summarize", "overview", "TL;DR"
2. SECTION_EXPLAIN - explain a concept, topic, or section
3. STEP_BY_STEP - "step by step", "walk me through", "how does X work"
4. CLARIFICATION - "what if", "what happens if", "is this mandatory"
5. GENERAL_QUESTION - any other question about the page

Intent is detected using:
1. Lightweight keyword rules (fast, no LLM call)
2. Fallback to LLM classification if needed
"""

import logging
import re
from enum import Enum
from typing import Optional, Tuple
from pydantic import BaseModel

from ..services import get_llm_service
from .prompts import SYSTEM_PROMPTS

logger = logging.getLogger(__name__)


class UserIntent(str, Enum):
    """
    Enumeration of user intent categories.
    Agent behavior changes based on detected intent.
    """
    PAGE_SUMMARY = "page_summary"      # Full page overview
    SECTION_EXPLAIN = "section_explain" # Explain specific topic/section
    STEP_BY_STEP = "step_by_step"      # Procedural walkthrough
    CLARIFICATION = "clarification"     # What-if / conditional questions
    GENERAL_QUESTION = "general_question"  # Default catch-all


class IntentResult(BaseModel):
    """Result of intent classification."""
    intent: UserIntent
    confidence: float  # 0.0 to 1.0
    extracted_topic: Optional[str] = None  # For section_explain/step_by_step
    

# ============================================
# KEYWORD-BASED RULES (Fast, No LLM)
# ============================================

# Patterns for page-level summary intent
SUMMARY_PATTERNS = [
    r'\b(summarize|summary|summarise)\b',
    r'\btl;?dr\b',
    r'\boverview\b',
    r'\bkey\s*points?\b',
    r'\bmain\s*points?\b',
    r'\bgist\b',
    r'\bwhat\s+(is|does)\s+this\s+(page|article|document)\s+(about|cover)\b',
    r'\bbrief(ly)?\s+(explain|describe)\s+(this|the)\s+(page|article)\b',
]

# Patterns for step-by-step intent
STEP_BY_STEP_PATTERNS = [
    r'\bstep[\s-]*by[\s-]*step\b',
    r'\bwalk\s*(me\s*)?through\b',
    r'\bhow\s+(do|does|can|to)\b',
    r'\bexplain\s+(the\s+)?(process|procedure|steps)\b',
    r'\bguide\s*(me)?\b',
    r'\bsequence\b',
    r'\border\s+of\s+operations\b',
]

# Patterns for clarification/conditional intent
CLARIFICATION_PATTERNS = [
    r'\bwhat\s+(if|happens\s+if)\b',
    r'\bis\s+(this|it)\s+(required|mandatory|optional|necessary)\b',
    r'\bdo\s+i\s+(need|have)\s+to\b',
    r'\bcan\s+i\s+(skip|avoid|ignore)\b',
    r'\bwhat\s+are\s+the\s+(consequences|implications)\b',
    r'\bwhat\s+happens\s+when\b',
    r'\bif\s+i\s+(don\'t|do\s+not|skip|miss)\b',
]

# Patterns for section/topic explanation
SECTION_EXPLAIN_PATTERNS = [
    r'\bexplain\s+(?!the\s+process|the\s+steps)',  # "explain X" but not "explain the process"
    r'\bwhat\s+is\s+(?!this\s+(page|article))',  # "what is X" but not "what is this page"
    r'\btell\s+me\s+(about|more)\b',
    r'\bdescribe\b',
    r'\bdefine\b',
    r'\belaborate\b',
    r'\bexpand\s+on\b',
]


def classify_intent_by_rules(query: str) -> Tuple[Optional[UserIntent], float]:
    """
    Fast keyword-based intent classification.
    
    Returns:
        Tuple of (intent, confidence) or (None, 0) if no match
    """
    query_lower = query.lower().strip()
    
    # Check summary patterns (highest priority for explicit requests)
    for pattern in SUMMARY_PATTERNS:
        if re.search(pattern, query_lower, re.IGNORECASE):
            logger.debug(f"Rule match: PAGE_SUMMARY (pattern: {pattern})")
            return UserIntent.PAGE_SUMMARY, 0.9
    
    # Check step-by-step patterns
    for pattern in STEP_BY_STEP_PATTERNS:
        if re.search(pattern, query_lower, re.IGNORECASE):
            logger.debug(f"Rule match: STEP_BY_STEP (pattern: {pattern})")
            return UserIntent.STEP_BY_STEP, 0.85
    
    # Check clarification patterns
    for pattern in CLARIFICATION_PATTERNS:
        if re.search(pattern, query_lower, re.IGNORECASE):
            logger.debug(f"Rule match: CLARIFICATION (pattern: {pattern})")
            return UserIntent.CLARIFICATION, 0.85
    
    # Check section explain patterns
    for pattern in SECTION_EXPLAIN_PATTERNS:
        if re.search(pattern, query_lower, re.IGNORECASE):
            logger.debug(f"Rule match: SECTION_EXPLAIN (pattern: {pattern})")
            return UserIntent.SECTION_EXPLAIN, 0.8
    
    return None, 0.0


def extract_topic(query: str, intent: UserIntent) -> Optional[str]:
    """
    Extracts the topic of interest from the query.
    Used for targeted retrieval.
    """
    query_lower = query.lower().strip()
    
    # Remove common prefixes
    prefixes = [
        r'^(can you |please |could you |i want to |i\'d like to )',
        r'^(explain|tell me about|describe|what is|what are|how does|how do|how to) ',
    ]
    
    topic = query
    for prefix in prefixes:
        topic = re.sub(prefix, '', topic, flags=re.IGNORECASE)
    
    # Clean up
    topic = topic.strip('?!. ')
    
    # Don't return if it's too short or still contains question words
    if len(topic) < 3 or topic.lower() in ['this', 'it', 'that', 'the page', 'the article']:
        return None
    
    return topic


async def classify_intent_by_llm(query: str) -> IntentResult:
    """
    LLM-based intent classification for ambiguous queries.
    Only called when rule-based classification fails.
    """
    llm = get_llm_service()
    
    prompt = f"""Classify the user's intent for this question about a documentation page.

User query: "{query}"

Respond with ONLY ONE of these intents:
- PAGE_SUMMARY: User wants a full page summary/overview/TL;DR
- SECTION_EXPLAIN: User wants to understand a specific concept or section
- STEP_BY_STEP: User wants a procedural walkthrough or how-to guide
- CLARIFICATION: User is asking about conditions, requirements, or "what if" scenarios
- GENERAL_QUESTION: Any other question about the page content

Intent:"""

    try:
        response = await llm.generate(
            prompt=prompt,
            system_prompt="You are an intent classifier. Respond with exactly one intent name.",
            max_tokens=20,
            temperature=0.0  # Deterministic
        )
        
        response_upper = response.strip().upper().replace(' ', '_')
        
        if 'PAGE_SUMMARY' in response_upper or 'SUMMARY' in response_upper:
            return IntentResult(intent=UserIntent.PAGE_SUMMARY, confidence=0.75)
        elif 'STEP_BY_STEP' in response_upper or 'STEP' in response_upper:
            return IntentResult(intent=UserIntent.STEP_BY_STEP, confidence=0.75)
        elif 'CLARIFICATION' in response_upper or 'CLARIF' in response_upper:
            return IntentResult(intent=UserIntent.CLARIFICATION, confidence=0.75)
        elif 'SECTION_EXPLAIN' in response_upper or 'EXPLAIN' in response_upper:
            return IntentResult(intent=UserIntent.SECTION_EXPLAIN, confidence=0.75)
        else:
            return IntentResult(intent=UserIntent.GENERAL_QUESTION, confidence=0.6)
            
    except Exception as e:
        logger.error(f"LLM intent classification failed: {e}")
        return IntentResult(intent=UserIntent.GENERAL_QUESTION, confidence=0.5)


async def classify_intent(query: str) -> IntentResult:
    """
    Main intent classification function.
    
    Uses fast rule-based classification first, falls back to LLM if needed.
    
    Args:
        query: User's input query
        
    Returns:
        IntentResult with intent type and confidence
    """
    logger.info(f"Classifying intent for: {query[:100]}...")
    
    # Try rule-based first (fast)
    intent, confidence = classify_intent_by_rules(query)
    
    if intent and confidence >= 0.8:
        # High-confidence rule match
        topic = extract_topic(query, intent)
        logger.info(f"Intent classified by rules: {intent.value} (confidence: {confidence})")
        return IntentResult(intent=intent, confidence=confidence, extracted_topic=topic)
    
    # Fall back to LLM for ambiguous queries
    logger.info("Rule-based classification uncertain, using LLM")
    result = await classify_intent_by_llm(query)
    result.extracted_topic = extract_topic(query, result.intent)
    logger.info(f"Intent classified by LLM: {result.intent.value} (confidence: {result.confidence})")
    
    return result
