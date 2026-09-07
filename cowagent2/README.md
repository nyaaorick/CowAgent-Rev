# CowAgent 2 — 极简微信智能体系统 (WCF 3.9.12.56)

CowAgent 2 是专为 **Windows 原生微信 3.9.12.56 + WeChatFerry (WCF)** 打造的极简、高可靠、记忆完全隔离的下一代微信智能体。

---

## ✨ 核心特性

1. **零配置复用 (Zero-Config Reuse)**:
   - 自动读取并复用 `CowAgent/config.json` 中的智谱 AI GLM-4-flash 密钥与基础模型配置，无需二次输入。
2. **默认拒绝白名单模式 (Default-Deny Whitelist)**:
   - 仅在白名单中勾选启用的联系人 (`allowed_wxids`) 或群聊 (`allowed_rooms`) 才能触发机器人回复，杜绝误扰与未经授权对话。
3. **严格会话记忆隔离 (Strict Session Memory Isolation)**:
   - 每一个 `wxid` (私聊) 和每一个 `roomid` (群聊) 拥有完全物理隔离的记忆上下文和独立的滑动窗口修剪；
   - 杜绝跨联系人/跨群聊的内容串扰；
   - 支持单个会话独立清理记忆 (`#清除记忆` / `#reset`)。
4. **全拟人化人类模拟 (Full Human Simulation)**:
   - **自然人设**: 注入日常微信交流语气，真诚自然、口语化，杜绝机械化 AI 套话 (例如“我是人工智能助手”、“很高兴为您服务”)；
   - **真实打字与阅读延时**: 根据接收文本长度动态模拟人类阅读时间 (`0.6s - 2.5s`)，根据生成回复长度动态模拟人类打字速度与思考停顿 (`1.0s - 5.0s`)，避免毫秒级机器秒回，同时规避微信风控。
5. **Localhost Web 控制台与实时会话监听 (Reusing CowAgent Console)**:
   - 访问 `http://127.0.0.1:9900` 打开管理界面；
   - 实时监控微信运行状态与 WCF 连接健康度；
   - 动态扫描发现的微信好友与群聊，一键勾选/取消白名单与自动回复；
   - **Phase 2 实时监听**: 基于 SSE (Server-Sent Events) 实时监听对话流，在网页端以微信气泡样式静默观察对话，安全只读不干扰。
6. **底层修复与全量联系人三元绑定 (Full Contact Resolution)**:
   - 彻底修复 WeChat 3.9.12.56 数据库句柄偏移问题 (`storage + 0x38`)，永久解锁 `MicroMsg.db`；
   - 毫秒级提取并绑定 `wxid`（系统唯一标识）+ `微信号`（Alias）+ `显示名称/备注名`（Remark/NickName）；
   - 详见底层技术修复文档 [`docs/WCF_WECHAT_3.9.12.56_REPAIR.md`](../docs/WCF_WECHAT_3.9.12.56_REPAIR.md) 与专有路线图 [`cowagent2/ROADMAP.md`](ROADMAP.md)。
7. **防 Wedge 单例通信守卫**:
   - 强制使用 Release 版 `spy.dll` (`debug=False`)，彻底杜绝 MSVC Debug CRT 导致的崩溃 (`WCF-BUG-05`)；
   - 单进程守护连接，避免短命脚本频繁断连造成的 RPC 锁死 (`WCF-BUG-03`)。

---

## 📁 目录结构

```text
cowagent2/
├── app.py                     # 统一启动入口与生命周期管理
├── config.py                  # 配置管理器（复用 CowAgent/config.json，管理 whitelist.json）
├── wcf_gateway.py             # WCF 单例通信网关 (debug=False, 事件消费者)
├── scanner.py                 # 联系人与群聊动态扫描/绑定器
├── memory.py                  # 严格隔离的会话记忆引擎 (SessionMemoryManager)
├── human_simulator.py         # 人类打字延时、阅读耗时与拟人提示词引擎
├── bot.py                     # 极简 GLM-4-flash 智能调度与鉴权回路
├── web_server.py              # Localhost Web 控制台后端 (aiohttp, REST + SSE)
├── static/                    # 控制台前端界面 (纯原生响应式 HTML+CSS+JS)
│   └── index.html
├── data/                      # 运行时持久化数据 (gitignored)
│   ├── whitelist.json         # 白名单配置
│   └── contacts_cache.json    # 联系人绑定缓存
├── tests/                     # 自动化测试套件
│   ├── test_human_simulator.py
│   ├── test_memory_isolation.py
│   └── test_web_server.py
└── README.md                  # 本说明文档
```

---

## 🚀 快速启动

1. **手动打开并登录微信客户端** (微信版本 3.9.12.56)。
2. 启动 CowAgent 2：
   ```powershell
   .venv\Scripts\python.exe -m cowagent2.app
   ```
3. 在浏览器打开控制台：
   ```
   http://127.0.0.1:9900
   ```
4. 在控制台中勾选需要交互的好友或群聊（默认已允许 `filehelper` 文件传输助手）。
5. 在微信中向 `文件传输助手` 发送消息即可获得拟人化回复！

---

## 🧪 自动化测试

运行全部单元测试：
```powershell
.venv\Scripts\python.exe -m unittest discover cowagent2/tests
```

