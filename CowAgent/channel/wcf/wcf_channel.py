# encoding:utf-8

"""WeChatFerry channel — the adapter between WeChat and the agent bridge.

The connection itself is not here. It belongs to
:class:`~channel.wcf.gateway.WcfGateway`, which owns one WeChatFerry client for
the whole process: ``spy.dll`` is a singleton injection into a running
WeChat.exe, and a second client wedges it (ROADMAP WCF-BUG-03). This module
subscribes to that gateway and does the channel's own work -- mapping a
``WxMsg`` onto a ``ChatMessage``, deciding who may reach the agent, and sending
replies back.

``wcferry`` is pinned to ``39.6.0.0``: it is the only published build that
targets this host's **WeChat 3.9.12.56** (``39.5.2.0`` targets 3.9.12.51 and
access-violates on 3.9.12.56). The wheel's own DLLs are mis-built — see
``scripts/wcf_ci_dlls.py``, which replaces them with upstream's CI binaries.

The connection is always loopback. ``wcf_host`` is still accepted in config for
compatibility but is not read: wcferry is not built for cross-host use, and the
single-host deployment never wanted it (see ROADMAP "方案二").

Scope: **text messages only**. Image / voice / file receive and send are
Milestone 4.3; unsupported inbound types are logged and skipped, unsupported
outbound reply types are logged and dropped.
"""

import threading
import time

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from channel.chat_channel import ChatChannel
from channel.wcf.contact_filter import is_allowed_contact
from channel.wcf.contact_state import get_contact_state
from channel.wcf.wcf_message import WcfMessage
from common.log import logger
from common.singleton import singleton
from config import conf

# How long a seen msg_id is remembered for de-duplication.
_DEDUP_TTL = 60


