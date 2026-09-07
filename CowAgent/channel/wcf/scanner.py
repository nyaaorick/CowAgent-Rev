# encoding:utf-8

"""Contact and chatroom discovery for the WeChatFerry channel.

Ported from CowAgent 2's ``scanner.py`` (ROADMAP directive 6, Code Reuse Over
Reinvention), rebased onto this tree's logger, config and switch store.

Responsibilities:
  1. Multi-source discovery -- a built-in seed, the WCF API, the WeChat SQLite
     databases the spy has opened, and the live message stream.
  2. Identity binding -- associate a contact's remark / nickname and a room's
     name with the real ``wxid`` / ``roomid``.
  3. Persistence -- cache the catalog so the console has a list to show before
     the first scan of a session finishes.
  4. Projection -- merge in ``ContactState`` so the console can render and
     toggle each session's switches.

The four discovery sources deliberately overlap. ``get_contacts()`` is
unreliable on WeChat 3.9.12.56 (ROADMAP WCF-BUG-02), so ``MicroMsg.db`` is read
directly when the patched ``spy.dll`` has it open, and the message history
table backfills anyone the contact table misses.
"""

import json
import os
import re
import time
from typing import Any, Dict, List, Optional

from channel.wcf.contact_state import CHATROOM_SUFFIX
from common.log import logger
from config import get_data_root

# The File Transfer Assistant is WeChat's own endpoint and the only safe
# default test target (see ROADMAP "Operational Safety Rules").
FILEHELPER_ID = "filehelper"

# Prefixes used for auto-generated placeholder names. Both spellings are
# recognised: cached catalogs written by CowAgent 2 before that module was
# translated still carry the Chinese ones, and treating those as real names
# would freeze the placeholder in place once the true nickname finally arrived.
PLACEHOLDER_PREFIXES = ("Contact_", "Group_", "联系人_", "群聊_")

# Sources trusted to overwrite an existing display name. Anything else may only
# fill in a blank or replace a placeholder.
AUTHORITATIVE_SOURCES = ("manual", "micromsg_contact", "wcf_api")

# How much of an id to show in a placeholder name.
PLACEHOLDER_ID_CHARS = 6

# How far back the message history is read for talkers the contact table missed.
RECENT_TALKER_LIMIT = 200


def default_cache_path() -> str:
    """Where the discovered catalog is cached for this install.

    Beside the switch document under the data root: a contact belongs to the
    WeChat account, not to any one Agent's workspace.
    """
    return os.path.join(get_data_root(), "wcf", "contacts_cache.json")


