# encoding:utf-8

"""The single long-lived WeChatFerry connection for this process.

Ported from CowAgent 2's ``wcf_gateway`` (ROADMAP directive 6, Code Reuse Over
Reinvention). It lives here rather than being imported from ``cowagent2/``
because that tree is a read-only reference: a production channel that imports
it at runtime turns a reference into a dependency, and ties this process's
WeChat connection to a second entry point that can inject spy.dll into the same
WeChat.exe (ROADMAP WCF-BUG-03).

What this owns:

* **One connection, for the life of the process.** ``spy.dll`` is a singleton
  injection; a second client wedges it, and recovering means fully quitting
  WeChat.
* **Release spy only.** ``debug=False`` is mandatory. ``spy_debug.dll`` is built
  against the MSVC Debug CRT and hands Debug STL containers to a Release WeChat,
  which access-violates on the first send (ROADMAP WCF-BUG-05).
* **The pre-flight before any dial.** ``Wcf()`` answers a failed dial with
  ``os._exit(-2)`` -- not an exception, an immediate process kill that no
  ``except`` can catch and that takes the web console down with it, for a fault
  that only concerns WeChat. So the injection is driven here first, where the
  exit code can be read against the port's actual state.
* **Passive WeChat detection.** WeChat is never launched for the operator.
"""

import os
import queue
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from common.log import logger

# Where the RPC command channel binds. The event channel is this + 1.
DEFAULT_PORT = 10086

# How long the command port is given to bind after a fresh injection.
_PORT_WAIT_SECONDS = 15

# The lock wcferry leaves behind when a process dies without cleaning up.
_LOCK_FILE = ".wcf.lock"

MessageSubscriber = Callable[[Any], None]
OutboundSubscriber = Callable[[str, str, int], None]


# ---------------------------------------------------------------------------
# The spy pre-flight
# ---------------------------------------------------------------------------
def _spy_log_path() -> str:
    """Where spy.dll writes its own log -- the only place its failures surface."""
    try:
        import wcferry
        return os.path.join(os.path.dirname(wcferry.__file__), "logs", "wcf.txt")
    except Exception:
        return "<wcferry package>/logs/wcf.txt"


