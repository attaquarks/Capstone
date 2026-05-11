"""
Lab 4: Multi-Agent Orchestration
Implements a team of specialized agents (Researcher + Analyst) with handover logic.

Architecture:
  User Query -> Researcher Agent (gathers data) -> Handover -> Analyst Agent (synthesizes) -> Final Answer
"""

import os
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from dotenv import load_dotenv

from src.core.tools import (
    query_inventory,
    calculate_risk_score,
    search_suppliers,
    get_product_specs,
    generate_procurement_email,
)
from src.core.agents_config import AGENT_PERSONAS

load_dotenv()


# --- State Definition ---

class MultiAgentState(TypedDict):
    """State for multi-agent orchestration. Tracks messages and current agent."""
    messages: Annotated[list[BaseMessage], add_messages]
    current_agent: str
    handover_count: int


# --- Tool Sets ---

RESEARCHER_TOOLS = [query_inventory, calculate_risk_score, search_suppliers, get_product_specs]
ANALYST_TOOLS = [generate_procurement_email]


# --- LLM Factory ---

def get_agent_llm(agent_name: str):
    """Create an LLM bound to the specific agent's tools."""
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=os.getenv("GEMINI_API_KEY"),
        temperature=0.1,
        convert_system_message_to_human=True,
    )

    if agent_name == "researcher":
        return llm.bind_tools(RESEARCHER_TOOLS)
    elif agent_name == "analyst":
        return llm.bind_tools(ANALYST_TOOLS)
    return llm


# --- Node Functions ---

def researcher_node(state: MultiAgentState) -> dict:
    """Researcher Agent: Gathers data using inventory, supplier, and specs tools."""
    llm = get_agent_llm("researcher")
    persona = AGENT_PERSONAS["researcher"]

    messages = list(state["messages"])
    sys_msg = SystemMessage(content=persona["system_prompt"])

    response = llm.invoke([sys_msg] + messages)
    return {
        "messages": [response],
        "current_agent": "researcher",
        "handover_count": state.get("handover_count", 0),
    }


def analyst_node(state: MultiAgentState) -> dict:
    """Analyst Agent: Synthesizes research data into professional outputs."""
    llm = get_agent_llm("analyst")
    persona = AGENT_PERSONAS["analyst"]

    messages = list(state["messages"])
    sys_msg = SystemMessage(content=persona["system_prompt"])

    response = llm.invoke([sys_msg] + messages)
    return {
        "messages": [response],
        "current_agent": "analyst",
        "handover_count": state.get("handover_count", 0) + 1,
    }


# --- Routing Logic ---

def researcher_router(state: MultiAgentState) -> str:
    """Route from Researcher: tools, handover to analyst, or end."""
    last_message = state["messages"][-1]

    # If researcher wants to use tools
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "researcher_tools"

    # Research is complete, hand over to analyst
    return "analyst"


def analyst_router(state: MultiAgentState) -> str:
    """Route from Analyst: tools or end."""
    last_message = state["messages"][-1]

    # If analyst wants to use tools (e.g., generate email)
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "analyst_tools"

    # Otherwise, analyst is done
    return "end"


# --- Graph Construction ---

def build_multi_agent_graph() -> StateGraph:
    """Build and compile the multi-agent LangGraph."""
    researcher_tool_node = ToolNode(RESEARCHER_TOOLS)
    analyst_tool_node = ToolNode(ANALYST_TOOLS)

    workflow = StateGraph(MultiAgentState)

    # Add nodes
    workflow.add_node("researcher", researcher_node)
    workflow.add_node("researcher_tools", researcher_tool_node)
    workflow.add_node("analyst", analyst_node)
    workflow.add_node("analyst_tools", analyst_tool_node)

    # Entry point: always start with the researcher
    workflow.set_entry_point("researcher")

    # Researcher routing
    workflow.add_conditional_edges(
        "researcher",
        researcher_router,
        {
            "researcher_tools": "researcher_tools",
            "analyst": "analyst",
        },
    )
    workflow.add_edge("researcher_tools", "researcher")

    # Analyst routing
    workflow.add_conditional_edges(
        "analyst",
        analyst_router,
        {
            "analyst_tools": "analyst_tools",
            "end": END,
        },
    )
    workflow.add_edge("analyst_tools", "analyst")

    graph = workflow.compile()
    return graph


# --- Main Execution ---

if __name__ == "__main__":
    print("=" * 60)
    print("Multi-Agent Supply Chain Intelligence System")
    print("=" * 60)

    graph = build_multi_agent_graph()

    # Test case: Forces cooperation between agents
    test_query = (
        "Research the inventory status and risk level for Conveyor Belt 500mm (PRD-005), "
        "find the supplier details, and then write a professional procurement email "
        "requesting a quote for 50 units with high urgency."
    )

    print(f"\nUSER: {test_query}\n")
    print("-" * 60)

    result = graph.invoke({
        "messages": [HumanMessage(content=test_query)],
        "current_agent": "researcher",
        "handover_count": 0,
    })

    # Print trace showing agent collaboration
    print("\n=== COLLABORATION TRACE ===")
    for i, msg in enumerate(result["messages"]):
        role = msg.__class__.__name__
        agent = "Researcher" if i < len(result["messages"]) // 2 else "Analyst"
        content_preview = str(msg.content)[:200] if hasattr(msg, "content") else "N/A"
        print(f"\n[{i+1}] {role} ({agent}): {content_preview}...")

    print("\n=== FINAL OUTPUT ===")
    final = result["messages"][-1]
    print(final.content if hasattr(final, "content") else str(final))
