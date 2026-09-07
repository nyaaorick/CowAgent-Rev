# WCF 通道交接文档

> 最后更新：2026-09-06。给下一个 session / agent 的接手说明。
> 详细技术推理见 [ROADMAP.md](ROADMAP.md) 里程碑 4.1。

> **仓库结构（2026-09-06 重整）**：应用代码在 `CowAgent/`，vendored 的 `WeChatFerry/` 和 WCF/DLL 工具 `scripts/` 留在仓库根，`.venv/` 也在根。
> 本文档里 `channel/…`、`tests/…`、`test/…` 路径都相对 `CowAgent/`；
> `scripts/…`、`.venv/…` 相对仓库根。

---

## 1. 一句话现状

**收消息已打通，端到端验证通过（2026-09-06 19:03）。**
微信 3.9.12.56 + 打过补丁的 spy.dll，消息可以进来、agent 能处理、回复能发出。

唯一已知遗留：`MicroMsg.db` 句柄获取仍失败（独立缺陷，见第 6 节），
表现为 `get_contacts()` 返回 0、发送者名字显示成裸 wxid。**不影响收发消息。**

---

## 2. 验证证据

spy 日志（`.venv/Lib/site-packages/wcferry/logs/wcf.txt`）：

```
[info] [WCF] [rpc_server.cpp::286::RunMsgServer] MSG Server listening on tcp://0.0.0.0:10087
[debug] [WCF] [rpc_server.cpp::196::dispatcher] 0x20[Functions_FUNC_SEND_TXT] length: 258
```

第一行来自补丁新增的 `RunMsgServer()`，**在本机历史上从未出现过**。
`netstat` 同时确认 10087 已 LISTENING 且客户端 ESTABLISHED（不再是 ConnectionRefused）。

`app.py` 日志：

```
[WCF] logged in as '电子鹦鹉' (wxid_1u2zfb3han0g22)
[WCF] receiving messages
[Agent] Turn 1 → memory_search → Turn 2 → Done (2 turns)
[WCF] sent text to 25984984666999465@openim
```

另外两个佐证：`event channel not listening` 警告消失了，stderr 里的
`pynng.exceptions.ConnectionRefused` traceback 也消失了——之前每次必现。

### 重新拉起的步骤

```powershell
# 1. 先开微信并登录（必须先于 app.py）
# 2. 再启动（app 在 CowAgent/，.venv 在仓库根）
cd CowAgent
..\.venv\Scripts\python app.py
```
或直接双击 `CowAgent\test\run.cmd`。

注意 **一个微信会话只能开一个 `Wcf()`**。要重启 `app.py`，
最稳妥是连微信一起重启（原因见 5.2 的 spy 卡死问题）。

---

## 3. 根因链条（为什么之前一直收不到消息）

微信 3.9.12.56 改了内存布局，WeChatFerry 作者开了分支重写，**写完发送/联系人/数据库，没写完收消息就停了**：

1. 唯一支持 3.9.12.56 的是 wcferry `39.6.0.0`，它来自作者**至今未合并的 PR #429**（分支 `3.9.12.56`，55 个 commit）。所以它没有 git tag、没有 GitHub release——这是正常的，不是可疑。
2. 该分支里 `spy/rpc_server.cpp` 的 `msgSock` **只声明和 close，从未 open / listen / send**；整个 `spy/` 目录只有一个 `nng_listen`，绑的是 10086。
3. `gMsgQueue` 被 `message_receiver.cpp` 的两个 hook 正确地推入（有 `gMutex` + `gCV.notify_all()`），但**全树没有任何地方 pop**。
4. 于是：`enable_receiving_msg()` 返回成功（hook 确实装上了），消息堆在没人读的队列里，客户端 dial 10087 必然 `ConnectionRefused`。

**结论：不是环境问题、不是配置问题、不是我们的代码问题——是上游那个分支根本没实现这个功能。**

补充：PyPI 上的 39.6.0.0 wheel 是 **2026-07-09 04:01 UTC** 传的，而该分支 CI 第一次构建成功是 **2026-07-10 15:38**（中间三次全失败，都在修 x86 vcpkg 依赖）。所以 wheel 自带的 DLL 是「CI 还没跑通时手搓出来的」，数据库那条路也是坏的。

---

## 4. 已经做了什么

- Fork：**`nyaaorick/WeChatFerry`**，默认分支已改成 `fix/msg-transport`
  （必须改默认分支，否则 `workflow_dispatch` 不注册、fork 的 Actions 是空的）
