"""
Lab 11: Drift Monitoring & Feedback Loops
Streamlit Interactive UI with feedback mechanisms.

Features:
- Chat interface for the Supply Chain Intelligence Agent
- Thumbs up/down feedback after every response
- Optional comment for negative feedback
- Session state linked to thread_id and message_id
- Persistent feedback logging to SQLite
"""

import os
import uuid
import sqlite3
import json
from datetime import datetime

import streamlit as st
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing import Annotated, TypedDict
from dotenv import load_dotenv

load_dotenv()

# --- Configuration ---
DB_PATH = os.path.join(os.path.dirname(__file__), "feedback_log.db")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


# --- Feedback Database ---

def init_feedback_db():
    """Initialize the feedback logging database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS feedback_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            thread_id TEXT NOT NULL,
            message_id TEXT NOT NULL,
            user_input TEXT NOT NULL,
            agent_response TEXT NOT NULL,
            feedback_score INTEGER DEFAULT 0,
            optional_comment TEXT DEFAULT '',
            category TEXT DEFAULT 'general'
        )
    """)
    conn.commit()
    conn.close()


def log_interaction(thread_id: str, message_id: str, user_input: str,
                    agent_response: str, feedback_score: int = 0,
                    optional_comment: str = "", category: str = "general"):
    """Log an interaction with feedback to the database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO feedback_log 
        (timestamp, thread_id, message_id, user_input, agent_response, 
         feedback_score, optional_comment, category)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.now().isoformat(),
        thread_id,
        message_id,
        user_input,
        agent_response,
        feedback_score,
        optional_comment,
        category,
    ))
    conn.commit()
    conn.close()


def update_feedback(message_id: str, feedback_score: int, optional_comment: str = ""):
    """Update feedback for a specific message."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE feedback_log 
        SET feedback_score = ?, optional_comment = ?
        WHERE message_id = ?
    """, (feedback_score, optional_comment, message_id))
    conn.commit()
    conn.close()


def get_feedback_stats():
    """Get summary statistics from the feedback log."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM feedback_log")
    total = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM feedback_log WHERE feedback_score = 1")
    positive = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM feedback_log WHERE feedback_score = -1")
    negative = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM feedback_log WHERE feedback_score = 0")
    neutral = cursor.fetchone()[0]
    conn.close()
    return {"total": total, "positive": positive, "negative": negative, "neutral": neutral}


# --- Agent Setup (Simplified for Streamlit) ---

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


def get_agent_response(user_message: str) -> str:
    """Get a response from the agent."""
    try:
        from tools import ALL_TOOLS
        from graph import SYSTEM_PROMPT

        llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            google_api_key=GEMINI_API_KEY,
            temperature=0.1,
            convert_system_message_to_human=True,
        )
        llm_with_tools = llm.bind_tools(ALL_TOOLS)

        tool_node = ToolNode(ALL_TOOLS)

        def agent_node(state):
            messages = [SystemMessage(content=SYSTEM_PROMPT)] + list(state["messages"])
            response = llm_with_tools.invoke(messages)
            return {"messages": [response]}

        def should_continue(state):
            last = state["messages"][-1]
            if hasattr(last, "tool_calls") and last.tool_calls:
                return "tools"
            return "end"

        workflow = StateGraph(AgentState)
        workflow.add_node("agent", agent_node)
        workflow.add_node("tools", tool_node)
        workflow.set_entry_point("agent")
        workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", "end": END})
        workflow.add_edge("tools", "agent")
        graph = workflow.compile()

        result = graph.invoke({"messages": [HumanMessage(content=user_message)]})
        final = result["messages"][-1]
        return final.content if hasattr(final, "content") else str(final)

    except Exception as e:
        return f"Agent error: {str(e)}. Please ensure GEMINI_API_KEY is set."


# --- Streamlit UI ---

def main():
    st.set_page_config(
        page_title="Supply Chain Intelligence Agent",
        page_icon="🏭",
        layout="wide",
    )

    st.title("Supply Chain Intelligence Agent")
    st.caption("Powered by LangGraph + Gemini | Lab 11: Drift Monitoring & Feedback")

    # Initialize database
    init_feedback_db()

    # Session state initialization
    if "thread_id" not in st.session_state:
        st.session_state.thread_id = str(uuid.uuid4())
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "feedback_given" not in st.session_state:
        st.session_state.feedback_given = {}

    # Sidebar: Feedback Dashboard
    with st.sidebar:
        st.header("Feedback Dashboard")
        stats = get_feedback_stats()
        col1, col2, col3 = st.columns(3)
        col1.metric("Total", stats["total"])
        col2.metric("Positive", stats["positive"])
        col3.metric("Negative", stats["negative"])

        if stats["total"] > 0:
            satisfaction = stats["positive"] / stats["total"] * 100
            st.progress(satisfaction / 100)
            st.caption(f"Satisfaction Rate: {satisfaction:.1f}%")

        st.divider()
        st.subheader("Session Info")
        st.text(f"Thread: {st.session_state.thread_id[:8]}...")

        if st.button("New Conversation"):
            st.session_state.thread_id = str(uuid.uuid4())
            st.session_state.messages = []
            st.session_state.feedback_given = {}
            st.rerun()

        st.divider()
        st.subheader("Sample Queries")
        sample_queries = [
            "What is the stock of PRD-001?",
            "Calculate risk for PRD-005",
            "Find German suppliers",
            "Draft email to BearingTech for 500 bearings",
        ]
        for q in sample_queries:
            if st.button(q, key=f"sample_{q[:20]}"):
                st.session_state.pending_query = q
                st.rerun()

    # Display chat history
    for i, msg in enumerate(st.session_state.messages):
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

            # Feedback buttons for assistant messages
            if msg["role"] == "assistant":
                msg_id = msg.get("message_id", f"msg-{i}")
                if msg_id not in st.session_state.feedback_given:
                    col1, col2, col3 = st.columns([1, 1, 8])
                    with col1:
                        if st.button("👍", key=f"up_{msg_id}"):
                            update_feedback(msg_id, 1)
                            st.session_state.feedback_given[msg_id] = 1
                            st.rerun()
                    with col2:
                        if st.button("👎", key=f"down_{msg_id}"):
                            st.session_state.feedback_given[msg_id] = -1
                            st.rerun()

                    # If thumbs down, show comment box
                    if st.session_state.feedback_given.get(msg_id) == -1:
                        comment = st.text_input(
                            "What went wrong?",
                            key=f"comment_{msg_id}",
                        )
                        if st.button("Submit Feedback", key=f"submit_{msg_id}"):
                            update_feedback(msg_id, -1, comment)
                            st.success("Feedback recorded. Thank you!")
                else:
                    score = st.session_state.feedback_given[msg_id]
                    st.caption(f"{'👍 Helpful' if score == 1 else '👎 Needs improvement'}")

    # Handle pending query from sidebar
    if "pending_query" in st.session_state:
        user_input = st.session_state.pending_query
        del st.session_state.pending_query
    else:
        user_input = st.chat_input("Ask about inventory, suppliers, risk, or procurement...")

    # Process user input
    if user_input:
        message_id = str(uuid.uuid4())

        # Add user message
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        # Get agent response
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                response = get_agent_response(user_input)
            st.markdown(response)

        # Add assistant message with message_id
        st.session_state.messages.append({
            "role": "assistant",
            "content": response,
            "message_id": message_id,
        })

        # Log interaction to feedback database
        log_interaction(
            thread_id=st.session_state.thread_id,
            message_id=message_id,
            user_input=user_input,
            agent_response=response,
        )

        st.rerun()


if __name__ == "__main__":
    main()
