"""
Tests for strict session memory isolation in cowagent2.
"""

import unittest
from cowagent2.memory import SessionMemoryManager


class TestSessionMemoryIsolation(unittest.TestCase):
    def setUp(self):
        self.mem = SessionMemoryManager(max_history_turns=5)

    def test_strict_isolation_between_sessions(self):
        # Alice session
        self.mem.add_user_message("wxid_alice", "我叫爱丽丝，我喜欢苹果。")
        self.mem.add_assistant_message("wxid_alice", "你好爱丽丝，记住了你喜欢苹果。")

        # Bob session
        self.mem.add_user_message("wxid_bob", "我是鲍勃，我喜欢香蕉。")
        self.mem.add_assistant_message("wxid_bob", "你好鲍勃，记住了你喜欢香蕉。")

        # Group session
        self.mem.add_user_message("12345@chatroom", "大家晚上好！")

        alice_ctx = self.mem.get_context("wxid_alice")
        bob_ctx = self.mem.get_context("wxid_bob")
        room_ctx = self.mem.get_context("12345@chatroom")

        # Check Alice's context does NOT contain Bob's or Group's messages
        alice_contents = [m["content"] for m in alice_ctx]
        self.assertIn("我叫爱丽丝，我喜欢苹果。", alice_contents)
        self.assertNotIn("我是鲍勃，我喜欢香蕉。", alice_contents)
        self.assertNotIn("大家晚上好！", alice_contents)

        # Check Bob's context does NOT contain Alice's messages
        bob_contents = [m["content"] for m in bob_ctx]
        self.assertIn("我是鲍勃，我喜欢香蕉。", bob_contents)
        self.assertNotIn("我叫爱丽丝，我喜欢苹果。", bob_contents)

        # Check Room's context is strictly isolated
        room_contents = [m["content"] for m in room_ctx]
        self.assertEqual(room_contents, ["大家晚上好！"])

    def test_session_clear_isolation(self):
        self.mem.add_user_message("wxid_alice", "Hello")
        self.mem.add_user_message("wxid_bob", "Hi")

        self.mem.clear_session("wxid_alice")

        self.assertEqual(len(self.mem.get_context("wxid_alice")), 0)
        self.assertEqual(len(self.mem.get_context("wxid_bob")), 1)

    def test_sliding_window_trimming(self):
        # max_history_turns is 5 -> max messages is 10
        for i in range(8):
            self.mem.add_user_message("wxid_tester", f"User turn {i}")
            self.mem.add_assistant_message("wxid_tester", f"Bot reply {i}")

        history = self.mem.get_context("wxid_tester")
        self.assertLessEqual(len(history), 10)
        # Oldest turn 0 should be trimmed
        self.assertNotIn("User turn 0", [m["content"] for m in history])
        # Latest turn 7 should be present
        self.assertIn("User turn 7", [m["content"] for m in history])


if __name__ == "__main__":
    unittest.main()

