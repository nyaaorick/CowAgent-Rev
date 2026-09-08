# encoding:utf-8

"""Unit tests for the WeChat contact / chatroom scanner.

The scanner exists because ``get_contacts()`` is unreliable on WeChat
3.9.12.56 (ROADMAP WCF-BUG-02), so it reads four overlapping sources and has
to decide which one wins when they disagree. These tests pin that precedence
down, and pin down what happens when the sources fail — a scan against a
wedged spy must not erase a catalog the operator already has.

No real WeChat, no real wcferry, no real database.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from channel.wcf.contact_state import ContactState
from channel.wcf.scanner import FILEHELPER_ID, ContactScanner


# --------------------------------------------------------------------- fakes
class FakeWcf:
    """The subset of the wcferry client the scanner touches."""

    def __init__(self, *, self_wxid="wxid_me", dbs=None, sql_rows=None, contacts=None):
        self._self_wxid = self_wxid
        self._dbs = dbs if dbs is not None else ["MicroMsg.db", "MSG0.db"]
        self._sql_rows = sql_rows or {}
        self._contacts = contacts or []
        self.queries = []

    def get_self_wxid(self):
        return self._self_wxid

    def get_user_info(self):
        return {"name": "Operator"}

    def get_dbs(self):
        return list(self._dbs)

    def query_sql(self, db, sql):
        self.queries.append((db, sql))
        return self._sql_rows.get(db, [])

    def get_contacts(self):
        return list(self._contacts)


class ExplodingWcf(FakeWcf):
    """A wedged spy: every call raises the way a dead RPC socket does."""

    def get_self_wxid(self):
        raise RuntimeError("rpc timeout")

    def get_dbs(self):
        raise RuntimeError("rpc timeout")

    def get_contacts(self):
        raise RuntimeError("rpc timeout")


def contact_row(user_name, alias="", remark="", nick_name="", type_=3):
    return {
        "UserName": user_name,
        "Alias": alias,
        "Remark": remark,
        "NickName": nick_name,
        "Type": type_,
    }


@pytest.fixture
def cache_path(tmp_path):
    """Never the operator's real catalog of several thousand contacts."""
    return str(tmp_path / "contacts_cache.json")


# ------------------------------------------------------------------- seeding
def test_file_transfer_assistant_is_always_present(cache_path):
    """filehelper is WeChat's own endpoint and the only safe test target."""
    scanner = ContactScanner(cache_path=cache_path)
    assert scanner.get_contact(FILEHELPER_ID) is not None


def test_construction_does_not_write_the_cache(cache_path):
    """Importing the module must not rewrite the catalog on every startup."""
    ContactScanner(cache_path=cache_path)
    assert not os.path.exists(cache_path)


# ------------------------------------------------------- MicroMsg.db precedence
def test_micromsg_contact_table_supplies_alias_and_remark(cache_path):
    wcf = FakeWcf(
        sql_rows={"MicroMsg.db": [contact_row("wxid_alice", alias="alice_wx",
                                              remark="Alice", nick_name="A")]}
    )
    scanner = ContactScanner(cache_path=cache_path)
    scanner.scan_from_wcf(wcf)

    entry = scanner.get_contact("wxid_alice")
    assert entry["alias"] == "alice_wx"
    assert entry["remark"] == "Alice"


def test_remark_wins_over_nickname_for_the_display_name(cache_path):
    """The operator's own remark is what they recognise the contact by."""
    wcf = FakeWcf(
        sql_rows={"MicroMsg.db": [contact_row("wxid_alice", remark="Alice",
                                              nick_name="Nickname")]}
    )
    scanner = ContactScanner(cache_path=cache_path)
    scanner.scan_from_wcf(wcf)

    assert scanner.get_contact("wxid_alice")["name"] == "Alice"


def test_a_placeholder_name_is_replaced_once_a_real_one_arrives(cache_path):
    scanner = ContactScanner(cache_path=cache_path)
    scanner.register_or_update("wxid_alice", source="db_history", auto_save=False)
    assert scanner.get_contact("wxid_alice")["name"].startswith("Contact_")

    scanner.register_or_update("wxid_alice", name="Alice",
                               source="micromsg_contact", auto_save=False)
    assert scanner.get_contact("wxid_alice")["name"] == "Alice"


def test_a_weak_source_does_not_overwrite_a_real_name(cache_path):
    """The message stream must not downgrade a name the contact table set."""
    scanner = ContactScanner(cache_path=cache_path)
    scanner.register_or_update("wxid_alice", name="Alice",
                               source="micromsg_contact", auto_save=False)
    scanner.register_or_update("wxid_alice", name="whatever",
                               source="message_stream", auto_save=False)

    assert scanner.get_contact("wxid_alice")["name"] == "Alice"


