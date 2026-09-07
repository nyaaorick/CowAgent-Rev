# CowAgent-Rev & WeChatFerry Unified Technical Roadmap (ROADMAP)

This document establishes the technical roadmap for **CowAgent-Rev** and its vendored **WeChatFerry** subsystem.

## Core Directives

1. **100% Native Windows Development & Runtime**:
   All development, testing, and runtime operations occur directly on the native Windows environment. Cross-host assumptions (such as macOS remote development or SSH tunnels) have been eliminated.
2. **Unified Workspace Aggregation**:
   `CowAgent/` (the multi-agent cognitive architecture) and `WeChatFerry/` (the reverse-engineered WeChat 3.9.12.56 C++ hook & Python client) reside in the same repository, sharing a unified Python virtual environment (`.venv/`).
3. **In-Tree Maintenance & Repair of WeChatFerry**:
   WeChatFerry upstream is archived and PR #429 (branch `3.9.12.56`) was left incomplete. We take full ownership of maintaining, fixing, and testing the 12.56 hook code, Python SDK, and binary artifacts within this project.
4. **Strict Incremental MVP**:
   - **Phase 1 MVP**: Verification via WeChat's built-in **File Transfer Assistant (`filehelper`)** — outbound transmission, login status checks, and non-intrusive protocol validation.
   - **Phase 2 MVP**: Full inbound message capture via repaired socket delivery and automated AI reply loop with `glm-4-flash`.
   - **Phase 3 & Beyond**: Multimedia attachment handling, SQLite database handle diagnostics, and connection recovery.

---

## Upstream 3.9.12.56 Technical Assessment & Defect Matrix

### Upstream Status (Source of Truth)
- **Repository Archived**: Upstream `https://github.com/lich0821/WeChatFerry` is formally archived (read-only). The author announced in Issue #428: *"新版本修吧，这个不修了"* (Will fix in a future version, not fixing this one).
- **PR #429 Unmerged**: Adaptation for WeChat 3.9.12.56 exists solely in unmerged PR #429 (branch `3.9.12.56`, 55 commits). It has no Git tag, no official GitHub release, and development ceased on 2026-07-10.
- **x86 Architecture Shift**: WeChat 3.9.12.56 reverted from x64 to a 32-bit (x86) memory model, requiring 32-bit compilation for `spy.dll` and `sdk.dll`.

### Upstream Defect Matrix

| Defect ID | Component | Upstream Root Cause | Impact | Resolution Strategy |
|---|---|---|---|---|
| **WCF-BUG-01** | `spy/rpc_server.cpp` | `msgSock` socket is declared and closed, but never opened or bound via `nng_listen` to port 10087; `gMsgQueue` is populated in `message_receiver.cpp` but never popped anywhere in the tree. | `enable_receiving_msg()` succeeds superficially, but client connection to 10087 throws `ConnectionRefused`; inbound message receipt is completely broken. | Port the message consumer thread (`RunMsgServer`) from `master`: open `msgSock`, listen on `tcp://0.0.0.0:10087`, and run a condition-variable worker loop popping `gMsgQueue`. |
| **WCF-BUG-02** | `spy/database_executor.cpp` | `AccountStorageMgr` offset (`base + 0x4327610`) or storage-array traversal fails under 3.9.12.56 memory layout; `find_db_handle` logs `Failed to get handle for database 'MicroMsg.db'`. | `get_contacts()` returns 0 contacts; contact nicknames fall back to raw `wxid`. | In-process DB access diagnostic. Does not block message hook delivery (group `@` tags are extracted from message XML directly). |
| **WCF-BUG-03** | `wcferry/client.py` & `spy.dll` | Short-lived Python processes invoke `Wcf.__del__` -> `cleanup()` -> `wcf.exe stop`, unhooking WeChat ungracefully or leaving file locks open. | Spy becomes wedged or crashes WeChat; subsequent injection fails with `spy 已注入` or silent failure. Requires complete WeChat restart. | Enforce single long-lived process convention; avoid short throwaway scripts; use defensive shutdown handling. |
| **WCF-BUG-04** | `clients/python/wcferry/wxmsg.py` | Line 59 regular expression uses `[\s|\S]*` without raw string declaration (`r"..."`). | Triggers `SyntaxWarning: invalid escape sequence '\s'` on Python 3.12+ and Python 3.13. | Update string literal to raw string `r"..."`. |
| **WCF-BUG-05** | `spy_debug.dll` / `wcferry.Wcf(debug=True)` | `Wcf(debug=True)` (wcferry default) injects `spy_debug.dll`, compiled with MSVC Debug CRT (`/MDd` / `_ITERATOR_DEBUG_LEVEL=2`). Passing Debug STL containers (`std::vector<WxString>`, `std::wstring`) into Release WeChat (`WeChatWin.dll` `/MD`) triggers an immediate access violation / breakpoint (`0x80000003`) crash in `sendMsg`. | WeChat client crashes immediately with error dialog reporting `错误模块: spy_debug.dll` upon sending text. | Explicitly instantiate `Wcf(debug=False)` to inject the Release `spy.dll` which strictly shares Release CRT ABI with WeChat. Clean `.wcf.lock` on startup. |

