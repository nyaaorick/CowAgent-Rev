r"""Replace wcferry's bundled DLLs with the ones from upstream's CI build.

Why this exists
---------------
This host runs WeChat **3.9.12.56**. The only wcferry build that targets it is
``39.6.0.0``, which comes from the maintainer's still-open PR #429 ("WeChat
3.9.12.56 Support") rather than from ``master`` -- there is no ``v39.6.0`` tag
or GitHub release.

The wheel on PyPI was uploaded **2026-07-09 04:01 UTC**, before that branch's CI
ever built successfully. Three CI runs failed after it, every one of them fixing
the x86 build:

    ci:  build x86 to match 3.9.12.56 target
    fix(ci): stop passing VcpkgTriplet via /p to avoid empty triplet
    fix(ci): generate nanopb sources before msbuild
    fix(ci): use manifest-installed vcpkg dependencies for x86 builds

The wheel's spy.dll behaves exactly like something built against the wrong
dependencies: injection, ``is_login``, ``get_self_wxid`` and ``send_text`` all
work, but ``AccountStorageMgr`` / ``MicroMsg.db`` lookups fail and the event
port (10087) never binds -- so no message is ever received.

This script installs the binaries from ``RUN_ID``, the single successful CI run
on that branch, and verifies them before touching anything.

Usage
-----
    .venv\Scripts\python scripts\wcf_ci_dlls.py            # install
    .venv\Scripts\python scripts\wcf_ci_dlls.py --status   # show what's in place
    .venv\Scripts\python scripts\wcf_ci_dlls.py --restore  # put the wheel's DLLs back

To install a build from somewhere else -- e.g. a fork carrying the
message-push fix that upstream's branch is missing -- pass both overrides:

    .venv\Scripts\python scripts\wcf_ci_dlls.py --repo you/WeChatFerry --run 12345

Nothing here talks to WeChat. After installing, fully quit and reopen WeChat --
a spy.dll already mapped into a running WeChat is not replaced by a file swap.
"""

import argparse
import io
import os
import re
import shutil
import struct
import sys
import urllib.request
import zipfile

# The one successful CI run on the 3.9.12.56 branch (commit 9081f0b, 2026-07-10).
# Artifacts expire 2026-10-08; after that, re-run CI or build from the branch.
REPO = "lich0821/WeChatFerry"
RUN_ID = "29104451248"
ARTIFACT = "wechatferry-binaries"


def artifact_url(repo=None, run_id=None):
    """nightly.link proxies GitHub Actions artifacts without a token."""
    return (f"https://nightly.link/{repo or REPO}/actions/runs/"
            f"{run_id or RUN_ID}/{ARTIFACT}.zip")


MEMBERS = ("sdk.dll", "spy.dll", "spy_debug.dll", "wcf.exe")
BACKUP_SUFFIX = ".wheel-backup"

IMAGE_FILE_MACHINE_I386 = 0x14C
TARGET_WECHAT = "3.9.12.56"
# Symbols that only exist in the 3.9.12.56 lineage -- absent from 39.5.2.0.
REQUIRED_SYMBOLS = ("AccountStorageMgr", "contact_manager", "MicroMsg.db")


def wcferry_dir():
    try:
        import wcferry
    except ImportError:
        sys.exit("wcferry is not installed in this interpreter.")
    return os.path.dirname(wcferry.__file__)


def pe_machine(data):
    """PE machine type, or None if this isn't a PE image."""
    if len(data) < 0x40 or data[:2] != b"MZ":
        return None
    offset = struct.unpack_from("<I", data, 0x3C)[0]
    if data[offset:offset + 4] != b"PE\0\0":
        return None
    return struct.unpack_from("<H", data, offset + 4)[0]


def strings_of(data):
    """MSVC mixes narrow literals and wide resource strings; search both."""
    return data.decode("latin-1", "ignore") + "\x00" + data.decode("utf-16-le", "ignore")


