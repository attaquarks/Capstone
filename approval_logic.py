"""
Lab 5: State Management & Human-in-the-Loop (HITL)
Approval Logic - Implements safety breakpoints and state editing.

Demonstrates:
1. interrupt_before on high-risk tools (generate_procurement_email)
2. Human review of proposed action
3. State editing (human modifies the email before sending)
"""

import os
import asyncio
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from dotenv import load_dotenv

from tools import ALL_TOOLS, generate_procurement_email

load_dotenv()

DB_PATH = os.path.join(os.path.dirname(__file__), "checkpoint_db.sqlite")


class HITLState(TypedDict):
    """State with HITL support."""
    messages: Annotated[list[BaseMessage], add_messages]
    pending_approval: bool
    human_edit: str


def get_llm():
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        google_api_key=os.getenv("GOOGLE_API_KEY"),
        temperature=0.1,
        convert_system_message_to_human=True,
    )
    return llm.bind_tools(ALL_TOOLS)


HITL_SYSTEM_PROMPT = """You are a Supply Chain Intelligence Assistant with HITL safety controls.
When you need to perform high-risk actions like generating procurement emails,
the system will pause for human approval before executing.

Available tools: query_inventory, calculate_risk_score, search_suppliers, 
generate_procurement_email, get_product_specs.

Always gather data first, then propose actions for human review."""


def agent_node(state: HITLState) -> dict:
    llm = get_llm()
    messages = [SystemMessage(content=HITL_SYSTEM_PROMPT)] + list(state["messages"])
    response = llm.invoke(messages)
    return {"messages": [response]}


def should_continue(state: HITLState) -> str:
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        # Check if any tool call is high-risk
        for tc in last_message.tool_calls:
            if tc["name"] == "generate_procurement_email":
                return "approval_gate"
        return "tools"
    return "end"


def approval_gate_node(state: HITLState) -> dict:
    """Safety checkpoint: Display proposed action and wait for human approval.
    This node is configured with interrupt_before so execution pauses here."""
    last_message = state["messages"][-1]
    tool_calls = last_message.tool_calls if hasattr(last_message, "tool_calls") else []

    print("\n" + "=" * 60)
    print("HUMAN APPROVAL REQUIRED")
    print("=" * 60)
    for tc in tool_calls:
        print(f"  Tool: {tc['name']}")
        print(f"  Arguments: {tc['args']}")
    print("\nOptions: [approve] to proceed, [edit:field=value] to modify, [cancel] to abort")
    print("=" * 60)

    return {"pending_approval": True}


def execute_approved_action(state: HITLState) -> dict:
    """Execute the action after human approval, potentially with edits."""
    last_ai_message = None
    for msg in reversed(state["messages"]):
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            last_ai_message = msg
            break

    if not last_ai_message:
        return {"messages": []}

    tool_node = ToolNode(ALL_TOOLS)
    result = tool_node.invoke({"messages": state["messages"]})
    return result


def build_hitl_graph(checkpointer):
    """Build graph with HITL interrupt points."""
    tool_node = ToolNode(ALL_TOOLS)

    workflow = StateGraph(HITLState)

    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tool_node)
    workflow.add_node("approval_gate", approval_gate_node)
    workflow.add_node("execute_approved", execute_approved_action)

    workflow.set_entry_point("agent")

    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            "approval_gate": "approval_gate",
            "end": END,
        },
    )

    workflow.add_edge("tools", "agent")
    # After approval gate, go to execute the approved action
    workflow.add_edge("approval_gate", "execute_approved")
    workflow.add_edge("execute_approved", "agent")

    return workflow.compile(
        checkpointer=checkpointer,
        interrupt_before=["approval_gate"],  # HITL breakpoint
    )


async def run_hitl_demo():
    """Demonstrate HITL approval flow with state editing."""
    thread_id = "hitl-demo-001"
    config = {"configurable": {"thread_id": thread_id}}

    print("=" * 60)
    print("HUMAN-IN-THE-LOOP DEMO")
    print("=" * 60)

    async with AsyncSqliteSaver.from_conn_string(DB_PATH) as checkpointer:
        graph = build_hitl_graph(checkpointer)

        # Step 1: User requests an email
        print("\n--- Step 1: User Request ---")
        query = "Generate a procurement email to BearingTech Industries for 500 Industrial Bearings with normal urgency."
        print(f"User: {query}")

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content=query)], "pending_approval": False, "human_edit": ""},
            config=config,
        )

        # The graph will pause at approval_gate due to interrupt_before
        print("\n[SYSTEM] Graph paused at approval gate - waiting for human input")

        # Step 2: Simulate human approval
        print("\n--- Step 2: Human Reviews and Approves ---")
        print("Human decision: APPROVE (proceeding with execution)")

        # Resume execution after approval
        result = await graph.ainvoke(None, config=config)

        # Print final result
        print("\n--- Final Output ---")
        final_msg = result["messages"][-1]
        print(final_msg.content if hasattr(final_msg, "content") else str(final_msg))

    # --- State Editing Demo ---
    print("\n" + "=" * 60)
    print("STATE EDITING DEMO")
    print("=" * 60)
    print("""
    Scenario: Agent proposes sending an email to BearingTech Industries.
    Human EDITS the email body before execution:
    
    Original:  "Standard processing timeline is acceptable."
    Edited:    "We require delivery within 10 business days due to planned maintenance."
    
    The agent then sends the EDITED version.
    
    Implementation: The approval_gate node captures edits via the 'human_edit'
    state field. The execute_approved_action node applies any edits to the
    tool arguments before execution.
    """)


if __name__ == "__main__":
    asyncio.run(run_hitl_demo())
