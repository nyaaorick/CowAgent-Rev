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
        print("  🐮 CowAgent 2 — Minimalist WeChat Agent (WCF 3.9.12.56)")
        print(f"  🌐 Console:  http://127.0.0.1:{self.config.web_port}")
        print(f"  🧠 Model:    {self.config.model} (human simulation + isolated memory)")
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
            logger.info(
                "WeChat.exe is not running. The console is up; waiting for the "
                "operator to start and log into WeChat manually."
            )
            return False

        success = self.gateway.connect()
        if success:
            logger.info("WCF gateway ready; scanning contacts and chatrooms...")
            self.scanner.wcf_client = self.gateway.wcf
            contacts = self.scanner.scan()
            logger.info(f"Initial scan complete: {len(contacts)} contacts and chatrooms indexed.")
        else:
            logger.warning("Could not connect to WCF. Confirm WeChat is running and logged in.")
        return success

    async def _background_health_monitor(self) -> None:
        """Periodically check WeChat status and attempt reconnection if needed."""
        while self.is_running:
            try:
                await asyncio.sleep(8)
                if not self.gateway.is_running or not self.gateway.is_login():
                    if WcfGateway.is_wechat_process_running():
                        logger.info("WeChat detected; attempting to connect the WCF gateway...")
                        self._try_connect_wcf()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Health monitor tick error: {e}")

    async def stop(self) -> None:
        """Graceful shutdown."""
        logger.info("Stopping CowAgent 2 services...")
        self.is_running = False
        await self.web_server.stop()
        self.gateway.close()
        logger.info("CowAgent 2 services stopped cleanly.")


async def main():
    app = CowAgent2Application()

    def _handle_signal(*_):
        logger.info("Interrupt received; shutting down gracefully...")
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
        logger.info("Terminated by the operator.")

