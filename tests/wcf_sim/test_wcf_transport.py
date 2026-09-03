"""The transport half: real wcferry client <-> fake WeChatFerry server.

No CowAgent-Rev code is involved here. These tests prove the harness itself is
faithful, so that when the end-to-end tests fail we know it is the adapter and
not the simulation.
"""

import pytest


def test_client_connects_and_reports_login(wcf_client):
    assert wcf_client.is_login() is True


def test_client_reads_its_own_wxid(wcf_client, wcf_server):
    assert wcf_client.get_self_wxid() == wcf_server.self_wxid


def test_send_text_reaches_the_server(wcf_client, wcf_server):
    wcf_client.send_text("hello from the bot", "wxid_alice")

    assert len(wcf_server.sent) == 1
    assert wcf_server.sent[0]["msg"] == "hello from the bot"
    assert wcf_server.sent[0]["receiver"] == "wxid_alice"


def test_inbound_message_arrives_through_the_event_channel(wcf_client, wcf_server):
    wcf_client.enable_receiving_msg()
    assert wcf_server.wait_until_receiving()

    wcf_server.push("ping", sender="wxid_alice")

    msg = wcf_client.get_msg()
    assert msg.content == "ping"
    assert msg.sender == "wxid_alice"
    assert not msg.from_group()


def test_group_message_carries_the_mention(wcf_client, wcf_server):
    wcf_client.enable_receiving_msg()
    assert wcf_server.wait_until_receiving()

    wcf_server.push_group_at("@bot what is 2+2", at_wxid=wcf_server.self_wxid)

    msg = wcf_client.get_msg()
    assert msg.from_group()
    assert msg.roomid == "12345678@chatroom"
    # The mention must be visible the way the adapter will read it.
    assert msg.is_at(wcf_server.self_wxid)
