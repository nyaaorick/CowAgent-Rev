"""Guards on test/ -- the Windows one-click deploy folder.

The folder exists to be copied onto a fresh machine and double-clicked, so the
two things that must never rot are: it ships no secrets, and run.cmd still
points at files that exist.
"""

import io
import json
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPLOY = os.path.join(ROOT, "test")


def _read(name):
    return io.open(os.path.join(DEPLOY, name), encoding="utf-8").read()


def test_the_folder_has_everything_an_operator_needs():
    for name in ("run.cmd", "config.example.json", "check_config.py",
                 "README.md", "logo.ico", "logo.png",
                 "enable-ssh.cmd", "enable-ssh.ps1"):
        assert os.path.isfile(os.path.join(DEPLOY, name)), f"test/{name} is missing"


def test_the_example_config_ships_no_secrets():
    """The single most damaging regression this folder could have."""
    cfg = json.load(io.open(os.path.join(DEPLOY, "config.example.json"), encoding="utf-8"))
    for key, value in cfg.items():
        if key.endswith("_api_key") or key.endswith("_secret") or key == "web_password":
            assert value == "", f"{key} must ship blank, got {value!r}"


def test_no_api_key_shaped_string_anywhere_in_the_folder():
    """Belt and braces: catch a key pasted into the README or run.cmd too."""
    # Zhipu keys look like <32 hex>.<16 alnum>; also catch sk- style tokens.
    suspicious = re.compile(r"[0-9a-f]{32}\.[A-Za-z0-9]{12,}|sk-[A-Za-z0-9]{20,}")
    for name in os.listdir(DEPLOY):
        path = os.path.join(DEPLOY, name)
        if not os.path.isfile(path) or name.endswith((".ico", ".png")):
            continue
        text = io.open(path, encoding="utf-8", errors="replace").read()
        assert not suspicious.search(text), f"test/{name} looks like it contains a live key"


def test_the_example_config_defaults_to_a_channel_that_can_actually_start():
    """`wcf` cannot start until Milestone 4.2; a first run must not die on it."""
    cfg = json.load(io.open(os.path.join(DEPLOY, "config.example.json"), encoding="utf-8"))
    assert cfg["channel_type"] in ("web", "terminal")


def test_run_cmd_references_only_files_that_exist():
    cmd = _read("run.cmd")
    for referenced in ("config.example.json", "check_config.py"):
        assert referenced in cmd
        assert os.path.isfile(os.path.join(DEPLOY, referenced))
    assert "app.py" in cmd and os.path.isfile(os.path.join(ROOT, "app.py"))
    assert "requirements.txt" in cmd and os.path.isfile(os.path.join(ROOT, "requirements.txt"))


def test_run_cmd_sets_utf8_before_anything_prints():
    """Without this, Chinese output and CJK paths are mangled on cp936 hosts."""
    cmd = _read("run.cmd")
    assert "PYTHONUTF8=1" in cmd
    assert "chcp 65001" in cmd


def test_run_cmd_checks_the_vendored_wechatferry():
    """WeChatFerry is vendored, not a submodule: run.cmd must verify it is
    present and say so clearly, never tell the operator to init a submodule."""
    cmd = _read("run.cmd")
    assert "WeChatFerry" in cmd
    assert "git submodule" not in cmd, "WeChatFerry is vendored; submodule advice is wrong"


def test_the_real_config_is_git_ignored():
    gitignore = io.open(os.path.join(ROOT, ".gitignore"), encoding="utf-8").read()
    assert re.search(r"^config\.json$", gitignore, re.M), \
        "config.json must stay git-ignored -- it holds a live API key"


# ---------------------------------------------------------------------------
# enable-ssh.cmd / .ps1 -- the remote debug channel
# ---------------------------------------------------------------------------

def test_enable_ssh_elevates_itself():
    """Every step needs admin; without elevation it fails halfway through."""
    cmd = _read("enable-ssh.cmd")
    assert "net session" in cmd, "must detect whether it is already elevated"
    assert "-Verb RunAs" in cmd, "must re-launch elevated when it is not"


def test_enable_ssh_does_not_forward_arguments_through_elevation():
    """An SSH key contains spaces. Passing it through cmd -> PowerShell ->
    Start-Process quoting is fragile, and an empty -ArgumentList throws.
    The ps1 prompts instead."""
    assert "-ArgumentList" not in _read("enable-ssh.cmd")


def test_enable_ssh_restricts_the_firewall_rule_to_the_private_profile():
    """Opening port 22 on the Public profile would expose it on untrusted
    networks (cafe wifi, hotel), which is the one thing this must never do."""
    ps1 = _read("enable-ssh.ps1")
    assert "-Profile Private" in ps1
    assert "-Profile Any" not in ps1
    assert "-Profile Public" not in ps1


def test_enable_ssh_handles_the_administrators_authorized_keys_quirk():
    """sshd ignores ~/.ssh/authorized_keys for accounts in the Administrators
    group and reads only the shared file -- the usual reason key auth silently
    falls back to a password prompt."""
    ps1 = _read("enable-ssh.ps1")
    assert "administrators_authorized_keys" in ps1
    assert "IsInRole" in ps1, "must actually test group membership, not guess"
    assert "icacls" in ps1, "sshd rejects that file if its ACL is too permissive"


def test_enable_ssh_refuses_a_private_key():
    """Pasting the file without .pub is an easy, and very bad, mistake."""
    ps1 = _read("enable-ssh.ps1")
    assert "ssh-ed25519" in ps1 and "notmatch" in ps1
    assert "PRIVATE key" in ps1, "must warn explicitly about pasting a private key"


def test_enable_ssh_is_idempotent():
    """It is normal to run this twice; it must not duplicate a firewall rule
    or an authorized key."""
    ps1 = _read("enable-ssh.ps1")
    assert "Get-NetFirewallRule" in ps1, "must check before creating the rule"
    assert "$existing -contains $PublicKey" in ps1, "must check before appending the key"


def test_enable_ssh_reports_how_to_connect():
    ps1 = _read("enable-ssh.ps1")
    assert "Get-NetIPAddress" in ps1
    assert "HostName" in ps1, "should print a ready-to-paste ssh config block"


def test_enable_ssh_is_documented_in_the_readme():
    readme = _read("README.md")
    assert "enable-ssh.cmd" in readme


def test_enable_ssh_does_not_hide_the_install_progress():
    """Add-WindowsCapability takes minutes. Piping it to Out-Null hides DISM's
    progress bar and makes a working install look frozen."""
    ps1 = _read("enable-ssh.ps1")
    assert "Add-WindowsCapability -Online -Name $cap.Name\n" in ps1 or \
           "Add-WindowsCapability -Online -Name $cap.Name" in ps1
    assert "Add-WindowsCapability -Online -Name $cap.Name | Out-Null" not in ps1


def test_enable_ssh_offers_a_windows_update_fallback():
    """Windows Update is frequently unreachable behind a proxy/VPN, which is
    where this step actually stalls. The script must say what to do instead."""
    ps1 = _read("enable-ssh.ps1")
    assert "Win32-OpenSSH" in ps1, "must point at the GitHub release"
    assert "dism.log" in ps1, "must say how to diagnose the stall"
