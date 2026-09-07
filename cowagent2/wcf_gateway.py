"""
cowagent2.wcf_gateway
~~~~~~~~~~~~~~~~~~~~~
Long-lived Singleton WCF Gateway for CowAgent 2.
Enforces:
- Release spy.dll (debug=False) to prevent MSVC Debug CRT crashes (WCF-BUG-05).
- Single long-lived connection to prevent RPC wedge lockouts (WCF-BUG-03).
- Passive WeChat process detection (no auto-launch).
- Thread-safe outbound messaging and event subscription.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Any

from wcferry import Wcf, WxMsg

logger = logging.getLogger("cowagent2.wcf_gateway")

# Type alias for message subscribers
MessageSubscriber = Callable[[WxMsg], None]


class WcfGateway:
    """Singleton WCF Gateway managing RPC connection to WeChat 3.9.12.56."""

    _instance: Optional[WcfGateway] = None
    _lock = threading.Lock()

    def __init__(self, port: int = 10086):
        self.port = port
        self.wcf: Optional[Wcf] = None
        self.is_running = False
        self._listener_thread: Optional[threading.Thread] = None
        self._subscribers: List[MessageSubscriber] = []
        self._outbound_subscribers: List[Callable[[str, str, int], None]] = []
        self._send_lock = threading.Lock()

    @classmethod
    def get_instance(cls, port: int = 10086) -> WcfGateway:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(port=port)
            return cls._instance

    @staticmethod
    def is_wechat_process_running() -> bool:
        """Passively check if WeChat.exe is currently running on Windows."""
        try:
            import subprocess
            res = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq WeChat.exe", "/NH"],
                capture_output=True,
                text=True,
                check=False,
            )
            return "WeChat.exe" in res.stdout
        except Exception as e:
            logger.warning(f"Failed to check WeChat process: {e}")
            return False

    @staticmethod
    def clean_stale_locks() -> None:
        """Remove any stale .wcf.lock files left by abnormal terminations."""
        lock_file = Path(".wcf.lock")
        if lock_file.exists():
            try:
                lock_file.unlink()
                logger.info("Cleaned stale .wcf.lock file.")
            except Exception as e:
                logger.warning(f"Could not remove .wcf.lock: {e}")

    def connect(self) -> bool:
        """
        Connect to WeChat via WCF.
        CRITICAL: debug=False is mandatory to use Release spy.dll.
        """
        if self.wcf and self.wcf.is_login():
            logger.info("WCF already connected and logged in.")
            return True

        if not self.is_wechat_process_running():
            logger.warning("WeChat.exe is NOT running. Please start and log into WeChat manually.")
            return False

        self.clean_stale_locks()

        try:
            logger.info(f"Connecting to WCF on port {self.port} (debug=False, Release spy)...")
            # debug=False is strictly required to avoid WCF-BUG-05 CRT crash
            self.wcf = Wcf(port=self.port, debug=False, block=False)
            
            # CRITICAL ANTI-WEDGE: Unregister wcferry's atexit cleanup!
            # wcferry.cleanup() calls wcf.exe stop which kills the RPC server in spy.dll.
            # Unregistering it allows the process to restart seamlessly without wedging WeChat.
            import atexit
            try:
                atexit.unregister(self.wcf.cleanup)
            except Exception:
                pass

            if not self.wcf.is_login():
                logger.warning("WeChat is running but user is not logged in.")
                return False

            user_info = self.wcf.get_user_info() or {}
            wxid = user_info.get("wxid", "unknown")
            name = user_info.get("name", "unknown")
            logger.info(f"WCF connected successfully! Logged in as: {name} ({wxid})")

            # Enable receiving inbound messages on port 10087
            self.wcf.enable_receiving_msg()
            self.is_running = True

            # Start background message listener loop
            self._start_listener()
            return True

        except Exception as e:
            logger.error(f"Failed to connect to WCF: {e}", exc_info=True)
            self.wcf = None
            self.is_running = False
            return False

    def subscribe(self, callback: MessageSubscriber) -> None:
        """Subscribe to incoming WeChat messages."""
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def subscribe_outbound(self, callback: Callable[[str, str, int], None]) -> None:
        """Subscribe to outbound sent messages (receiver, content, status)."""
        if callback not in self._outbound_subscribers:
            self._outbound_subscribers.append(callback)

    def _start_listener(self) -> None:
        """Start the background daemon thread to consume messages from 10087."""
        if self._listener_thread and self._listener_thread.is_alive():
            return

        def _loop():
            logger.info("WCF inbound message listener loop started.")
            while self.is_running and self.wcf:
                try:
                    msg = self.wcf.get_msg()
                    if not msg:
                        continue

                    # Dispatch to all subscribers
                    for sub in list(self._subscribers):
                        try:
                            sub(msg)
                        except Exception as err:
                            logger.error(f"Error in message subscriber {sub}: {err}", exc_info=True)

                except queue.Empty:
                    continue
                except Exception as e:
                    if self.is_running:
                        logger.warning(f"Error reading message from WCF: {e}")
                    time.sleep(0.1)

            logger.info("WCF inbound message listener loop terminated.")

        self._listener_thread = threading.Thread(target=_loop, name="WcfMsgListener", daemon=True)
        self._listener_thread.start()

    def send_text(self, msg: str, receiver: str, at_list: str = "") -> int:
        """
        Thread-safe message transmission to WeChat recipient.
        Returns: 0 on success, non-zero on failure.
        """
        if not self.wcf or not self.is_running:
            logger.error(f"Cannot send message to {receiver}: WCF gateway not running.")
            return -1

        with self._send_lock:
            try:
                logger.info(f"Sending text to {receiver} ({len(msg)} chars)...")
                status = self.wcf.send_text(msg=msg, receiver=receiver, at_list=at_list)
                
                # Notify outbound subscribers
                for sub in list(self._outbound_subscribers):
                    try:
                        sub(receiver, msg, status)
                    except Exception as err:
                        logger.error(f"Error in outbound subscriber: {err}")

                if status == 0:
                    logger.info(f"Message sent to {receiver} successfully.")
                else:
                    logger.warning(f"Failed to send message to {receiver}, return code: {status}")
                return status

            except Exception as e:
                logger.error(f"Exception sending message to {receiver}: {e}", exc_info=True)
                return -2

    def get_user_info(self) -> Dict[str, Any]:
        """Get current logged-in WeChat account info."""
        if self.wcf and self.is_running:
            try:
                return self.wcf.get_user_info() or {}
            except Exception as e:
                logger.warning(f"Failed to get user info: {e}")
        return {}

    def is_login(self) -> bool:
        """Check if logged in."""
        if self.wcf and self.is_running:
            try:
                return bool(self.wcf.is_login())
            except Exception:
                return False
        return False

    def close(self) -> None:
        """Gracefully shutdown WCF gateway without stopping WeChat in-memory RPC."""
        logger.info("Shutting down WCF gateway...")
        self.is_running = False
        if self.wcf:
            try:
                self.wcf.disable_recv_msg()
            except Exception:
                pass
            try:
                self.wcf.cmd_socket.close()
                self.wcf.msg_socket.close()
            except Exception:
                pass
            self.wcf._is_running = False
            self.wcf = None
        logger.info("WCF gateway closed.")

