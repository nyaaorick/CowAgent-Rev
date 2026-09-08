# encoding:utf-8

"""Whose long-term memory a turn belongs to.

Memory is stored per person on disk (``memory/users/<id>/``) or shared
(``memory/*.md``), and ``scope`` is inferred from that path when the index is
built -- see ``manager.py``. Both the write side (MemoryFlushManager) and the
read side (MemoryManager.search) already take a ``user_id``; nothing ever
supplied one, so every conversation wrote and read the same shared pile.

That is the right answer for the console, where every conversation is the
operator talking to their own agent. It is the wrong answer for WeChat, where
each conversation is a different person: what the agent learns about one
contact would surface while it talks to another.

The rule here is deliberately narrow. A channel is listed only when its
sessions genuinely belong to different people; everything else keeps the
shared pile it has always had, so this changes nothing for existing installs.
"""

import re
from typing import Optional

from common import const

# Channels where each session is a different person, so memory has to be
# partitioned. Web and terminal are one operator talking to their own agent --
# splitting those would fragment one person's memory across conversations,
# which is worse than sharing it.
PER_PERSON_CHANNELS = frozenset({const.WCF})

# A wxid becomes a directory name, and it arrives from WeChat rather than from
# us. Keep the characters real ids actually use (``wxid_a1b2``,
# ``25984...@openim``, ``room@chatroom``) and fold anything else into "_", so a
# hostile or malformed id cannot climb out of memory/users/.
_SAFE_ID = re.compile(r"[^A-Za-z0-9_.@-]")

# Long enough for any real id, short enough to stay well inside MAX_PATH once
# the workspace prefix and a filename are added.
_MAX_ID_LEN = 64


def sanitize_owner_id(raw) -> Optional[str]:
    """A filesystem-safe directory name for an owner id, or None if unusable.

    Returns None rather than a fallback for anything that cannot be made into
    a distinct directory name: a caller that gets None writes to the shared
    pile, which is the pre-existing behaviour and never the wrong *place* --
    only a less private one. Inventing a name instead risks two different
    people colliding in one directory, which is the actual harm.
    """
    if not raw:
        return None
    cleaned = _SAFE_ID.sub("_", str(raw).strip())[:_MAX_ID_LEN]
    # "." and ".." survive the character filter but are not names.
    if not cleaned or set(cleaned) <= {".", "_"}:
        return None
    return cleaned


def memory_owner_id(context) -> Optional[str]:
    """The owner of this turn's memory, or None to use the shared pile.

    Derived from ``session_id`` rather than from the sender, so memory is
    partitioned exactly the way the conversation is: one WeChat contact is one
    session and one memory, and a group room is one shared room memory rather
    than a scattering of per-speaker ones.
    """
    if not context:
        return None
    channel = (context.get("channel_type") or "").strip()
    if channel not in PER_PERSON_CHANNELS:
        return None
    return sanitize_owner_id(context.get("session_id"))
