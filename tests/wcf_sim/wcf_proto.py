"""Import the genuine `wcferry` package out of the vendored WeChatFerry tree.

Deliberately not `pip install wcferry`: the point of the harness is to exercise
the exact client and protobuf definitions this repo vendors, so a version drift
between the vendored tree and PyPI shows up as a test failure rather than as a
surprise on the Windows host.
"""

from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CLIENT_PATH = os.path.join(_REPO_ROOT, "WeChatFerry", "clients", "python")

SUBMODULE_HINT = (
    f"wcferry client not found at {CLIENT_PATH}. WeChatFerry is vendored in this "
    "repo, so this usually means an incomplete checkout -- try: git checkout -- WeChatFerry"
)


def available() -> bool:
    return os.path.isfile(os.path.join(CLIENT_PATH, "wcferry", "client.py"))


if available() and CLIENT_PATH not in sys.path:
    sys.path.insert(0, CLIENT_PATH)

try:
    from wcferry import wcf_pb2  # noqa: E402
    from wcferry.client import Wcf  # noqa: E402
    from wcferry.wxmsg import WxMsg  # noqa: E402
    IMPORT_ERROR = None
except Exception as e:  # pragma: no cover - only when the vendored tree is missing
    wcf_pb2 = None
    Wcf = None
    WxMsg = None
    IMPORT_ERROR = e
