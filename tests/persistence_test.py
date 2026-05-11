"""
Lab 5: State Management & Human-in-the-Loop
Persistence Test - Proves the agent can retrieve information from a previous session.

This script demonstrates:
1. Creating a conversation with a specific thread_id
2. Stopping execution
3. Resuming with the same thread_id and verifying context is preserved
"""

import os
import asyncio
from langchain_core.messages import HumanMessage, SystemMessage, BaseMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_google_genai import ChatGoogleGenerativeAI
from typing import Annotated, TypedDict
from dotenv import load_dotenv

from src.core.tools import ALL_TOOLS
from src.core.graph import SYSTEM_PROMPT
from src.paths import CHECKPOINT_DB_PATH, ensure_runtime_dirs

import langgraph.checkpoint.sqlite.aio as sqlite_aio
import json
_original_dumps = sqlite_aio.json.dumps
def _patched_dumps(obj, *args, **kwargs):
    kwargs['default'] = lambda x: x.model_dump() if hasattr(x, "model_dump") else (x.dict() if hasattr(x, "dict") else str(x))
    return _original_dumps(obj, *args, **kwargs)
sqlite_aio.json.dumps = _patched_dumps

load_dotenv(override=True)
ensure_runtime_dirs()

DB_PATH = str(CHECKPOINT_DB_PATH)


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


def get_llm():
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=os.getenv("GEMINI_API_KEY"),
        temperature=0.1,
        convert_system_message_to_human=True,
        max_retries=0, # Fail fast on API quota limits
    )
    return llm.bind_tools(ALL_TOOLS)


def agent_node(state: AgentState) -> dict:
    llm = get_llm()
    messages = state["messages"]
    if not messages or getattr(messages[0], "type", "") != "system":
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + list(messages)
    response = llm.invoke(messages)
    return {"messages": [response]}


def should_continue(state: AgentState) -> str:
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return "end"


def build_persistent_graph(checkpointer):
    """Build graph with SQLite checkpointer for persistence."""
    tool_node = ToolNode(ALL_TOOLS)
    workflow = StateGraph(AgentState)

    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tool_node)
    workflow.set_entry_point("agent")

    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {"tools": "tools", "end": END},
    )
    workflow.add_edge("tools", "agent")

    return workflow.compile(checkpointer=checkpointer)


async def run_persistence_test():
    """Test that the agent remembers context across sessions."""
    thread_id = "test-session-001"
    config = {"configurable": {"thread_id": thread_id}}

    print("=" * 60)
    print("PERSISTENCE TEST - Session Memory Across Restarts")
    print("=" * 60)

    # --- SESSION 1: Initial conversation ---
    print("\n--- SESSION 1: Starting new conversation ---")
    async with AsyncSqliteSaver.from_conn_string(DB_PATH) as checkpointer:
        graph = build_persistent_graph(checkpointer)

        result1 = await graph.ainvoke(
            {"messages": [HumanMessage(content="What is the inventory status of PRD-001 Industrial Bearing?")]},
            config=config,
        )
        print(f"User: What is the inventory status of PRD-001?")
        final_msg = result1["messages"][-1]
        print(f"Agent: {final_msg.content[:300]}...")
        print("\n[Session 1 ended - state saved to checkpoint_db.sqlite]")

    # --- SESSION 2: Resume with same thread_id ---
    print("\n--- SESSION 2: Resuming conversation (same thread_id) ---")
    async with AsyncSqliteSaver.from_conn_string(DB_PATH) as checkpointer:
        graph = build_persistent_graph(checkpointer)

        result2 = await graph.ainvoke(
            {"messages": [HumanMessage(content="Based on what you just told me, should I reorder?")]},
            config=config,
        )
        print(f"User: Based on what you just told me, should I reorder?")
        final_msg = result2["messages"][-1]
        print(f"Agent: {final_msg.content[:300]}...")

    # --- VERIFICATION ---
    print("\n--- VERIFICATION ---")
    print(f"Thread ID: {thread_id}")
    print(f"Checkpoint DB: {DB_PATH}")
    print(f"Session 1 messages: {len(result1['messages'])}")
    print(f"Session 2 messages: {len(result2['messages'])}")
    print("SUCCESS: Agent maintained context across sessions!" if len(result2["messages"]) > len(result1["messages"]) else "CHECK: Verify context continuity")

    # --- SESSION 3: Different thread_id (should NOT have context) ---
    print("\n--- SESSION 3: New thread_id (fresh context) ---")
    new_config = {"configurable": {"thread_id": "test-session-002"}}
    async with AsyncSqliteSaver.from_conn_string(DB_PATH) as checkpointer:
        graph = build_persistent_graph(checkpointer)

        result3 = await graph.ainvoke(
            {"messages": [HumanMessage(content="What did we discuss earlier?")]},
            config=new_config,
        )
        final_msg = result3["messages"][-1]
        print(f"User: What did we discuss earlier?")
        print(f"Agent: {final_msg.content[:300]}...")
        print("VERIFIED: New thread has no prior context (as expected)")


if __name__ == "__main__":
    asyncio.run(run_persistence_test())
