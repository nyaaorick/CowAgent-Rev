# -*- coding: utf-8 -*-
"""
cowagent2.scanner
~~~~~~~~~~~~~~~~~
Contact and chatroom discovery for CowAgent 2.

Responsibilities:
  1. Multi-source discovery -- built-in seeds, the WCF API, the WeChat SQLite
     databases the spy has opened, and the live message stream.
  2. Identity binding -- associate a contact's remark / nickname and a room's
     name with the real ``wxid`` / ``roomid``.
  3. Persistence -- cache the catalog in ``cowagent2/data/contacts_cache.json``.
  4. Whitelist projection -- merge in the live ``whitelist.json`` state for the
     web console to render and toggle.

The four discovery sources deliberately overlap. ``get_contacts()`` is
unreliable on WeChat 3.9.12.56 (ROADMAP WCF-BUG-02), so ``MicroMsg.db`` is
read directly when the patched ``spy.dll`` has it open, and the message
history table backfills anyone the contact table misses.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

from cowagent2.config import CHATROOM_SUFFIX, CONTACTS_CACHE_PATH, cfg

logger = logging.getLogger("cowagent2.scanner")

# The File Transfer Assistant is WeChat's own endpoint and the only safe
# default test target (see ROADMAP "Operational Safety Rules").
FILEHELPER_ID = "filehelper"

# Prefixes used for auto-generated placeholder names. Both spellings are
# recognised: cached catalogs written before this module was translated still
# carry the Chinese ones, and treating those as real names would freeze the
# placeholder in place once the true nickname finally arrived.
PLACEHOLDER_PREFIXES = ("Contact_", "Group_", "联系人_", "群聊_")

# Sources trusted to overwrite an existing display name. Anything else may
# only fill in a blank or replace a placeholder.
AUTHORITATIVE_SOURCES = ("manual", "micromsg_contact", "wcf_api")

# How much of an id to show in a placeholder name.
PLACEHOLDER_ID_CHARS = 6


class ContactScanner:
    """Discovers WeChat contacts and chatrooms and binds names to their ids."""

    def __init__(
        self,
        wcf_client: Optional[Any] = None,
        cache_path: str = CONTACTS_CACHE_PATH,
    ):
        self.wcf_client = wcf_client
        # Overridable so a test does not read or write the operator's
        # live catalog of several thousand real contacts.
        self.cache_path = cache_path
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
        """Load the previously discovered catalog from disk."""
        if not os.path.exists(self.cache_path):
            return
        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                self.catalog[item["id"]] = item
            logger.info(f"Loaded {len(self.catalog)} contacts/chatrooms from cache")
        except Exception as e:
            logger.warning(f"Failed to load contact cache: {e}")

    def save_cache(self) -> None:
        """Persist the catalog to disk."""
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(list(self.catalog.values()), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save contact cache: {e}")

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
                    f"Discovered new session [{entry_type}]: {display_name} ({target_id})"
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
        """
        count_before = len(self.catalog)
        try:
            # 1. The logged-in account itself.
            self_wxid = wcf.get_self_wxid()
            if self_wxid:
                user_info = wcf.get_user_info() or {}
                self.register_or_update(
                    target_id=self_wxid,
                    name=user_info.get("name", "Me"),
                    remark="Currently logged-in account on this host",
                    is_group=False,
                    source="self",
                    auto_save=False,
                )

            dbs = wcf.get_dbs() or []

            # 2. MicroMsg.db Contact table -- the authoritative source for
            #    alias (the user-chosen WeChat ID), remark and nickname.
            if "MicroMsg.db" in dbs:
                try:
                    sql = (
                        "SELECT UserName, Alias, Remark, NickName, Type FROM Contact "
                        "WHERE UserName IS NOT NULL AND UserName != '';"
                    )
                    rows = wcf.query_sql("MicroMsg.db", sql) or []
                    for row in rows:
                        user_name = row.get("UserName", "").strip()
                        if not user_name or user_name == FILEHELPER_ID:
                            continue
                        remark_val = row.get("Remark", "").strip()
                        nick_val = row.get("NickName", "").strip()
                        self.register_or_update(
                            target_id=user_name,
                            name=remark_val or nick_val or user_name,
                            remark=remark_val,
                            alias=row.get("Alias", "").strip(),
                            is_group=user_name.endswith(CHATROOM_SUFFIX),
                            source="micromsg_contact",
                            auto_save=False,
                        )
                    logger.info(
                        f"Bulk read from MicroMsg.db Contact table: {len(rows)} rows"
                    )
                except Exception as e:
                    logger.warning(f"Failed to read contacts from MicroMsg.db: {e}")

            # 3. The native WCF contact API, merging in its own alias/nickname.
            try:
                for contact in wcf.get_contacts() or []:
                    wxid = contact.get("wxid", "").strip()
                    if not wxid:
                        continue
                    self.register_or_update(
                        target_id=wxid,
                        name=contact.get("name", "").strip(),
                        remark=contact.get("remark", "").strip(),
                        alias=contact.get("code", "").strip(),
                        is_group=wxid.endswith(CHATROOM_SUFFIX),
                        source="wcf_api",
                        auto_save=False,
                    )
            except Exception as e:
                logger.debug(f"WCF get_contacts scan failed: {e}")

            # 4. Recently active talkers from the message history table.
            if "MSG0.db" in dbs:
                try:
                    rows = wcf.query_sql(
                        "MSG0.db",
                        "SELECT DISTINCT StrTalker FROM MSG "
                        "ORDER BY CreateTime DESC LIMIT 200;",
                    ) or []
                    for row in rows:
                        talker = row.get("StrTalker", "").strip()
                        if talker and len(talker) > 3 and talker != FILEHELPER_ID:
                            self.register_or_update(
                                target_id=talker,
                                name="",
                                is_group=talker.endswith(CHATROOM_SUFFIX),
                                source="db_history",
                                auto_save=False,
                            )
                except Exception as e:
                    logger.debug(f"Failed to query talkers from the MSG table: {e}")

        except Exception as e:
            logger.warning(f"WCF contact scan failed: {e}")

        self.save_cache()
        added = len(self.catalog) - count_before
        logger.info(
            f"Scan complete: {added} new sessions, {len(self.catalog)} in catalog"
        )
        return len(self.catalog)

    def scan(self) -> List[Dict[str, Any]]:
        """Run an active scan and return the whole catalog."""
        if self.wcf_client:
            self.scan_from_wcf(self.wcf_client)
        return list(self.catalog.values())

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
            logger.debug(f"Failed to read the latest outbound talker from MSG0.db: {e}")
        return ""

    def update_from_message(self, msg) -> Dict[str, Any]:
        """Register the session a live WeChat message belongs to."""
        is_group = bool(getattr(msg, "from_group", lambda: False)())
        is_self = bool(getattr(msg, "from_self", lambda: False)())

        if is_group:
            target_id = getattr(msg, "roomid", "")
        elif is_self:
            # For a private message this account sent, ``sender`` is us, so
            # the peer's wxid has to come from the newest MSG0.db row instead.
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
            logger.debug(f"on_wcf_message scan error: {e}")

    def add_talker(self, target_id: str, is_group: bool = False) -> Dict[str, Any]:
        """Register an active conversation partner seen at runtime."""
        return self.register_or_update(
            target_id=target_id, is_group=is_group, source="talker"
        )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def get_contact(self, target_id: str) -> Optional[Dict[str, Any]]:
        """The catalog entry for one id, or None when it is unknown."""
        return self.catalog.get(target_id)

    def get_all_with_whitelist_status(self, config_obj=None) -> List[Dict[str, Any]]:
        """The full catalog projected for the console, whitelist state merged in."""
        config = config_obj or cfg
        results = []
        for target_id, item in self.catalog.items():
            is_group = item["type"] == "chatroom"
            results.append({
                "wxid": target_id,
                "name": item.get("name") or target_id,
                "nickname": item.get("remark") or item.get("name") or target_id,
                "remark": item.get("remark", ""),
                "alias": item.get("alias", ""),
                "is_group": is_group,
                "is_whitelisted": config.is_allowed(target_id, is_group),
                "auto_reply": config.get_session_auto_reply(target_id),
                "last_seen": item.get("last_seen", 0),
            })

        # Whitelisted sessions first, then most recently active.
        results.sort(key=lambda x: (not x["is_whitelisted"], -x["last_seen"]))
        return results

    def get_contacts_with_whitelist(self, config_obj=None) -> List[Dict[str, Any]]:
        """Alias used by the web console."""
        return self.get_all_with_whitelist_status(config_obj)
