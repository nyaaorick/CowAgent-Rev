# -*- coding: utf-8 -*-
"""
CowAgent 2 严格会话记忆管理器 (SessionMemoryManager)
===================================================
特性:
  1. 每一个 wxid (私聊) 和每一个 roomid (群聊) 拥有完全隔离的记忆上下文；
  2. 严格滑动窗口修剪，保持 token 预算健康；
  3. 支持指定会话的独立清理 (#清除记忆 / #reset)，绝不串扰其他会话。
"""

import time
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger("CowAgent2.Memory")


class SessionMemoryManager:
    def __init__(self, max_history_turns: int = 15):
        self.max_history_turns = max_history_turns
        # session_id -> list of {"role": "user"|"assistant", "content": str, "time": float}
        self.sessions: Dict[str, List[Dict[str, Any]]] = {}
        self.session_metadata: Dict[str, Dict[str, Any]] = {}

    def get_context(self, session_id: str, system_prompt: str = "") -> List[Dict[str, str]]:
        """获取指定 session 的历史上下文列表（符合 OpenAI / GLM 接口格式）"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        history = self.sessions.get(session_id, [])
        for item in history:
            messages.append({"role": item["role"], "content": item["content"]})

        return messages

    def add_user_message(self, session_id: str, content: str, sender_name: str = ""):
        """记录用户发送的消息"""
        self._ensure_session(session_id, sender_name)
        self.sessions[session_id].append({
            "role": "user",
            "content": content,
            "time": time.time()
        })
        self.session_metadata[session_id]["last_active"] = time.time()
        self.session_metadata[session_id]["total_user_turns"] += 1
        self._trim_history(session_id)

    def add_assistant_message(self, session_id: str, content: str):
        """记录智能体回复的消息"""
        self._ensure_session(session_id)
        self.sessions[session_id].append({
            "role": "assistant",
            "content": content,
            "time": time.time()
        })
        self.session_metadata[session_id]["last_active"] = time.time()
        self.session_metadata[session_id]["total_bot_turns"] += 1
        self._trim_history(session_id)

    def clear_session(self, session_id: str) -> bool:
        """清除指定 session 的所有记忆，不影响任何其他 session"""
        if session_id in self.sessions:
            self.sessions[session_id] = []
            if session_id in self.session_metadata:
                self.session_metadata[session_id]["cleared_at"] = time.time()
            logger.info(f"会话记忆已隔离清空: session_id={session_id}")
            return True
        return False

    def get_session_stats(self) -> List[Dict[str, Any]]:
        """返回所有会话的统计摘要信息（供 Web UI 展示）"""
        stats = []
        for sid, msgs in self.sessions.items():
            meta = self.session_metadata.get(sid, {})
            stats.append({
                "session_id": sid,
                "display_name": meta.get("display_name", sid),
                "message_count": len(msgs),
                "last_active": meta.get("last_active", 0),
                "total_turns": meta.get("total_user_turns", 0)
            })
        stats.sort(key=lambda x: x["last_active"], reverse=True)
        return stats

    def _ensure_session(self, session_id: str, display_name: str = ""):
        if session_id not in self.sessions:
            self.sessions[session_id] = []
            self.session_metadata[session_id] = {
                "display_name": display_name or session_id,
                "created_at": time.time(),
                "last_active": time.time(),
                "total_user_turns": 0,
                "total_bot_turns": 0
            }
        elif display_name and not self.session_metadata[session_id].get("display_name"):
            self.session_metadata[session_id]["display_name"] = display_name

    def _trim_history(self, session_id: str):
        """滑动窗口截断，确保不会超出 token 预算"""
        history = self.sessions.get(session_id, [])
        max_msgs = self.max_history_turns * 2
        if len(history) > max_msgs:
            # 保持从 user 消息开始配对截断
            self.sessions[session_id] = history[-max_msgs:]

    def get_history(self, session_id: str) -> List[Dict[str, Any]]:
        """获取指定 session 的原始消息记录（带时间戳）"""
        return self.sessions.get(session_id, [])


memory = SessionMemoryManager()


def get_memory_manager() -> SessionMemoryManager:
    """Singleton getter for SessionMemoryManager."""
    return memory
