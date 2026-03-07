"""
Lab 3: The Reasoning Loop - LangGraph ReAct Agent
Implements a StateGraph with Agent Node, Tool Node, and Conditional Router.

The agent uses a ReAct (Reason + Act) loop:
1. Agent Node: LLM decides what to do next
2. Router: Checks if LLM wants to use a tool or give final answer
3. Tool Node: Executes the requested tool
4. Loop back to Agent Node with tool results
"""

import os
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from dotenv import load_dotenv

from tools import ALL_TOOLS

load_dotenv()

# --- State Definition ---

class AgentState(TypedDict):
    """State schema for the Supply Chain Intelligence Agent.
    Stores the full message history (thoughts and actions)."""
    messages: Annotated[list[BaseMessage], add_messages]


# --- System Prompt ---

SYSTEM_PROMPT = """You are a Supply Chain Intelligence Assistant. Your role is to help 
supply chain managers make data-driven decisions about inventory, procurement, and logistics.

You have access to the following tools:
- query_inventory: Check current stock levels for products
- calculate_risk_score: Compute reorder risk based on stock, lead time, and supplier reliability
- search_suppliers: Query the knowledge base for supplier information
- generate_procurement_email: Draft professional procurement communications
- get_product_specs: Retrieve technical specifications for products

Guidelines:
1. Always use tools to get real data before making recommendations.
2. When asked about inventory, first query the inventory to get current numbers.
3. When assessing risk, use the calculate_risk_score tool for accurate scoring.
4. Provide clear, actionable recommendations based on the data.
5. Never fabricate inventory numbers or supplier details - always use the tools.
6. If you cannot find the requested information, say so clearly.
7. For procurement emails, gather product and supplier details first, then generate the email.
"""


# --- LLM Setup ---

def get_llm():
    """Initialize the Google Gemini LLM with tool binding."""
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        google_api_key=os.getenv("GOOGLE_API_KEY"),
        temperature=0.1,
        convert_system_message_to_human=True,
    )
    return llm.bind_tools(ALL_TOOLS)


# --- Node Functions ---

def agent_node(state: AgentState) -> dict:
    """The Agent Node: Takes current state, calls the LLM, returns the next step.
    The LLM will either request a tool call or provide a final answer."""
    llm = get_llm()
    messages = state["messages"]

    # Ensure system prompt is present
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + list(messages)

    response = llm.invoke(messages)
    return {"messages": [response]}


# --- Conditional Router ---

def should_continue(state: AgentState) -> str:
    """The Router: Checks the LLM's last message to determine the next step.
    - If the LLM generated tool calls -> route to 'tools' node
    - If the LLM generated a final answer -> route to END
    """
    last_message = state["messages"][-1]

    # Check if the LLM wants to call tools
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"

    # Otherwise, the LLM has provided a final answer
    return "end"


# --- Graph Construction ---

def build_graph() -> StateGraph:
    """Build and compile the LangGraph ReAct agent."""
    # Create the tool node with all available tools
    tool_node = ToolNode(ALL_TOOLS)

    # Build the state graph
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tool_node)

    # Set the entry point
    workflow.set_entry_point("agent")

    # Add conditional edge from agent: either go to tools or end
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            "end": END,
        },
    )

    # After tools execute, always go back to agent
    workflow.add_edge("tools", "agent")

    # Compile the graph
    graph = workflow.compile()
    return graph


# --- Main Execution ---

if __name__ == "__main__":
    print("=" * 60)
    print("Supply Chain Intelligence Agent - ReAct Loop")
    print("=" * 60)

    graph = build_graph()

    # Test queries
    test_queries = [
        "What is the current inventory status of the Hydraulic Pump HP-300?",
        "Calculate the reorder risk for PRD-005 (Conveyor Belt).",
        "Find me reliable suppliers for bearings.",
    ]

    for query in test_queries:
        print(f"\n{'='*60}")
        print(f"USER: {query}")
        print("=" * 60)

        result = graph.invoke({
            "messages": [HumanMessage(content=query)]
        })

        # Print the final response
        final_message = result["messages"][-1]
        print(f"\nAGENT: {final_message.content}")
        print("-" * 60)
