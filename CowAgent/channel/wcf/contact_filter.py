# encoding:utf-8

"""Which WeChat contacts the agent is allowed to answer.

WeChat is the operator's own account, so a channel that replies to anyone who
writes in is not a feature -- it is an incident. Group chats already gate on
``group_name_white_list`` inside ``ChatChannel``; private chats had no
equivalent, so this module supplies one for ``wcf_contact_white_list``.

An entry matches either side of a contact's identity, because the two are not
interchangeable in practice: ``get_contacts()`` is broken on WeChat 3.9.12.56
(ROADMAP WCF-BUG-02), so a display name resolves to the raw wxid on this host,
while a wxid is stable but unreadable. Accepting both lets the operator write
``filehelper`` today and ``小明`` once the database defect is fixed, without
either spelling silently going dead.
"""

# Answers every private chat. Deliberately verbose, and deliberately not "" --
# an empty list must mean "nobody", so a truncated or half-written config fails
# closed rather than opening the bot to every contact.
ALL_CONTACT = "ALL_CONTACT"


def normalize_white_list(raw) -> list:
    """Config value -> list of non-empty entries.

    Accepts the same shapes ``channel_type`` does: a list, or a
    comma-separated string typed into the console's config editor.

    Non-string entries are dropped rather than coerced. Stringifying them
    would turn a JSON ``null`` into the entry ``"None"`` -- and since a
    contact's display name is chosen by the contact, a stranger could then
    match it by renaming themselves. A malformed list has to narrow this
    gate, never widen it.
    """
    if isinstance(raw, str):
        items = raw.split(",")
    elif isinstance(raw, (list, tuple, set)):
        items = list(raw)
    else:
        return []
    return [item.strip() for item in items if isinstance(item, str) and item.strip()]


def is_allowed_contact(white_list, wxid, display_name="") -> bool:
    """True when a private chat with this contact may reach the agent.

    ``white_list`` is the raw config value; ``wxid`` is the peer's id and
    ``display_name`` its resolved nickname (may be equal to the wxid when the
    contact database is unreadable).
    """
    entries = normalize_white_list(white_list)
    if not entries:
        return False
    if ALL_CONTACT in entries:
        return True
    candidates = {value for value in (wxid, display_name) if value}
    return bool(candidates & set(entries))
