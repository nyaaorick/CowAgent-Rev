# encoding:utf-8
"""Filesystem capability probes for tests.

Creating a symlink on Windows needs SeCreateSymbolicLinkPrivilege, which an
ordinary account only holds when Developer Mode is on. Tests that build a
symlink to set up their fixture otherwise die with
``OSError: [WinError 1314] A required privilege is not held by the client``
before they ever reach the behaviour under test.

Probe the capability rather than branching on ``os.name``: the guards these
tests pin (symlink escapes out of the workspace, symlinks into the credential
dir) are real on Windows too, so the tests should run there whenever the host
can actually make a symlink.
"""

import os
import tempfile

import pytest


def symlinks_supported() -> bool:
    """True when this process can create a symlink in a temp directory."""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            link = os.path.join(tmp, "probe-link")
            target = os.path.join(tmp, "probe-target")
            open(target, "w").close()
            os.symlink(target, link)
            return True
    except (OSError, NotImplementedError, AttributeError):
        return False


requires_symlinks = pytest.mark.skipif(
    not symlinks_supported(),
    reason="cannot create symlinks (on Windows this needs Developer Mode "
    "or an elevated shell)",
)
