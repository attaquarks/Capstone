"""
Lab 8: The API Layer - Pydantic Schema Definitions
Defines the contract between the client and the Supply Chain Intelligence Agent.
"""

from typing import Optional
from pydantic import BaseModel, Field
from uuid import uuid4


class ChatRequest(BaseModel):
    """Request model for the /chat and /stream endpoints."""
    message: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="The user's message to the agent.",
        examples=["What is the current stock of PRD-001?"],
    )
    thread_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique thread/session ID for conversation persistence. "
                    "Reuse the same thread_id to continue a conversation.",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )


class ChatResponse(BaseModel):
    """Response model for the /chat endpoint."""
    answer: str = Field(
        ...,
        description="The agent's final response to the user's query.",
    )
    thread_id: str = Field(
        ...,
        description="The thread ID for this conversation (use to continue the session).",
    )
    status: str = Field(
        default="success",
        description="Status of the request: 'success', 'error', or 'blocked'.",
    )
    tool_calls_made: list[str] = Field(
        default_factory=list,
        description="List of tool names the agent invoked during this request.",
    )
    message_count: int = Field(
        default=0,
        description="Total number of messages in this conversation thread.",
    )


class StreamEvent(BaseModel):
    """Model for individual Server-Sent Events in the /stream endpoint."""
    event: str = Field(
        ...,
        description="Event type: 'agent_thinking', 'tool_call', 'token', 'done', 'error'.",
    )
    data: str = Field(
        ...,
        description="Event payload: token text, tool name, or status message.",
    )
    node: Optional[str] = Field(
        default=None,
        description="Which graph node generated this event.",
    )


class HealthResponse(BaseModel):
    """Response model for the /health endpoint."""
    status: str = Field(default="healthy")
    version: str = Field(default="1.0.0")
    agent_ready: bool = Field(default=True)
