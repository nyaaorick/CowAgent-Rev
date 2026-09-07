# -*- coding: utf-8 -*-
"""
cowagent2.config
~~~~~~~~~~~~~~~~
Configuration manager for CowAgent 2.

Responsibilities:
  1. Reuse the Zhipu AI / GLM credentials and model parameters already present
     in ``CowAgent/config.json`` so the operator never re-enters them.
  2. Own the access-control whitelist in ``cowagent2/data/whitelist.json``.
  3. Own the contact / chatroom binding cache in
     ``cowagent2/data/contacts_cache.json``.

Access control follows the rule established by CowAgent 1's
``channel/wcf/contact_filter.py``: an empty or malformed allow list must mean
"nobody", so a truncated config fails closed rather than opening the bot up to
every contact.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Set

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
V2_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(V2_DIR, "data")
LEGACY_CONFIG_PATH = os.path.join(BASE_DIR, "CowAgent", "config.json")
WHITELIST_PATH = os.path.join(DATA_DIR, "whitelist.json")
CONTACTS_CACHE_PATH = os.path.join(DATA_DIR, "contacts_cache.json")

# The marker WeChat appends to every group id. A session id carrying it
# addresses a chatroom; anything else is a one-to-one contact.
CHATROOM_SUFFIX = "@chatroom"

# ROADMAP "Model Selection Policy": glm-4.7-flash is banned (recurrent HTTP 429
# and empty reasoning tokens), so any 4.7 variant is rewritten to the baseline.
DEFAULT_MODEL = "glm-4-flash"
BANNED_MODEL_MARKER = "4.7"

DEFAULT_WEB_PORT = 9900

os.makedirs(DATA_DIR, exist_ok=True)
logger = logging.getLogger("cowagent2.config")


class Config:
    """Runtime configuration and access-control state for CowAgent 2."""

    def __init__(self, whitelist_path: str = WHITELIST_PATH):
        self.whitelist_path = whitelist_path
        self.legacy_config: Dict[str, Any] = {}
        self.whitelist: Dict[str, Any] = {
            "enabled": True,                  # Default-deny mode is on
            "allowed_wxids": ["filehelper"],  # File Transfer Assistant is safe by default
            "allowed_rooms": [],              # Chatroom ids allowed to converse
            "auto_reply_sessions": [],        # Sessions replying without an @mention
        }
        self.load_legacy_config()
        self.load_whitelist()

    # ------------------------------------------------------------------
    # CowAgent 1 configuration reuse
    # ------------------------------------------------------------------
    def load_legacy_config(self) -> None:
        """Load and reuse ``CowAgent/config.json``."""
        if not os.path.exists(LEGACY_CONFIG_PATH):
            logger.warning(f"CowAgent config not found: {LEGACY_CONFIG_PATH}")
            return
        try:
            with open(LEGACY_CONFIG_PATH, "r", encoding="utf-8") as f:
                self.legacy_config = json.load(f)
            logger.info(f"Reusing CowAgent base configuration: {LEGACY_CONFIG_PATH}")
        except Exception as e:
            logger.warning(f"Failed to read CowAgent config: {e}; using defaults")

    # ------------------------------------------------------------------
    # LLM parameters
    # ------------------------------------------------------------------
    @property
    def api_key(self) -> str:
        return self.legacy_config.get("zhipu_ai_api_key", "")

    @property
    def api_base(self) -> str:
        return self.legacy_config.get(
            "zhipu_ai_api_base", "https://open.bigmodel.cn/api/paas/v4"
        )

    @property
    def model(self) -> str:
        configured = self.legacy_config.get("model", DEFAULT_MODEL)
        if configured and BANNED_MODEL_MARKER in configured:
            return DEFAULT_MODEL
        return configured or DEFAULT_MODEL

    @property
    def system_prompt(self) -> str:
        return self.legacy_config.get(
            "character_desc",
            "You are a real person chatting on WeChat. Keep replies short, "
            "warm and natural.",
        )

    @property
    def system_prompt_template(self) -> str:
        """Alias kept for callers that read the persona as a prompt template."""
        return self.system_prompt

    @property
    def temperature(self) -> float:
        return float(self.legacy_config.get("temperature", 0.7))

    @property
    def top_p(self) -> float:
        return float(self.legacy_config.get("top_p", 0.7))

    @property
    def web_port(self) -> int:
        return int(self.legacy_config.get("cowagent2_web_port", DEFAULT_WEB_PORT))

    @property
    def debug_sql_enabled(self) -> bool:
        """Whether the console exposes the raw SQL inspection endpoint.

        Off by default: that endpoint reads the operator's entire WeChat
        message database, and the console has no authentication of its own.
        """
        return bool(self.legacy_config.get("cowagent2_debug_sql", False))

    def get_zhipu_api_key(self) -> str:
        return self.api_key

    # ------------------------------------------------------------------
    # Whitelist persistence
    # ------------------------------------------------------------------
    def load_whitelist(self) -> None:
        """Load the whitelist from disk, writing defaults on first run."""
        if not os.path.exists(self.whitelist_path):
            self.save_whitelist()
            return
        try:
            with open(self.whitelist_path, "r", encoding="utf-8") as f:
                self.whitelist = json.load(f)
        except Exception as e:
            logger.error(f"Failed to read whitelist, restoring defaults: {e}")
            self.save_whitelist()

    def save_whitelist(self) -> None:
        """Persist the whitelist to disk."""
        try:
            with open(self.whitelist_path, "w", encoding="utf-8") as f:
                json.dump(self.whitelist, f, ensure_ascii=False, indent=2)
            logger.info("Whitelist updated and persisted")
        except Exception as e:
            logger.error(f"Failed to save whitelist: {e}")

    # ------------------------------------------------------------------
    # Access control
    # ------------------------------------------------------------------
    @staticmethod
    def is_group_session(session_id: str) -> bool:
        """True when a session id addresses a chatroom rather than a contact."""
        return bool(session_id) and session_id.endswith(CHATROOM_SUFFIX)

    def is_allowed(self, session_id: str, is_group: Optional[bool] = None) -> bool:
        """Whether this session may reach the bot.

        ``session_id`` is the reply target: a ``wxid`` for a private chat and a
        ``roomid`` for a group, matching how the bot and the console address a
        conversation everywhere else.

        ``is_group`` selects which list is consulted, and is inferred from the
        ``@chatroom`` suffix when omitted. The inference is what makes a
        single-argument call safe: the previous ``(wxid, roomid)`` form checked
        rooms against ``allowed_wxids`` whenever a caller passed only the
        session id, so a group the operator had explicitly enabled in the
        console still never received a reply.
        """
        if not session_id:
            return False
        if not self.whitelist.get("enabled", True):
            return True

        if is_group is None:
            is_group = self.is_group_session(session_id)

        key = "allowed_rooms" if is_group else "allowed_wxids"
        allowed: Set[str] = set(self._entries(key))
        return session_id in allowed

    def _entries(self, key: str) -> List[str]:
        """Non-empty string entries for a whitelist key.

        Non-string entries are dropped rather than coerced: stringifying a JSON
        ``null`` would create the entry ``"None"``, and since a contact chooses
        their own display name, a malformed list must only ever narrow this
        gate, never widen it.
        """
        raw = self.whitelist.get(key, [])
        if not isinstance(raw, (list, tuple, set)):
            return []
        return [item.strip() for item in raw if isinstance(item, str) and item.strip()]

    def toggle_whitelist(self, target_id: str, is_group: bool, enable: bool) -> bool:
        """Add or remove a contact / chatroom from the whitelist."""
        if not target_id:
            return False
        key = "allowed_rooms" if is_group else "allowed_wxids"
        current = self._entries(key)

        if enable and target_id not in current:
            current.append(target_id)
        elif not enable and target_id in current:
            current.remove(target_id)

        self.whitelist[key] = current
        self.save_whitelist()
        return True

    # ------------------------------------------------------------------
    # Unconditional auto-reply (skips the group @mention requirement)
    # ------------------------------------------------------------------
    def get_session_auto_reply(self, session_id: str) -> bool:
        """Whether this session replies without needing an @mention."""
        return session_id in set(self._entries("auto_reply_sessions"))

    def set_session_auto_reply(self, session_id: str, enable: bool) -> None:
        sessions = set(self._entries("auto_reply_sessions"))
        if enable:
            sessions.add(session_id)
        else:
            sessions.discard(session_id)
        self.whitelist["auto_reply_sessions"] = sorted(sessions)
        self.save_whitelist()


cfg = Config()


def get_config() -> Config:
    """Singleton getter for the CowAgent 2 configuration."""
    return cfg
