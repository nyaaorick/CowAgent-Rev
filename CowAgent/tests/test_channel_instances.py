"""Multi-instance channel resolution and persistence.

Two worlds must coexist: a legacy install driven by ``channel_type`` + flat
credentials, and a multi-instance install driven by an explicit
``channel_instances`` list in the roster file. These tests pin the legacy
behavior (so it never regresses) and cover the persistence helpers.

CowAgent-Rev runs WCF and the web console only, so ``CREDENTIAL_KEYS`` and
``MULTI_INSTANCE_READY`` are both empty here. The cases that covered folding
feishu / weixin / dingtalk flat credentials into per-instance records went with
them: there is no longer a channel type for which that machinery does anything.
What is left is the part that is still reachable -- id generation, legacy
``channel_type`` parsing, and the upsert/remove/members helpers.
"""

import os

import pytest

from channel import channel_instances as ci


# ---------------------------------------------------------------------------
# instance id generation
# ---------------------------------------------------------------------------

def test_new_instance_id_has_type_prefix_and_is_unique():
    ids = set()
    for _ in range(50):
        new = ci.new_instance_id("feishu", ids)
        assert new.startswith("feishu-")
        assert new not in ids
        ids.add(new)


def test_new_instance_id_normalizes_type_and_handles_empty():
    assert ci.new_instance_id("wx").startswith("weixin-")
    assert ci.new_instance_id("").startswith("channel-")


def test_new_instance_id_avoids_taken():
    taken = {f"feishu-{i:010d}" for i in range(3)}
    assert ci.new_instance_id("feishu", taken) not in taken


# ---------------------------------------------------------------------------
# legacy compatibility: no channel_instances -> synthesized from channel_type
# ---------------------------------------------------------------------------

def test_legacy_channel_type_string(tmp_path):
    settings = {"agent_workspace": str(tmp_path), "channel_type": "feishu, dingtalk"}
    insts = ci.resolve_channel_instances(settings)
    ids = {i.instance_id for i in insts}
    assert ids == {"feishu", "dingtalk"}
    # legacy instances carry no per-instance credentials or binding
    for i in insts:
        assert i.legacy is True
        assert i.credentials == {}
        assert i.agent_id == ""


def test_legacy_channel_type_list(tmp_path):
    settings = {"agent_workspace": str(tmp_path), "channel_type": ["feishu"]}
    insts = ci.resolve_channel_instances(settings)
    assert [i.instance_id for i in insts] == ["feishu"]
    assert insts[0].legacy is True


def test_legacy_normalizes_wx(tmp_path):
    settings = {"agent_workspace": str(tmp_path), "channel_type": "wx"}
    insts = ci.resolve_channel_instances(settings)
    assert insts[0].channel_type == "weixin"


# ---------------------------------------------------------------------------
# explicit multi-instance resolution
# ---------------------------------------------------------------------------

def _write_instances(tmp_path, records):
    """Persist records to team.json and return settings with them overlaid.

    Mirrors how the launcher reads channels: team.resolve() lifts the roster
    file (where channel_instances lives) onto the flat settings before
    resolve_channel_instances() runs.
    """
    from agent import team

    base = {"agent_workspace": str(tmp_path)}
    team.write(base, {"channel_instances": records})
    return team.resolve(base)


def test_upsert_honors_provided_id(tmp_path):
    settings = {"agent_workspace": str(tmp_path)}
    inst = ci.upsert_instance(
        settings, channel_type="feishu", instance_id="from-remote-123",
        agent_id="a", credentials={"feishu_app_id": "A"},
    )
    assert inst.instance_id == "from-remote-123"


def test_remove_instance(tmp_path):
    settings = {"agent_workspace": str(tmp_path)}
    inst = ci.upsert_instance(settings, channel_type="feishu",
                              credentials={"feishu_app_id": "A"})
    assert ci.remove_instance(settings, inst.instance_id) is True
    assert ci.read_raw_instances(settings) == []
    # removing a missing id is a no-op
    assert ci.remove_instance(settings, "nope") is False


# ---------------------------------------------------------------------------
# team members: a channel instance owns a roster (owner + teammates)
# ---------------------------------------------------------------------------

def test_explicit_instance_parses_members(tmp_path):
    settings = _write_instances(
        tmp_path,
        [
            {
                "instance_id": "feishu-team",
                "channel_type": "feishu",
                "agent_id": "leader",
                "members": ["ops", "research", "leader", "ops", ""],
                "credentials": {"feishu_app_id": "A"},
            }
        ],
    )
    inst = ci.resolve_channel_instances(settings)[0]
    # owner is never a member; duplicates and blanks are dropped; order kept
    assert inst.members == ["ops", "research"]


def test_upsert_sets_and_preserves_members(tmp_path):
    settings = {"agent_workspace": str(tmp_path)}
    inst = ci.upsert_instance(
        settings, channel_type="feishu", agent_id="leader",
        members=["ops", "leader", "research"],
        credentials={"feishu_app_id": "A"},
    )
    assert inst.members == ["ops", "research"]  # owner filtered out

    # a credentials-only update must not drop the team
    kept = ci.upsert_instance(
        settings, channel_type="feishu", instance_id=inst.instance_id,
        credentials={"feishu_app_secret": "S"},
    )
    assert kept.members == ["ops", "research"]

    # members=[] clears the team
    cleared = ci.upsert_instance(
        settings, channel_type="feishu", instance_id=inst.instance_id,
        members=[],
    )
    assert cleared.members == []
    assert "members" not in ci.read_raw_instances(settings)[0]


# ---------------------------------------------------------------------------
# bootstrap: carry a legacy flat feishu channel into channel_instances the
# first time the roster file is written (crossing into multi-Agent mode)
# ---------------------------------------------------------------------------

def test_bootstrap_is_idempotent_when_feishu_record_exists(tmp_path):
    settings = {
        "agent_workspace": str(tmp_path),
        "channel_type": "feishu",
        "feishu_app_id": "APP",
        "feishu_app_secret": "SECRET",
    }
    roster = {
        "channel_instances": [
            {"instance_id": "feishu-a", "channel_type": "feishu", "agent_id": "ops"}
        ]
    }
    records = ci.bootstrap_legacy_instances(settings, roster, "primary")
    # no duplicate feishu record was added
    assert [r["instance_id"] for r in records] == ["feishu-a"]


def test_bootstrap_skips_when_no_credentials(tmp_path):
    settings = {"agent_workspace": str(tmp_path), "channel_type": "feishu"}
    assert ci.bootstrap_legacy_instances(settings, {}, "primary") == []


def test_bootstrap_ignores_non_multi_instance_types(tmp_path):
    # wechatcom_app is a fixed-port webhook channel: it is not multi-instance
    # ready, so its flat config credentials must NOT be folded into an instance.
    settings = {
        "agent_workspace": str(tmp_path),
        "channel_type": "wechatcom_app",
        "wechatcom_corp_id": "corp",
        "wechatcomapp_secret": "sec",
    }
    assert ci.bootstrap_legacy_instances(settings, {}, "primary") == []
