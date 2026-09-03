<p align="center"><img src="logo.png" width="96" alt="CowAgent-Rev"></p>

# Start here

Three steps on a fresh Windows machine.

### 1. Clone (not download)

```cmd
git clone --recursive https://github.com/<you>/CowAgent-Rev.git
```

`--recursive` pulls WeChatFerry too. A **ZIP download will not work** — GitHub
ZIPs omit submodules. If you already cloned without it, `run.cmd` fixes it for
you on first start.

### 2. Double-click `run.cmd`

The first run creates `config.json`, opens it in Notepad, and stops. Paste your
Zhipu GLM key into `"zhipu_ai_api_key"` (get one at
<https://open.bigmodel.cn/usercenter/apikeys>), save, and double-click again.

### 3. Open the console

<http://127.0.0.1:9899>

---

## What `run.cmd` does

| Step | Action |
|---|---|
| 1 | Finds Python 3.13 → 3.10 via the `py` launcher, else `python` on PATH |
| 2 | Fetches the WeChatFerry submodule if missing |
| 3 | Creates `.venv` and installs `requirements.txt` (first run only) |
| 4 | Creates `config.json` from the template; refuses to start without an API key |
| 5 | Starts `app.py` with `PYTHONUTF8=1` so Chinese text is not mangled |

Re-running is cheap: steps 2–4 are skipped once satisfied.

## Switching to WeChat

`config.example.json` ships with `"channel_type": "web"` so the first run always
works. WeChat needs `"channel_type": "wcf"`, which additionally requires:

- a WCF-compatible WeChat build, logged in on this machine;
- `pip install wcferry` inside `.venv` (Windows-only wheel);
- **the `wcf` channel adapter, which is not implemented yet** — Milestone 4.2 in
  [`ROADMAP.md`](../ROADMAP.md). Until then `run.cmd` will tell you so rather
  than failing obscurely.

## Files here

| File | Purpose |
|---|---|
| `run.cmd` | The double-click entry point |
| `config.example.json` | Config template, **API keys blank** |
| `check_config.py` | Pre-flight validation with actionable errors |
| `logo.ico` / `logo.png` | Icon for a desktop shortcut |

## Notes

`config.json` lives at the **repo root**, not in this folder, and is
git-ignored — your API key is never committed. This folder only holds the
blank template.

The console binds `127.0.0.1`. To reach it from another machine on the LAN, set
`"web_host": "0.0.0.0"` and allow TCP 9899 on the Windows private-profile
firewall (see ROADMAP Milestone 3.4).