def _port_listening(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket() as s:
        s.settimeout(0.4)
        try:
            s.connect((host, port))
            return True
        except OSError:
            return False


def _wait_for_port(port: int, timeout: int = _PORT_WAIT_SECONDS) -> bool:
    """Wait for the command port, which binds a moment after injection."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_listening(port):
            return True
        time.sleep(0.5)
    return False


def ensure_spy_listening(port: int) -> None:
    """Get spy.dll injected and answering on ``port``, or raise saying why.

    This exists because of how wcferry fails. ``Wcf(host=None)`` runs
    ``wcf.exe start <port>`` and accepts exit code 10 ("spy 已注入") as "already
    ready" -- but a spy can be injected with its RPC server stopped, which is
    what an earlier ``cleanup()`` leaves behind (ROADMAP WCF-BUG-03). Nothing
    then listens, the dial fails, and wcferry answers with ``os._exit(-2)``: not
    an exception, an immediate process kill. The channel thread cannot catch it
    and the web console dies with it.

    So the injection is driven here first, where the exit code can be read
    against the port's actual state, and a bad one becomes an ordinary
    exception that the caller logs while every other channel keeps running.

    The injection is always the Release spy: ``wcf.exe start <port> debug``
    would load ``spy_debug.dll``, which crashes WeChat outright (WCF-BUG-05).
    """
    if _port_listening(port):
        return  # spy is already up and answering; Wcf will just dial it.

    try:
        import wcferry
        wcf_exe = os.path.join(os.path.dirname(wcferry.__file__), "wcf.exe")
    except Exception as e:
        raise RuntimeError(f"cannot locate wcf.exe: {e}") from e

    try:
        rc = subprocess.run(
            [wcf_exe, "start", str(port)],
            cwd=os.path.dirname(wcf_exe), capture_output=True, timeout=60,
        ).returncode
    except Exception as e:
        raise RuntimeError(f"could not run wcf.exe: {e}") from e

    # Exit codes are wcf.exe's own (see its --help): 0 ok, 10 already injected,
    # 4 WeChat not running, 5 injection refused.
    if rc in (0, 10) and _wait_for_port(port):
        return

    if rc == 10:
        raise RuntimeError(
            f"spy.dll is injected into WeChat but nothing is listening on "
            f"127.0.0.1:{port}. A previous run stopped its RPC server without "
            f"unloading the DLL, and it cannot be restarted in place. Fully "
            f"quit WeChat (including the tray icon), reopen and log in, then "
            f"start CowAgent-Rev again. See {_spy_log_path()}."
        )
    if rc == 4:
        raise RuntimeError(
            "WeChat is not running. Start WeChat 3.9.12.x and log in first."
        )
    raise RuntimeError(
        f"wcf.exe start failed (exit {rc}); spy.dll was not injected. "
        f"See {_spy_log_path()}."
    )


# ---------------------------------------------------------------------------
# The gateway
# ---------------------------------------------------------------------------
class WcfGateway:
    """The process's one WeChatFerry connection."""

    _instance: Optional["WcfGateway"] = None
    _instance_lock = threading.Lock()

    def __init__(self, port: int = DEFAULT_PORT):
        self.port = port
        self.wcf = None
        self.is_running = False
        self._listener_thread: Optional[threading.Thread] = None
        self._subscribers: List[MessageSubscriber] = []
        self._outbound_subscribers: List[OutboundSubscriber] = []
        self._send_lock = threading.Lock()

    @classmethod
    def get_instance(cls, port: int = DEFAULT_PORT) -> "WcfGateway":
        """The one gateway for this process, created on first use."""
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls(port=port)
            return cls._instance

    # ------------------------------------------------------------------
    # Pre-connection checks
    # ------------------------------------------------------------------
    @staticmethod
    def is_wechat_process_running() -> bool:
        """Is WeChat.exe running? Checked, never started on the operator's behalf."""
        try:
            res = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq WeChat.exe", "/NH"],
                capture_output=True, text=True, check=False,
            )
            return "WeChat.exe" in res.stdout
        except Exception as e:
            logger.warning(f"[Gateway] Failed to check the WeChat process: {e}")
            return False

    @staticmethod
    def clean_stale_locks() -> None:
        """Remove a .wcf.lock left behind by a process that died mid-run."""
        lock_file = Path(_LOCK_FILE)
        if not lock_file.exists():
            return
        try:
            lock_file.unlink()
            logger.info("[Gateway] Cleaned a stale .wcf.lock")
        except Exception as e:
            logger.warning(f"[Gateway] Could not remove .wcf.lock: {e}")

    def _build_client(self):
        """Construct the wcferry client. Split out so tests never dial WeChat.

        ``debug=False`` is not a preference: ``spy_debug.dll`` is compiled
        against the Debug CRT and crashes a Release WeChat on the first send
        (WCF-BUG-05). ``block=False`` keeps the constructor from parking this
        thread until someone logs in.
        """
        try:
            from wcferry import Wcf
        except ImportError as e:
            raise RuntimeError(
                "channel_type is 'wcf' but the 'wcferry' package is not "
                "installed. Run: .venv\\Scripts\\pip install wcferry  "
                "(Windows only)."
            ) from e
        return Wcf(port=self.port, debug=False, block=False)

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------
    def connect(self) -> bool:
        """Bring the connection up. True when it is live and logged in.

        Never raises and never exits: every failure here concerns WeChat alone,
        and the web console and every other channel have to keep running.
        """
        if self.wcf and self.is_login():
            logger.info("[Gateway] Already connected and logged in")
            return True

        if not self.is_wechat_process_running():
            logger.warning(
                "[Gateway] WeChat.exe is not running. Start WeChat and log in; "
                "it is never launched automatically."
            )
            return False

        self.clean_stale_locks()

        # Before anything constructs a client. A dial against a dead port ends
        # the process outright, so this has to come first and its failure has
        # to stop the sequence here.
        try:
            ensure_spy_listening(self.port)
        except RuntimeError as e:
            logger.error(f"[Gateway] {e}")
            return False

        try:
            logger.info(f"[Gateway] Connecting on port {self.port} (Release spy)...")
            self.wcf = self._build_client()
            self._disarm_wcferry_cleanup()

            if not self.wcf.is_login():
                logger.warning("[Gateway] WeChat is running but nobody is logged in")
                self.wcf = None
                return False

            info = self.wcf.get_user_info() or {}
            logger.info(
                f"[Gateway] Connected as {info.get('name', 'unknown')!r} "
                f"({info.get('wxid', 'unknown')})"
            )

            self.wcf.enable_receiving_msg()
            self.is_running = True
            self._start_listener()
            return True
        except Exception as e:
            logger.error(f"[Gateway] Failed to connect: {e}")
            self.wcf = None
            self.is_running = False
            return False

    def _disarm_wcferry_cleanup(self) -> None:
        """Stop wcferry from unhooking WeChat when this process exits.

        Its ``atexit`` hook runs ``wcf.exe stop``, which kills the RPC server
        inside spy.dll while leaving the DLL injected -- precisely the wedged
        state that then needs a full WeChat restart to clear (WCF-BUG-03).
        Leaving the spy running means the next start just dials it again.
        """
        import atexit
        try:
            atexit.unregister(self.wcf.cleanup)
        except Exception as e:
            logger.debug(f"[Gateway] Could not unregister wcferry cleanup: {e}")

    # ------------------------------------------------------------------
    # Inbound
    # ------------------------------------------------------------------
    def subscribe(self, callback: MessageSubscriber) -> None:
        """Receive every inbound WeChat message."""
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def subscribe_outbound(self, callback: OutboundSubscriber) -> None:
        """Receive every outbound send as ``(receiver, content, status)``."""
        if callback not in self._outbound_subscribers:
            self._outbound_subscribers.append(callback)

    def _start_listener(self) -> None:
        """Run the message pump on its own daemon thread."""
        if self._listener_thread and self._listener_thread.is_alive():
            return

        def _loop():
            logger.info("[Gateway] Inbound listener started")
            while self.is_running and self.wcf:
                try:
                    msg = self.wcf.get_msg()
                    if not msg:
                        continue
                    for sub in list(self._subscribers):
                        # One subscriber's failure must not stop the pump, or a
                        # single bad handler silences the whole channel.
                        try:
                            sub(msg)
                        except Exception as err:
                            logger.error(f"[Gateway] Subscriber {sub} failed: {err}")
                except queue.Empty:
                    continue
                except Exception as e:
                    if self.is_running:
                        logger.warning(f"[Gateway] Error reading a message: {e}")
                    time.sleep(0.1)
            logger.info("[Gateway] Inbound listener stopped")

        self._listener_thread = threading.Thread(
            target=_loop, name="WcfMsgListener", daemon=True
        )
        self._listener_thread.start()

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------
    def send_text(self, msg: str, receiver: str, at_list: str = "") -> int:
        """Send one text message. Returns WeChat's status: 0 is delivered.

        Serialised: the RPC socket pair is one 5s send plus one 5s receive, and
        two threads interleaving on it get each other's answers.
        """
        if not self.wcf or not self.is_running:
            logger.error(f"[Gateway] Cannot send to {receiver}: not connected")
            return -1

        with self._send_lock:
            try:
                status = self.wcf.send_text(msg=msg, receiver=receiver, aters=at_list)
            except Exception as e:
                logger.error(f"[Gateway] Exception sending to {receiver}: {e}")
                return -2

            for sub in list(self._outbound_subscribers):
                try:
                    sub(receiver, msg, status)
                except Exception as err:
                    logger.error(f"[Gateway] Outbound subscriber failed: {err}")

            if status == 0:
                logger.info(f"[Gateway] Sent text to {receiver}")
            else:
                logger.warning(
                    f"[Gateway] Send to {receiver} failed (status={status})"
                )
            return status

    # ------------------------------------------------------------------
    # Reads and shutdown
    # ------------------------------------------------------------------
    def get_user_info(self) -> Dict[str, Any]:
        """The logged-in account, or an empty dict when there is none."""
        if self.wcf and self.is_running:
            try:
                return self.wcf.get_user_info() or {}
            except Exception as e:
                logger.warning(f"[Gateway] Failed to read user info: {e}")
        return {}

    def is_login(self) -> bool:
        if not self.wcf:
            return False
        try:
            return bool(self.wcf.is_login())
        except Exception:
            return False

    def close(self) -> None:
        """Shut down without unhooking WeChat.

        The sockets are closed and the pump stopped, but spy.dll is left
        injected and listening: telling it to stop is what wedges it.
        """
        logger.info("[Gateway] Shutting down...")
        self.is_running = False
        if self.wcf:
            for step in ("disable_recv_msg", "cmd_socket", "msg_socket"):
                try:
                    attr = getattr(self.wcf, step)
                    attr.close() if step.endswith("socket") else attr()
                except Exception:
                    pass
            self.wcf._is_running = False
            self.wcf = None
        logger.info("[Gateway] Closed")


def reset_instance() -> None:
    """Drop the process-wide gateway. For tests and for a deliberate reconnect."""
    with WcfGateway._instance_lock:
        WcfGateway._instance = None