---

## Architectural Topology & Workspace Layout

```
[ Local Windows 11 PC — Single Host Development & Runtime ]
   │
   ├── Native WeChat Client (WeChat.exe v3.9.12.56, officially logged in)
   │     ▲
   │     │ Injected via wcf.exe (32-bit)
   │     ▼
   ├── WeChatFerry Subsystem (WeChatFerry/)
   │     ├── spy.dll (x86 C++ Hook & In-Memory Detours)
   │     │     ├── TCP 127.0.0.1:10086 (Command Channel: send, status, contacts)
   │     │     └── TCP 127.0.0.1:10087 (Repaired Event Channel: incoming message push)
   │     └── Python Client (clients/python/wcferry/)
   │           └── Wcf RPC Client (pynng connection to 10086 & 10087)
   │
   ├── CowAgent-Rev Core (CowAgent/)
   │     ├── Channel Layer: CowAgent/channel/wcf/ (WcfChannel adapter)
   │     ├── Bridge & Orchestrator: CowAgent/bridge/
   │     ├── Multi-Agent Runtime: Agent teams, skills, evolution, persistent memory
   │     ├── Web Console: TCP 127.0.0.1:9899 (management UI)
   │     └── LLM Provider: Zhipu AI GLM SDK (native glm-4-flash)
   │
   └── Unified Environment
         └── .venv/ (Python 3.13.15 64-bit with wcferry, pynng, zai-sdk, pytest)
```

### Directory Structure
```text
C:\Users\1\CowAgent-Rev\
├── .venv/                         # Shared Python 3.13 virtual environment
├── CowAgent/                      # Main application codebase
│   ├── app.py                     # Primary entry point
│   ├── config.py                  # System configuration loader
│   ├── agent/                     # Agent runtime, tools, memory, permissions
│   ├── bridge/                    # Message routing & LLM bridge
│   ├── channel/                   # Channel implementations (web, terminal, wcf)
│   ├── tests/                     # 950+ unit & integration test suite
│   └── docs/                      # CowAgent-Rev system documentation
├── WeChatFerry/                    # Vendored WeChatFerry (branch 3.9.12.56)
│   ├── WeChatFerry/               # C++ Visual Studio project
│   │   ├── spy/                   # Core hooks, rpc_server, message_receiver
│   │   ├── sdk/                   # DLL injection bootstrap
│   │   └── wcf/                   # CLI launcher (wcf.exe)
│   └── clients/python/            # Python wcferry client source
├── backup/                        # [DEPRECATED / ARCHIVED] Historic patches & notes
├── ROADMAP.md                     # This authoritative document
└── pyproject.toml / requirements  # Project dependency definitions
```

---

## Detailed Execution Milestones

### Milestone 1: Workspace Consolidation & Pure Windows Baseline
> **Goal**: Solidify the local Python 3.13 runtime on Windows, eliminate syntax warnings, and lock in the unit test baseline.

- [x] **1.1 Clone WeChatFerry 3.9.12.56 into Workspace**
  - Checked out `https://github.com/lich0821/WeChatFerry.git` branch `3.9.12.56` (`9081f0b`) into `WeChatFerry/`.
  - Deprecated legacy `backup/` contents with explicit warnings.
