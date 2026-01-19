"""
Streaming Utilities Module
Handles Server-Sent Events (SSE) formatting and response creation.
Provides utilities for streaming tokens and progress updates to clients.
"""

import json
import asyncio
import logging
from typing import AsyncGenerator, Any, Optional
from enum import Enum

from ..config import settings

logger = logging.getLogger(__name__)


class StreamingEventType(str, Enum):
    """Enumeration of SSE event types used in the API."""
    
    # Progress events
    STATUS = "status"
    PROGRESS = "progress"
    
    # Summarization events
    CHUNK_START = "chunk_start"
    CHUNK_END = "chunk_end"
    FINAL_START = "final_start"
    FINAL_END = "final_end"
    
    # Token streaming
    TOKEN = "token"
    
    # Follow-up events
    FOLLOWUP_START = "followup_start"
    FOLLOWUP_END = "followup_end"
    
    # Completion events
    COMPLETE = "complete"
    ERROR = "error"
    
    # Connection events
    PING = "ping"
    CONNECTED = "connected"


def format_sse_event(
    event_type: StreamingEventType | str,
    data: Any,
    event_id: Optional[str] = None
) -> str:
    """
    Formats data as a Server-Sent Event string.
    
    SSE format:
    event: <event_type>
    id: <optional_id>
    data: <json_data>
    
    Args:
        event_type: Type of the event
        data: Data payload (will be JSON serialized)
        event_id: Optional event ID for client tracking
        
    Returns:
        Formatted SSE string
    """
    lines = []
    
    # Event type
    event_name = event_type.value if isinstance(event_type, StreamingEventType) else event_type
    lines.append(f"event: {event_name}")
    
    # Optional ID
    if event_id:
        lines.append(f"id: {event_id}")
    
    # Data (JSON serialized if not a string)
    if isinstance(data, str):
        # For token streaming, send as-is
        lines.append(f"data: {json.dumps(data)}")
    else:
        lines.append(f"data: {json.dumps(data)}")
    
    # SSE messages end with double newline
    return "\n".join(lines) + "\n\n"


def format_sse_token(token: str) -> str:
    """
    Optimized formatting for streaming tokens.
    Minimizes overhead for high-frequency token events.
    
    Args:
        token: The token text
        
    Returns:
        Formatted SSE string
    """
    # Escape the token for JSON
    escaped = json.dumps(token)
    return f"event: token\ndata: {escaped}\n\n"


def format_sse_status(status: str) -> str:
    """
    Formats a status update event.
    
    Args:
        status: Status message
        
    Returns:
        Formatted SSE string
    """
    return f'event: status\ndata: {json.dumps({"message": status})}\n\n'


async def create_sse_response(
    generator: AsyncGenerator[dict, None],
    include_heartbeat: bool = True,
    heartbeat_interval: float = 15.0
) -> AsyncGenerator[str, None]:
    """
    Wraps an async generator to produce SSE-formatted strings.
    Optionally includes heartbeat pings to keep connection alive.
    
    Args:
        generator: Async generator yielding event dicts
        include_heartbeat: Whether to send periodic pings
        heartbeat_interval: Seconds between heartbeats
        
    Yields:
        SSE-formatted event strings
    """
    # Send initial connected event
    yield format_sse_event(StreamingEventType.CONNECTED, {"status": "connected"})
    
    event_count = 0
    last_heartbeat = asyncio.get_event_loop().time()
    
    try:
        async for event in generator:
            event_count += 1
            event_type = event.get("event", "message")
            data = event.get("data", "")
            
            # Convert event type string to enum if possible
            try:
                event_enum = StreamingEventType(event_type)
            except ValueError:
                event_enum = event_type
            
            # Use optimized formatting for tokens
            if event_type == "token":
                yield format_sse_token(data)
            else:
                yield format_sse_event(event_enum, data, event_id=str(event_count))
            
            # Check for heartbeat
            if include_heartbeat:
                current_time = asyncio.get_event_loop().time()
                if current_time - last_heartbeat > heartbeat_interval:
                    yield format_sse_event(StreamingEventType.PING, {"time": current_time})
                    last_heartbeat = current_time
            
            # Small delay to prevent overwhelming the client
            if event_type == "token":
                await asyncio.sleep(settings.stream_delay_ms / 1000)
                
    except Exception as e:
        logger.error(f"Streaming error: {e}")
        yield format_sse_event(StreamingEventType.ERROR, {"error": str(e)})


async def stream_with_progress(
    generator: AsyncGenerator[str, None],
    total_steps: int,
    step_callback: Optional[callable] = None
) -> AsyncGenerator[str, None]:
    """
    Wraps a token generator to add progress tracking.
    
    Args:
        generator: Token generator
        total_steps: Total number of expected steps
        step_callback: Optional callback for step completion
        
    Yields:
        SSE-formatted strings with progress
    """
    current_step = 0
    
    async for token in generator:
        yield token
        
        # Check for step markers (customize based on your needs)
        if "." in token or "\n\n" in token:
            current_step += 1
            progress = min(current_step / total_steps, 1.0)
            yield format_sse_event(
                StreamingEventType.PROGRESS,
                {"progress": progress, "step": current_step}
            )
            
            if step_callback:
                await step_callback(current_step, progress)


class StreamBuffer:
    """
    Buffer for accumulating streaming tokens.
    Useful for collecting the complete response while streaming.
    """
    
    def __init__(self):
        self.buffer = ""
        self.tokens: list[str] = []
        self.is_complete = False
    
    def add_token(self, token: str) -> None:
        """Add a token to the buffer."""
        self.buffer += token
        self.tokens.append(token)
    
    def get_content(self) -> str:
        """Get the accumulated content."""
        return self.buffer
    
    def mark_complete(self) -> None:
        """Mark the stream as complete."""
        self.is_complete = True
    
    def clear(self) -> None:
        """Clear the buffer."""
        self.buffer = ""
        self.tokens = []
        self.is_complete = False


def parse_sse_event(event_string: str) -> dict:
    """
    Parses an SSE event string back into a dictionary.
    Useful for testing and client-side parsing.
    
    Args:
        event_string: Raw SSE event string
        
    Returns:
        Parsed event dict with 'event', 'data', 'id' keys
    """
    result = {"event": "message", "data": None, "id": None}
    
    for line in event_string.strip().split("\n"):
        if line.startswith("event:"):
            result["event"] = line[6:].strip()
        elif line.startswith("data:"):
            data_str = line[5:].strip()
            try:
                result["data"] = json.loads(data_str)
            except json.JSONDecodeError:
                result["data"] = data_str
        elif line.startswith("id:"):
            result["id"] = line[3:].strip()
    
    return result
