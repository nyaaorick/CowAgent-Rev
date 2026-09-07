# encoding:utf-8

"""The long-lived WeChatFerry gateway.

Ported out of ``cowagent2`` so the production channel no longer imports a
read-only reference tree at runtime, and re-joined to the spy pre-flight it had
been bypassing.

That pre-flight is the point of most of these tests. ``wcferry``'s ``Wcf()``
constructor answers a failed dial with ``os._exit(-2)`` -- not an exception, an
immediate process kill that takes the web console down with it (ROADMAP
WCF-BUG-03). So the gateway has to establish that something is listening
*before* it ever constructs a client, and a bad outcome has to become an
ordinary return value.
"""

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from channel.wcf import gateway as mod
from channel.wcf.gateway import WcfGateway


class _FakeRun:
    def __init__(self, returncode):
        self.returncode = returncode


class _FakeWcf:
    def __init__(self, logged_in=True):
        self._logged_in = logged_in
        self.sent = []
        self.recv_enabled = False

    def is_login(self):
        return self._logged_in

    def get_user_info(self):
        return {"wxid": "wxid_me", "name": "Operator"}

    def enable_receiving_msg(self):
        self.recv_enabled = True
        return True

    def get_msg(self):
        raise RuntimeError("no messages in tests")

    def send_text(self, msg, receiver, aters=""):
        self.sent.append((msg, receiver, aters))
        return 0


@pytest.fixture
def gw():
    """A gateway that is not the process-wide singleton."""
    return WcfGateway(port=10086)


@pytest.fixture
def wechat_running(monkeypatch):
    monkeypatch.setattr(WcfGateway, "is_wechat_process_running", staticmethod(lambda: True))
    monkeypatch.setattr(WcfGateway, "clean_stale_locks", staticmethod(lambda: None))


# ------------------------------------------------------------- independence
def test_the_gateway_does_not_import_the_reference_tree():
    """cowagent2 is a read-only reference; production must not load it.

    Checked against the parsed imports rather than the file's text, so the
    docstring may keep explaining where this was ported from.
    """
    import ast

    tree = ast.parse(open(mod.__file__, encoding="utf-8").read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    assert not [name for name in imported if name.split(".")[0] == "cowagent2"]
    assert not any(name.split(".")[0] == "cowagent2" for name in sys.modules)


# ------------------------------------------------------------- the pre-flight
def _preflight(monkeypatch, *, rc, listening):
    monkeypatch.setattr(mod, "_port_listening", lambda port, host="127.0.0.1": listening)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeRun(rc))
    # Keep the retry loop from costing the test 15 seconds.
    monkeypatch.setattr(mod, "_wait_for_port", lambda port, timeout=15: listening)
    return mod.ensure_spy_listening(10086)


def test_an_already_listening_spy_needs_no_injection(monkeypatch):
    monkeypatch.setattr(mod, "_port_listening", lambda port, host="127.0.0.1": True)

    def fail(*a, **k):
        raise AssertionError("wcf.exe must not run when the port already answers")

    monkeypatch.setattr(subprocess, "run", fail)
    assert mod.ensure_spy_listening(10086) is None


def test_a_fresh_injection_that_comes_up_is_accepted(monkeypatch):
    assert _preflight(monkeypatch, rc=0, listening=True) is None


def test_a_wedged_spy_raises_instead_of_killing_the_process(monkeypatch):
    """Exit code 10 means "already injected", which wcferry treats as ready.

    It is also what a stopped-but-loaded spy returns, and then nothing is
    listening -- the case that used to reach os._exit.
    """
    with pytest.raises(RuntimeError) as excinfo:
        _preflight(monkeypatch, rc=10, listening=False)

    message = str(excinfo.value)
    assert "10086" in message
    assert "quit WeChat" in message  # the only remedy that actually works


def test_an_injected_and_healthy_spy_is_accepted(monkeypatch):
    assert _preflight(monkeypatch, rc=10, listening=True) is None


