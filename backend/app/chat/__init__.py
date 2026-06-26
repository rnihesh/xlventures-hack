"""Agentic chatbot package.

Exposes the whole platform as TOOLS to a conversational agent. ``tools`` is the
shared tool registry (thin wrappers over the existing services) and ``agent``
drives them via real LLM tool-calling when a key is present or a deterministic
intent router offline.
"""

from __future__ import annotations

from app.chat import agent, tools

__all__ = ["agent", "tools"]
