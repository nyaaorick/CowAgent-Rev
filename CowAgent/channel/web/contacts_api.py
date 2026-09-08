# encoding:utf-8

"""Console endpoints for the WeChat address book.

The console's left pane is a contact list rather than a list of conversations,
so it needs four things the rest of the web channel does not provide: the
catalog the scanner discovered, a way to re-run that scan on demand, the four
per-session switches, and the per-contact ``PROFILE.md`` the Workspace button
opens.

These live here rather than in ``web_channel`` because web.py resolves a
handler by class name against that module's namespace -- so the classes below
are imported there, and only the ``urls`` entries live alongside the rest.

Everything here is behind ``_require_auth``: the catalog is the operator's real
address book, and the switches decide who the agent answers.
"""

import json
import os

import web

from agent.memory.identity import sanitize_owner_id
from channel.wcf.contact_state import get_contact_state
from channel.wcf.scanner import ContactScanner
from common.log import logger

# The switches a request may set. The name arrives in a request body and is
# used to index the state document, so it is matched against this tuple rather
# than passed through -- an unrecognised name is a bug or an attack, and either
# way must not create a field the gate might later read.
SWITCHES = ("allowed", "auto_answer", "at_free")

# What a freshly created profile says. Deliberately not empty: the prompt
# loader skips a file that holds only a template placeholder, and an operator
# who opens a blank pane has nothing to react to.
_PROFILE_TEMPLATE = """# Contact profile

Notes the agent should keep in mind for this conversation - how to address
them, what they are working on, anything to avoid. Written by you; the agent's
own consolidated notes live in MEMORY.md beside this file.
"""

_scanner = None


def get_scanner() -> ContactScanner:
    """The catalog for this process, created on first use.

    Built without a client: the WeChat connection may not exist yet when the
    console first asks for the list, and a cached catalog is still worth
    showing. ``ContactsScanHandler`` supplies the live client when the operator
    presses Scan.
    """
    global _scanner
    if _scanner is None:
        _scanner = ContactScanner()
    return _scanner


def set_scanner(scanner) -> None:
    """Replace the process-wide catalog; ``None`` drops it. For tests."""
    global _scanner
    _scanner = scanner


def live_wcf_client():
    """The running WeChat connection, or None when the channel is not up.

    The console and the WeChat channel are two threads of one process
    (``app.py`` starts both), and ``WcfChannel`` is a ``@singleton``, so asking
    for it here returns the instance that is already connected rather than
    building a second one -- which would inject spy.dll twice (ROADMAP
    WCF-BUG-03).
    """
    try:
        from channel.wcf.wcf_channel import WcfChannel

        return WcfChannel().wcf
    except Exception as e:
        logger.debug(f"[ContactsAPI] no live WCF client: {e}")
        return None


# ----------------------------------------------------------------------------
# Pure helpers
# ----------------------------------------------------------------------------
def filter_rows(rows, kind: str = "", query: str = "") -> list:
    """Narrow the catalog to what one console pane is showing.

    ``kind`` is "contact" or "group"; anything else that is not empty matches
    nothing, so a typo in the query string shows an empty list rather than
    quietly mixing groups into the contact pane.

    ``query`` is matched case-insensitively against the remark, the nickname,
    the WeChat ID and the raw id -- the raw id included because on a host where
    the contact database is unreadable (ROADMAP WCF-BUG-02) it is the only
    handle the operator has.
    """
    result = rows
    if kind:
        if kind not in ("contact", "group"):
            return []
        want_group = kind == "group"
        result = [r for r in result if bool(r.get("is_group")) == want_group]

    needle = (query or "").strip().lower()
    if needle:
        result = [
            r for r in result
            if any(
                needle in str(r.get(field) or "").lower()
                for field in ("remark", "nickname", "name", "alias", "wxid")
            )
        ]
    return result