- 分支 `fix/msg-transport` = `origin/3.9.12.56`(`9081f0b`) + 2 个 commit：
  - `a4d756a` 把 master 的消息推送消费者移植过来（`rpc_server.cpp` +96 行）
  - `bce88fb` 给 `ci.yml` 加 `workflow_dispatch`
  - 补丁副本存在 [scripts/wcf-msg-transport/](scripts/wcf-msg-transport/)，含 README
- CI **构建成功**：run `34046206067`，4 分 30 秒全绿
- 产物已验证并安装（`spy.dll` 1099 KB，x86，targets 3.9.12.56）：

  | 符号 | 打补丁后 | 打补丁前 |
  |---|---|---|
  | `MSG Server listening on` | **有** | 无 |
  | `msgSock-nng_listen error` | **有** | 无 |
  | `msgSock-nng_send` | **有** | 无 |
  | `AccountStorageMgr` / `contact_manager` | 有 | 有 |

  （`Leave MSG Server` 只在 `spy_debug.dll` 里，因为是 `LOG_DEBUG`，Release 会被裁掉——39.5.2.0 也是同样的分布，属正常。）

### 相关工具

```powershell
# 查看当前装的是哪套 DLL
.venv\Scripts\python scripts\wcf_ci_dlls.py --status
# 回滚到 wheel 自带的（备份都在，后缀 .wheel-backup）
.venv\Scripts\python scripts\wcf_ci_dlls.py --restore
# 重新安装（CI 产物 2026-10-08 过期，过期后要重跑 CI 拿新 run id）
.venv\Scripts\python scripts\wcf_ci_dlls.py --repo nyaaorick/WeChatFerry --run 34046206067
```

---

## 5. 踩过的坑（重要，别重蹈覆辙）

### 5.1 我做过的错误判断（三次，都是同一类错误）

| 结论 | 依据 | 为什么错 |
|---|---|---|
| 「微信必须是 3.9.12.51」 | vendored 源码里的 `SUPPORT_VERSION` | 那是源码，跑的是 wheel 里的 spy.dll |
| 「39.6.0.0 是损坏的发布，有供应链风险」 | 没 tag、体积更小、版本号乱序 | 全是**旁证**。它是未合并 PR 的产物；体积小是因为**重写**了 DB 层；版本号就是分支 `spy.rc` 里写的 |
| 「只能降级微信到 3.9.12.51」 | 上面那个错误前提 | 12.56 是支持的，降级完全没必要 |

**教训：文件大小、版本字符串、缺少 tag、上传日期这类旁证只能提出假设，不能当证据。**
要下结论就去找**代码本身**：把两个二进制的符号表 diff 一下，再和源码树对一遍。
「没有 release/tag」通常只意味着未合并或未发布，不意味着有问题。**要看分支、PR 和 CI 历史，不能只看默认分支。**

用户两次纠正我（"why you think it can only run on 51? thats not true"、"it is supported by wcf without dout, pls double check"），两次都是用户对。

还有一次：我自己的探测早就显示 CI 构建里没有 `MSG Server` 字符串、而 39.5.2.0 的 `spy_debug.dll` 里有——**当时读过去了没当回事**。符号在二进制里缺失时，先去源码确认它是否**从来就没写过**，别默认是构建坏了。

### 5.2 环境类的坑

- **spy.dll 极易卡死**：`Wcf.cleanup()` 会跑 `wcf.exe stop`，而 **`Wcf.__del__` 也会调 `cleanup()`**——任何短命脚本退出时都会把 spy 搞坏。强杀进程则是另一种搞坏方式。症状和版本不匹配**一模一样**，曾被误判。规则：一个微信会话只开一个 `Wcf()`，不要 cleanup 后重注入；要恢复只能完整重启微信。
- **已加载的 DLL 不能被覆盖**，但 Windows 允许**改名**——`wcf_ci_dlls.py` 就是这么绕过去的（会留下 `.locked` 文件，微信重启后可删）。
- `.venv/Lib/site-packages/wcferry/` 里保留着四个 `.wheel-backup`，**不要删**（`--restore` 要用）。旧的 `.locked` 残留已在微信重启后清掉。旧日志归档为 `logs/wcf.txt.prev-*`。
- **PowerShell 5.1**：`$pid` 是只读的；`Expand-Archive` 不认 `.whl`；原生命令的 stderr 会被包成 `NativeCommandError`（`git clone` 成功也会「报错」）。Bash 工具里用 `$` 变量会被 shell 吃掉，写 PowerShell 请用 PowerShell 工具。
- **反斜杠**：heredoc 传 Python 脚本时反斜杠会被吃。用 `chr(92)` 或 raw 字符串规避。

