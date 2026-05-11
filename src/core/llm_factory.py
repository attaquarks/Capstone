"""Pluggable LLM factory.

The agent originally targeted Google Gemini exclusively. The free-tier daily
quota on a single Gemini key (20 RPD per model) is brittle for live demos and
local CI evaluations, so we add a portable second backend (Groq's hosted
Llama-3 / Mixtral / etc.) that can be selected at runtime via environment
variables. No code outside this module needs to know which provider is in use:
both backends expose the same `.invoke()` / `.bind_tools()` interface that
LangChain's `BaseChatModel` defines.

Selection rules (highest precedence first):

  1. `LLM_PROVIDER=groq`  ->  Groq
  2. `LLM_PROVIDER=google` (or `gemini`)  ->  Google Gemini
  3. `GROQ_API_KEY` is set  ->  Groq
  4. fallback  ->  Google Gemini

Per-provider model selection:

* Google: `AGENT_MODEL` (default `gemini-2.5-flash`) for the agent,
  `JUDGE_MODEL` (default `gemini-2.5-flash-lite`) for the eval judge.
* Groq:   `AGENT_MODEL` (default `llama-3.3-70b-versatile`) for the agent,
  `JUDGE_MODEL` (default `llama-3.1-8b-instant`) for the eval judge.

Per-provider credentials:

* Google: `GEMINI_API_KEY` or `GOOGLE_API_KEY`.
* Groq:   `GROQ_API_KEY`.
"""

from __future__ import annotations

import os
from typing import Optional


GOOGLE_DEFAULT_AGENT_MODEL = "gemini-2.5-flash"
GOOGLE_DEFAULT_JUDGE_MODEL = "gemini-2.5-flash-lite"
GROQ_DEFAULT_AGENT_MODEL = "llama-3.3-70b-versatile"
GROQ_DEFAULT_JUDGE_MODEL = "llama-3.1-8b-instant"


def resolve_provider() -> str:
    """Return either ``'groq'`` or ``'google'``."""
    explicit = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    if explicit in {"groq"}:
        return "groq"
    if explicit in {"google", "gemini"}:
        return "google"
    if os.getenv("GROQ_API_KEY"):
        return "groq"
    return "google"


def _google_api_key() -> str:
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""


def _resolve_model(role: str, override: Optional[str], provider: str) -> str:
    """Pick the model id for the given role/provider, honouring overrides."""
    if override:
        return override
    if provider == "groq":
        return (
            os.getenv("AGENT_MODEL", GROQ_DEFAULT_AGENT_MODEL)
            if role == "agent"
            else os.getenv("JUDGE_MODEL", GROQ_DEFAULT_JUDGE_MODEL)
        )
    return (
        os.getenv("AGENT_MODEL", GOOGLE_DEFAULT_AGENT_MODEL)
        if role == "agent"
        else os.getenv("JUDGE_MODEL", GOOGLE_DEFAULT_JUDGE_MODEL)
    )


def build_llm(role: str = "agent", *, model: Optional[str] = None, temperature: float = 0.1):
    """Return a configured LangChain chat model for the requested role.

    `role` is either ``'agent'`` (the production agent / eval target) or
    ``'judge'`` (the LLM-as-a-judge used by run_eval.py).
    """
    if role not in {"agent", "judge"}:
        raise ValueError(f"Unknown role {role!r}; expected 'agent' or 'judge'.")

    provider = resolve_provider()
    chosen_model = _resolve_model(role, model, provider)

    if provider == "groq":
        # Imported lazily so the dependency is only required when the user
        # actually wants the Groq backend.
        from langchain_groq import ChatGroq

        api_key = os.getenv("GROQ_API_KEY") or ""
        return ChatGroq(
            model=chosen_model,
            api_key=api_key,
            temperature=temperature,
        )

    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=chosen_model,
        google_api_key=_google_api_key(),
        temperature=temperature,
        convert_system_message_to_human=True,
    )


def describe_provider() -> str:
    """Human-readable description of the active provider/model setup.
    Used for logging in run_eval.py and during agent startup."""
    provider = resolve_provider()
    agent_model = _resolve_model("agent", None, provider)
    judge_model = _resolve_model("judge", None, provider)
    return f"provider={provider} agent_model={agent_model} judge_model={judge_model}"