def normalize_switch(name):
    """The switch a request is asking for, or None when it names none."""
    return name if name in SWITCHES else None


def is_wechat_session(session_id: str) -> bool:
    """Does this id belong to a real WeChat contact or room?

    Answered from the address book, not from the conversation store. The store
    only knows a session's channel once a message has actually reached it, so
    a contact nobody has ever written to has no record there -- and asking the
    store first sent the operator's very first message to that contact through
    the agent instead of through WeChat, then stored the mistake as fact by
    tagging the session `web`. Every later message to the same contact
    inherited it, because there was now history to point at.

    The catalog does not have that chicken-and-egg problem: a contact is in it
    the moment a scan has ever seen them, before anyone has said a word.
    """
    if not session_id:
        return False
    try:
        return get_scanner().get_contact(session_id) is not None
    except Exception as e:
        logger.debug(f"[ContactsAPI] scanner lookup failed for {session_id}: {e}")
        return False


def ensure_profile(workspace_root: str, session_id: str) -> str:
    """The workspace-relative path of a session's profile, creating it if new.

    The directory is the one the memory subsystem already uses for this
    contact, resolved through the same ``sanitize_owner_id``: an id WeChat
    chose must not be able to name a path of its own, and the profile has to
    land beside the memory it belongs to rather than in a parallel tree.

    Raises ``ValueError`` for an id that cannot become a distinct directory
    name. Falling back to a shared directory would be worse than refusing --
    two contacts would then share one profile.
    """
    owner_id = sanitize_owner_id(session_id)
    if not owner_id:
        raise ValueError(f"unusable session id: {session_id!r}")

    rel = f"memory/users/{owner_id}/PROFILE.md"
    abs_path = os.path.join(workspace_root, "memory", "users", owner_id, "PROFILE.md")
    if not os.path.exists(abs_path):
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(_PROFILE_TEMPLATE)
        logger.info(f"[ContactsAPI] Created profile for {owner_id}")
    return rel


def relay_to_wechat(session_id: str, text: str, agent_id: str = None) -> dict:
    """Send what the operator typed to the WeChat conversation they are in.

    This is the manual half of the reply-mode switch: the console composer no
    longer refuses a WeChat conversation, it carries the message across. The
    agent is not involved -- the operator is speaking for themselves, so
    nothing is generated, prefixed or remembered as an agent turn.

    The sent text is written into the conversation store so the console shows
    it in the thread the operator is looking at. Without that the message
    leaves and the screen does not change, which reads as a failed send.

    Returns the response envelope for the caller to serialise.
    """
    text = (text or "").strip()
    if not text:
        return {"status": "error", "message": "message is required"}

    try:
        from channel.wcf.wcf_channel import WcfChannel

        channel = WcfChannel()
    except Exception as e:
        logger.error(f"[ContactsAPI] relay: WeChat channel unavailable: {e}")
        return {"status": "error", "code": "wcf_offline",
                "message": "WeChat channel is not running"}

    if not channel.send_as_operator(session_id, text):
        return {"status": "error", "code": "send_failed",
                "message": "WeChat did not accept the message"}

    try:
        from agent.memory import get_conversation_store
        from channel.web.web_channel import _get_workspace_root
        from common import const

        store = get_conversation_store(_get_workspace_root(agent_id=agent_id))
        # Self-heal channel_type: if a session was previously tagged as 'web'
        # due to routing bugs, heal it back to 'wcf'.
        if store.get_channel_type(session_id) not in ("", const.WCF):
            try:
                with store._lock:
                    conn = store._connect()
                    try:
                        with conn:
                            conn.execute(
                                "UPDATE sessions SET channel_type = ? WHERE session_id = ?",
                                (const.WCF, session_id),
                            )
                    finally:
                        conn.close()
            except Exception as heal_err:
                logger.warning(f"[ContactsAPI] channel_type self-heal failed for {session_id}: {heal_err}")

        store.append_messages(
            session_id,
            [{"role": "assistant", "content": text}],
            channel_type=const.WCF,
        )
    except Exception as e:
        # The message is already in WeChat; failing the request now would
        # invite the operator to send it a second time.
        logger.error(f"[ContactsAPI] relay: could not record the sent message: {e}")

    return {"status": "success", "relayed": True}