def test_a_fresh_injection_that_never_binds_raises(monkeypatch):
    with pytest.raises(RuntimeError):
        _preflight(monkeypatch, rc=0, listening=False)


def test_an_unknown_exit_code_still_raises_rather_than_continuing(monkeypatch):
    with pytest.raises(RuntimeError) as excinfo:
        _preflight(monkeypatch, rc=5, listening=False)
    assert "exit 5" in str(excinfo.value)


def test_wechat_not_running_says_so(monkeypatch):
    with pytest.raises(RuntimeError) as excinfo:
        _preflight(monkeypatch, rc=4, listening=False)
    assert "WeChat is not running" in str(excinfo.value)


# --------------------------------------------------- connect() ordering rules
def test_connect_runs_the_preflight_before_building_a_client(gw, monkeypatch, wechat_running):
    """The whole point: nothing may construct Wcf() against a dead port."""
    order = []
    monkeypatch.setattr(mod, "ensure_spy_listening",
                        lambda port: order.append("preflight"))
    monkeypatch.setattr(WcfGateway, "_build_client",
                        lambda self: (order.append("client"), _FakeWcf())[1])

    assert gw.connect() is True
    assert order == ["preflight", "client"]


def test_a_failed_preflight_never_builds_a_client(gw, monkeypatch, wechat_running):
    def boom(port):
        raise RuntimeError("spy is wedged")

    def must_not_run(self):
        raise AssertionError("Wcf() must not be constructed after a failed pre-flight")

    monkeypatch.setattr(mod, "ensure_spy_listening", boom)
    monkeypatch.setattr(WcfGateway, "_build_client", must_not_run)

    assert gw.connect() is False
    assert gw.is_running is False


def test_a_stopped_wechat_is_reported_rather_than_dialled(gw, monkeypatch):
    monkeypatch.setattr(WcfGateway, "is_wechat_process_running", staticmethod(lambda: False))
    monkeypatch.setattr(WcfGateway, "_build_client",
                        lambda self: (_ for _ in ()).throw(AssertionError("must not dial")))
    assert gw.connect() is False


def test_a_running_but_logged_out_wechat_does_not_start_the_listener(
        gw, monkeypatch, wechat_running):
    monkeypatch.setattr(mod, "ensure_spy_listening", lambda port: None)
    monkeypatch.setattr(WcfGateway, "_build_client", lambda self: _FakeWcf(logged_in=False))

    assert gw.connect() is False
    assert gw.is_running is False


# ------------------------------------------------------------------ outbound
def test_sending_before_connecting_is_refused(gw):
    assert gw.send_text("hi", "wxid_alice") == -1


def test_a_connected_gateway_sends(gw, monkeypatch, wechat_running):
    monkeypatch.setattr(mod, "ensure_spy_listening", lambda port: None)
    fake = _FakeWcf()
    monkeypatch.setattr(WcfGateway, "_build_client", lambda self: fake)
    monkeypatch.setattr(WcfGateway, "_start_listener", lambda self: None)

    gw.connect()
    assert gw.send_text("hi", "wxid_alice") == 0
    assert fake.sent == [("hi", "wxid_alice", "")]


def test_an_exception_while_sending_is_reported_not_raised(gw, monkeypatch, wechat_running):
    monkeypatch.setattr(mod, "ensure_spy_listening", lambda port: None)

    class Exploding(_FakeWcf):
        def send_text(self, msg, receiver, aters=""):
            raise RuntimeError("rpc timeout")

    monkeypatch.setattr(WcfGateway, "_build_client", lambda self: Exploding())
    monkeypatch.setattr(WcfGateway, "_start_listener", lambda self: None)

    gw.connect()
    assert gw.send_text("hi", "wxid_alice") != 0


# ----------------------------------------------------------------- singleton
def test_get_instance_returns_one_gateway_per_process():
    """One injection per process; a second client would wedge spy.dll."""
    mod.reset_instance()
    try:
        assert WcfGateway.get_instance(port=10086) is WcfGateway.get_instance(port=10086)
    finally:
        mod.reset_instance()
