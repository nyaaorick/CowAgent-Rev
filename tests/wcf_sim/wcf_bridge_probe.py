"""A minimal WxMsg -> Bridge -> send_text loop.

This is a *probe*, not the adapter. `channel/wcf/wcf_channel.py` (Milestone 4.2)
is the real thing: it inherits ChatChannel and inherits sessions, plugins,
permissions and the agent pipeline with it. This file exists so the wiring
between WeChatFerry and the model can be proven end-to-end on macOS *before*
that adapter exists, and so 4.2 has an executable reference for the three
decisions that are easy to get wrong:

  1. **who to reply to** — in a group the receiver is `roomid`, not `sender`;
     replying to `sender` silently direct-messages someone who spoke in a group.
  2. **when to reply in a group** — only when @-mentioned, read from
     `<atuserlist>` in the raw XML via `WxMsg.is_at`, never from a substring of
     the visible text.
  3. **what to strip** — the literal "@Name " prefix WeChat prepends, so the
     model does not see it as part of the question.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Delivery:
    """One outbound reply: what was said, and to whom."""
    text: str
    receiver: str
    aters: str = ""


@dataclass
class ProbeResult:
    deliveries: List[Delivery] = field(default_factory=list)
    ignored: List[str] = field(default_factory=list)


_AT_PREFIX = re.compile(r"^@[^\s ]+[\s ]+")


def strip_at_prefix(content: str) -> str:
    """Drop the leading '@Bot ' WeChat puts in front of a group mention.

    WeChat separates the mention from the text with U+2005 (four-per-em space),
    not a normal space, which is why a plain `split()` misses it.
    """
    return _AT_PREFIX.sub("", content or "", count=1).strip()


def route(msg, self_wxid: str) -> Optional[str]:
    """Return the receiver id to answer, or None when the bot should stay quiet."""
    if msg.from_self():
        return None
    if msg.from_group():
        # Group: answer only when addressed, and answer the room.
        return msg.roomid if msg.is_at(self_wxid) else None
    return msg.sender


def reply_for(query: str, session_id: str, reply_fn) -> str:
    """Ask the model. `reply_fn` is injected so tests can run mocked or live."""
    return reply_fn(query, session_id)


def handle(msg, self_wxid: str, reply_fn) -> ProbeResult:
    """Full inbound -> outbound decision for one message."""
    out = ProbeResult()
    receiver = route(msg, self_wxid)
    if receiver is None:
        out.ignored.append(msg.content)
        return out

    query = strip_at_prefix(msg.content) if msg.from_group() else (msg.content or "").strip()
    if not query:
        out.ignored.append(msg.content)
        return out

    answer = reply_for(query, receiver, reply_fn)
    if not answer:
        out.ignored.append(msg.content)
        return out

    # In a group, @ the person who asked so the reply is visibly addressed.
    aters = msg.sender if msg.from_group() else ""
    out.deliveries.append(Delivery(text=answer, receiver=receiver, aters=aters))
    return out
