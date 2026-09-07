"""
cowagent2.human_simulator
~~~~~~~~~~~~~~~~~~~~~~~~~
Full human conversational simulation engine:
1. Simulates realistic reading latency (reading input message).
2. Simulates realistic typing latency (keystroke timing and thinking pauses).
3. Constructs human-like persona prompts strictly eliminating robotic AI clichés.
4. Provides human chat etiquette (polite, concise, natural colloquialisms).
"""

from __future__ import annotations

import asyncio
import random
import re
import time
from typing import List, Optional


class HumanSimulator:
    """Simulates realistic human messaging behaviors on WeChat."""

    def __init__(
        self,
        enabled: bool = True,
        min_reading_delay: float = 0.6,
        max_reading_delay: float = 2.5,
        min_typing_delay: float = 1.0,
        max_typing_delay: float = 5.0,
        typing_speed_chars_per_sec: float = 25.0,
    ):
        self.enabled = enabled
        self.min_reading_delay = min_reading_delay
        self.max_reading_delay = max_reading_delay
        self.min_typing_delay = min_typing_delay
        self.max_typing_delay = max_typing_delay
        self.typing_speed = typing_speed_chars_per_sec

    def calculate_reading_delay(self, text: str) -> float:
        """Calculate realistic reading delay based on incoming message length."""
        if not self.enabled:
            return 0.0
        # Average reading speed ~ 8-12 characters per second
        char_count = len(text.strip()) if text else 1
        base = char_count / 10.0
        jitter = random.uniform(0.3, 0.9)
        delay = base + jitter
        return round(max(self.min_reading_delay, min(self.max_reading_delay, delay)), 2)

    def calculate_typing_delay(self, reply_text: str) -> float:
        """Calculate realistic typing delay based on outbound reply length."""
        if not self.enabled:
            return 0.0
        char_count = len(reply_text.strip()) if reply_text else 1
        base = char_count / self.typing_speed
        # Human hesitation / pauses
        hesitation = random.uniform(0.5, 1.6)
        delay = base + hesitation
        return round(max(self.min_typing_delay, min(self.max_typing_delay, delay)), 2)

    async def sleep_reading_pace(self, text: str) -> float:
        """Asynchronously sleep for reading duration."""
        delay = self.calculate_reading_delay(text)
        if delay > 0:
            await asyncio.sleep(delay)
        return delay

    async def sleep_typing_pace(self, reply_text: str) -> float:
        """Asynchronously sleep for typing duration."""
        delay = self.calculate_typing_delay(reply_text)
        if delay > 0:
            await asyncio.sleep(delay)
        return delay

    def build_system_prompt(
        self,
        peer_name: str = "",
        is_group: bool = False,
        custom_instructions: str = "",
    ) -> str:
        """
        Build an authentic human persona system prompt.
        Strictly prevents robotic markers (e.g. 'As an AI model', markdown spam).
        """
        peer_desc = f"对方昵称: {peer_name}。" if peer_name else "当前是一对一私聊。"
        group_desc = "当前在微信群聊中，请注意发言得体，融入大家的对话氛围。" if is_group else "当前是微信私聊，像真实好友一样自然交流。"

        prompt = f"""你是一个真实的微信好友/同事，正在微信上与对方聊天。
{peer_desc}
{group_desc}

【核心人设与行为准则】
1. 完全模拟正常人类：
   - 你是真人，绝对不要透露或暗示自己是AI、语言模型、机器人、人工智能助手或由程序运行。
   - 严禁出现以下机械化套话：“作为人工智能”、“很高兴为您服务”、“请问有什么可以帮助您的”、“根据我的分析”、“以上回答希望对您有帮助”。
2. 微信日常语言风格：
   - 语气真诚、亲切、自然、口语化，就像微信里常聊天的朋友或靠谱伙伴。
   - 适度使用微信常用口头禅和语气词（如“好嘞”、“收到”、“哈哈确实”、“行呀”、“等下哈”、“没问题”、“嗯嗯”）。
   - 遇到开心或好玩的事可以打“哈哈”，遇到关心的问题展现真诚。
3. 篇幅与排版控制：
   - 日常聊天请保持简洁轻量，短小精悍（1-3句话为主），切忌动辄输出几百字的大段说教或学术论文。
   - 除非对方明确要求列清单或写长篇方案，否则切勿机械堆砌 Markdown 大标题、加粗符号（**）和数字序号列表。
   - 像真人打字一样，句子之间用逗号、句号、空格或自然换行即可。
4. 情绪与真实感：
   - 拥有人类正常的常识、温度和情绪感知。
   - 不懂或记不清的事情可以诚实说“这个我还真不太清楚/我回头去查查”，切忌机械性空泛编造。
"""
        if custom_instructions:
            prompt += f"\n【补充偏好】\n{custom_instructions.strip()}\n"

        return prompt.strip()

    def clean_human_reply(self, raw_reply: str) -> str:
        """Strip robotic preambles the model may prepend to an otherwise fine reply.

        Every pattern must be anchored on an explicit assistant-disclosure or
        service-desk phrase. A rule keyed only on a casual opener would fight
        the persona instead of enforcing it: ``build_system_prompt`` asks the
        model for exactly those openers ("好嘞", "收到", "好的"), so a bare
        ``^好的[，,]`` rule turned "好的，我马上去看一下" into "我马上去看一下"
        and quietly flattened the voice on ordinary replies.
        """
        text = raw_reply.strip()

        # Robotic preambles. Each requires a disclosure or boilerplate phrase,
        # never a standalone conversational opener.
        patterns = [
            r"^(作为一个|作为一名)?[^，,。:\n]*(人工智能|AI|语言模型|智能助手|机器人)[^，,。:\n]*[，,。:]\s*",
            r"^你好[！!，,]?(很高兴为您服务|请问有什么可以帮您[？?]?)\s*",
            r"^(好的|好的呢)[，,]\s*作为[^\n]+?[，,]\s*",
            r"^\*+🤖[^\n]+\*+\n*",
        ]
        for p in patterns:
            text = re.sub(p, "", text, flags=re.IGNORECASE).strip()

        # A removed preamble can leave its separator behind ("很高兴为您服务，"
        # ends one clause, and the comma opened the next). Drop dangling
        # leading punctuation so the reply still starts like a sentence.
        text = re.sub(r"^[，,。：:、；;！!？?\s]+", "", text)

        # Strip accidental thought tags if any leak
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

        return text
