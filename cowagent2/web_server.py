"""
cowagent2.web_server
~~~~~~~~~~~~~~~~~~~~
Localhost Web Console backend for CowAgent 2 (running at http://127.0.0.1:9900).
Features:
- Live WeChat process & login health monitoring.
- Discovered contacts & chatrooms table with instant whitelist toggle.
- Real-time Server-Sent Events (SSE) live chat streaming (reusing CowAgent web concepts).
- Session inspector & conversation history browser.
- Safe test-message transmission.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Any

from aiohttp import web

from cowagent2.config import get_config
from cowagent2.memory import get_memory_manager
from cowagent2.scanner import ContactScanner
from cowagent2.wcf_gateway import WcfGateway

logger = logging.getLogger("cowagent2.web_server")

STATIC_DIR = Path(__file__).parent / "static"


class WebServer:
    """Asynchronous Web Server managing REST endpoints and SSE live stream."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9900,
        gateway: Optional[WcfGateway] = None,
        scanner: Optional[ContactScanner] = None,
    ):
        self.host = host
        self.port = port
        self.config = get_config()
        self.gateway = gateway or WcfGateway.get_instance()
        self.scanner = scanner or ContactScanner(wcf_client=self.gateway.wcf)
        self.memory = get_memory_manager()
        self.app = web.Application()
        self._sse_queues: Set[asyncio.Queue] = set()
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._setup_routes()

    def _setup_routes(self) -> None:
        self.app.router.add_get("/api/status", self.handle_status)
        self.app.router.add_get("/api/contacts", self.handle_contacts)
        self.app.router.add_post("/api/whitelist", self.handle_toggle_whitelist)
        self.app.router.add_post("/api/auto_reply", self.handle_toggle_auto_reply)
        self.app.router.add_post("/api/scan", self.handle_scan)
        self.app.router.add_get("/api/sessions", self.handle_sessions)
        self.app.router.add_get("/api/sessions/{session_id}/history", self.handle_session_history)
        self.app.router.add_post("/api/sessions/{session_id}/clear", self.handle_session_clear)
        self.app.router.add_get("/api/stream", self.handle_sse_stream)
        self.app.router.add_post("/api/test_send", self.handle_test_send)
        self.app.router.add_post("/api/contacts/add", self.handle_add_contact)
        self.app.router.add_post("/api/contacts/update", self.handle_update_contact)
        self.app.router.add_get("/api/debug_db", self.handle_debug_db)

        # Static assets and index
        if STATIC_DIR.exists():
            self.app.router.add_get("/", self.handle_index)
            self.app.router.add_static("/static/", path=str(STATIC_DIR), name="static")

    async def handle_index(self, request: web.Request) -> web.FileResponse:
        index_file = STATIC_DIR / "index.html"
        return web.FileResponse(str(index_file))

    async def handle_status(self, request: web.Request) -> web.Response:
        """System health and connection status."""
        wx_process = WcfGateway.is_wechat_process_running()
        is_login = self.gateway.is_login()
        user_info = self.gateway.get_user_info() if is_login else {}
        session_stats = self.memory.get_session_stats()

        data = {
            "status": "online" if is_login else ("waiting_login" if wx_process else "no_wechat"),
            "wechat_process_running": wx_process,
            "wcf_connected": bool(self.gateway.wcf and self.gateway.is_running),
            "is_login": is_login,
            "user_info": user_info,
            "active_sessions_count": len(session_stats),
            "whitelisted_contacts": len(self.config.whitelist.get("allowed_wxids", [])),
            "whitelisted_rooms": len(self.config.whitelist.get("allowed_rooms", [])),
            "whitelist_enabled": self.config.whitelist.get("enabled", True),
            "model": self.config.model,
        }
        return web.json_response(data)

    async def handle_contacts(self, request: web.Request) -> web.Response:
        """Get discovered contacts with whitelist toggle state."""
        contacts = self.scanner.get_contacts_with_whitelist(self.config)
        return web.json_response({"status": "success", "contacts": contacts})

    async def handle_toggle_whitelist(self, request: web.Request) -> web.Response:
        """Toggle whitelist status for a contact or chatroom."""
        try:
            body = await request.json()
            target_id = body.get("target_id", "").strip()
            is_group = bool(body.get("is_group", False))
            enable = bool(body.get("enable", False))

            if not target_id:
                return web.json_response({"status": "error", "message": "target_id is required"}, status=400)

            self.config.toggle_whitelist(target_id, is_group=is_group, enable=enable)
            logger.info(f"Whitelist updated: target={target_id} is_group={is_group} enable={enable}")

            await self.broadcast_event("whitelist_updated", {
                "target_id": target_id,
                "is_group": is_group,
                "enable": enable,
            })

            return web.json_response({"status": "success", "target_id": target_id, "enable": enable})
        except Exception as e:
            logger.error(f"Error updating whitelist: {e}")
            return web.json_response({"status": "error", "message": str(e)}, status=500)

    async def handle_toggle_auto_reply(self, request: web.Request) -> web.Response:
        """Toggle auto-reply status for a contact or chatroom."""
        try:
            body = await request.json()
            target_id = body.get("target_id", "").strip()
            enable = bool(body.get("enable", False))

            if not target_id:
                return web.json_response({"status": "error", "message": "target_id is required"}, status=400)

            self.config.set_session_auto_reply(target_id, enable=enable)
            return web.json_response({"status": "success", "target_id": target_id, "auto_reply": enable})
        except Exception as e:
            return web.json_response({"status": "error", "message": str(e)}, status=500)

    async def handle_add_contact(self, request: web.Request) -> web.Response:
        """Manually add or bind a contact / chatroom wxid."""
        try:
            body = await request.json()
            target_id = body.get("target_id", "").strip()
            name = body.get("name", "").strip()
            remark = body.get("remark", "").strip()
            alias = body.get("alias", "").strip()
            is_group = bool(body.get("is_group", target_id.endswith("@chatroom")))
            auto_allow = bool(body.get("auto_allow", True))

            if not target_id:
                return web.json_response({"status": "error", "message": "target_id is required"}, status=400)

            item = self.scanner.register_or_update(
                target_id=target_id,
                name=name,
                remark=remark,
                alias=alias,
                is_group=is_group,
                source="manual",
            )
            if auto_allow:
                self.config.toggle_whitelist(target_id, is_group=is_group, enable=True)

            await self.broadcast_event("whitelist_updated", {
                "target_id": target_id,
                "is_group": is_group,
                "enable": True,
            })
            return web.json_response({"status": "success", "contact": item})
        except Exception as e:
            logger.error(f"Error manually adding contact: {e}")
            return web.json_response({"status": "error", "message": str(e)}, status=500)

    async def handle_update_contact(self, request: web.Request) -> web.Response:
        """Update display name, remark, or alias of an existing contact."""
        try:
            body = await request.json()
            target_id = body.get("target_id", "").strip()
            name = body.get("name", "").strip()
            remark = body.get("remark", "").strip()
            alias = body.get("alias", "").strip()

            if not target_id:
                return web.json_response({"status": "error", "message": "target_id is required"}, status=400)

            item = self.scanner.register_or_update(
                target_id=target_id,
                name=name,
                remark=remark,
                alias=alias,
                source="manual",
            )
            await self.broadcast_event("contact_updated", {"contact": item})
            return web.json_response({"status": "success", "contact": item})
        except Exception as e:
            logger.error(f"Error updating contact: {e}")
            return web.json_response({"status": "error", "message": str(e)}, status=500)

    async def handle_scan(self, request: web.Request) -> web.Response:
        """Trigger scan and refresh contacts list."""
        try:
            contacts = self.scanner.scan()
            return web.json_response({"status": "success", "count": len(contacts)})
        except Exception as e:
            return web.json_response({"status": "error", "message": str(e)}, status=500)

    async def handle_sessions(self, request: web.Request) -> web.Response:
        """List active conversation sessions."""
        stats = self.memory.get_session_stats()
        # Merge friendly contact names
        for item in stats:
            sid = item["session_id"]
            c = self.scanner.get_contact(sid)
            if c:
                item["display_name"] = c.get("name") or c.get("nickname") or sid
                item["is_group"] = c.get("is_group", False)
            else:
                item["is_group"] = sid.endswith("@chatroom")
        return web.json_response({"status": "success", "sessions": stats})

    async def handle_session_history(self, request: web.Request) -> web.Response:
        """Get message history for a specific session."""
        session_id = request.match_info["session_id"]
        history = self.memory.get_history(session_id)
        contact = self.scanner.get_contact(session_id) or {}
        return web.json_response({
            "status": "success",
            "session_id": session_id,
            "contact": contact,
            "messages": history,
        })

    async def handle_session_clear(self, request: web.Request) -> web.Response:
        """Clear memory for a specific session."""
        session_id = request.match_info["session_id"]
        cleared = self.memory.clear_session(session_id)
        await self.broadcast_event("session_cleared", {"session_id": session_id})
        return web.json_response({"status": "success", "cleared": cleared})

    async def handle_test_send(self, request: web.Request) -> web.Response:
        """Send a test message via WCF."""
        try:
            body = await request.json()
            receiver = body.get("receiver", "filehelper").strip()
            message = body.get("message", "CowAgent 2 测试消息").strip()

            if not receiver or not message:
                return web.json_response({"status": "error", "message": "receiver and message required"}, status=400)

            ret = self.gateway.send_text(msg=message, receiver=receiver)
            return web.json_response({"status": "success", "return_code": ret})
        except Exception as e:
            return web.json_response({"status": "error", "message": str(e)}, status=500)

    async def handle_debug_db(self, request: web.Request) -> web.Response:
        wcf = self.gateway.wcf
        if not wcf:
            return web.json_response({"error": "wcf not ready"})
        try:
            sql_param = request.query.get("sql", "").strip()
            q = request.query.get("q", "").strip()
            if sql_param:
                sql = sql_param
            elif q:
                sql = f"SELECT StrTalker, StrContent, IsSender, CreateTime FROM MSG WHERE StrContent LIKE '%{q}%' ORDER BY CreateTime DESC LIMIT 10;"
            else:
                sql = "SELECT StrTalker, StrContent, IsSender, CreateTime FROM MSG WHERE StrTalker NOT LIKE '%@chatroom%' AND StrTalker != 'filehelper' ORDER BY CreateTime DESC LIMIT 25;"

            rows = wcf.query_sql("MSG0.db", sql) or []
            return web.json_response({
                "status": "success",
                "count": len(rows),
                "rows": rows,
            })
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_sse_stream(self, request: web.Request) -> web.StreamResponse:
        """
        Server-Sent Events stream for real-time live chat listening and updates.
        Reuses CowAgent SSE concepts for real-time monitoring.
        """
        response = web.StreamResponse(
            status=200,
            reason="OK",
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
            },
        )
        await response.prepare(request)

        q = asyncio.Queue()
        self._sse_queues.add(q)
        logger.info(f"New SSE client connected (total: {len(self._sse_queues)})")

        try:
            # Send initial connected greeting
            init_msg = json.dumps({"event": "connected", "time": time.time()})
            await response.write(f"data: {init_msg}\n\n".encode("utf-8"))

            while True:
                data = await q.get()
                payload = json.dumps(data, ensure_ascii=False)
                await response.write(f"data: {payload}\n\n".encode("utf-8"))
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            self._sse_queues.discard(q)
            logger.info(f"SSE client disconnected (remaining: {len(self._sse_queues)})")

        return response

    async def broadcast_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Push an event to all connected SSE clients."""
        payload = {"event": event_type, "data": data, "timestamp": time.time()}
        for q in list(self._sse_queues):
            try:
                q.put_nowait(payload)
            except Exception:
                pass

    def on_turn_completed(self, turn_data: Dict[str, Any]) -> None:
        """Callback invoked by Bot when a turn completes."""
        asyncio.run_coroutine_threadsafe(
            self.broadcast_event("chat_turn", turn_data),
            self.app.loop,
        )

    def on_raw_message(self, msg) -> None:
        """Callback to stream raw inbound messages to console."""
        try:
            content = getattr(msg, "content", "")
            sender = getattr(msg, "sender", "")
            roomid = getattr(msg, "roomid", "")
            msg_type = getattr(msg, "type", 1)
            is_group = bool(getattr(msg, "from_group", lambda: False)())
            session_id = roomid if is_group else sender

            contact = self.scanner.get_contact(session_id) or {}
            peer_name = contact.get("name") or contact.get("nickname") or session_id

            # Dynamically feed scanner with talker
            self.scanner.add_talker(session_id, is_group=is_group)

            event_data = {
                "session_id": session_id,
                "peer_name": peer_name,
                "sender": sender,
                "content": content,
                "msg_type": msg_type,
                "is_group": is_group,
                "whitelisted": self.config.is_allowed(session_id),
                "time": time.time(),
            }
            if self.app.loop and self.app.loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self.broadcast_event("inbound_msg", event_data),
                    self.app.loop,
                )
        except Exception as e:
            logger.warning(f"Error handling raw message for SSE: {e}")

    async def start(self) -> None:
        """Start aiohttp server."""
        self._runner = web.AppRunner(self.app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()
        logger.info(f"CowAgent 2 Web Console running at http://{self.host}:{self.port}")

    async def stop(self) -> None:
        """Stop aiohttp server."""
        if self._runner:
            await self._runner.cleanup()
            logger.info("CowAgent 2 Web Console stopped.")

