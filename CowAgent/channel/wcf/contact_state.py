# encoding:utf-8

"""Per-contact and per-room switches the operator flips in the console.

``contact_filter`` answers "may this contact reach the agent" from a flat list
in ``config.json``. That list cannot express the rest of what the console now
offers -- whether the agent answers on its own or the operator has taken the
conversation over, and whether a room needs an @mention -- and it is the wrong
file to rewrite on every toggle: the console's config editor holds the whole
document in a textarea, so a switch flipped mid-edit would be lost on save.

So the switches live here instead, in their own small document, keyed by the
session id the rest of the system already uses: a ``wxid`` for a contact and a
``roomid`` for a room.

Every read fails closed. A session with no record is *not* allowed by this
store -- the caller falls back to the ``config.json`` list, which is what keeps
existing installs working -- and a record that has been hand-edited into
something that is not a boolean is treated as absent rather than as consent. A
malformed document has to narrow this gate, never widen it.
"""

import json
import os
import tempfile
import threading

from common.log import logger
from config import get_data_root

# A session id ending in this addresses a chatroom rather than a person.
CHATROOM_SUFFIX = "@chatroom"

# What a switch means for a session the operator has never touched.
#
# ``allowed`` is False because permission is the operator's to grant.
# ``auto_answer`` is True because whitelisting someone is how you ask the agent
# to answer them -- a contact who was allowed but silent would look broken.
# ``at_free`` is False because that is how group chats behave today: without an
# @mention the message is ignored.
_DEFAULTS = {"allowed": False, "auto_answer": True, "at_free": False}

# What every switch reads as once the document exists but cannot be parsed.
#
# The defaults above are for a session nobody has decided about yet. A document
# that is present and unreadable is a different thing: the operator did make
# decisions and they have been lost. Reading `auto_answer` as its default there
# would put the agent back to answering, on its own, in exactly the
# conversations the operator had taken over by hand -- so a lost document
# silences everything until it is fixed.
_DEGRADED = {"allowed": False, "auto_answer": False, "at_free": False}


def default_state_path() -> str:
    """Where the switches live for this install.

    Alongside ``config.json`` under the data root rather than in an Agent's
    workspace: a contact is a property of the WeChat account, and every Agent
    on this host talks to the same one.
    """
    return os.path.join(get_data_root(), "wcf", "contacts_state.json")


def is_group_session(session_id: str) -> bool:
    """True when a session id addresses a chatroom rather than a contact."""
    return bool(session_id) and session_id.endswith(CHATROOM_SUFFIX)


