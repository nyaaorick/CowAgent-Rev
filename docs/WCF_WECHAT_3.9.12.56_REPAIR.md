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

---

## 5. WCF 发送机制与 CowAgent 1 核心代码复用规范 (WCF Outbound & Code Reuse Guide)

### 5.1 缺陷现象与复盘
在 CowAgent 2 的 Web 控制台测试发信中，曾出现以下故障：
- 前端点击「发送微信消息」后，输入框被清空，但微信客户端完全收不到消息（发不出去）；
- 网页对话气泡区也没有任何新增消息呈现（不显示）；
- 查阅后台日志捕获到致命异常：
  ```text
  TypeError: Wcf.send_text() got an unexpected keyword argument 'at_list'
  ```

### 5.2 为什么 CowAgent 1 完全没有这个错误？
在 **CowAgent 1** 的通道核心实现 [`CowAgent/channel/wcf/wcf_channel.py`](../CowAgent/channel/wcf/wcf_channel.py)（第 325-343 行）中，代码经过严格的实机与单元测试检验：
```python
# CowAgent 1 的权威正确实现：
if reply.type in (ReplyType.TEXT, ReplyType.TEXT_, ReplyType.INFO, ReplyType.ERROR):
    aters = ""
    if context.get("isgroup") and context.get("msg") is not None:
        aters = context["msg"].actual_user_id or ""
    
    # 1. 严格使用位置参数调用，且变量名与 wcferry 底层 protobuf 定义对齐 (aters: at-users)
    status = self.wcf.send_text(reply.content, receiver, aters)
    
    # 2. 严格对返回码 status == 0 进行真假校验，严禁掩盖错误
    if status == 0:
        logger.info(f"[WCF] sent text to {receiver}")
    else:
        logger.error(f"[WCF] send to {receiver} failed (status={status})")
```
CowAgent 1 精准遵循了 `wcferry` 的底层 RPC 规范：
- `wcferry.Wcf.send_text` 的原生签名是：
  ```python
  def send_text(self, msg: str, receiver: str, aters: Optional[str] = "") -> int:
  ```
- 第三个参数代表「@提醒的 wxid 列表」，protobuf 字段名为 `aters`（at-users 缩写），绝非 `at_list`。
- CowAgent 1 采用位置参数传递，并具有严格的 `status == 0` 判定体系。

### 5.3 CowAgent 2 是什么实现导致了这个错误？
在开发 CowAgent 2 时，未能彻底贯彻**“复用 CowAgent 1 核心沉淀”**的原则，导致了以下偏差：
1. **自作主张臆造参数名**：
   在 `cowagent2/wcf_gateway.py` 封装时，凭主观习惯编写了 `self.wcf.send_text(msg=msg, receiver=receiver, at_list=at_list)`。由于 `wcferry` 根本不存在 `at_list` 形参，Python 运行时立即抛出 `TypeError`，使发信在进入 RPC 管道前即刻崩溃，返回值被异常捕获降级为 `-2`。
2. **掩耳盗铃式的状态处理**：
   在 `cowagent2/web_server.py` 的 `handle_test_send` 中，最初没有复用 CowAgent 1 的强校验模式，而是直接返回 HTTP 200 `{"status": "success", "return_code": ret}`。前端只判断了 `status === 'success'`，误以为成功发送并清空了输入框，掩盖了底层的崩溃。
3. **测试发信脱离记忆与监听管道**：
   原有控制台发信只是单向执行发信，并未将外发消息写入会话记忆引擎（`SessionMemoryManager`），导致前端刷新历史记录时依然为空。

### 5.4 核心代码复用原则 (Architecture Alignment Directive)
为了防止类似重蹈覆辙的错误再次发生，确立以下铁律：
1. **WCF 底层通信能力 100% 对齐 CowAgent 1**：
   凡涉及 `wcferry` 接口调用（发信 `send_text`、登录检测 `is_login`、联系人读取、群成员解析等），必须以 `CowAgent/channel/wcf/wcf_channel.py` 的现成成熟实现为权威基准，**优先直接复用或严格照搬其调用形态与参数约定，严禁无依据重写**。
2. **生命周期闭环原则**：
   所有从控制台、机器人内核发出的外发消息，必须遵循：`底层发信 -> 状态强校验(status==0) -> 写入上下文记忆 -> SSE 实时广播 -> 前端即时渲染气泡` 的完整闭环。