- [ ] **1.2 Python 3.13 Syntax & Import Hygiene**
  - Fix invalid escape sequence in `WeChatFerry/clients/python/wcferry/wxmsg.py:59` (`r"..."`).
  - Verify clean import: `python -c "import wcferry"` with zero warnings or errors.
- [ ] **1.3 Preserve CowAgent Test Baseline**
  - Verify existing CowAgent unit test baseline: 959 passed, zero regressions.
  - Keep test execution isolated from live WeChat processes during automated runs.

---

### Milestone 2: WeChatFerry 3.9.12.56 Repair & Build Pipeline
> **Goal**: Fix the upstream message push defect (WCF-BUG-01) and ensure runtime DLL compatibility.

- [ ] **2.1 Implement Inbound Message Consumer Thread (`RunMsgServer`)**
  - In `WeChatFerry/WeChatFerry/spy/rpc_server.cpp`:
    - Allocate and initialize `msgSock` with `nng_pair1_open`.
    - Bind `msgSock` to `tcp://0.0.0.0:10087` via `nng_listen`.
    - Implement the worker loop waiting on `gCV.wait(lock)` when `gMsgQueue` is empty.
    - Dequeue items from `gMsgQueue`, serialize to protobuf (`WxMsg`), and dispatch via `nng_send`.
    - Integrate clean thread cancellation into `RpcStopServer`.
- [ ] **2.2 Binary Artifact Verification**
  - Verify that the active `spy.dll` loaded by `wcferry` in `.venv` possesses:
    - 32-bit PE x86 architecture.
    - Strings `MSG Server listening on` and `msgSock-nng_send`.
    - Compatibility with WeChat 3.9.12.56.
- [ ] **2.3 Injection Lifecycle Hardening**
  - Ensure `wcf.exe` checks for already-injected modules before attempting re-injection.
  - Implement defensive process cleanup in Python client to avoid leaving orphaned hooks upon exit.

---

### Milestone 3: Minimal MVP — File Transfer Assistant Verification (`filehelper`)
> **Goal**: Prove end-to-end WCF connectivity and outbound transmission safely without disturbing external chat contacts.

- [x] **3.1 Session & State Verification**
  - Verified native WeChat 3.9.12.56 running and authenticated on Windows.
  - Connected `Wcf(debug=False, block=False)` client in local mode.
  - Validated responses: `is_login() -> True`, `self_wxid -> wxid_1u2zfb3han0g22`.
- [x] **3.2 Outbound Filehelper Transmission**
  - Executed test suite via [`smoketest/wcf_smoke_test.py`](smoketest/wcf_smoke_test.py).
  - Outbound text transmission succeeded:
    ```python
    wcf.send_text("【实机测试】WCF 发信验证成功！时间: 2026-09-07 05:42:43", "filehelper")
    # Returns 0 (SUCCESS), verified received in local WeChat UI.
    ```
  - Confirmed message appeared immediately in WeChat's `文件传输助手` chat window.
- [x] **3.3 Graceful Teardown & ABI Stabilization**
  - Verified `wcf.cleanup()` gracefully closes 10086/10087 socket pairs.
  - Documented singleton injection constraint (avoid multiple short-lived client restarts against the same WeChat process).
  - Enforced `debug=False` (Release `spy.dll`) to avoid Debug CRT ABI memory crashes (WCF-BUG-05).

---

### Milestone 4: Secondary MVP — Automated Inbound Message Reply Loop
> **Goal**: Connect repaired inbound event stream (10087) through CowAgent core and dispatch automated AI replies.

- [ ] **4.1 Inbound Event Listener Verification**
  - Call `wcf.enable_receiving_msg()`.
  - Verify TCP port 10087 is in `LISTENING` state via `netstat -ano`.
  - Send a message from mobile phone to the PC WeChat account or to `filehelper`.
  - Verify `wcf.get_msg()` pulls the message off the queue with matching XML, sender wxid, and text content.
- [ ] **4.2 Wire `WcfChannel` into CowAgent**
  - Re-enable `channel/wcf/` adapter inheriting from `ChatChannel`:
    - `WcfMessage` wrapper parsing `WxMsg` attributes.
    - White-listing `filehelper` and configured test contacts.
    - Group `@mention` detection from raw XML `<atuserlist>`.
  - Register `wcf` channel in `CowAgent/channel/channel_factory.py`.
