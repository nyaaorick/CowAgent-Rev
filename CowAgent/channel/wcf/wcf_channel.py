# encoding:utf-8

"""WeChatFerry channel — local mode (Milestone 4.2).

Talks to WeChatFerry over its nng RPC. By default it runs the library in
**local mode**: ``Wcf(host=None)`` runs ``wcf.exe start <port>`` as a
subprocess, which injects ``spy.dll`` into a running WeChat.exe and binds
``127.0.0.1:10086`` (commands) / ``:10087`` (events). spy is 32-bit and is
driven out-of-process so that 64-bit Python can use it. Set ``wcf_host`` to a
real IP only to attach to a WeChatFerry already running on another machine —
the single-host deployment never does (see ROADMAP "方案二").

``wcferry`` is pinned to ``39.6.0.0``: it is the only published build that
targets this host's **WeChat 3.9.12.56** (``39.5.2.0`` targets 3.9.12.51 and
access-violates on 3.9.12.56). The wheel's own DLLs are mis-built — see
``scripts/wcf_ci_dlls.py``, which replaces them with upstream's CI binaries.

Scope: **text messages only**. Image / voice / file receive and send are
Milestone 4.3; unsupported inbound types are logged and skipped, unsupported
outbound reply types are logged and dropped.
"""

import os
import socket
import threading
import time

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from channel.chat_channel import ChatChannel
from channel.wcf.contact_filter import is_allowed_contact
from channel.wcf.wcf_message import WcfMessage
from common.log import logger
from common.singleton import singleton
from config import conf

# wcf_host values that mean "run WeChatFerry here" rather than "dial a remote one".
_LOCAL_HOSTS = {"", "127.0.0.1", "localhost", "local", "::1"}

# How long a seen msg_id is remembered for de-duplication.
_DEDUP_TTL = 60


def _spy_log_path():
    """Where spy.dll writes its own log — the only place its failures surface."""
    try:
        import wcferry
        return os.path.join(os.path.dirname(wcferry.__file__), "logs", "wcf.txt")
    except Exception:
        return "<wcferry package>/logs/wcf.txt"


def _port_listening(port, host="127.0.0.1"):
    with socket.socket() as s:
        s.settimeout(0.4)
        try:
            s.connect((host, port))
            return True
        except OSError:
            return False


