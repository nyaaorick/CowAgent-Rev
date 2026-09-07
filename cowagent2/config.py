# -*- coding: utf-8 -*-
"""
CowAgent 2 配置管理器
=====================
特性:
  1. 自动复用 CowAgent/config.json 中的 Zhipu AI / GLM 配置与密钥，零重复输入；
  2. 独立管理 cowagent2/data/whitelist.json 白名单规则；
  3. 独立管理 cowagent2/data/contacts_cache.json 联系人/群聊绑定缓存。
"""

import os
import json
import logging
from typing import Dict, Any, List, Set

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
V2_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(V2_DIR, "data")
LEGACY_CONFIG_PATH = os.path.join(BASE_DIR, "CowAgent", "config.json")
WHITELIST_PATH = os.path.join(DATA_DIR, "whitelist.json")
CONTACTS_CACHE_PATH = os.path.join(DATA_DIR, "contacts_cache.json")

os.makedirs(DATA_DIR, exist_ok=True)
logger = logging.getLogger("CowAgent2.Config")


class Config:
    def __init__(self):
        self.legacy_config: Dict[str, Any] = {}
        self.whitelist: Dict[str, Any] = {
            "enabled": True,             # 是否开启白名单模式（默认开启）
            "allowed_wxids": ["filehelper"],  # 允许对话的个人 wxid（默认允许文件传输助手）
            "allowed_rooms": []          # 允许对话的群聊 roomid
        }
        self.load_legacy_config()
        self.load_whitelist()

    def load_legacy_config(self):
        """读取并复用 CowAgent/config.json"""
        if os.path.exists(LEGACY_CONFIG_PATH):
            try:
                with open(LEGACY_CONFIG_PATH, "r", encoding="utf-8") as f:
                    self.legacy_config = json.load(f)
                logger.info(f"成功复用 CowAgent 基础配置: {LEGACY_CONFIG_PATH}")
            except Exception as e:
                logger.warning(f"读取 CowAgent 配置失败: {e}，将使用默认参数")
        else:
            logger.warning(f"未找到 CowAgent 配置文件: {LEGACY_CONFIG_PATH}")

    # LLM 相关参数
    @property
    def api_key(self) -> str:
        return self.legacy_config.get("zhipu_ai_api_key", "")

    @property
    def api_base(self) -> str:
        return self.legacy_config.get("zhipu_ai_api_base", "https://open.bigmodel.cn/api/paas/v4")

    @property
    def model(self) -> str:
        m = self.legacy_config.get("model", "glm-4-flash")
        # 强制拦截 glm-4.7-flash，保证使用 glm-4-flash (ROADMAP 规定)
        if "4.7" in m:
            return "glm-4-flash"
        return m or "glm-4-flash"

    @property
    def system_prompt(self) -> str:
        return self.legacy_config.get(
            "character_desc",
            "你是基于 WeChatFerry 运行的智能微信助手 CowAgent 2。回答简洁、准确、友好、有帮助。"
        )

    @property
    def temperature(self) -> float:
        return float(self.legacy_config.get("temperature", 0.7))

    @property
    def top_p(self) -> float:
        return float(self.legacy_config.get("top_p", 0.7))

    @property
    def web_port(self) -> int:
        return int(self.legacy_config.get("cowagent2_web_port", 9900))

    # 白名单管理
    def load_whitelist(self):
        """从 data/whitelist.json 加载白名单"""
        if os.path.exists(WHITELIST_PATH):
            try:
                with open(WHITELIST_PATH, "r", encoding="utf-8") as f:
                    self.whitelist = json.load(f)
            except Exception as e:
                logger.error(f"读取白名单失败: {e}")
                self.save_whitelist()
        else:
            self.save_whitelist()

    def save_whitelist(self):
        """持久化白名单到 data/whitelist.json"""
        try:
            with open(WHITELIST_PATH, "w", encoding="utf-8") as f:
                json.dump(self.whitelist, f, ensure_ascii=False, indent=2)
            logger.info("白名单已更新并持久化")
        except Exception as e:
            logger.error(f"保存白名单失败: {e}")

    def is_allowed(self, wxid: str, roomid: str = "") -> bool:
        """核心鉴权判断：检查指定会话是否在白名单中允许对话"""
        if not self.whitelist.get("enabled", True):
            return True  # 若关闭白名单模式，则全放行

        allowed_wxids: Set[str] = set(self.whitelist.get("allowed_wxids", []))
        allowed_rooms: Set[str] = set(self.whitelist.get("allowed_rooms", []))

        # 群聊消息判断：必须群聊在白名单中
        if roomid:
            return roomid in allowed_rooms

        # 私聊消息判断：必须联系人在白名单中
        return wxid in allowed_wxids

    def toggle_whitelist(self, target_id: str, is_group: bool, enable: bool) -> bool:
        """切换某联系人或群聊的白名单状态"""
        key = "allowed_rooms" if is_group else "allowed_wxids"
        current_list = self.whitelist.get(key, [])

        if enable and target_id not in current_list:
            current_list.append(target_id)
        elif not enable and target_id in current_list:
            current_list.remove(target_id)

        self.whitelist[key] = current_list
        self.save_whitelist()
        return True

    def get_zhipu_api_key(self) -> str:
        return self.api_key

    @property
    def system_prompt_template(self) -> str:
        return self.system_prompt

    def get_session_auto_reply(self, session_id: str) -> bool:
        """Check if group or contact has auto-reply unconditionally enabled."""
        auto_replies = self.whitelist.get("auto_reply_sessions", [])
        return session_id in auto_replies

    def set_session_auto_reply(self, session_id: str, enable: bool) -> None:
        auto_replies = set(self.whitelist.get("auto_reply_sessions", []))
        if enable:
            auto_replies.add(session_id)
        else:
            auto_replies.discard(session_id)
        self.whitelist["auto_reply_sessions"] = list(auto_replies)
        self.save_whitelist()


cfg = Config()


def get_config() -> Config:
    """Singleton getter for CowAgent 2 configuration."""
    return cfg
