"""Access-control tests for cowagent2.config.Config.

The whitelist is the only thing standing between the operator's personal
WeChat account and an agent that answers strangers, so the rules it has to
keep are asserted directly rather than inferred from the console's behaviour.
"""

import os
import tempfile
import unittest

from cowagent2.config import Config

ROOM = "8888888888@chatroom"
CONTACT = "wxid_alice"


class TestAccessControl(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.config = Config(
            whitelist_path=os.path.join(self._tmpdir.name, "whitelist.json")
        )
        self.config.whitelist = {
            "enabled": True,
            "allowed_wxids": [CONTACT],
            "allowed_rooms": [ROOM],
            "auto_reply_sessions": [],
        }

    def tearDown(self):
        self._tmpdir.cleanup()

    # -- the regression this API change exists for -------------------------
    def test_room_is_authorised_without_an_explicit_is_group_flag(self):
        """A single-argument call must still consult the room list.

        The previous ``is_allowed(wxid, roomid="")`` signature fell through to
        the contact list whenever a caller passed only the session id, so an
        enabled group never received a reply.
        """
        self.assertTrue(self.config.is_allowed(ROOM))
        self.assertTrue(self.config.is_allowed(ROOM, True))

    def test_room_and_contact_lists_do_not_cross(self):
        self.assertFalse(self.config.is_allowed(ROOM, False))
        self.assertFalse(self.config.is_allowed(CONTACT, True))

    def test_contact_is_authorised(self):
        self.assertTrue(self.config.is_allowed(CONTACT))
        self.assertTrue(self.config.is_allowed(CONTACT, False))

    # -- default-deny ------------------------------------------------------
    def test_unknown_peers_are_denied(self):
        self.assertFalse(self.config.is_allowed("wxid_stranger"))
        self.assertFalse(self.config.is_allowed("9999@chatroom"))

    def test_empty_session_id_is_denied(self):
        self.assertFalse(self.config.is_allowed(""))

    def test_empty_lists_mean_nobody(self):
        self.config.whitelist["allowed_wxids"] = []
        self.config.whitelist["allowed_rooms"] = []
        self.assertFalse(self.config.is_allowed(CONTACT))
        self.assertFalse(self.config.is_allowed(ROOM))

    def test_malformed_entries_narrow_the_gate_rather_than_widening_it(self):
        """A JSON null must not become the matchable entry "None"."""
        self.config.whitelist["allowed_wxids"] = [None, 123, "  ", CONTACT]
        self.assertTrue(self.config.is_allowed(CONTACT))
        self.assertFalse(self.config.is_allowed("None"))
        self.assertFalse(self.config.is_allowed("123"))

    def test_malformed_list_type_denies_everyone(self):
        self.config.whitelist["allowed_wxids"] = "not-a-list-of-entries"
        self.assertFalse(self.config.is_allowed(CONTACT))

    def test_disabling_the_whitelist_allows_everything(self):
        self.config.whitelist["enabled"] = False
        self.assertTrue(self.config.is_allowed("wxid_stranger"))
        self.assertTrue(self.config.is_allowed("9999@chatroom"))

    # -- toggles persist to the right list ---------------------------------
    def test_toggle_writes_rooms_and_contacts_to_separate_lists(self):
        fresh = Config(whitelist_path=os.path.join(self._tmpdir.name, "toggle.json"))
        fresh.whitelist["allowed_wxids"] = []
        fresh.whitelist["allowed_rooms"] = []

        fresh.toggle_whitelist("room1@chatroom", is_group=True, enable=True)
        fresh.toggle_whitelist("wxid_bob", is_group=False, enable=True)

        self.assertEqual(fresh.whitelist["allowed_rooms"], ["room1@chatroom"])
        self.assertEqual(fresh.whitelist["allowed_wxids"], ["wxid_bob"])
        self.assertTrue(fresh.is_allowed("room1@chatroom"))
        self.assertTrue(fresh.is_allowed("wxid_bob"))

        fresh.toggle_whitelist("room1@chatroom", is_group=True, enable=False)
        self.assertFalse(fresh.is_allowed("room1@chatroom"))

    def test_auto_reply_round_trips(self):
        self.assertFalse(self.config.get_session_auto_reply(ROOM))
        self.config.set_session_auto_reply(ROOM, True)
        self.assertTrue(self.config.get_session_auto_reply(ROOM))
        self.config.set_session_auto_reply(ROOM, False)
        self.assertFalse(self.config.get_session_auto_reply(ROOM))


class TestModelPolicy(unittest.TestCase):
    """ROADMAP bans glm-4.7-flash; the config must enforce it."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.config = Config(
            whitelist_path=os.path.join(self._tmpdir.name, "whitelist.json")
        )

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_banned_model_is_rewritten_to_the_baseline(self):
        self.config.legacy_config["model"] = "glm-4.7-flash"
        self.assertEqual(self.config.model, "glm-4-flash")

    def test_missing_model_falls_back_to_the_baseline(self):
        self.config.legacy_config["model"] = ""
        self.assertEqual(self.config.model, "glm-4-flash")

    def test_an_allowed_model_is_passed_through(self):
        self.config.legacy_config["model"] = "glm-4-plus"
        self.assertEqual(self.config.model, "glm-4-plus")


if __name__ == "__main__":
    unittest.main()
