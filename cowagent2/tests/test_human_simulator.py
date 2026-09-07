"""
Tests for HumanSimulator in cowagent2.
"""

import unittest
from cowagent2.human_simulator import HumanSimulator


class TestHumanSimulator(unittest.TestCase):
    def setUp(self):
        self.sim = HumanSimulator(enabled=True)

    def test_reading_delay_bounds(self):
        short_delay = self.sim.calculate_reading_delay("Hi")
        self.assertGreaterEqual(short_delay, self.sim.min_reading_delay)
        self.assertLessEqual(short_delay, self.sim.max_reading_delay)

        long_msg = "这是一段比较长的测试消息，用来验证模拟人类阅读长句时的耗时计算是否正确处于合理的上限范围内。" * 5
        long_delay = self.sim.calculate_reading_delay(long_msg)
        self.assertLessEqual(long_delay, self.sim.max_reading_delay)

    def test_typing_delay_bounds(self):
        short_delay = self.sim.calculate_typing_delay("好的")
        self.assertGreaterEqual(short_delay, self.sim.min_typing_delay)
        self.assertLessEqual(short_delay, self.sim.max_typing_delay)

        long_reply = "好的没问题，我稍后把整理好的文档发你微信上，你先看看那个第四章的内容。" * 4
        long_delay = self.sim.calculate_typing_delay(long_reply)
        self.assertLessEqual(long_delay, self.sim.max_typing_delay)

    def test_human_system_prompt(self):
        prompt = self.sim.build_system_prompt(peer_name="小李", is_group=False)
        self.assertIn("小李", prompt)
        self.assertIn("完全模拟正常人类", prompt)
        self.assertIn("严禁出现以下机械化套话", prompt)
        # Verify it specifically forbids AI clichés
        self.assertIn("作为人工智能", prompt)
        self.assertIn("很高兴为您服务", prompt)

    def test_clean_human_reply(self):
        robotic_reply = "作为一个人工智能助手，今天天气很好。"
        cleaned = self.sim.clean_human_reply(robotic_reply)
        self.assertEqual(cleaned, "今天天气很好。")

        normal_reply = "哈哈好嘞，我晚点看下！"
        cleaned_normal = self.sim.clean_human_reply(normal_reply)
        self.assertEqual(cleaned_normal, normal_reply)


if __name__ == "__main__":
    unittest.main()

