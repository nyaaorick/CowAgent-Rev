# WCF 实机冒烟测试套件 (Smoke Test Suite)

本目录包含对 **WeChat 3.9.12.56** 与 **WeChatFerry (WCF)** 的实机全流程冒烟测试套件。

---

## 🎯 设计原则与关键特性

1. **手动模式（非侵入）**：
   - 严禁任何脚本自动拉起、篡改或强制终止 `WeChat.exe`。
   - 脚本采用**被动状态监听器**（Process Monitor），在未检测到微信运行时持续轮询输出操作指引，提示用户手动启动微信并登录。
2. **Release 模式强制保护**：
   - 强制使用 `Wcf(debug=False)`，彻底避免 `spy_debug.dll` 因 MSVC Debug CRT 与微信 Release STL 容器 ABI 不兼容引发的崩溃（缺陷记录详见 `ROADMAP.md` 的 `WCF-BUG-05`）。
3. **环境深度诊断与容错**：
   - 运行前自检 Python 架构、`wcferry` 版本、DLL 完整性、10086/10087 端口状态，并自动清除残留的 `.wcf.lock`。
4. **已知缺陷容错评估**：
   - 对 `get_contacts()` 和 `get_dbs()` 采取安全调用模式，当返回 0 时标记为预期的已知降级（`WARN` - `WCF-BUG-02`），不阻断主链路发信。
5. **双向日志记录**：
   - 控制台输出高可读性的实时进度与结构化结果报告。
   - 文件日志输出到 `smoketest/smoke_test.log`，包含微秒级时间戳与完整调用堆栈。

---

## 📁 目录结构

- [`wcf_smoke_test.py`](wcf_smoke_test.py)：核心冒烟测试套件，包含环境自检、进程监听、登录态检查、用户信息、消息类型注册表、数据库/联系人诊断、收信信道探测、文件传输助手发信等 9 大环节。
- [`smoke_test.log`](smoke_test.log)：执行日志输出文件（自动追加生成）。

---

## 🚀 快速运行指南

在项目根目录下，直接使用项目 `.venv` 环境运行：

```powershell
# 1. (若微信未启动) 手动打开 Windows 微信客户端并登录
# 2. 执行冒烟测试
.\.venv\Scripts\python smoketest/wcf_smoke_test.py
```

---

## 📊 包含的冒烟测试用例

| 编号 | 测试用例 | 验证目标 | 预期结果 |
| :--- | :--- | :--- | :--- |
| **01** | `01_ENV_CHECK` | Python 3.13 64位环境、wcferry 39.6.0.0、`spy.dll` 存在性 | PASS |
| **02** | `02_WECHAT_PROCESS` | 监听 Windows 微信进程（`WeChat.exe`）PID 与内存 | PASS |
| **03** | `03_RPC_CONNECT` | 建立 WCF 本地 RPC 连接（端口 10086，Release 模式） | PASS |
| **04** | `04_LOGIN_STATE` | 轮询监听并确认微信登录状态，获取当前账号 wxid | PASS |
| **05** | `05_USER_INFO` | 调用 `get_user_info()` 获取昵称、账号、数据目录等 | PASS |
| **06** | `06_MSG_TYPES` | 调用 `get_msg_types()` 获取受支持的消息类型映射字典 | PASS |
| **07** | `07_DB_CONTACTS` | 诊断数据库与联系人接口状态（容错评估 `WCF-BUG-02`） | PASS / WARN |
| **08** | `08_RECV_CHANNEL` | 测试 `enable_receiving_msg()` 与 10087 端口监听 | PASS |
| **09** | `09_SEND_FILEHELPER` | 实机向文件传输助手 (`filehelper`) 发送带时间戳文本 | PASS (返回码 0) |

---

## 🛠️ 故障排查与调试提示

1. **若报错 `spy 已注入，请勿重复 start` 或 `Connection refused`**：
   - 原因：前序 Python 进程异常退出导致 `spy.dll` 处于卸载中途或端口未重新就绪。
   - 解决：完全退出微信客户端，重新启动微信并扫码登录后再运行。
2. **若报错 `错误模块: spy_debug.dll`**：
   - 原因：误使用了 `debug=True` 注入了 Debug 版 DLL。
   - 解决：确认调用中保持 `debug=False`。
3. **若联系人返回数量为 0**：
   - 这是微信 3.9.12.56 上游的已知数据库偏移缺陷（`WCF-BUG-02`），系统会自动降级为裸 wxid 模式，正常收发消息不受影响。

