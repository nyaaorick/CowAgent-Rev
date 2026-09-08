# -*- coding: utf-8 -*-
"""
cowagent2.memory
~~~~~~~~~~~~~~~~
Short-term conversation memory for CowAgent 2.

Guarantees:
  1. Every ``wxid`` (private chat) and every ``roomid`` (group chat) owns a
     fully isolated context; nothing crosses between sessions.
  2. A sliding window keeps each session inside the token budget.
  3. A session can be cleared on its own (``#清除记忆`` / ``#reset``) without
     touching any other session.

Scope note: this layer is deliberately in-process and volatile, so a restart
loses every transcript. Durable long-term memory -- the shared global memory
plus per-contact memory and workspaces ported from CowAgent 1's
``agent/memory/`` -- is Milestone 7 in ``cowagent2/ROADMAP.md``. The public
API here is the one that layer will wrap, so call sites do not have to change
when it lands.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

logger = logging.getLogger("cowagent2.memory")

# Turns, not messages: one turn is a user message plus its assistant reply.
DEFAULT_MAX_HISTORY_TURNS = 15


class SessionMemoryManager:
    """Per-session rolling transcript with strict isolation between sessions."""

    def __init__(self, max_history_turns: int = DEFAULT_MAX_HISTORY_TURNS):
        self.max_history_turns = max_history_turns
        # session_id -> [{"role": "user" | "assistant", "content": str, "time": float}]
        self.sessions: Dict[str, List[Dict[str, Any]]] = {}
        self.session_metadata: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def get_context(self, session_id: str, system_prompt: str = "") -> List[Dict[str, str]]:
        """Chat history for one session in OpenAI / GLM message format."""
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        for item in self.sessions.get(session_id, []):
            messages.append({"role": item["role"], "content": item["content"]})

        return messages

    def get_history(self, session_id: str) -> List[Dict[str, Any]]:
        """Raw message records for one session, timestamps included."""
        return self.sessions.get(session_id, [])

    def get_session_stats(self) -> List[Dict[str, Any]]:
        """Summary of every live session, most recently active first."""
        stats = []
        for session_id, messages in self.sessions.items():
            meta = self.session_metadata.get(session_id, {})
            stats.append({
                "session_id": session_id,
                "display_name": meta.get("display_name", session_id),
                "message_count": len(messages),
                "last_active": meta.get("last_active", 0),
                "total_turns": meta.get("total_user_turns", 0),
            })
        stats.sort(key=lambda item: item["last_active"], reverse=True)
        return stats

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    def add_user_message(self, session_id: str, content: str, sender_name: str = "") -> None:
        """Record an inbound message from the peer."""
        self._append(session_id, "user", content, display_name=sender_name)

    def add_assistant_message(self, session_id: str, content: str) -> None:
        """Record an outbound message the agent sent."""
        self._append(session_id, "assistant", content)

    def clear_session(self, session_id: str) -> bool:
        """Erase one session's history, leaving every other session intact."""
        if session_id not in self.sessions:
            return False
        self.sessions[session_id] = []
        if session_id in self.session_metadata:
            self.session_metadata[session_id]["cleared_at"] = time.time()
        logger.info(f"Session memory cleared in isolation: session_id={session_id}")
        return True

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _append(self, session_id: str, role: str, content: str, display_name: str = "") -> None:
        self._ensure_session(session_id, display_name)
        now = time.time()
        self.sessions[session_id].append({
            "role": role,
            "content": content,
            "time": now,
        })
        meta = self.session_metadata[session_id]
        meta["last_active"] = now
        counter = "total_user_turns" if role == "user" else "total_bot_turns"
        meta[counter] += 1
        self._trim_history(session_id)

    def _ensure_session(self, session_id: str, display_name: str = "") -> None:
        if session_id not in self.sessions:
            now = time.time()
            self.sessions[session_id] = []
            self.session_metadata[session_id] = {
                "display_name": display_name or session_id,
                "created_at": now,
                "last_active": now,
                "total_user_turns": 0,
                "total_bot_turns": 0,
            }
        elif display_name and not self.session_metadata[session_id].get("display_name"):
            self.session_metadata[session_id]["display_name"] = display_name

    def _trim_history(self, session_id: str) -> None:
        """Drop the oldest messages once the window overflows.

        The window is counted in messages (turns x 2) and trimmed from the
        front, so the newest exchange always survives. Trimmed content is
        simply discarded today; Milestone 7 routes it into the daily memory
        summariser before it is dropped.
        """
        history = self.sessions.get(session_id, [])
        max_messages = self.max_history_turns * 2
        if len(history) > max_messages:
            self.sessions[session_id] = history[-max_messages:]


memory = SessionMemoryManager()


def get_memory_manager() -> SessionMemoryManager:
    """Singleton getter for the session memory manager."""
    return memory
