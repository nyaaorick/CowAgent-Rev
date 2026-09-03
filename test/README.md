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

## Files here

| File | Purpose |
|---|---|
| `run.cmd` | The double-click entry point |
| `config.example.json` | Config template, **API keys blank** |
| `check_config.py` | Pre-flight validation with actionable errors |
| `logo.ico` / `logo.png` | Icon for a desktop shortcut |

## Notes

`config.json` lives at the **repo root**, not in this folder, and is
git-ignored — your API key is never committed. This folder holds only the blank
template.

The console binds `127.0.0.1`. To reach it from another machine on the LAN, set
`"web_host": "0.0.0.0"` and allow TCP 9899 on the Windows private-profile
firewall (see ROADMAP Milestone 3.4).
