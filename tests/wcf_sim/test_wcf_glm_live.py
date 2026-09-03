"""The real thing: fake WeChat -> real wcferry client -> real GLM -> back.

Opt-in. These cost money and need network, so they carry @pytest.mark.live and
pyproject's default `addopts = -m 'not live'` deselects them. Run with:

    ZHIPU_AI_API_KEY=... python -m pytest tests/wcf_sim -m live

The key is read from the environment, never from config.json -- config.json is
git-ignored and holds a live key, and a test that reaches into it would make
that key a test dependency.
"""

import os

import pytest

from .wcf_bridge_probe import handle

pytestmark = pytest.mark.live

MODEL = os.environ.get("COW_TEST_GLM_MODEL", "glm-4.7-flash")


@pytest.fixture(scope="module")
def glm_reply():
    """A reply_fn backed by the real Zhipu GLM API."""
    key = os.environ.get("ZHIPU_AI_API_KEY", "").strip()
    if not key:
        pytest.skip("ZHIPU_AI_API_KEY is not set; live GLM tests skipped")
    zai = pytest.importorskip("zai", reason="zai-sdk not installed")
    client = zai.ZhipuAiClient(api_key=key)

    def reply_fn(query, session_id):
        rsp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content":
                 "You are a terse assistant inside a WeChat bot. Answer in under 20 words."},
                {"role": "user", "content": query},
            ],
        )
        return (rsp.choices[0].message.content or "").strip()

    return reply_fn


def test_a_private_question_gets_a_real_glm_answer(wcf_client, wcf_server, glm_reply):
    wcf_client.enable_receiving_msg()
    assert wcf_server.wait_until_receiving()
    wcf_server.push("Reply with exactly the single word: PONG", sender="wxid_alice")

    msg = wcf_client.get_msg()
    result = handle(msg, wcf_server.self_wxid, glm_reply)
    for d in result.deliveries:
        wcf_client.send_text(d.text, d.receiver, d.aters)

    assert len(wcf_server.sent) == 1, "the model produced no reply"
    sent = wcf_server.sent[0]
    assert sent["receiver"] == "wxid_alice"
    assert "PONG" in sent["msg"].upper()


def test_a_group_mention_gets_a_real_glm_answer_in_the_room(wcf_client, wcf_server, glm_reply):
    wcf_client.enable_receiving_msg()
    assert wcf_server.wait_until_receiving()
    wcf_server.push_group_at(
        "@CowAgent What is 2+2? Answer with the digit only.",
        at_wxid=wcf_server.self_wxid, sender="wxid_bob", roomid="room1@chatroom",
    )

    msg = wcf_client.get_msg()
    result = handle(msg, wcf_server.self_wxid, glm_reply)
    for d in result.deliveries:
        wcf_client.send_text(d.text, d.receiver, d.aters)

    assert len(wcf_server.sent) == 1
    sent = wcf_server.sent[0]
    assert sent["receiver"] == "room1@chatroom"
    assert sent["aters"] == "wxid_bob"
    assert "4" in sent["msg"]


def test_the_configured_bridge_routes_to_the_glm_bot():
    """config.json's model must actually resolve to the Zhipu bot.

    Cheap but load-bearing: a typo in `model` silently falls back to the
    OpenAI-compatible path and fails on the Windows host, not here.
    """
    import config
    config.load_config()
    from bridge.bridge import Bridge

    assert Bridge().btype["chat"] == "zhipu"
