"""A stand-in for WeChatFerry's RPC server, good enough to drive the real client.

Why this exists
---------------
`wcf.exe` only runs on Windows: it injects `spy.dll` into WeChat.exe. But the
*client* half of WeChatFerry is portable — `Wcf(host=...)` connects over nng TCP
and never loads the DLL (`_sdk_init` runs only when `host is None`). So on macOS
we can stand up a server that speaks the same wire protocol and drive it with
the genuine, unmodified `wcferry` client from the submodule.

That distinction matters: this is not a mock of the client. The client under
test is the same code the Windows host will run. Only the WeChat end is faked.

Protocol (read off WeChatFerry/clients/python/wcferry/client.py):
  * command channel — nng Pair1 on tcp://127.0.0.1:<port>. The client sends a
    serialized `wcf_pb2.Request` and blocks for one `wcf_pb2.Response`.
  * message channel — nng Pair1 on tcp://127.0.0.1:<port+1>. The server pushes
    `Response` envelopes whose `wxmsg` field carries an inbound message.
"""

from __future__ import annotations

import socket
import threading
from typing import Callable, Dict, List, Optional

import pynng

from . import wcf_proto as proto

wcf_pb2 = proto.wcf_pb2


def free_port() -> int:
    """Reserve a port pair (<p>, <p>+1) that is currently unused.

    The client derives the message channel as ``port + 1``, so both must be
    free or the test binds one socket and silently fails on the other.
    """
    for _ in range(50):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        with socket.socket() as s2:
            try:
                s2.bind(("127.0.0.1", port + 1))
            except OSError:
                continue
        return port
    raise RuntimeError("could not find a free consecutive port pair")


class FakeWcfServer:
    """Serves the subset of WeChatFerry RPCs the CowAgent-Rev adapter uses."""

    def __init__(self, port: Optional[int] = None, self_wxid: str = "wxid_cowagent_bot"):
        self.port = port or free_port()
        self.self_wxid = self_wxid
        #: every send_text the bot performed, in order — what tests assert on
        self.sent: List[Dict] = []
        #: extra handlers keyed by Functions enum, for per-test behavior
        self.handlers: Dict[int, Callable] = {}
        self._cmd_sock: Optional[pynng.Pair1] = None
        self._msg_sock: Optional[pynng.Pair1] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._msg_ready = threading.Event()
        self._recv_enabled = threading.Event()

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def start(self) -> "FakeWcfServer":
        self._cmd_sock = pynng.Pair1(listen=f"tcp://127.0.0.1:{self.port}")
        self._cmd_sock.recv_timeout = 200
        self._msg_sock = pynng.Pair1(listen=f"tcp://127.0.0.1:{self.port + 1}")
        self._running = True
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        for sock in (self._cmd_sock, self._msg_sock):
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass

    def __enter__(self) -> "FakeWcfServer":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    # ------------------------------------------------------------------
    # command channel
    # ------------------------------------------------------------------
    def _serve(self) -> None:
        while self._running:
            try:
                raw = self._cmd_sock.recv_msg().bytes
            except pynng.Timeout:
                continue
            except Exception:
                if self._running:
                    continue
                break
            req = wcf_pb2.Request()
            req.ParseFromString(raw)
            rsp = self._dispatch(req)
            try:
                self._cmd_sock.send(rsp.SerializeToString())
            except Exception:
                if not self._running:
                    break

    def _dispatch(self, req: wcf_pb2.Request) -> wcf_pb2.Response:
        rsp = wcf_pb2.Response()
        rsp.func = req.func
        F = wcf_pb2

        override = self.handlers.get(req.func)
        if override is not None:
            override(req, rsp)
            return rsp

        if req.func == F.FUNC_IS_LOGIN:
            rsp.status = 1
        elif req.func == F.FUNC_GET_SELF_WXID:
            rsp.str = self.self_wxid
        elif req.func == F.FUNC_SEND_TXT:
            self.sent.append({
                "msg": req.txt.msg,
                "receiver": req.txt.receiver,
                "aters": req.txt.aters,
            })
            rsp.status = 0
        elif req.func == F.FUNC_ENABLE_RECV_TXT:
            self._recv_enabled.set()
            rsp.status = 0
        elif req.func == F.FUNC_DISABLE_RECV_TXT:
            self._recv_enabled.clear()
            rsp.status = 0
        else:
            # Unknown call: answer rather than hang, so a test failure reads as
            # "unsupported func" instead of a five-second client timeout.
            rsp.status = -1
        return rsp

    # ------------------------------------------------------------------
    # message channel
    # ------------------------------------------------------------------
    def wait_until_receiving(self, timeout: float = 5.0) -> bool:
        """Block until the client has called enable_receiving_msg."""
        return self._recv_enabled.wait(timeout)

    def push(
        self,
        content: str,
        sender: str = "wxid_alice",
        roomid: str = "",
        msg_type: int = 1,
        is_self: bool = False,
        msg_id: int = 1,
        xml: str = "",
        extra: str = "",
    ) -> None:
        """Push one inbound message, exactly as wcf.exe would."""
        rsp = wcf_pb2.Response()
        rsp.func = wcf_pb2.FUNC_ENABLE_RECV_TXT
        m = rsp.wxmsg
        m.is_self = is_self
        m.is_group = bool(roomid)
        m.id = msg_id
        m.type = msg_type
        m.ts = 1_756_000_000
        m.roomid = roomid
        m.content = content
        m.sender = sender
        m.sign = ""
        m.thumb = ""
        m.extra = extra
        m.xml = xml
        self._msg_sock.send(rsp.SerializeToString())

    def push_group_at(self, content: str, at_wxid: str, sender: str = "wxid_alice",
                      roomid: str = "12345678@chatroom", msg_id: int = 2) -> None:
        """Push a group message that @-mentions ``at_wxid``.

        WxMsg.is_at() looks for the wxid inside <atuserlist> in the raw XML, so
        the mention has to live there — putting it only in `content` would make
        the bot ignore a message a real WeChat user would expect it to answer.
        """
        xml = (
            '<msgsource><atuserlist><![CDATA[,'
            f'{at_wxid}]]></atuserlist></msgsource>'
        )
        self.push(content=content, sender=sender, roomid=roomid,
                  msg_id=msg_id, xml=xml)