# ------------------------------------------------------------- other sources
def test_message_history_backfills_contacts_the_table_missed(cache_path):
    wcf = FakeWcf(
        sql_rows={
            "MicroMsg.db": [],
            "MSG0.db": [{"StrTalker": "wxid_bob"}],
        }
    )
    scanner = ContactScanner(cache_path=cache_path)
    scanner.scan_from_wcf(wcf)

    assert scanner.get_contact("wxid_bob") is not None


def test_chatroom_ids_are_typed_as_groups(cache_path):
    wcf = FakeWcf(sql_rows={"MicroMsg.db": [contact_row("12345@chatroom", nick_name="Team")]})
    scanner = ContactScanner(cache_path=cache_path)
    scanner.scan_from_wcf(wcf)

    assert scanner.get_contact("12345@chatroom")["type"] == "chatroom"


def test_wcf_api_contacts_are_merged(cache_path):
    wcf = FakeWcf(contacts=[{"wxid": "wxid_carol", "name": "Carol",
                             "remark": "", "code": "carol_wx"}])
    scanner = ContactScanner(cache_path=cache_path)
    scanner.scan_from_wcf(wcf)

    assert scanner.get_contact("wxid_carol")["alias"] == "carol_wx"


def test_absent_databases_are_not_queried(cache_path):
    """A spy that has not opened MicroMsg.db must not be asked to read it."""
    wcf = FakeWcf(dbs=[])
    scanner = ContactScanner(cache_path=cache_path)
    scanner.scan_from_wcf(wcf)

    assert wcf.queries == []


# ------------------------------------------------------------------- failure
def test_a_failed_scan_keeps_the_existing_catalog(cache_path):
    """AC-002: a wedged spy must not blank out a catalog already on disk."""
    scanner = ContactScanner(cache_path=cache_path)
    scanner.register_or_update("wxid_alice", name="Alice", source="micromsg_contact")

    scanner.scan_from_wcf(ExplodingWcf())

    assert scanner.get_contact("wxid_alice")["name"] == "Alice"


def test_a_failed_scan_does_not_raise(cache_path):
    """The console asks for a scan on a button press; it must answer."""
    scanner = ContactScanner(cache_path=cache_path)
    assert scanner.scan_from_wcf(ExplodingWcf()) >= 1


# ----------------------------------------------------------------- persistence
def test_catalog_survives_a_reload(cache_path):
    scanner = ContactScanner(cache_path=cache_path)
    scanner.register_or_update("wxid_alice", name="Alice", remark="Alice",
                               source="micromsg_contact")

    reloaded = ContactScanner(cache_path=cache_path)
    assert reloaded.get_contact("wxid_alice")["name"] == "Alice"


def test_chinese_names_are_stored_unescaped(cache_path):
    scanner = ContactScanner(cache_path=cache_path)
    scanner.register_or_update("wxid_alice", name="小明", source="micromsg_contact")

    raw = open(cache_path, encoding="utf-8").read()
    assert "小明" in raw


def test_a_corrupt_cache_does_not_break_startup(cache_path):
    with open(cache_path, "w", encoding="utf-8") as f:
        f.write("[{'not': 'json'")

    scanner = ContactScanner(cache_path=cache_path)
    assert scanner.get_contact(FILEHELPER_ID) is not None


# ------------------------------------------------------------------ projection
def test_console_projection_merges_the_switch_state(cache_path, tmp_path):
    state = ContactState(state_path=str(tmp_path / "contacts_state.json"))
    state.set_allowed("wxid_alice", True)

    scanner = ContactScanner(cache_path=cache_path)
    scanner.register_or_update("wxid_alice", name="Alice", remark="Alice",
                               alias="alice_wx", source="micromsg_contact")

    rows = {row["wxid"]: row for row in scanner.get_all_with_state(state)}
    assert rows["wxid_alice"]["allowed"] is True
    assert rows["wxid_alice"]["auto_answer"] is True
    assert rows["wxid_alice"]["alias"] == "alice_wx"


def test_allowed_sessions_sort_first(cache_path, tmp_path):
    """The operator's own contacts should not be buried under 6000 strangers."""
    state = ContactState(state_path=str(tmp_path / "contacts_state.json"))
    state.set_allowed("wxid_bob", True)

    scanner = ContactScanner(cache_path=cache_path)
    scanner.register_or_update("wxid_alice", name="Alice", source="micromsg_contact")
    scanner.register_or_update("wxid_bob", name="Bob", source="micromsg_contact")

    assert scanner.get_all_with_state(state)[0]["wxid"] == "wxid_bob"
