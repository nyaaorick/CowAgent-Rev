# encoding:utf-8
"""Cross-platform HOME redirection for tests that need an isolated home dir.

``os.environ["HOME"] = tmp`` is a POSIX-only idiom. On Windows
``ntpath.expanduser`` never looks at ``HOME`` -- it reads ``USERPROFILE``
first, falling back to ``HOMEDRIVE`` + ``HOMEPATH``. A test that sets only
``HOME`` therefore still resolves ``~`` to the developer's real home on
Windows, and any assertion about a temp-dir home silently compares against
the wrong path.

Set every variable the two platforms consult so ``~`` resolves to *path*
everywhere.
"""

import os

_HOME_VARS = ("HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH")


def redirect_home(path):
    """Point ``~`` at *path*. Returns a token for :func:`restore_home`."""
    saved = {name: os.environ.get(name) for name in _HOME_VARS}
    drive, tail = os.path.splitdrive(os.path.abspath(path))
    os.environ["HOME"] = path
    os.environ["USERPROFILE"] = path
    os.environ["HOMEDRIVE"] = drive
    os.environ["HOMEPATH"] = tail or os.sep
    return saved


def restore_home(saved):
    """Undo a :func:`redirect_home`, including vars that were unset before."""
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def redirect_home_monkeypatch(monkeypatch, path):
    """The :func:`redirect_home` behaviour for pytest's ``monkeypatch``."""
    drive, tail = os.path.splitdrive(os.path.abspath(path))
    monkeypatch.setenv("HOME", str(path))
    monkeypatch.setenv("USERPROFILE", str(path))
    monkeypatch.setenv("HOMEDRIVE", drive)
    monkeypatch.setenv("HOMEPATH", tail or os.sep)
