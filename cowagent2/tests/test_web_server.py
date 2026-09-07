"""
Tests for WebServer in cowagent2.
"""

import unittest
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
from cowagent2.web_server import WebServer


class TestWebServer(AioHTTPTestCase):
    async def get_application(self):
        self.cow_web_server = WebServer(host="127.0.0.1", port=9900)
        return self.cow_web_server.app

    @unittest_run_loop
    async def test_status_endpoint(self):
        resp = await self.client.request("GET", "/api/status")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertIn("status", data)
        self.assertIn("wechat_process_running", data)
        self.assertIn("wcf_connected", data)

    @unittest_run_loop
    async def test_contacts_endpoint(self):
        resp = await self.client.request("GET", "/api/contacts")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["status"], "success")
        self.assertIsInstance(data["contacts"], list)

    @unittest_run_loop
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

        # Check toggle disable
        resp2 = await self.client.request(
            "POST",
            "/api/whitelist",
            json={"target_id": "test_contact_123", "is_group": False, "enable": False},
        )
        data2 = await resp2.json()
        self.assertFalse(data2["enable"])

    @unittest_run_loop
    async def test_sessions_endpoint(self):
        # Insert a test message into memory
        self.cow_web_server.memory.add_user_message("test_sid", "Hello")
        resp = await self.client.request("GET", "/api/sessions")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["status"], "success")
        sids = [s["session_id"] for s in data["sessions"]]
        self.assertIn("test_sid", sids)

        # Check history endpoint
        resp_hist = await self.client.request("GET", "/api/sessions/test_sid/history")
        self.assertEqual(resp_hist.status, 200)
        data_hist = await resp_hist.json()
        self.assertEqual(len(data_hist["messages"]), 1)
        self.assertEqual(data_hist["messages"][0]["content"], "Hello")


if __name__ == "__main__":
    unittest.main()