class ContactState:
    """The switch document, loaded once and written through on every change."""

    def __init__(self, state_path: str = None):
        # Overridable so a test never reads or writes the operator's real file.
        self.state_path = state_path or default_state_path()
        # The console writes from the web thread while the channel reads from
        # the WCF thread.
        self._lock = threading.Lock()
        # Held for a whole save. Separate from _lock so a write to disk never
        # blocks a gate check on the WeChat thread, but two savers can never
        # publish over each other.
        self._save_lock = threading.Lock()
        self._sessions = {}
        # True once the document was found but could not be read. Every switch
        # then denies, and callers must not fall back to config.json: the
        # operator's decisions are missing, not absent.
        self._degraded = False
        self.load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def load(self) -> None:
        """Read the document, discarding anything that is not a switch record.

        A file that cannot be parsed leaves the store empty, which denies
        everyone rather than crashing the channel that asked.
        """
        if not os.path.exists(self.state_path):
            # No document yet: a fresh install, not a lost one.
            self._degraded = False
            return
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error(
                f"[ContactState] Unreadable switch file, denying all and "
                f"silencing the agent until it is repaired: {e}"
            )
            self._degraded = True
            return

        raw = data.get("sessions") if isinstance(data, dict) else None
        if not isinstance(raw, dict):
            logger.error("[ContactState] Switch file has no sessions map, denying all")
            self._degraded = True
            return

        sessions = {}
        for session_id, entry in raw.items():
            # An entry that is not a record cannot say anything about
            # permission, so it says nothing at all.
            if isinstance(session_id, str) and session_id and isinstance(entry, dict):
                sessions[session_id] = entry
        with self._lock:
            self._sessions = sessions
        self._degraded = False
        logger.info(f"[ContactState] Loaded switches for {len(sessions)} sessions")

    def save(self) -> None:
        """Write the document atomically.

        A direct write that is interrupted leaves truncated JSON, and the next
        load would then deny every contact the operator had allowed. Writing a
        temporary file and replacing it means a reader sees either the old
        document or the new one.
        """
        directory = os.path.dirname(self.state_path) or "."
        # One writer at a time. A shared temp filename let two console requests
        # interleave their json.dump into the same file and then race
        # os.replace, publishing a torn document -- which the next load reads as
        # "every switch the operator ever set is gone".
        with self._save_lock:
            tmp_path = None
            try:
                os.makedirs(directory, exist_ok=True)
                with self._lock:
                    payload = {"sessions": dict(self._sessions)}
                fd, tmp_path = tempfile.mkstemp(
                    dir=directory, prefix=".contacts_state-", suffix=".tmp"
                )
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, self.state_path)
                tmp_path = None
            except Exception as e:
                logger.error(f"[ContactState] Failed to save switches: {e}")
            finally:
                # A temp file left behind by a failed write is not the document
                # and must not be mistaken for one later.
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def get(self, session_id: str):
        """The stored record for one session, or None when there is none."""
        if not session_id:
            return None
        with self._lock:
            entry = self._sessions.get(session_id)
        return dict(entry) if entry is not None else None

    @property
    def degraded(self) -> bool:
        """True when the document exists but could not be read.

        Callers that would otherwise fall back to a broader permission source
        must not do so while this holds: the fallback would answer a question
        the operator has already answered, using a setting that predates their
        answer.
        """
        return self._degraded

    def has(self, session_id: str, key: str) -> bool:
        """Whether the operator has actually set this switch for this session.

        The difference between "switched off" and "never touched" is the whole
        of the fallback rule: an untouched session defers to the
        ``config.json`` whitelist, a switched-off one does not.
        """
        entry = self.get(session_id)
        return isinstance(entry, dict) and isinstance(entry.get(key), bool)

    def _flag(self, session_id: str, key: str) -> bool:
        """One switch, falling back to its default.

        Only a real boolean counts. A string, a number or a list in a switch's
        place is a malformed document, and reading it for truthiness is how
        ``"no"`` would come to mean yes.
        """
        if self._degraded:
            return _DEGRADED[key]
        entry = self.get(session_id)
        if entry is None:
            return _DEFAULTS[key]
        value = entry.get(key)
        return value if isinstance(value, bool) else _DEFAULTS[key]

    def is_allowed(self, session_id: str) -> bool:
        """Whether this store grants this session access to the agent."""
        return self._flag(session_id, "allowed")

    def auto_answer(self, session_id: str) -> bool:
        """False when the operator has taken this conversation over by hand."""
        return self._flag(session_id, "auto_answer")

    def at_free(self, session_id: str) -> bool:
        """True when this room is answered without needing an @mention."""
        return self._flag(session_id, "at_free")

    def snapshot(self, session_id: str) -> dict:
        """Every switch for one session, defaults filled in, for the console."""
        return {key: self._flag(session_id, key) for key in _DEFAULTS}

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    def _set(self, session_id: str, key: str, value: bool) -> None:
        if not session_id:
            logger.warning(f"[ContactState] Ignored {key} toggle for an empty id")
            return
        with self._lock:
            entry = dict(self._sessions.get(session_id) or {})
            entry[key] = bool(value)
            self._sessions[session_id] = entry
        self.save()

    def set_allowed(self, session_id: str, value: bool) -> None:
        self._set(session_id, "allowed", value)

    def set_auto_answer(self, session_id: str, value: bool) -> None:
        self._set(session_id, "auto_answer", value)

    def set_at_free(self, session_id: str, value: bool) -> None:
        self._set(session_id, "at_free", value)


# ----------------------------------------------------------------------------
# Process-wide instance
# ----------------------------------------------------------------------------
# The switches are read on every inbound message and written from the console's
# web thread, so the document is held once for the process rather than re-read
# per call. ``set_contact_state`` exists for tests, which must never touch the
# operator's real file, and for a future reload.
_state = None


def get_contact_state() -> ContactState:
    """The switch store for this process, created on first use."""
    global _state
    if _state is None:
        _state = ContactState()
    return _state


def set_contact_state(state) -> None:
    """Replace the process-wide store; ``None`` drops it so the next read
    rebuilds from disk."""
    global _state
    _state = state
