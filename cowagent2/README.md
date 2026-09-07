# CowAgent 2 — Minimalist WeChat Agent (WCF 3.9.12.56)

CowAgent 2 is a clean-room rebuild of CowAgent dedicated to **native Windows
WeChat 3.9.12.56 driven through WeChatFerry (WCF)**. It drops the multi-channel
adapter stack of CowAgent 1 in favour of one long-lived process, strict
session isolation, and a human-simulated conversational surface.

- **Roadmap and milestones:** [`ROADMAP.md`](ROADMAP.md)
- **Workspace-wide roadmap (authoritative):** [`../ROADMAP.md`](../ROADMAP.md)
- **WCF repair notes:** [`../docs/WCF_WECHAT_3.9.12.56_REPAIR.md`](../docs/WCF_WECHAT_3.9.12.56_REPAIR.md)

---

## Core features

1. **Zero-config reuse.** LLM credentials and model parameters are read
   straight from `CowAgent/config.json` (`zhipu_ai_api_key`, `model`,
   `temperature`, `top_p`, `character_desc`). Nothing is entered twice.
2. **Default-deny access control.** Only contacts in `allowed_wxids` and rooms
   in `allowed_rooms` can reach the bot. An empty or malformed list means
   *nobody*, so a truncated config fails closed — the rule established by
   CowAgent 1's `channel/wcf/contact_filter.py`.
3. **Strict session isolation.** Every `wxid` and every `roomid` owns a
   separate context with its own sliding window. Nothing crosses between
   sessions, and `#清除记忆` / `#reset` clears only the caller's own history.
4. **Human simulation.** A persona prompt tuned for real WeChat speech, plus
   length-derived reading (0.6–2.5 s) and typing (1.0–5.0 s) delays so replies
   never land in machine time.
5. **Localhost console.** `http://127.0.0.1:9900` serves live WeChat and WCF
   health, the discovered contact/room table with one-click whitelist and
   auto-reply toggles, a session inspector, and an SSE live-chat stream.
6. **Full contact resolution.** With the patched `spy.dll` (offset `0x20dd4`,
   `0x34` → `0x38`), `MicroMsg.db` opens natively and every session binds
   `wxid` + WeChat ID (`Alias`) + display name (`Remark` / `NickName`).
7. **Anti-wedge singleton gateway.** One long-lived `Wcf(debug=False)`
   instance using the Release `spy.dll`, avoiding the Debug-CRT crash
   (WCF-BUG-05) and the RPC lockouts caused by short-lived clients
   (WCF-BUG-03).
8. **CowAgent 1 as the reuse baseline.** Anything touching WCF transport
   follows the implementation already proven on real hardware in
   `CowAgent/channel/wcf/wcf_channel.py` — `send_text(msg, receiver, aters)`
   positionally, `status == 0` checked strictly, `is_login()` for liveness.

---

## Layout

```text
cowagent2/
├── __init__.py                # Package marker
├── app.py                     # Entry point and lifespan coordinator
├── config.py                  # Config reuse + whitelist / access control
├── wcf_gateway.py             # WCF singleton gateway and message listener
├── scanner.py                 # Contact & chatroom discovery and name binding
├── memory.py                  # Isolated short-term session memory
├── human_simulator.py         # Persona prompt, reading/typing pacing
├── bot.py                     # GLM dispatch loop and authorisation gate
├── web_server.py              # Console backend (aiohttp REST + SSE)
├── static/index.html          # Console frontend
├── data/                      # Runtime state (gitignored)
│   ├── whitelist.json
│   └── contacts_cache.json
├── tests/
│   ├── test_config_access_control.py
│   ├── test_human_simulator.py
│   ├── test_memory_isolation.py
│   └── test_web_server.py
├── README.md                  # This document
└── ROADMAP.md                 # Milestones and the memory-system plan
```

---

## Running

1. Start and log into the WeChat client (3.9.12.56) manually. CowAgent 2 never
   launches or terminates WeChat itself.
2. Launch the agent:
   ```powershell
   .venv\Scripts\python.exe -m cowagent2.app
   ```
3. Open the console at `http://127.0.0.1:9900`.
4. Tick the contacts or rooms the bot may talk to. `filehelper` (File Transfer
   Assistant) is allowed by default and is the only safe first test target.
5. Message the File Transfer Assistant from WeChat to see a reply.

### Configuration keys

All keys live in `CowAgent/config.json` and are shared with CowAgent 1.

| Key | Default | Meaning |
|---|---|---|
| `zhipu_ai_api_key` | — | Zhipu AI credential (required) |
| `model` | `glm-4-flash` | Chat model. Any `4.7` variant is rewritten to `glm-4-flash` per the ROADMAP model policy. |
| `temperature` / `top_p` | `0.7` | Sampling parameters |
| `character_desc` | — | Extra persona instructions appended to the human-simulation prompt |
| `cowagent2_web_port` | `9900` | Console port |
| `cowagent2_debug_sql` | `false` | Enables the console's raw-SQL inspection endpoint. Leave off: it reads the entire WeChat message database and the console is unauthenticated. |

---

## Tests

```powershell
.venv\Scripts\python.exe -m pytest cowagent2/tests -q
```

The suite injects its own config, scanner cache, and memory store, so it never
reads or writes the operator's live `data/` files.

---

## Known constraints

- **Memory is volatile.** Session history lives in process only; a restart is
  total amnesia. Durable global and per-contact memory is Milestone 7 in
  [`ROADMAP.md`](ROADMAP.md).
- **The console has no authentication.** It binds to `127.0.0.1` only, but any
  process on the host can call it. CowAgent 1's HMAC token scheme
  (`CowAgent/channel/web/web_channel.py`) is the intended port — Milestone 9.2.
- **Text only.** `WxMsg.type != 1` is ignored; images, voice and files are
  Milestone 8.
- **The console UI is still Chinese.** Backend code, comments and docs are
  English; `static/index.html` has not been translated yet (Milestone 9.4).
