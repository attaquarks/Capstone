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
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from dotenv import load_dotenv

from src.core.llm_factory import build_llm
from src.core.tools import ALL_TOOLS, generate_procurement_email
from src.paths import CHECKPOINT_DB_PATH, ensure_runtime_dirs

import langgraph.checkpoint.sqlite.aio as sqlite_aio

load_dotenv()
ensure_runtime_dirs()

DB_PATH = str(CHECKPOINT_DB_PATH)


class HITLState(TypedDict):
    """State with HITL support."""
    messages: Annotated[list[BaseMessage], add_messages]
    pending_approval: bool
    human_edit: str


def get_llm():
    """Return the agent LLM via the pluggable factory (Gemini or Groq)."""
    return build_llm(role="agent", temperature=0.1).bind_tools(ALL_TOOLS)


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
    """Execute the action after human approval, applying any human edits to tool arguments."""
    last_ai_message = None
    for msg in reversed(state["messages"]):
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            last_ai_message = msg
            break

    if not last_ai_message:
        return {"messages": []}

    # Apply human edits to tool call arguments if provided
    human_edit = state.get("human_edit", "")
    if human_edit and last_ai_message.tool_calls:
        import copy
        edited_message = copy.deepcopy(last_ai_message)
        for tc in edited_message.tool_calls:
            if tc["name"] == "generate_procurement_email":
                # Parse edit string in format "field=value" or direct text replacement
                if "=" in human_edit:
                    field, value = human_edit.split("=", 1)
                    field = field.strip()
                    value = value.strip()
                    tc["args"][field] = value
                else:
                    # Treat as a note to append to the urgency field
                    tc["args"]["urgency"] = human_edit
        # Replace the last AI message with the edited version in state
        messages = list(state["messages"])
        for i in range(len(messages) - 1, -1, -1):
            if hasattr(messages[i], "tool_calls") and messages[i].tool_calls:
                messages[i] = edited_message
                break
        tool_node = ToolNode(ALL_TOOLS)
        result = tool_node.invoke({"messages": messages})
        return result

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

    async with sqlite_aio.AsyncSqliteSaver.from_conn_string(DB_PATH) as checkpointer:
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

    edit_thread_id = "hitl-edit-demo-001"
    edit_config = {"configurable": {"thread_id": edit_thread_id}}

    async with sqlite_aio.AsyncSqliteSaver.from_conn_string(DB_PATH) as checkpointer:
        graph = build_hitl_graph(checkpointer)

        # Step 1: User requests an email (will trigger approval gate)
        print("\n--- Step 1: User requests email ---")
        edit_query = "Generate a procurement email to SteelMax Corp for 200 Steel Plates with normal urgency."
        print(f"User: {edit_query}")

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content=edit_query)], "pending_approval": False, "human_edit": ""},
            config=edit_config,
        )
        print("[SYSTEM] Graph paused at approval gate - human can now edit")

        # Step 2: Human edits the urgency before approving
        print("\n--- Step 2: Human edits the tool arguments ---")
        print("Human edit: urgency=critical")
        print("(Changing urgency from 'normal' to 'critical' before execution)")

        # Update the state with human's edit and resume
        current_state = await graph.aget_state(edit_config)
        await graph.aupdate_state(
            edit_config,
            {"human_edit": "urgency=critical"},
        )

        # Resume execution with the edited state
        result = await graph.ainvoke(None, config=edit_config)

        print("\n--- Final Output (with human edit applied) ---")
        final_msg = result["messages"][-1]
        print(final_msg.content if hasattr(final_msg, "content") else str(final_msg))
        print("\nState editing verified: human modified urgency from 'normal' to 'critical' before execution.")


if __name__ == "__main__":
    asyncio.run(run_hitl_demo())
