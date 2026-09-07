# encoding:utf-8

"""WeChatFerry ``WxMsg`` -> CowAgent-Rev ``ChatMessage``.

``ChatChannel`` consumes the unified contract in ``channel/chat_message.py``
(6 fields for a group message, 8 for a private one). This class fills it in
from a ``wcferry.WxMsg``.

Milestone 4.2 handles **text only**. Any other ``WxMsg.type`` raises
``NotImplementedError`` so ``WcfChannel._handle_wxmsg`` can log-and-skip it
until Milestone 4.3 adds image / voice / file download.

The three decisions this mapping exists to get right (see
``tests/wcf_sim/wcf_bridge_probe.py``):

1. **who to answer** — in a group the reply target is ``roomid``, never the
   speaker, so ``other_user_id`` (which the base class copies into
   ``receiver``) is set to the room.
2. **when to answer a group** — only when the bot is in ``<atuserlist>``;
   ``WxMsg.is_at`` reads that from the raw XML, not from the visible text.
3. **what the model sees** — the literal ``@Name`` prefix WeChat prepends
   (separated by U+2005) is stripped by the base class once ``at_list``
   carries the bot's display name.
"""

from bridge.context import ContextType
from channel.chat_message import ChatMessage

# WxMsg.type == 1 is a plain text message (wcferry get_msg_types()).
_TYPE_TEXT = 1


class WcfMessage(ChatMessage):
    def __init__(self, channel, wcf_msg, is_group=False):
        super().__init__(wcf_msg)

        self.msg_id = str(wcf_msg.id)
        self.create_time = wcf_msg.ts
        self.is_group = bool(is_group or wcf_msg.from_group())
        self.my_msg = wcf_msg.from_self()

        self_wxid = channel.user_id
        self_name = channel.name or ""

        if wcf_msg.type == _TYPE_TEXT:
            self.ctype = ContextType.TEXT
            self.content = wcf_msg.content or ""
        else:
            raise NotImplementedError(
                f"WCF message type {wcf_msg.type} is not supported yet (Milestone 4.3)"
            )

        sender = wcf_msg.sender
        self.from_user_id = sender
        self.from_user_nickname = channel.get_display_name(sender)
        self.to_user_id = self_wxid
        self.to_user_nickname = self_name

        if self.is_group:
            room = wcf_msg.roomid
            self.other_user_id = room
            self.other_user_nickname = channel.get_display_name(room)
            self.actual_user_id = sender
            self.actual_user_nickname = (
                channel.get_room_alias(sender, room) or self.from_user_nickname
            )
            self.is_at = wcf_msg.is_at(self_wxid)
            # at_list feeds the base class's "@<name> " prefix stripping.
            # WeChat only ever prepends the bot's own display name, so listing
            # that (plus any room alias) is enough.
            self.self_display_name = channel.get_room_alias(self_wxid, room) or self_name
            self.at_list = [n for n in (self_name, self.self_display_name) if n]
        else:
            self.other_user_id = sender
            self.other_user_nickname = self.from_user_nickname
            self.actual_user_id = sender
            self.actual_user_nickname = self.from_user_nickname
            self.is_at = False
