"""
Prompt Manager - 集中化提示词管理与热更新引擎

负责加载和管理全局 prompts.json，支持：
1. 层次化 key 路径检索（如 'system_prompt.response_language'）
2. 语言自动回退（zh / en）
3. 变量插值（format）
4. 文件修改时间（mtime）热重载，无需重启生效
5. 代码内置 Fallback，防止 JSON 损坏导致系统崩溃
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from common.log import logger


class PromptManager:
    """集中式提示词管理器，具备单例缓存与热重载能力。"""

    _instance: Optional[PromptManager] = None
    _lock = threading.Lock()

    def __init__(self, json_path: Optional[str] = None):
        self._custom_path = json_path
        self._prompts: Dict[str, Any] = {}
        self._mtime: float = 0.0
        self._last_check: float = 0.0
        self._check_interval: float = 1.0  # 最多每秒检测一次 mtime，性能极高
        self._resolved_path: Optional[Path] = None
        self._data_lock = threading.RLock()
        self.reload(force=True)

    @classmethod
    def get_instance(cls, json_path: Optional[str] = None) -> PromptManager:
        """获取或创建全局单例实例。"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = PromptManager(json_path)
        return cls._instance

    def _resolve_file_path(self) -> Optional[Path]:
        """按优先级解析 prompts.json 所在路径。"""
        if self._custom_path:
            p = Path(self._custom_path)
            if p.exists():
                return p

        # 候选搜索路径
        candidates = [
            Path(__file__).resolve().parent.parent.parent / "prompts.json",  # CowAgent/prompts.json
            Path(__file__).resolve().parent / "prompts.json",               # agent/prompt/prompts.json
            Path.cwd() / "prompts.json",
        ]

        for cand in candidates:
            if cand.exists():
                return cand

        return candidates[0]

    def _check_reload(self) -> None:
        """根据文件修改时间轻量级检查是否需要热重载。"""
        now = time.time()
        if now - self._last_check < self._check_interval:
            return
        self._last_check = now

        if not self._resolved_path or not self._resolved_path.exists():
            resolved = self._resolve_file_path()
            if resolved and resolved.exists():
                self._resolved_path = resolved
                self.reload(force=True)
            return

        try:
            current_mtime = os.path.getmtime(self._resolved_path)
            if current_mtime > self._mtime:
                self.reload(force=True)
        except OSError:
            pass

    def reload(self, force: bool = False) -> bool:
        """重载 prompts.json 文件。"""
        with self._data_lock:
            path = self._resolved_path or self._resolve_file_path()
            if not path or not path.exists():
                logger.debug(f"[PromptManager] prompts.json not found at {path}, using fallbacks")
                return False

            try:
                mtime = os.path.getmtime(path)
                if not force and mtime <= self._mtime:
                    return True

                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                if isinstance(data, dict):
                    self._prompts = data
                    self._mtime = mtime
                    self._resolved_path = path
                    logger.info(f"[PromptManager] Loaded prompts from {path} (version={data.get('$schema_version', '1.0')})")
                    return True
                else:
                    logger.warning(f"[PromptManager] Invalid root format in {path}: expected dict, got {type(data)}")
                    return False
            except Exception as e:
                logger.warning(f"[PromptManager] Failed to load {path}: {e}, keeping existing prompts")
                return False

    def get(
        self,
        key_path: str,
        lang: Optional[str] = None,
        fallback: Any = None,
        **kwargs
    ) -> Any:
        """
        检索指定路径的提示词数据，支持点号路径、多语言回退及变量格式化插值。

        Args:
            key_path: 点号分隔的路径，例如 "system_prompt.tooling.guidelines"
            lang: 可选语言 ("zh" 或 "en")
            fallback: 找不到对应配置时的默认返回值
            **kwargs: 字符串格式化参数 (如 user_prompt, read_tool_name 等)

        Returns:
            提示词字符串、列表或字典
        """
        self._check_reload()

        with self._data_lock:
            parts = [p for p in key_path.split(".") if p]
            curr = self._prompts

            for part in parts:
                if isinstance(curr, dict) and part in curr:
                    curr = curr[part]
                elif isinstance(curr, dict) and (lang and lang in curr and isinstance(curr[lang], dict) and part in curr[lang]):
                    curr = curr[lang][part]
                elif isinstance(curr, dict) and ("zh" in curr and isinstance(curr["zh"], dict) and part in curr["zh"]):
                    curr = curr["zh"][part]
                elif isinstance(curr, dict) and ("en" in curr and isinstance(curr["en"], dict) and part in curr["en"]):
                    curr = curr["en"][part]
                else:
                    curr = None
                    break

            # 如果命中且指定了语言
            if curr is not None and lang:
                if isinstance(curr, dict):
                    if lang in curr:
                        curr = curr[lang]
                    elif "zh" in curr:
                        curr = curr["zh"]
                    elif "en" in curr:
                        curr = curr["en"]

            if curr is None or (isinstance(curr, str) and not curr.strip() and fallback):
                val = fallback
            else:
                val = curr

            # 支持变量插值
            if kwargs and val is not None:
                return self._interpolate(val, kwargs)

            return val

    def _interpolate(self, val: Any, kwargs: Dict[str, Any]) -> Any:
        """递归对字符串、列表、字典进行安全格式化插值。"""
        if isinstance(val, str):
            try:
                return val.format(**kwargs)
            except Exception:
                return val
        elif isinstance(val, list):
            return [self._interpolate(item, kwargs) for item in val]
        elif isinstance(val, dict):
            return {k: self._interpolate(v, kwargs) for k, v in val.items()}
        return val


# 便捷访问函数
def get_prompt_manager() -> PromptManager:
    return PromptManager.get_instance()


def get_prompt(
    key_path: str,
    lang: Optional[str] = None,
    fallback: Any = None,
    **kwargs
) -> Any:
    return get_prompt_manager().get(key_path, lang=lang, fallback=fallback, **kwargs)
