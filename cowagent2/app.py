"""
cowagent2.app
~~~~~~~~~~~~~
CowAgent 2 Main Application Orchestrator.
- Manages long-lived WCF Singleton Gateway (debug=False).
- Hosts Localhost Web Console at http://127.0.0.1:9900.
- Runs passive Contact & Chatroom Discovery.
- Dispatches inbound messages to Human-Simulated Bot under default-deny Whitelist.
- Broadcasts real-time live chat turns to web console.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
import time
from typing import Optional

from cowagent2.bot import CowBot
from cowagent2.config import get_config
from cowagent2.scanner import ContactScanner
from cowagent2.wcf_gateway import WcfGateway
from cowagent2.web_server import WebServer

# Configure unified logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("cowagent2.app")


class CowAgent2Application:
    """Unified lifespan coordinator for CowAgent 2."""

    def __init__(self):
        self.config = get_config()
        self.gateway = WcfGateway.get_instance()
        self.scanner = ContactScanner(wcf_client=self.gateway.wcf)
        self.web_server = WebServer(
            host="127.0.0.1",
            port=self.config.web_port,
            gateway=self.gateway,
            scanner=self.scanner,
        )
        self.bot = CowBot(
            gateway=self.gateway,
            scanner=self.scanner,
            on_turn_completed=self.web_server.on_turn_completed,
        )
        self.is_running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    async def start(self) -> None:
        """Start CowAgent 2 services."""
        self.is_running = True
        self._loop = asyncio.get_running_loop()
        self.bot.set_event_loop(self._loop)

        print("\n" + "=" * 60)
        print("  🐮 CowAgent 2 — 极简微信智能体系统 (WCF 3.9.12.56)")
        print(f"  🌐 控制台地址: http://127.0.0.1:{self.config.web_port}")
        print(f"  🧠 对话模型: {self.config.model} (真人拟态 + 严格记忆隔离)")
        print("=" * 60 + "\n")

        # 1. Start Web Server first so dashboard is immediately accessible
        await self.web_server.start()

        # 2. Wire message subscribers
        self.gateway.subscribe(self.scanner.on_wcf_message)
        self.gateway.subscribe(self.web_server.on_raw_message)
        self.gateway.subscribe(self.bot.on_wcf_message)

        # 3. Connect to WCF
        self._try_connect_wcf()

        # 4. Background monitor task
        asyncio.create_task(self._background_health_monitor())

    def _try_connect_wcf(self) -> bool:
        """Attempt passive connection to WeChat."""
        if not WcfGateway.is_wechat_process_running():
            logger.info("WeChat.exe 未运行，控制台已启动，等待用户手动打开并登录微信...")
            return False

        success = self.gateway.connect()
        if success:
            logger.info("WCF 网关初始化成功，开始扫描可用联系人与群聊...")
            self.scanner.wcf_client = self.gateway.wcf
            contacts = self.scanner.scan()
            logger.info(f"首轮扫描完成，共索引 {len(contacts)} 个联系人与群聊。")
        else:
            logger.warning("未能连接到 WCF，请确认微信已登录并在运行。")
        return success

    async def _background_health_monitor(self) -> None:
        """Periodically check WeChat status and attempt reconnection if needed."""
        while self.is_running:
            try:
                await asyncio.sleep(8)
                if not self.gateway.is_running or not self.gateway.is_login():
                    if WcfGateway.is_wechat_process_running():
                        logger.info("检测到 WeChat 正在运行，尝试连接 WCF 网关...")
                        self._try_connect_wcf()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Health monitor tick error: {e}")

    async def stop(self) -> None:
        """Graceful shutdown."""
        logger.info("正在停止 CowAgent 2 服务...")
        self.is_running = False
        await self.web_server.stop()
        self.gateway.close()
        logger.info("CowAgent 2 服务已安全停止。")


async def main():
    app = CowAgent2Application()

    def _handle_signal(*_):
        logger.info("收到中断信号，开始优雅退出...")
        asyncio.create_task(app.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handle_signal)
        except Exception:
            pass

    await app.start()

    # Keep running until cancelled
    try:
        while app.is_running:
            await asyncio.sleep(1)
    except (asyncio.CancelledError, KeyboardInterrupt):
        await app.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("程序已被用户手动终止。")

