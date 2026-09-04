<p align="center"><img src="logo.png" width="96" alt="CowAgent-Rev"></p>

# Start here

Two steps on a fresh Windows machine.

### 1. Get the code

```cmd
git clone https://github.com/nyaaorick/CowAgent-Rev.git
```

That is the whole thing. **WeChatFerry is vendored inside this repository**, so
one clone — or one `git pull` — gets both halves. No `--recursive`, no submodule
init. A GitHub ZIP download works too.

### 2. Double-click `run.cmd`

The first run creates `config.json`, opens it in Notepad, and stops. Paste your
Zhipu GLM key into `"zhipu_ai_api_key"` (get one at
<https://open.bigmodel.cn/usercenter/apikeys>), save, and double-click again.

Then open <http://127.0.0.1:9899>.

---

## What `run.cmd` does

| Step | Action |
|---|---|
| 1 | Finds Python 3.13 → 3.10 via the `py` launcher, else `python` on PATH |
| 2 | Verifies the vendored `WeChatFerry/clients/python` is present |
| 3 | Creates `.venv` and installs `requirements.txt` (first run only) |
| 4 | Creates `config.json` from the template; refuses to start without an API key |
| 5 | Starts `app.py` with `PYTHONUTF8=1` so Chinese text is not mangled |

Re-running is cheap: steps 2–4 are skipped once satisfied.

## Switching to WeChat

`config.example.json` ships with `"channel_type": "web"` so the first run always
works. WeChat needs `"channel_type": "wcf"`, which additionally requires:

- a WCF-compatible WeChat build, logged in on this machine;
- `pip install wcferry` inside `.venv` (Windows-only wheel — `requirements.txt`
  installs it automatically on Windows and skips it elsewhere);
- **the `wcf` channel adapter, which is not implemented yet** — Milestone 4.2 in
  [`ROADMAP.md`](../ROADMAP.md). Until then `run.cmd` says so rather than
  failing obscurely.

## Remote debugging from another machine (optional)

If you want to drive this PC from a Mac or another box on the same LAN —
editing, running `pytest`, tailing logs — double-click **`enable-ssh.cmd`**. It
asks for administrator rights, then:

1. installs the **OpenSSH Server** Windows capability;
2. starts `sshd` and sets it to start automatically on boot;
3. adds an inbound firewall rule for **TCP 22 on the Private profile only**;
4. prompts for the client's SSH **public** key and installs it in the right
   place (see the warning below);
5. prints the IP, username, and a ready-to-paste `~/.ssh/config` block.

Safe to run twice — every step checks its own state first.

> **Port 22 is opened on the Private (home LAN) profile only.** Nothing here
> touches your router, so it is not reachable from the internet unless you
> separately forward the port. Don't.

> **Paste the `.pub` file, never the private key.** The script rejects anything
> that is not a public key, but the file you want is `id_ed25519.pub` — the one
> *with* the extension.

**If it stalls on "installing OpenSSH Server":** that step pulls the package
from Windows Update and legitimately takes several minutes. Check progress from
a second admin PowerShell with `Get-WindowsCapability -Online -Name OpenSSH.Server*`
(look at `State`) and `Get-Content C:\Windows\Logs\DISM\dism.log -Tail 20`. If
Windows Update is unreachable — common behind a proxy or VPN — install OpenSSH
directly from the [Win32-OpenSSH releases](https://github.com/PowerShell/Win32-OpenSSH/releases)
and re-run this script; it detects the existing install and skips that step.

**The Administrators gotcha:** if your Windows account is an administrator,
`sshd` **ignores** `C:\Users\<you>\.ssh\authorized_keys` entirely and reads
only `C:\ProgramData\ssh\administrators_authorized_keys`, which must also have
a locked-down ACL. Getting this wrong is the usual reason key authentication
"silently" falls back to asking for a password. `enable-ssh.cmd` detects your
group membership and handles both cases, including the ACL.

If the connection still refuses, the most common cause is the network adapter
being classified **Public** — the firewall rule does not apply there. The script
warns when it sees this and prints the one-liner to fix it.

## Files here

| File | Purpose |
|---|---|
| `run.cmd` | The double-click entry point |
| `config.example.json` | Config template, **API keys blank** |
| `check_config.py` | Pre-flight validation with actionable errors |
| `logo.ico` / `logo.png` | Icon for a desktop shortcut |
| `enable-ssh.cmd` | Opens the remote debug channel (self-elevating) |
| `enable-ssh.ps1` | The work behind `enable-ssh.cmd` |

## Notes

`config.json` lives at the **repo root**, not in this folder, and is
git-ignored — your API key is never committed. This folder holds only the blank
template.

The console binds `127.0.0.1`. To reach it from another machine on the LAN, set
`"web_host": "0.0.0.0"` and allow TCP 9899 on the Windows private-profile
firewall (see ROADMAP Milestone 3.4).