@singleton
class WcfChannel(ChatChannel):
    NOT_SUPPORT_REPLYTYPE = [ReplyType.VOICE]

    def __init__(self):
        super().__init__()
        self.wcf = None
        self._seen = {}            # msg_id -> first-seen monotonic time
        self._seen_lock = threading.Lock()
        self._contacts = {}        # wxid -> contact dict (from get_contacts)

    # ------------------------------------------------------------------ startup
    def startup(self):
        try:
            from wcferry import Wcf
        except ImportError as e:
            raise RuntimeError(
                "channel_type is 'wcf' but the 'wcferry' package is not installed. "
                "Run: .venv\\Scripts\\pip install wcferry  (Windows only)."
            ) from e

        raw_host = str(conf().get("wcf_host", "") or "").strip()
        port = int(conf().get("wcf_port", 10086))
        debug = bool(conf().get("wcf_debug", False))
        host = None if raw_host.lower() in _LOCAL_HOSTS else raw_host

        mode = "local (spawns wcf.exe)" if host is None else f"remote {host}:{port}"
        logger.info(f"[WCF] connecting in {mode} mode ...")

        # Refuse to hand a doomed connection to wcferry: its constructor calls
        # os._exit(-2) when the dial fails, which no except block can catch and
        # which takes the web console down with it. See _ensure_spy_listening.
        if host is None:
            self._ensure_spy_listening(port, debug)

        # block=True: returns only once WeChat is logged in.
        self.wcf = Wcf(host=host, port=port, debug=debug)

        self.user_id = self.wcf.get_self_wxid()
        try:
            self.name = (self.wcf.get_user_info() or {}).get("name") or ""
        except Exception:
            self.name = ""
        logger.info(f"[WCF] logged in as {self.name!r} ({self.user_id})")

        allowed = conf().get("wcf_contact_white_list", []) or []
        logger.info(f"[WCF] private chats answered for: {allowed or 'nobody (whitelist empty)'}")

        self._refresh_contacts()
        if not self._contacts:
            # spy reaches WeChat's databases through its AccountStorageMgr.
            # On the 3.9.12.56 build that lookup fails, so the log fills with
            # "Failed to get handle for database 'MicroMsg.db'" and contacts
            # come back empty, while is_login() and get_self_wxid() keep working
            # because they read a different structure.
            #
            # This is cosmetic, not fatal: message receive is hook-based and does
            # not touch the databases -- an end-to-end round trip was confirmed
            # with an empty contact list. Only display names degrade to raw
            # wxids. Group @-detection parses the message XML, not the DB.
            logger.warning(
                "[WCF] no contacts returned — spy cannot read WeChat's databases, "
                "so sender names will show as raw wxids. Messages still work. See "
                f"{_spy_log_path()} and ROADMAP 4.1 (MicroMsg.db defect)."
            )

        # The client returns False both when the hook genuinely failed AND when
        # spy answers status=1 ("already listening", from a previous injection
        # into this same WeChat session) -- in the second case it also skips
        # starting its own receive thread, so no message is ever delivered and
        # nothing is logged. Neither case is survivable, so say so plainly.
        if not self.wcf.enable_receiving_msg():
            logger.error(
                "[WCF] enable_receiving_msg() failed. Usually spy is still "
                "injected from an earlier run (status=1 'already listening'). "
                "Fully quit and reopen WeChat, then start again."
            )
        self._verify_event_channel(port)
        self.report_startup_success()

        logger.info("[WCF] receiving messages")
        self._recv_loop()

    def _ensure_spy_listening(self, port, debug):
        """Get spy.dll injected and answering on ``port``, or raise saying why.

        This exists because of how wcferry fails. ``Wcf(host=None)`` runs
        ``wcf.exe start <port>`` and accepts exit code 10 ("spy 已注入") as
        "already ready" -- but a spy can be injected with its RPC server
        stopped, which is what an earlier ``cleanup()`` leaves behind
        (ROADMAP WCF-BUG-03). Nothing then listens, the dial fails, and
        wcferry answers with ``os._exit(-2)``: not an exception, an immediate
        process kill. The channel thread cannot catch it and the web console
        dies with it, for a fault that only concerns WeChat.

        So the injection is driven here first, where the exit code can be read
        against the port's actual state, and a bad one becomes an ordinary
        exception that ChannelManager logs while every other channel keeps
        running.
        """
        import subprocess

        if _port_listening(port):
            return  # spy is already up and answering; Wcf will just dial it.

        try:
            import wcferry
            wcf_exe = os.path.join(os.path.dirname(wcferry.__file__), "wcf.exe")
        except Exception as e:
            raise RuntimeError(f"cannot locate wcf.exe: {e}") from e

        cmd = [wcf_exe, "start", str(port)] + (["debug"] if debug else [])
        try:
            rc = subprocess.run(
                cmd, cwd=os.path.dirname(wcf_exe), capture_output=True, timeout=60
            ).returncode
        except Exception as e:
            raise RuntimeError(f"could not run wcf.exe: {e}") from e

        # Exit codes are wcf.exe's own (see its --help): 0 ok, 10 already
        # injected, 4 WeChat not running, 5 injection refused.
        if rc == 0 and self._wait_for_port(port):
            return
        if rc == 10 and self._wait_for_port(port):
            return  # injected by an earlier run and still healthy.

        if rc == 10:
            raise RuntimeError(
                f"spy.dll is injected into WeChat but nothing is listening on "
                f"127.0.0.1:{port}. A previous run stopped its RPC server "
                f"without unloading the DLL, and it cannot be restarted in "
                f"place. Fully quit WeChat (including the tray icon), reopen "
                f"and log in, then start CowAgent-Rev again. "
                f"See {_spy_log_path()}."
            )
        if rc == 4:
            raise RuntimeError(
                "WeChat is not running. Start WeChat 3.9.12.x and log in first."
            )
        raise RuntimeError(
            f"wcf.exe start failed (exit {rc}); spy.dll was not injected. "
            f"See {_spy_log_path()}."
        )

    @staticmethod
    def _wait_for_port(port, timeout=15):
        """Wait for the command port, which binds a moment after injection."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if _port_listening(port):
                return True
            time.sleep(0.3)
        return False

    def _verify_event_channel(self, cmd_port):
        """Warn if the event socket (``cmd_port + 1``) has not come up.

        `enable_receiving_msg` starts wcferry's "GetMessage" thread, which dials
        that socket. If it is not listening the thread dies on
        ``ConnectionRefused`` and no inbound message ever arrives, while the
        command RPC and login keep working — a confusing half-alive state worth
        a log line.

        This only **warns**. The usual cause is a poisoned spy.dll from an
        earlier `Wcf.cleanup()` / re-inject cycle without restarting WeChat, and
        the socket can also simply be slow to bind — neither is worth refusing
        to start over.
        """
        evt_port = cmd_port + 1
        for _ in range(15):
            if _port_listening(evt_port):
                return True
            if not any(t.name == "GetMessage" and t.is_alive()
                       for t in threading.enumerate()):
                break
            time.sleep(1)
        logger.warning(
            f"[WCF] event channel 127.0.0.1:{evt_port} is not listening — inbound "
            "messages will not arrive. Restart WeChat, then start CowAgent-Rev "
            "again (spy.dll gets wedged if a previous run was killed without "
            "cleanup). Sending still works."
        )
        return False

    def _recv_loop(self):
        while True:
            try:
                msg = self.wcf.get_msg()
            except Exception as e:
                # get_msg raises queue.Empty on an idle timeout; anything else
                # is worth a debug line but not worth tearing the loop down.
                if e.__class__.__name__ != "Empty":
                    logger.debug(f"[WCF] get_msg: {e}")
                time.sleep(0.2)
                continue
            if msg is not None:
                self._handle_wxmsg(msg)

    # ------------------------------------------------------------------ inbound
    def _handle_wxmsg(self, wcf_msg):
        try:
            if wcf_msg.from_self():
                return
            if self._is_duplicate(str(wcf_msg.id)):
                return

            try:
                cmsg = WcfMessage(self, wcf_msg)
            except NotImplementedError as e:
                logger.debug(f"[WCF] skip unsupported inbound message: {e}")
                return

            # Private chats gate here; group chats gate on group_name_white_list
            # inside ChatChannel._compose_context, which this must not shadow.
            if not cmsg.is_group and not self._contact_allowed(cmsg):
                logger.debug(
                    f"[WCF] ignoring {cmsg.from_user_id} "
                    f"({cmsg.from_user_nickname!r}): not in wcf_contact_white_list"
                )
                return

            context = self._compose_context(
                cmsg.ctype, cmsg.content, isgroup=cmsg.is_group, msg=cmsg
            )
            if context:
                self.produce(context)
        except Exception as e:
            logger.error(f"[WCF] failed to handle message: {e}")
            logger.exception(e)

    def _contact_allowed(self, cmsg):
        """Is this private chat with a contact the operator opted in to?

        Read from config on every message rather than cached at startup, so
        adding a contact in the console takes effect on the next message
        instead of on the next WeChat restart -- restarting is expensive here
        (spy.dll is a singleton injection, ROADMAP WCF-BUG-03).
        """
        return is_allowed_contact(
            conf().get("wcf_contact_white_list", []),
            cmsg.from_user_id,
            cmsg.from_user_nickname,
        )

    def _is_duplicate(self, msg_id):
        now = time.monotonic()
        with self._seen_lock:
            for mid, seen_at in list(self._seen.items()):
                if now - seen_at > _DEDUP_TTL:
                    del self._seen[mid]
            if msg_id in self._seen:
                return True
            self._seen[msg_id] = now
            return False

    # ----------------------------------------------------------------- outbound
    def send(self, reply: Reply, context: Context):
        receiver = context.get("receiver")
        if not receiver:
            logger.error("[WCF] send: empty receiver")
            return

        if reply.type in (ReplyType.TEXT, ReplyType.TEXT_, ReplyType.INFO, ReplyType.ERROR):
            aters = ""
            if context.get("isgroup") and context.get("msg") is not None:
                aters = context["msg"].actual_user_id or ""
            # send_text returns rsp.status: 0 is success, anything else (or a
            # timed-out RPC) is not. Logging success unconditionally made a
            # wedged spy look healthy - the socket pair is 5s send + 5s recv,
            # so a dead spy still produced a cheerful "sent text" line exactly
            # 10s later.
            status = self.wcf.send_text(reply.content, receiver, aters)
            if status == 0:
                logger.info(f"[WCF] sent text to {receiver}")
            else:
                logger.error(
                    f"[WCF] send to {receiver} failed (status={status}); the "
                    f"reply may not have been delivered. A spy that stops "
                    f"answering shows up here first - check "
                    f"wcferry/logs/wcf.txt for the matching FUNC_SEND_TXT."
                )
        else:
            logger.warning(f"[WCF] reply type {reply.type} not supported yet (Milestone 4.3)")

    # -------------------------------------------------------------- name lookup
    def _refresh_contacts(self):
        try:
            contacts = self.wcf.get_contacts() or []
            self._contacts = {c.get("wxid"): c for c in contacts if c.get("wxid")}
        except Exception as e:
            logger.debug(f"[WCF] get_contacts failed: {e}")
            self._contacts = {}

    def get_display_name(self, wxid):
        if not wxid:
            return ""
        if wxid == self.user_id:
            return self.name or ""
        contact = self._contacts.get(wxid)
        if contact:
            return contact.get("name") or contact.get("nickname") or wxid
        return wxid

    def get_room_alias(self, wxid, roomid):
        if not (wxid and roomid):
            return ""
        try:
            return self.wcf.get_alias_in_chatroom(wxid, roomid) or ""
        except Exception:
            return ""

    # -------------------------------------------------------------------- close
    def stop(self):
        if self.wcf is not None:
            try:
                self.wcf.cleanup()
            except Exception as e:
                logger.debug(f"[WCF] cleanup: {e}")