@singleton
class WcfChannel(ChatChannel):
    NOT_SUPPORT_REPLYTYPE = [ReplyType.VOICE]

    def __init__(self):
        super().__init__()
        self.wcf = None
        self.gateway = None
        self._seen = {}            # msg_id -> first-seen monotonic time
        self._seen_lock = threading.Lock()
        self._contacts = {}        # wxid -> contact dict (from get_contacts)

    # ------------------------------------------------------------------ startup
    def startup(self):
        """Bring the WeChat connection up and hand inbound messages to the bridge.

        The connection itself belongs to :class:`~channel.wcf.gateway.WcfGateway`
        -- one per process, because spy.dll is a singleton injection -- and this
        method is the channel's adapter onto it: subscribe, then stay alive for
        as long as the gateway is running.

        A gateway that cannot connect is not fatal here. Every failure it
        reports concerns WeChat alone, and the web console and every other
        channel have to keep running; ChannelManager logs the return.
        """
        from channel.wcf.gateway import WcfGateway

        port = int(conf().get("wcf_port", 10086))
        if conf().get("wcf_debug", False):
            # spy_debug.dll is built against the Debug CRT and access-violates
            # inside a Release WeChat on the first send (ROADMAP WCF-BUG-05), so
            # the gateway always injects the Release spy. Say so rather than
            # ignoring the setting quietly.
            logger.warning(
                "[WCF] wcf_debug is set but ignored: the debug spy crashes "
                "WeChat 3.9.12.56 on send (ROADMAP WCF-BUG-05)."
            )

        logger.info(f"[WCF] connecting through the gateway on port {port}...")
        self.gateway = WcfGateway.get_instance(port=port)
        if not self.gateway.connect():
            logger.warning(
                "[WCF] the gateway could not connect; this channel stays idle "
                "and the rest of CowAgent keeps running."
            )
            return

        self.wcf = self.gateway.wcf
        self.user_id = self.wcf.get_self_wxid() if self.wcf else ""
        self.name = (self.gateway.get_user_info() or {}).get("name") or ""
        logger.info(f"[WCF] logged in as {self.name!r} ({self.user_id})")

        allowed = conf().get("wcf_contact_white_list", []) or []
        logger.info(
            f"[WCF] private chats answered for: "
            f"{allowed or 'nobody (whitelist empty)'}"
        )

        self._refresh_contacts()
        self.report_startup_success()

        self.gateway.subscribe(self._handle_wxmsg)
        logger.info("[WCF] receiving messages")
        while self.gateway.is_running:
            time.sleep(1)

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
            # inside ChatChannel._compose_context (overridden per room by
            # ``room_allowed``), which this must not shadow.
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
            state=get_contact_state(),
        )

    def room_allowed(self, roomid):
        """Has the operator decided about this room in the console?

        Three answers, not two: True and False are the console's switch, and
        None means nobody has touched this room, so the decision belongs to
        ``group_name_white_list`` in ``ChatChannel`` where it always has. The
        console switch is keyed by ``roomid`` rather than by group name because
        a group's name is chosen by its members and can change under us.
        """
        state = get_contact_state()
        # A lost switch document is a refusal, not an absence of opinion:
        # ``group_name_white_list`` is ``ALL_GROUP`` on plenty of installs, and
        # deferring to it here would readmit every room the operator had
        # switched off.
        if state.degraded:
            return False
        if not state.has(roomid, "allowed"):
            return None
        return state.is_allowed(roomid)

    def at_free_session(self, session_id) -> bool:
        """True when this room was opened for replies without an @mention."""
        return get_contact_state().at_free(session_id)

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
    def _send_text(self, text, receiver, aters="") -> int:
        """Hand one text message to whichever transport this channel has.

        Returns WeChat's own status: 0 is delivered, anything else is not. The
        no-transport case answers -1 rather than raising, so both callers treat
        "not connected" the same way they treat "WeChat refused it" -- neither
        one delivered the message, and the difference is for the log.
        """
        if self.gateway:
            return self.gateway.send_text(text, receiver, aters)
        if self.wcf:
            return self.wcf.send_text(msg=text, receiver=receiver, aters=aters)
        logger.error("[WCF] no connection to WeChat")
        return -1

    def send_as_operator(self, receiver, text) -> bool:
        """Send a message the operator typed in the console. True when it left.

        Deliberately not routed through ``send``: that path enforces the
        observe-only switch, and this is the person that switch hands the
        conversation to. Silencing the agent must not silence them.

        The message goes out under the operator's own WeChat account, because
        that is the only account there is -- the contact sees an ordinary
        message from them, with nothing marking it as console-typed.
        """
        receiver = (receiver or "").strip()
        text = (text or "").strip()
        if not receiver or not text:
            logger.warning("[WCF] operator send: empty receiver or message")
            return False

        status = self._send_text(text, receiver)
        if status == 0:
            logger.info(f"[WCF] operator sent text to {receiver}")
            return True
        logger.error(
            f"[WCF] operator send to {receiver} failed (status={status}); "
            f"the message may not have been delivered."
        )
        return False

    def send(self, reply: Reply, context: Context):
        receiver = context.get("receiver")
        if not receiver:
            logger.error("[WCF] send: empty receiver")
            return

        # Manual takeover. Checked here, at the last point before the wire,
        # rather than earlier where the reply is generated: this is the one
        # place every outbound path funnels through, so a switch honoured here
        # cannot be bypassed by a plugin or a future caller. The cost is that
        # the model has already answered by now and the answer is discarded --
        # worth it, because the failure mode of the cheaper check is a message
        # the operator thought they had intercepted arriving anyway.
        if not get_contact_state().auto_answer(receiver):
            logger.info(f"[WCF] observe-only: reply to {receiver} withheld")
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
            status = self._send_text(reply.content, receiver, aters)
            if status == 0:
                logger.info(f"[WCF] sent text to {receiver}")
            else:
                logger.error(
                    f"[WCF] send to {receiver} failed (status={status}); the "
                    f"reply may not have been delivered."
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
        if self.gateway is not None:
            self.gateway.close()
        elif self.wcf is not None:
            try:
                self.wcf.disable_recv_msg()
            except Exception as e:
                logger.debug(f"[WCF] disable_recv_msg: {e}")
