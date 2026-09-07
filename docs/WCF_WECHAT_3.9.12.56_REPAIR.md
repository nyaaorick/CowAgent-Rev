# WeChat 3.9.12.56 WCF 底层修复与适配文档 (WCF MicroMsg.db Repair Guide)

## 1. 背景与缺陷分析

在针对 **WeChat 3.9.12.56 (x86)** 使用 WeChatFerry (WCF) 39.6.0.0 时，遇到了以下阻断性缺陷：
- 调用 `wcf.get_contacts()` 永远返回 `[]`（0 个联系人）；
- 执行 `wcf.query_sql("MicroMsg.db", ...)` 报错 `Timed out`；
- 日志中频繁出现：`Failed to get handle for database 'MicroMsg.db'`。

### 根本原因 (Root Cause)
在微信历史版本中，微信内部 `AccountStorageMgr` 保存各数据库句柄（`sqlite3*`）的数组偏移量为 `storage + 0x34`。
而在 **WeChat 3.9.12.56** 中，腾讯底层结构发生变动，该句柄被移至 **`storage + 0x38`**。

由于官方未针对 3.9.12.56 修正该偏移量，`spy.dll` 内部寻址读到的指针为 NULL (`0x00`)，导致 WCF 无法打开微信核心通讯录库 `MicroMsg.db`。

---

## 2. 修复方案与二进制补丁细节

### 补丁位置与汇编对比
- **目标文件**: `.venv/Lib/site-packages/wcferry/spy.dll`
- **原版备份**: `.venv/Lib/site-packages/wcferry/spy.dll.bak`
- **文件偏移量 (File Offset)**: `0x20dd4`
- **内存虚拟地址 (RVA)**: `0x219d4`
- **指令修改**:
  ```text
  修改前: 8D 42 34   lea eax, [edx + 34h]   ; 寻址 storage + 0x34 (旧版微信)
  修改后: 8D 42 38   lea eax, [edx + 38h]   ; 寻址 storage + 0x38 (3.9.12.56)
  ```

### 安全性与范围
- **只修改 Python 虚拟环境内 WCF 注入器**中的 1 个字节；
- **完全不修改任何官方微信程序**（`WeChat.exe`、系统 DLL 等完全零改动）；
- 完全可逆，恢复备份文件即可即时还原。

---

## 3. CowAgent 1 与 CowAgent 2 的共享调用说明

### 3.1 CowAgent 1 (CowAgent-Rev) 能否调用？
**完全可以，且已自动生效！**
- `CowAgent` (CowAgent 1) 与 `cowagent2` (CowAgent 2) 共同使用项目根目录的虚拟环境 `.venv/`。
- CowAgent 1 的 `channel/wcf/wcf_channel.py` 中 `self.wcf.get_contacts()` 原先因该 Bug 只能返回空列表，退化为仅用 raw wxid；
- 现由于底层 `spy.dll` 已修复，**CowAgent 1 启动时也将直接自动获得全量 6,000+ 联系人、真实昵称与微信号**，其 `wcf_contact_white_list` 也能正常匹配好友真实备注名。

### 3.2 两者能否同时运行？
**注意：建议交替运行（对比测试效果）**。
- WCF 在微信进程内绑定 TCP 端口：
  - `10086`: 指令通道 (Command RPC)
  - `10087`: 事件推送通道 (Inbound Event Socket)
- NNG 协议的 `PAIR` 事件 Socket (`10087`) 属于**点对点单客户端独占连接**。
- 如果 CowAgent 1 和 CowAgent 2 两个独立进程同时启动并尝试各自监听 `10087`，后启动的进程将遭遇端口冲突或连接拒绝。
- **推荐工作模式**：
  - 评测 CowAgent 2 时：启动 `python -m cowagent2.app`；
  - 评测 CowAgent 1 时：停止 CowAgent 2，启动 `python app.py`；
  - 两个版本共享已打好补丁的 `spy.dll`，均具备完全一致的底层能力。

---

## 4. 还原/回滚步骤 (Rollback)

如需随时撤销补丁恢复官方默认状态，在根目录下执行：
```powershell
Copy-Item .venv\Lib\site-packages\wcferry\spy.dll.bak .venv\Lib\site-packages\wcferry\spy.dll -Force
```
恢复后，WCF 将回到原版状态（对 3.9.12.56 返回 0 个联系人）。

