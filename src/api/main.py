"""
Lab 8: The API Layer (FastAPI & LangServe)
FastAPI application exposing the Supply Chain Intelligence Agent via REST API.

Endpoints:
  POST /chat    - Synchronous chat with the agent
  POST /stream  - Server-Sent Events streaming response
  GET  /health  - Health check
"""

import os
import json
import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing import Annotated, TypedDict
from dotenv import load_dotenv

from src.core.llm_factory import build_llm
from src.api.schema import ChatRequest, ChatResponse, HealthResponse
from src.core.tools import ALL_TOOLS
from src.core.graph import SYSTEM_PROMPT
from src.core.guardrails_config import check_guardrails, sanitize_output, SafetyVerdict
from src.paths import CHECKPOINT_DB_PATH, ensure_runtime_dirs

load_dotenv()

# --- Global State ---
# Use the centralised path helper. ``CHECKPOINT_DB_PATH`` env var still wins,
# because the paths module reads it; here we just resolve to a concrete string.
ensure_runtime_dirs()
DB_PATH = str(CHECKPOINT_DB_PATH)
checkpointer = None
compiled_graph = None


# --- Agent State ---

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


# --- Graph Builder ---

def get_llm():
    """Initialize the agent's LLM. Mirrors graph.get_llm() so both the
    interactive CLI (`python graph.py`) and the production FastAPI entrypoint
    use the same provider/model selection logic (Google Gemini by default,
    Groq when ``GROQ_API_KEY`` / ``LLM_PROVIDER=groq`` is set)."""
    return build_llm(role="agent", temperature=0.1).bind_tools(ALL_TOOLS)


def agent_node(state: AgentState) -> dict:
    llm = get_llm()
    messages = state["messages"]
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + list(messages)
    response = llm.invoke(messages)
    return {"messages": [response]}


def should_continue(state: AgentState) -> str:
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return "end"


def build_graph_with_checkpointer(cp):
    tool_node = ToolNode(ALL_TOOLS)
    workflow = StateGraph(AgentState)
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tool_node)
    workflow.set_entry_point("agent")
    workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", "end": END})
    workflow.add_edge("tools", "agent")
    return workflow.compile(checkpointer=cp)


# --- FastAPI Lifespan ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the checkpointer at app startup (not per-request)."""
    global checkpointer, compiled_graph
    checkpointer = AsyncSqliteSaver.from_conn_string(DB_PATH)
    async with checkpointer as cp:
        compiled_graph = build_graph_with_checkpointer(cp)
        yield
    checkpointer = None
    compiled_graph = None


# --- FastAPI App ---

app = FastAPI(
    title="Supply Chain Intelligence Agent API",
    description="REST API for the Supply Chain Intelligence Agent powered by LangGraph and Gemini.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Endpoints ---

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        agent_ready=compiled_graph is not None,
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Synchronous chat endpoint. Sends the message to the agent and waits for the full response."""
    if compiled_graph is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    # Guardrail check
    verdict, reason = check_guardrails(request.message)
    if verdict == SafetyVerdict.UNSAFE:
        return ChatResponse(
            answer=f"Request blocked by security guardrails: {reason}",
            thread_id=request.thread_id,
            status="blocked",
        )

    # Run the agent with thread_id for persistence
    config = {"configurable": {"thread_id": request.thread_id}}

    try:
        result = await compiled_graph.ainvoke(
            {"messages": [HumanMessage(content=request.message)]},
            config=config,
        )

        # Extract final answer
        final_message = result["messages"][-1]
        answer = final_message.content if hasattr(final_message, "content") else str(final_message)
        answer = sanitize_output(answer)

        # Collect tool calls made
        tool_calls = []
        for msg in result["messages"]:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                tool_calls.extend([tc["name"] for tc in msg.tool_calls])

        return ChatResponse(
            answer=answer,
            thread_id=request.thread_id,
            status="success",
            tool_calls_made=tool_calls,
            message_count=len(result["messages"]),
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")


@app.post("/stream")
async def stream(request: ChatRequest):
    """Streaming endpoint using Server-Sent Events (SSE).
    Yields chunks of the response as the agent processes the query."""
    if compiled_graph is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    # Guardrail check
    verdict, reason = check_guardrails(request.message)
    if verdict == SafetyVerdict.UNSAFE:
        async def blocked_stream():
            event = {"event": "error", "data": f"Blocked: {reason}", "node": "guardrail"}
            yield f"data: {json.dumps(event)}\n\n"
        return StreamingResponse(blocked_stream(), media_type="text/event-stream")

    config = {"configurable": {"thread_id": request.thread_id}}

    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE events from the agent's processing."""
        try:
            async for event in compiled_graph.astream_events(
                {"messages": [HumanMessage(content=request.message)]},
                config=config,
                version="v2",
            ):
                kind = event.get("event", "")

                if kind == "on_chat_model_start":
                    sse = {"event": "agent_thinking", "data": "Processing...", "node": "agent"}
                    yield f"data: {json.dumps(sse)}\n\n"

                elif kind == "on_chat_model_stream":
                    chunk = event.get("data", {})
                    if hasattr(chunk, "content") and chunk.content:
                        sse = {"event": "token", "data": chunk.content, "node": "agent"}
                        yield f"data: {json.dumps(sse)}\n\n"

                elif kind == "on_tool_start":
                    tool_name = event.get("name", "unknown")
                    sse = {"event": "tool_call", "data": tool_name, "node": "tools"}
                    yield f"data: {json.dumps(sse)}\n\n"

                elif kind == "on_tool_end":
                    sse = {"event": "tool_result", "data": "Tool completed", "node": "tools"}
                    yield f"data: {json.dumps(sse)}\n\n"

            sse = {"event": "done", "data": "Stream complete", "node": None}
            yield f"data: {json.dumps(sse)}\n\n"

        except Exception as e:
            sse = {"event": "error", "data": str(e), "node": None}
            yield f"data: {json.dumps(sse)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
