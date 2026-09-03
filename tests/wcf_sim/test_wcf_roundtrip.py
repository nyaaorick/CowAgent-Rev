"""End-to-end WCF -> CowAgent-Rev -> WCF, with the model mocked.

Runs offline and free, in the normal suite. The live twin
(test_wcf_glm_live.py) proves the same path against the real GLM API.
"""

from .wcf_bridge_probe import handle, strip_at_prefix


def _echo(prefix="answer: "):
    def reply_fn(query, session_id):
        return f"{prefix}{query}"
    return reply_fn


def _deliver(server, client, msg, self_wxid, reply_fn):
    result = handle(msg, self_wxid, reply_fn)
    for d in result.deliveries:
        client.send_text(d.text, d.receiver, d.aters)
    return result


def test_private_message_round_trips_to_the_sender(wcf_client, wcf_server):
    wcf_client.enable_receiving_msg()
    assert wcf_server.wait_until_receiving()
    wcf_server.push("what is the capital of France", sender="wxid_alice")

    msg = wcf_client.get_msg()
    _deliver(wcf_server, wcf_client, msg, wcf_server.self_wxid, _echo())

    assert len(wcf_server.sent) == 1
    sent = wcf_server.sent[0]
    assert sent["msg"] == "answer: what is the capital of France"
    assert sent["receiver"] == "wxid_alice"


def test_group_reply_goes_to_the_room_not_the_speaker(wcf_client, wcf_server):
    wcf_client.enable_receiving_msg()
    assert wcf_server.wait_until_receiving()
    wcf_server.push_group_at("@bot hello", at_wxid=wcf_server.self_wxid,
                             sender="wxid_alice", roomid="room1@chatroom")

    msg = wcf_client.get_msg()
    _deliver(wcf_server, wcf_client, msg, wcf_server.self_wxid, _echo())

    sent = wcf_server.sent[0]
    # The reply must land in the room; sending to `sender` would DM someone who
    # spoke in a group -- the single easiest mistake in this adapter.
    assert sent["receiver"] == "room1@chatroom"
    assert sent["aters"] == "wxid_alice"


def test_group_message_without_a_mention_is_ignored(wcf_client, wcf_server):
    wcf_client.enable_receiving_msg()
    assert wcf_server.wait_until_receiving()
    wcf_server.push("just chatting among ourselves", sender="wxid_bob",
                    roomid="room1@chatroom", msg_id=7)

    msg = wcf_client.get_msg()
    result = _deliver(wcf_server, wcf_client, msg, wcf_server.self_wxid, _echo())

    assert result.deliveries == []
    assert wcf_server.sent == []


def test_the_bot_does_not_answer_itself(wcf_client, wcf_server):
    wcf_client.enable_receiving_msg()
    assert wcf_server.wait_until_receiving()
    wcf_server.push("something the bot said", sender=wcf_server.self_wxid,
                    is_self=True, msg_id=9)

    msg = wcf_client.get_msg()
    result = _deliver(wcf_server, wcf_client, msg, wcf_server.self_wxid, _echo())

    assert result.deliveries == []
    assert wcf_server.sent == []


def test_the_mention_prefix_is_stripped_before_the_model_sees_it():
    # WeChat separates the mention with U+2005, not an ordinary space.
    assert strip_at_prefix("@CowAgent what is 2+2") == "what is 2+2"
    assert strip_at_prefix("@CowAgent what is 2+2") == "what is 2+2"
    assert strip_at_prefix("no mention here") == "no mention here"