### 5.3 权限限制（auto mode classifier）

本 session 被拦下的操作：安装 DLL 的脚本、启动微信、`gh repo fork`、`Stop-Process`、以及**用 `update-config` skill 改自己的权限**。
最后一条是**设计如此**——agent 不该能给自己放权，别试图绕过。被拦就把命令交给用户执行。

### 5.4 用户环境的硬约束

- **这台机器是用户的生产机**，微信是本人账号。**动微信 / `app.py` / web 控制台之前必须先问**。曾经在用户和 bot 聊天中途重启了 5 次微信 + 杀掉所有 python，用户很不满。
- **必须留在 WeChat 3.9.12.56**，不要再提降级。
- `config.json` 在 `CowAgent/`、已被 gitignore（`CowAgent/.gitignore:10`），里面有**真实 GLM key**。不要提交、不要放进 `test/`（`tests/test_deploy_folder.py` 有检查）。push 前跑 `/security-scan`。
- 模型用 `glm-4-flash`。**不要用 `glm-4.7-flash`**——实测 5 次里 3 次 HTTP 429（`code 1305`），而且是推理模型、`content` 为空，之前「Failed to send. Please try again.」就是它造成的。

---

## 6. 已知但未解决

- **`MicroMsg.db` 句柄获取失败**（和收消息是**两个独立问题**，这次补丁没碰）。
  表现：`get_contacts()` 返回 0，日志 `Failed to get handle for database 'MicroMsg.db'`，
  发送者名字会退化成裸 wxid。
  已定位到 `database_executor.cpp` 的 `refresh_db_map()`：读 `base + OsDb::INSTANCE (0x4327610)`。
  两次运行表现**不同**（一次 `AccountStorageMgr instance is null`，一次管理器找到了但 storage 数组遍历为空且**静默返回**），说明多半是该分支偏移/布局的问题。
  注意 `find_db_handle()` 会调 `refresh_db_map()` **两次**，所以 null 那行日志出现**两次**才代表指针为 0；出现**零次**却仍失败 = 管理器找到了、数组走空了。
  群聊 `@` 检测读的是消息 XML 不是数据库，不受影响。
- 上游 PR #429 自 2026-07-10 起没动静，指望作者修完不现实。
- 有个 fork `yuanyeichen/WeChatFerry` 分支 `research/fix-39.6-message-transport` 也实现了传输层（还带 ack/持久化），但**它自己的文档写明从未在 Windows 编译过、从未对真实微信测过**，而且改了 wire protocol。当时选了移植 master 的最小改动，理由是那份代码已经在生产里跑了很多年。

---

## 7. 提交状态

已提交在分支 **`feat/wcf-channel`**（7 个 commit，尚未合并回 master、尚未 push）：

```
f04da83a docs: record the wcf inbound investigation and add a session handoff
69ca71c8 chore(vendor): restore WeChatFerry/clients/ from a clean re-pull
8e3c4a53 fix(test): drop checks on a vendored path that never existed
13c09e39 fix(model): default to glm-4-flash instead of glm-4.7-flash
6a7fb7d6 fix(git): keep .patch files at LF
c6ace170 fix(wcf): pin wcferry to 39.6.0.0 and ship the patched spy.dll installer
7be0f44d feat(channel): add the WeChatFerry (wcf) channel
```

合并：`git checkout master && git merge feat/wcf-channel`

注意仓库里 `core.autocrlf=true`，`.gitattributes` 已加 `*.patch -text`，
否则 `scripts/wcf-msg-transport/` 里的补丁会被转成 CRLF 导致 `git am` 失败。
git 身份是**仓库级**设的（`nyaaorick <swx1226@Hotmail.com>`，与既有 commit 一致），没动全局配置。

测试基线（在 `CowAgent/` 下）：`..\.venv\Scripts\python -m pytest tests/`
→ **0 failed / 959 passed / 36 skipped / 3 deselected**（连跑 3 次稳定）。
`CowAgent/tests/test_wcf_channel.py` 12/12，`CowAgent/tests/test_deploy_folder.py` 18/18（含 key 泄露检查）。