class ContactScanner:
    """Discovers WeChat contacts and chatrooms and binds names to their ids."""

    def __init__(
        self,
        wcf_client: Optional[Any] = None,
        cache_path: Optional[str] = None,
    ):
        self.wcf_client = wcf_client
        # Overridable so a test does not read or write the operator's live
        # catalog of several thousand real contacts.
        self.cache_path = cache_path or default_cache_path()
        # target_id -> catalog entry
        self.catalog: Dict[str, Dict[str, Any]] = {}
        self._init_defaults()
        self.load_cache()

    def _init_defaults(self) -> None:
        """Seed the catalog with the contacts that always exist.

        ``auto_save=False``: construction has nothing new to persist, and
        writing here rewrote the cache file on every import.
        """
        self.register_or_update(
            target_id=FILEHELPER_ID,
            name="File Transfer Assistant",
            remark="WeChat built-in File Transfer Assistant",
            is_group=False,
            source="system",
            auto_save=False,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def load_cache(self) -> None:
        """Load the previously discovered catalog from disk.

        Entries that are not a record with an id are skipped rather than
        aborting the load: one bad row in a 6,000-contact file should cost that
        row, not the whole catalog.
        """
        if not os.path.exists(self.cache_path):
            return
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.warning(f"[Scanner] Failed to load contact cache: {e}")
            return

        loaded = 0
        for item in data if isinstance(data, list) else []:
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]:
                self.catalog[item["id"]] = item
                loaded += 1
        logger.info(f"[Scanner] Loaded {loaded} contacts/chatrooms from cache")

    def save_cache(self) -> None:
        """Persist the catalog to disk.

        Written through a temporary file: a direct write interrupted partway
        through several thousand entries leaves JSON the next load cannot read,
        and the operator would open the console to an empty address book.
        """
        try:
            os.makedirs(os.path.dirname(self.cache_path) or ".", exist_ok=True)
            tmp_path = f"{self.cache_path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(list(self.catalog.values()), f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.cache_path)
        except Exception as e:
            logger.error(f"[Scanner] Failed to save contact cache: {e}")

    # ------------------------------------------------------------------
    # Catalog maintenance
    # ------------------------------------------------------------------
    @staticmethod
    def _is_placeholder_name(name: str) -> bool:
        """True when a stored name is auto-generated rather than real."""
        return not name or name.startswith(PLACEHOLDER_PREFIXES)

    def register_or_update(
        self,
        target_id: str,
        name: str = "",
        remark: str = "",
        is_group: bool = False,
        source: str = "runtime",
        alias: str = "",
        auto_save: bool = True,
    ) -> Dict[str, Any]:
        """Create or refresh one contact / chatroom entry.

        ``auto_save`` is off during a bulk scan so several thousand entries
        cost one write instead of one write each.
        """
        if not target_id:
            return {}

        now = time.time()
        is_chatroom = is_group or target_id.endswith(CHATROOM_SUFFIX)

        if target_id not in self.catalog:
            kind = "Group" if is_chatroom else "Contact"
            placeholder = f"{kind}_{target_id[:PLACEHOLDER_ID_CHARS]}"
            display_name = remark or name or placeholder
            self.catalog[target_id] = {
                "id": target_id,
                "name": name or display_name,
                "remark": remark,
                "alias": alias,
                "type": "chatroom" if is_chatroom else "contact",
                "source": source,
                "first_seen": now,
                "last_seen": now,
            }
            if auto_save:
                entry_type = self.catalog[target_id]["type"]
                logger.info(
                    f"[Scanner] Discovered new session [{entry_type}]: "
                    f"{display_name} ({target_id})"
                )
        else:
            item = self.catalog[target_id]
            is_placeholder = self._is_placeholder_name(item.get("name") or "")
            if name and (is_placeholder or source in AUTHORITATIVE_SOURCES):
                item["name"] = name
            if remark:
                item["remark"] = remark
            if alias:
                item["alias"] = alias
            item["last_seen"] = now

        if auto_save:
            self.save_cache()
        return self.catalog[target_id]

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------
    def scan_from_wcf(self, wcf) -> int:
        """Full catalog scan against a live WCF instance.

        Every source writes with ``auto_save=False`` and the cache is flushed
        once at the end, which is what keeps a 6,000-contact scan sub-second.

        Nothing raises out of here. The console calls this on a button press,
        and a wedged spy has to produce an error message next to the catalog
        the operator already had, not an empty list and a stack trace.
        """
        count_before = len(self.catalog)
        try:
            self._scan_self(wcf)
            dbs = wcf.get_dbs() or []
            self._scan_micromsg_contacts(wcf, dbs)
            self._scan_wcf_api(wcf)
            self._scan_recent_talkers(wcf, dbs)
        except Exception as e:
            logger.warning(f"[Scanner] WCF contact scan failed: {e}")

        self.save_cache()
        added = len(self.catalog) - count_before
        logger.info(
            f"[Scanner] Scan complete: {added} new sessions, "
            f"{len(self.catalog)} in catalog"
        )
        return len(self.catalog)

    def _scan_self(self, wcf) -> None:
        """Source 1 -- the logged-in account itself."""
        self_wxid = wcf.get_self_wxid()
        if not self_wxid:
            return
        user_info = wcf.get_user_info() or {}
        self.register_or_update(
            target_id=self_wxid,
            name=user_info.get("name", "Me"),
            remark="Currently logged-in account on this host",
            is_group=False,
            source="self",
            auto_save=False,
        )

    def _scan_micromsg_contacts(self, wcf, dbs) -> None:
        """Source 2 -- the ``MicroMsg.db`` Contact table.

        The authoritative source for alias (the user-chosen WeChat ID), remark
        and nickname, and the reason the patched ``spy.dll`` matters at all.
        """
        if "MicroMsg.db" not in dbs:
            return
        try:
            sql = (
                "SELECT UserName, Alias, Remark, NickName, Type FROM Contact "
                "WHERE UserName IS NOT NULL AND UserName != '';"
            )
            rows = wcf.query_sql("MicroMsg.db", sql) or []
            for row in rows:
                user_name = (row.get("UserName") or "").strip()
                if not user_name or user_name == FILEHELPER_ID:
                    continue
                remark_val = (row.get("Remark") or "").strip()
                nick_val = (row.get("NickName") or "").strip()
                self.register_or_update(
                    target_id=user_name,
                    name=remark_val or nick_val or user_name,
                    remark=remark_val,
                    alias=(row.get("Alias") or "").strip(),
                    is_group=user_name.endswith(CHATROOM_SUFFIX),
                    source="micromsg_contact",
                    auto_save=False,
                )
            logger.info(
                f"[Scanner] Bulk read from MicroMsg.db Contact table: {len(rows)} rows"
            )
        except Exception as e:
            logger.warning(f"[Scanner] Failed to read contacts from MicroMsg.db: {e}")

    def _scan_wcf_api(self, wcf) -> None:
        """Source 3 -- the native WCF contact API.

        Broken on this host (WCF-BUG-02) but harmless to ask, and it is the
        source that works once the defect is fixed upstream.
        """
        try:
            for contact in wcf.get_contacts() or []:
                wxid = (contact.get("wxid") or "").strip()
                if not wxid:
                    continue
                self.register_or_update(
                    target_id=wxid,
                    name=(contact.get("name") or "").strip(),
                    remark=(contact.get("remark") or "").strip(),
                    alias=(contact.get("code") or "").strip(),
                    is_group=wxid.endswith(CHATROOM_SUFFIX),
                    source="wcf_api",
                    auto_save=False,
                )
        except Exception as e:
            logger.debug(f"[Scanner] WCF get_contacts scan failed: {e}")

    def _scan_recent_talkers(self, wcf, dbs) -> None:
        """Source 4 -- recently active talkers from the message history."""
        if "MSG0.db" not in dbs:
            return
        try:
            rows = wcf.query_sql(
                "MSG0.db",
                "SELECT DISTINCT StrTalker FROM MSG "
                f"ORDER BY CreateTime DESC LIMIT {RECENT_TALKER_LIMIT};",
            ) or []
            for row in rows:
                talker = (row.get("StrTalker") or "").strip()
                if talker and len(talker) > 3 and talker != FILEHELPER_ID:
                    self.register_or_update(
                        target_id=talker,
                        name="",
                        is_group=talker.endswith(CHATROOM_SUFFIX),
                        source="db_history",
                        auto_save=False,
                    )
        except Exception as e:
            logger.debug(f"[Scanner] Failed to query talkers from the MSG table: {e}")

    def scan(self) -> List[Dict[str, Any]]:
        """Run an active scan and return the whole catalog."""
        if self.wcf_client:
            self.scan_from_wcf(self.wcf_client)
        return list(self.catalog.values())

    # ------------------------------------------------------------------
    # Live message stream
    # ------------------------------------------------------------------
    def _get_latest_talker_from_db(self) -> str:
        """The peer of the most recent private message this account sent."""
        if not self.wcf_client:
            return ""
        try:
            sql = (
                "SELECT StrTalker FROM MSG WHERE IsSender = 1 "
                "ORDER BY CreateTime DESC LIMIT 1;"
            )
            rows = self.wcf_client.query_sql("MSG0.db", sql)
            if rows:
                talker = rows[0].get("StrTalker", "")
                if (
                    talker
                    and not talker.endswith(CHATROOM_SUFFIX)
                    and talker != FILEHELPER_ID
                ):
                    return talker
        except Exception as e:
            logger.debug(f"[Scanner] Failed to read the latest outbound talker: {e}")
        return ""

    def update_from_message(self, msg) -> Dict[str, Any]:
        """Register the session a live WeChat message belongs to."""
        is_group = bool(getattr(msg, "from_group", lambda: False)())
        is_self = bool(getattr(msg, "from_self", lambda: False)())

        if is_group:
            target_id = getattr(msg, "roomid", "")
        elif is_self:
            # For a private message this account sent, ``sender`` is us, so the
            # peer's wxid has to come from the newest MSG0.db row instead.
            target_id = self._get_latest_talker_from_db() or getattr(msg, "sender", "")
        else:
            target_id = getattr(msg, "sender", "")

        if not target_id or target_id == FILEHELPER_ID:
            return {}

        # Best-effort room name / nickname extraction from the raw XML.
        name_candidate = ""
        xml_str = getattr(msg, "xml", "")
        if xml_str:
            match = re.search(
                r"<displayname><!\[CDATA\[(.*?)\]\]></displayname>", xml_str
            )
            if match:
                name_candidate = match.group(1)

        return self.register_or_update(
            target_id=target_id,
            name=name_candidate,
            is_group=is_group,
            source="message_stream",
        )

    def on_wcf_message(self, msg) -> None:
        """WCF subscriber callback: harvest contacts from the live stream."""
        try:
            self.update_from_message(msg)
        except Exception as e:
            logger.debug(f"[Scanner] on_wcf_message scan error: {e}")

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def get_contact(self, target_id: str) -> Optional[Dict[str, Any]]:
        """The catalog entry for one id, or None when it is unknown."""
        return self.catalog.get(target_id)

    def get_all_with_state(self, state) -> List[Dict[str, Any]]:
        """The full catalog projected for the console, switch state merged in.

        ``state`` is a :class:`~channel.wcf.contact_state.ContactState`. Its
        answers are reported as they are; whether an unrecorded session is
        nonetheless allowed by ``config.json`` is ``contact_filter``'s question,
        not the console list's.
        """
        results = []
        for target_id, item in self.catalog.items():
            switches = state.snapshot(target_id)
            results.append({
                "wxid": target_id,
                "name": item.get("name") or target_id,
                "nickname": item.get("remark") or item.get("name") or target_id,
                "remark": item.get("remark", ""),
                "alias": item.get("alias", ""),
                "is_group": item["type"] == "chatroom",
                "last_seen": item.get("last_seen", 0),
                **switches,
            })

        # Allowed sessions first, then most recently active: the operator's own
        # handful of contacts should not be buried under several thousand
        # strangers the contact table happened to know about.
        results.sort(key=lambda x: (not x["allowed"], -x["last_seen"]))
        return results