def verify(name, data):
    """Reject anything that isn't a 32-bit 3.9.12.56 spy build.

    These DLLs get injected into WeChat, so check before installing rather than
    finding out from a crashed WeChat.
    """
    problems = []
    if pe_machine(data) != IMAGE_FILE_MACHINE_I386:
        problems.append(f"not a 32-bit PE (machine={pe_machine(data)!r}); WeChat is x86")

    # Only the spy DLLs carry version strings and the storage symbols; sdk.dll
    # and wcf.exe are thin loaders and legitimately have neither.
    if name.startswith("spy"):
        blob = strings_of(data)
        versions = set(re.findall(r"\b3\.9\.\d+\.\d+\b", blob))
        if TARGET_WECHAT not in versions:
            problems.append(f"does not target {TARGET_WECHAT} (found {sorted(versions) or 'none'})")
        missing = [s for s in REQUIRED_SYMBOLS if s not in blob]
        if missing:
            problems.append(f"missing 3.9.12.56 symbols: {', '.join(missing)}")
    return problems


def fetch(url):
    print(f"downloading {url}")
    with urllib.request.urlopen(url, timeout=120) as r:
        blob = r.read()
    print(f"  {len(blob):,} bytes")
    payload = {}
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        names = {os.path.basename(n): n for n in z.namelist()}
        for m in MEMBERS:
            if m not in names:
                sys.exit(f"artifact has no {m} (contains: {sorted(names)})")
            payload[m] = z.read(names[m])
    return payload


def install(repo=None, run_id=None):
    target = wcferry_dir()
    payload = fetch(artifact_url(repo, run_id))

    print("\nverifying:")
    failed = False
    for name, data in payload.items():
        problems = verify(name, data)
        if problems:
            failed = True
            print(f"  FAIL {name}")
            for p in problems:
                print(f"       - {p}")
        else:
            print(f"  ok   {name}  ({len(data)//1024} KB)")
    if failed:
        sys.exit("\nverification failed; nothing was installed.")

    print(f"\ninstalling into {target}")
    for name, data in payload.items():
        dst = os.path.join(target, name)
        backup = dst + BACKUP_SUFFIX
        if os.path.exists(dst) and not os.path.exists(backup):
            shutil.copy2(dst, backup)
            print(f"  backed up {name} -> {os.path.basename(backup)}")
        try:
            with open(dst, "wb") as f:
                f.write(data)
        except PermissionError:
            # A spy.dll mapped into a running WeChat cannot be overwritten, but
            # Windows does allow renaming it out of the way.
            shutil.move(dst, dst + ".locked")
            with open(dst, "wb") as f:
                f.write(data)
            print(f"  {name} was locked by a running WeChat; moved aside")
        print(f"  wrote {name}  ({len(data)//1024} KB)")

    print("\nDone. Fully quit and reopen WeChat before starting CowAgent-Rev --")
    print("a spy.dll already mapped into a running WeChat is not replaced by a file swap.")


def restore():
    target = wcferry_dir()
    n = 0
    for name in MEMBERS:
        backup = os.path.join(target, name + BACKUP_SUFFIX)
        if os.path.exists(backup):
            shutil.copy2(backup, os.path.join(target, name))
            print(f"  restored {name} from the wheel's copy")
            n += 1
    print(f"{n} file(s) restored." if n else "no backups found; nothing to restore.")


def status():
    target = wcferry_dir()
    print(f"wcferry package: {target}\n")
    for name in MEMBERS:
        path = os.path.join(target, name)
        if not os.path.exists(path):
            print(f"  {name:<16} MISSING")
            continue
        data = open(path, "rb").read()
        blob = strings_of(data) if name.startswith("spy") else ""
        versions = sorted(set(re.findall(r"\b3\.9\.\d+\.\d+\b", blob))) if blob else []
        has_backup = os.path.exists(path + BACKUP_SUFFIX)
        print(f"  {name:<16} {len(data)//1024:>5} KB  "
              f"targets={','.join(versions) or '-':<10} "
              f"{'[CI build installed]' if has_backup else ''}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--restore", action="store_true", help="put the wheel's DLLs back")
    g.add_argument("--status", action="store_true", help="show which DLLs are in place")
    ap.add_argument("--repo", help=f"owner/name to pull the build from (default {REPO})")
    ap.add_argument("--run", help=f"CI run id to install (default {RUN_ID})")
    args = ap.parse_args()

    if args.status:
        status()
    elif args.restore:
        restore()
    else:
        install(args.repo, args.run)
