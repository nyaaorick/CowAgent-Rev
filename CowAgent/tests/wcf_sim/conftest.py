import pytest

from . import wcf_proto


@pytest.fixture(autouse=True)
def _require_submodule():
    if wcf_proto.IMPORT_ERROR is not None:
        pytest.skip(f"{wcf_proto.SUBMODULE_HINT} ({wcf_proto.IMPORT_ERROR})")


@pytest.fixture
def wcf_server():
    from .fake_wcf_server import FakeWcfServer
    with FakeWcfServer() as server:
        yield server


@pytest.fixture
def wcf_client(wcf_server):
    """The real mainline wcferry client, in remote mode against the fake server."""
    client = wcf_proto.Wcf(host="127.0.0.1", port=wcf_server.port, debug=False)
    try:
        yield client
    finally:
        try:
            client.cleanup()
        except Exception:
            pass