- [ ] **4.3 Full Cognitive Loop Execution**
  - Configure `config.json`:
    ```json
    {
      "channel_type": "wcf",
      "model": "glm-4-flash",
      "single_chat_prefix": [""],
      "group_name_white_list": ["ALL_GROUP"]
    }
    ```
  - Send message to `filehelper`: `"Who are you and what time is it?"`
  - Verify execution flow:
    `WeChat Msg` -> `spy.dll` -> `gMsgQueue` -> `10087` -> `WcfChannel` -> `CowAgent Engine` -> `Zhipu GLM API` -> `WcfChannel.send()` -> `10086` -> `WeChat Reply`.
  - Verify automated response arrives in `filehelper`.

---

### Milestone 5: Robustness, Media Handling & Long-Term Maintenance
> **Goal**: Expand capabilities to rich media and long-term background reliability.

- [ ] **5.1 Rich Media Support**
  - Image, voice, and file downloading via WCF attachment hooks.
  - Image decryption (XOR cipher) and Silk audio conversion.
- [ ] **5.2 Contact & Database Diagnostics**
  - Investigate `AccountStorageMgr` offset for WeChat 3.9.12.56 to restore `MicroMsg.db` handle and `get_contacts()` nickname resolution.
- [ ] **5.3 Connection Watchdog & Auto-Recovery**
  - Implement watchdog thread monitoring heartbeat on 10086.
  - If WeChat closes or crashes, pause channel gracefully, poll for process restart, and re-initialize injection automatically.
- [ ] **5.4 Web Console Status Indicator**
  - Expose live WCF connection status and bot wxid on the web console (`http://127.0.0.1:9899`).

---

## ECC Skills & Subagents Map

| Task Domain | Recommended ECC Skill / Subagent | Purpose |
|---|---|---|
| **Git Hygiene & Merging** | `git-workflow` | Safe branch tracking, isolated subdirectories, commit conventions. |
| **Documentation Governance** | `living-docs-governance` / `/update-docs` | Prevent doc rot; keep ROADMAP as the single authoritative source of truth. |
| **Regression Testing** | `ai-regression-testing` / `tdd-workflow` | Protect existing 959 tests while developing new WCF channel tests. |
| **Windows Desktop E2E** | `windows-desktop-e2e` | Windows-specific process monitoring, DLL injection verification, and port checks. |
| **Python Client Review** | `python-reviewer` | Code hygiene, type safety, Python 3.13 compatibility checks. |
| **C++ Spy Diagnostics** | `cpp-reviewer` / `cpp-build-resolver` | Review memory hooks, detour jumps, NNG socket threading, and vcpkg dependencies. |
| **Security Auditing** | `security-reviewer` | Guarantee API keys in `config.json` remain unstaged and uncommitted. |

---

## Operational Safety Rules (Production Environment Guardrails)

1. **Host is the Operator's Personal Machine**:
   - Never terminate `WeChat.exe` or kill `python.exe` processes without explicit operator permission.
   - Do not test with arbitrary third-party contacts; all initial testing MUST target **`filehelper`** (File Transfer Assistant).
2. **Spy Injection is a Singleton**:
   - Exactly **one** active `Wcf()` instance per WeChat session.
   - Never run short-lived throwaway test scripts that instantiate `Wcf()` and terminate, as `__del__` will wedge `spy.dll`.
   - If WeChat hooks crash or wedge, request the operator to perform a clean manual restart of the WeChat client.
3. **Model Selection Policy**:
   - Always use **`glm-4-flash`**.
   - Do **NOT** use `glm-4.7-flash` (recurrent HTTP 429 rate limits, empty reasoning tokens).
4. **Credential Isolation**:
   - `config.json` containing live Zhipu AI keys is strictly gitignored and must never be committed.
5. **Always Enforce Release Spy (`debug=False`)**:
   - Never use `Wcf(debug=True)` against native Release WeChat processes. MSVC Debug CRT iterator/container layouts in `spy_debug.dll` cause immediate crash in `sendMsg`. Always instantiate with `Wcf(debug=False)`.
   - Before connecting, ensure stale `.wcf.lock` files from unclean crashes are safely removed.