> **不再需要 `--ignore=tests/wcf_sim`** —— 实测 `tests/wcf_sim` 10 passed / 3 deselected。
> 它用 `free_port()` 取临时空闲端口对（**不是 10086/10087**）、`Wcf(host=...)` remote 模式不加载 `sdk.dll`，
> 完全不接触真实微信；3 个 live 测试由 `pyproject.toml` 的 `addopts = "-m 'not live'"` 默认排除，不花 API 额度。

> **2026-09-06 更新**：旧基线写的是「39 failed / 905 passed / 30 skipped，剩余全是 Windows 平台既有失败」。
> 实际是 **38 个稳定失败 + `test_agent_delegation_async.py` 的 1~3 个 flaky**（数字在 39/40/41 之间跳，容易被误判成回归）。
> 全部定位并修复，过程中挖出 **6 处真实产品缺陷**（都不是测试的问题）：
>
> | # | 产品缺陷 | 位置 | 影响 |
> |---|---|---|---|
> | 1 | 记忆索引路径键分隔符不一致：`MemoryManager` 用 `Path.relative_to()`（原生 `\`）写入，`KnowledgeService` 用 `/` 删除，`WHERE path = ?` 精确匹配 | `agent/memory/storage.py`、`agent/memory/manager.py` | **Windows 上删除/移动知识文档从不清除其 chunk**，`memory_search` 持续返回已不存在文件的内容 |
> | 2 | 调度任务备份用文本模式拷贝、不带 `encoding`；`'w'` 先截断旧备份，读取再因 locale 解码失败，`except: pass` 吞掉 | `agent/tools/scheduler/task_store.py` | **任何中文任务描述都会让备份变成 0 字节**，且每次保存销毁上一份好备份，全程静默 |
> | 3 | `expand_path('~/cow')` 在 Windows 返回混用分隔符的 `C:\Users\1/cow` | `common/utils.py` | 泄进用户可见日志；与 `os.path.join` 结果的字符串比较失配 |
> | 4 | 知识图谱节点 id 用 `str()` 而非 `as_posix()`，`rel.split("/")` 随即失效 | `agent/knowledge/service.py` | **所有节点 category 退化为 `root`**，链接匹配也失败 |
> | 5 | 损坏数据库隔离：rename 被占用句柄阻止时无兜底，且日志仍宣称「moved … replaced by an empty one」 | `agent/memory/storage.py` | 数据实际未保存；运维会去找一个不存在的 `.corrupt-*` 文件 |
> | 6 | 演化备份 manifest 存原生分隔符（持久化格式），restore 做 `ws / entry["rel"]` | `agent/evolution/backup.py` | Windows 写的备份在 POSIX 上还原成一个带字面反斜杠的文件名 |
>
> 缺陷 1 附带**幂等迁移**（改写而非删除，保住已有 embedding，不必重新调用 embedding API）。
> 已确认对本机实际数据库是空操作（`chunks`/`files` 各 1 行，0 行带原生分隔符）。
>
> 其余是测试自身的可移植性问题，主要四类：
> 1. **`os.environ["HOME"]` 在 Windows 对 `expanduser` 无效**（`ntpath` 只认 `USERPROFILE`）→ 新增 `tests/support_home.py`。
> 2. **创建 symlink 需要 Developer Mode**（WinError 1314）→ 新增 `tests/support_fs.py`，探测能力后条件跳过。
> 3. **POSIX 形状的断言**（`endswith("a/b.json")`、写死的 `/a/b.png`、写死的中文文案）。
> 4. **12 个 SSRF 测试**其实不需要浏览器：它们 stub 了 service，但没 stub 后加的引擎预检。**不必跑 `cow install-browser`**。
>
> flaky 的真实原因不是超时，是 **tearDown 竞态**：后台 `agent-delegate-*` 线程还开着 `index.db`，Windows 不允许删除被打开的文件。已改为先 join 再清理。
> （新增的 6 个 skip = 5 个 symlink + 1 个 `/proc`，都是平台条件跳过，在 Linux/CI 上依旧执行。）
>
> 新增回归测试：`tests/test_memory_path_keys.py`(6)、`tests/test_scheduler_task_store_backup.py`(3)、`tests/test_evolution_backup_manifest.py`(2)。
> 都已验证「去掉修复即变红」。注意知识服务原有测试用的是 `FakeMemoryManager`，所以它和 `MemoryManager` 之间的路径键契约**此前从未被覆盖**——缺陷 1 就藏在那里。

`config.json`（在 `CowAgent/`）已确认被 `CowAgent/.gitignore:10` 忽略且未跟踪——里面有真实 GLM key，别提交。
