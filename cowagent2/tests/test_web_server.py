"""Tests for the CowAgent 2 localhost web console.

Every fixture is injected. The console defaults to the process singletons,
which are bound to the operator's live ``data/whitelist.json`` and
``data/contacts_cache.json``; a test that used them would rewrite real
runtime state.
"""

import json
import os
import tempfile
import unittest

from aiohttp.test_utils import AioHTTPTestCase

from cowagent2.config import Config
from cowagent2.memory import SessionMemoryManager
from cowagent2.scanner import ContactScanner
from cowagent2.web_server import WebServer, _escape_sql_like


class TestWebServer(AioHTTPTestCase):
    async def get_application(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp = self._tmpdir.name

        config = Config(whitelist_path=os.path.join(tmp, "whitelist.json"))
        scanner = ContactScanner(cache_path=os.path.join(tmp, "contacts_cache.json"))

        self.cow_web_server = WebServer(
            host="127.0.0.1",
            port=9900,
            scanner=scanner,
            config=config,
            memory=SessionMemoryManager(),
        )
        return self.cow_web_server.app

    async def tearDownAsync(self):
        self._tmpdir.cleanup()
        await super().tearDownAsync()

    async def test_status_endpoint(self):
        resp = await self.client.request("GET", "/api/status")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("status", data)
        self.assertIn("wechat_process_running", data)
        self.assertIn("wcf_connected", data)

    async def test_contacts_endpoint(self):
        resp = await self.client.request("GET", "/api/contacts")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["status"], "success")
        self.assertIsInstance(data["contacts"], list)

    async def test_whitelist_toggle(self):
        resp = await self.client.request(
            "POST",
            "/api/whitelist",
            json={"target_id": "test_contact_123", "is_group": False, "enable": True},
        )
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["target_id"], "test_contact_123")
        self.assertTrue(data["enable"])

        resp2 = await self.client.request(
            "POST",
            "/api/whitelist",
            json={"target_id": "test_contact_123", "is_group": False, "enable": False},
        )
        data2 = await resp2.json()
        self.assertFalse(data2["enable"])

    async def test_toggling_a_room_authorises_that_room(self):
        """A room enabled in the console must read back as authorised.

        Regression: the console wrote the room into ``allowed_rooms`` while
        the bot's single-argument check compared it against ``allowed_wxids``,
        so every group chat stayed silent after being switched on.
        """
        room = "12345678@chatroom"
        resp = await self.client.request(
            "POST",
            "/api/whitelist",
            json={"target_id": room, "is_group": True, "enable": True},
        )
        self.assertEqual(resp.status, 200)

        config = self.cow_web_server.config
        self.assertIn(room, config.whitelist["allowed_rooms"])
        self.assertTrue(config.is_allowed(room, True))
        # The suffix alone is enough to route the lookup to the room list.
        self.assertTrue(config.is_allowed(room))

    async def test_whitelist_writes_stay_in_the_injected_file(self):
        """Console writes must not touch the operator's live whitelist."""
        await self.client.request(
            "POST",
            "/api/whitelist",
            json={"target_id": "scratch_contact", "is_group": False, "enable": True},
        )
        with open(self.cow_web_server.config.whitelist_path, encoding="utf-8") as f:
            persisted = json.load(f)
        self.assertIn("scratch_contact", persisted["allowed_wxids"])
        self.assertTrue(
            self.cow_web_server.config.whitelist_path.startswith(self._tmpdir.name)
        )

    async def test_sessions_endpoint(self):
        self.cow_web_server.memory.add_user_message("test_sid", "Hello")
        resp = await self.client.request("GET", "/api/sessions")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["status"], "success")
        sids = [s["session_id"] for s in data["sessions"]]
        self.assertIn("test_sid", sids)

        resp_hist = await self.client.request("GET", "/api/sessions/test_sid/history")
        self.assertEqual(resp_hist.status, 200)
        data_hist = await resp_hist.json()
        self.assertEqual(len(data_hist["messages"]), 1)
        self.assertEqual(data_hist["messages"][0]["content"], "Hello")

    async def test_raw_sql_is_refused_unless_explicitly_enabled(self):
        self.assertFalse(self.cow_web_server.config.debug_sql_enabled)
        resp = await self.client.request(
            "GET", "/api/debug_db", params={"sql": "SELECT 1;"}
        )
        self.assertEqual(resp.status, 403)
        data = await resp.json()
        self.assertIn("cowagent2_debug_sql", data["message"])


class TestSqlLikeEscaping(unittest.TestCase):
    """The search term is interpolated into SQL, so it must be inert."""

    def test_quote_cannot_close_the_literal(self):
        self.assertEqual(_escape_sql_like("o'neil"), "o''neil")

    def test_wildcards_are_escaped(self):
        self.assertEqual(_escape_sql_like("100%"), "100\\%")
        self.assertEqual(_escape_sql_like("a_b"), "a\\_b")

    def test_escape_character_is_escaped_first(self):
        self.assertEqual(_escape_sql_like("a" + chr(92) + "b"), "a" + chr(92) * 2 + "b")


if __name__ == "__main__":
    unittest.main()
