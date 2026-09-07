"""
cowagent2.bot
~~~~~~~~~~~~~
Cognitive dispatcher for CowAgent 2.
- Enforces strict whitelist-only security (default-deny).
- Strictly isolates conversation memory per wxid / roomid.
- Injects full human simulation (persona, reading & typing delays).
- Dispatches LLM calls to Zhipu AI GLM-4-flash.
- Broadcasts conversation turns for real-time web console monitoring.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Callable, Dict, Optional, Any

from wcferry import WxMsg
from zai import ZhipuAiClient

from cowagent2.config import get_config
from cowagent2.human_simulator import HumanSimulator
from cowagent2.memory import get_memory_manager
from cowagent2.scanner import ContactScanner
from cowagent2.wcf_gateway import WcfGateway

logger = logging.getLogger("cowagent2.bot")


class CowBot:
    """Minimalist, human-simulated WeChat bot engine."""

    def __init__(
        self,
        gateway: Optional[WcfGateway] = None,
        scanner: Optional[ContactScanner] = None,
        on_turn_completed: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.config = get_config()
        self.gateway = gateway or WcfGateway.get_instance()
        self.memory = get_memory_manager()
        self.scanner = scanner or ContactScanner(wcf_client=self.gateway.wcf)
        self.simulator = HumanSimulator(enabled=True)
        self.on_turn_completed = on_turn_completed
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._llm_client: Optional[ZhipuAiClient] = None
        self._my_wxid = ""

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def _get_llm_client(self) -> ZhipuAiClient:
        if self._llm_client is None:
            api_key = self.config.get_zhipu_api_key()
            if not api_key:
                raise ValueError("Zhipu AI API key is missing. Check CowAgent/config.json.")
            self._llm_client = ZhipuAiClient(api_key=api_key)
        return self._llm_client

    def on_wcf_message(self, msg: WxMsg) -> None:
        """Entry callback invoked by WcfGateway listener thread."""
        # Check if message is from ourselves
        if msg.from_self():
            return

        # Only handle standard text messages (type 1)
        if msg.type != 1:
            return

        # Schedule processing in background thread/task to not block WCF message queue
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self.process_message(msg), self._loop)
        else:
            threading.Thread(
                target=lambda: asyncio.run(self.process_message(msg)),
                daemon=True,
            ).start()

    async def process_message(self, msg: WxMsg) -> None:
        """Process an inbound text message through whitelist, memory, and LLM."""
        try:
            content = (msg.content or "").strip()
            if not content:
                return

            is_group = bool(msg.from_group())
            session_id = msg.roomid if is_group else msg.sender
            talker_wxid = msg.sender

            # 1. Check Whitelist (Default-Deny)
            if not self.config.is_allowed(session_id):
                logger.debug(f"[Whitelist] Ignored message from non-whitelisted: {session_id}")
                return

            # Retrieve friendly contact/group name
            contact_info = self.scanner.get_contact(session_id) or {}
            peer_name = contact_info.get("name") or contact_info.get("nickname") or session_id

            # 2. Group Chat Filtering: only respond if @mentioned or addressed
            if is_group:
                if not self._my_wxid and self.gateway.wcf:
                    user_info = self.gateway.wcf.get_user_info() or {}
                    self._my_wxid = user_info.get("wxid", "")

                # Check if group message is @me
                is_at_me = msg.is_at(self._my_wxid) if self._my_wxid else False
                # If not @me, check if group auto-reply is enabled or addressed
                if not is_at_me and not self.config.get_session_auto_reply(session_id):
                    logger.debug(f"[Group] Ignored message not @me in {session_id}")
                    return

                # Strip @tag if present
                clean_content = content
                if "@" in content:
                    clean_content = content.split("\u2005")[-1].strip() or content
                content = clean_content

            logger.info(f"[Inbound] From {peer_name} ({session_id}): {content}")

            # 3. Handle Command: Reset session memory
            if content in ("#清除记忆", "#reset", "#清空记忆"):
                self.memory.clear_session(session_id)
                reply = "好的，这边的对话记忆已经清空啦。"
                self.gateway.send_text(reply, receiver=session_id)
                self._notify_turn(session_id, peer_name, content, reply)
                return

            # 4. Human Simulation: Reading delay
            read_delay = await self.simulator.sleep_reading_pace(content)
            logger.debug(f"Simulated reading delay: {read_delay}s")

            # 5. Add User Message to Isolated Session Memory
            self.memory.add_user_message(session_id, content)

            # 6. Retrieve Isolated Context & Build Human Persona Prompt
            history_messages = self.memory.get_context(session_id)
            system_prompt = self.simulator.build_system_prompt(
                peer_name=peer_name,
                is_group=is_group,
                custom_instructions=self.config.system_prompt_template,
            )

            llm_messages = [{"role": "system", "content": system_prompt}] + history_messages

            # 7. Invoke LLM (GLM-4-flash)
            client = self._get_llm_client()
            model_name = self.config.model or "glm-4-flash"

            logger.info(f"Calling {model_name} for session {session_id} (context turns: {len(history_messages)})...")
            
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: client.chat.completions.create(
                    model=model_name,
                    messages=llm_messages,
                    temperature=self.config.temperature,
                    top_p=self.config.top_p,
                ),
            )

            raw_reply = response.choices[0].message.content or ""
            clean_reply = self.simulator.clean_human_reply(raw_reply)

            if not clean_reply:
                logger.warning(f"Empty LLM reply for session {session_id}")
                return

            # 8. Human Simulation: Typing delay
            type_delay = await self.simulator.sleep_typing_pace(clean_reply)
            logger.debug(f"Simulated typing delay: {type_delay}s")

            # 9. Send Reply to WeChat
            send_status = self.gateway.send_text(clean_reply, receiver=session_id)

            # 10. Record Assistant Message in Isolated Session Memory
            self.memory.add_assistant_message(session_id, clean_reply)

            logger.info(f"[Outbound] To {peer_name} ({session_id}) [status={send_status}]: {clean_reply}")

            # 11. Broadcast Turn to Web Console
            self._notify_turn(session_id, peer_name, content, clean_reply)

        except Exception as e:
            logger.error(f"Error processing message from {msg.sender}: {e}", exc_info=True)

    def _notify_turn(self, session_id: str, peer_name: str, user_msg: str, bot_reply: str) -> None:
        """Emit completed conversation turn for real-time web monitoring."""
        if self.on_turn_completed:
            try:
                turn_data = {
                    "session_id": session_id,
                    "peer_name": peer_name,
                    "user_msg": user_msg,
                    "bot_reply": bot_reply,
                    "timestamp": self.memory.get_history(session_id)[-1].get("timestamp", 0) if self.memory.get_history(session_id) else 0,
                }
                self.on_turn_completed(turn_data)
            except Exception as e:
                logger.error(f"Error invoking on_turn_completed callback: {e}")