# ----------------------------------------------------------------------------
# Handlers
# ----------------------------------------------------------------------------
class ContactsHandler:
    """The address book, with each session's switches merged in."""

    def GET(self):
        from channel.web.web_channel import _require_auth

        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            params = web.input(kind='', q='')
            rows = get_scanner().get_all_with_state(get_contact_state())
            rows = filter_rows(rows, kind=(params.kind or '').strip(),
                               query=params.q or '')
            return json.dumps({"status": "success", "contacts": rows},
                              ensure_ascii=False)
        except Exception as e:
            logger.error(f"[ContactsAPI] list failed: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class ContactsScanHandler:
    """Re-read the address book from WeChat.

    A scan that finds nothing leaves the cached catalog alone and says so, so a
    wedged spy costs the operator a message rather than their contact list
    (AC-002).
    """

    def POST(self):
        from channel.web.web_channel import _require_auth

        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            scanner = get_scanner()
            client = live_wcf_client()
            if client is None:
                return json.dumps({
                    "status": "error",
                    "code": "wcf_offline",
                    "message": "WeChat channel is not running",
                    "total": len(scanner.catalog),
                }, ensure_ascii=False)

            total = scanner.scan_from_wcf(client)
            return json.dumps({"status": "success", "total": total})
        except Exception as e:
            logger.error(f"[ContactsAPI] scan failed: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class ContactsToggleHandler:
    """Set one switch on one session."""

    def POST(self):
        from channel.web.web_channel import _require_auth

        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            body = json.loads(web.data() or b'{}')
            session_id = (body.get("wxid") or "").strip()
            if not session_id:
                return json.dumps({"status": "error", "message": "wxid is required"})

            switch = normalize_switch(body.get("switch"))
            if not switch:
                return json.dumps({"status": "error", "message": "unknown switch"})

            value = body.get("value")
            if not isinstance(value, bool):
                return json.dumps({"status": "error",
                                   "message": "value must be a boolean"})

            state = get_contact_state()
            getattr(state, f"set_{switch}")(session_id, value)
            logger.info(f"[ContactsAPI] {session_id}: {switch} -> {value}")
            return json.dumps({"status": "success",
                               "switches": state.snapshot(session_id)})
        except Exception as e:
            logger.error(f"[ContactsAPI] toggle failed: {e}")
            return json.dumps({"status": "error", "message": str(e)})


class ContactProfileHandler:
    """Where the Workspace button should open for the selected session.

    Returns a workspace-relative path the existing workspace read / write
    endpoints already understand, rather than serving the content itself: the
    preview panel and its editor stay exactly as they are.
    """

    def POST(self):
        from channel.web.web_channel import _get_workspace_root, _require_auth

        _require_auth()
        web.header('Content-Type', 'application/json; charset=utf-8')
        try:
            body = json.loads(web.data() or b'{}')
            session_id = (body.get("wxid") or "").strip()
            if not session_id:
                return json.dumps({"status": "error", "message": "wxid is required"})

            agent_id = body.get("agent") or None
            # Memory always lives in the Agent's own workspace, never in an
            # opened project directory, so the session is deliberately not
            # passed here.
            root = _get_workspace_root(agent_id=agent_id)
            rel = ensure_profile(root, session_id)
            return json.dumps({"status": "success", "path": rel},
                              ensure_ascii=False)
        except ValueError as e:
            return json.dumps({"status": "error", "message": str(e)})
        except Exception as e:
            logger.error(f"[ContactsAPI] profile resolve failed: {e}")
            return json.dumps({"status": "error", "message": str(e)})
