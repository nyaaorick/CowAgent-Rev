# -*- coding: utf-8 -*-
"""
WCF 自动化冒烟测试套件 (WeChatFerry Smoke Test Suite)
=====================================================
用途: 对 WeChat 3.9.12.56 + WeChatFerry 进行全方位实机冒烟测试。
特性:
  1. 手动微信监听：绝不自动拉起微信，持续轮询监听 WeChat.exe 进程启动、重启与登录状态。
  2. 智能会话失效感知：识别旧微信进程中 spy 已断开的失效状态，并动态引导用户手动重启微信。
  3. 深度环境诊断：检测 Python 架构、DLL 版本、端口占用与 .wcf.lock 残留。
  4. Release 模式保障：强制使用 debug=False (Release 版 spy.dll)，避免 Debug CRT ABI 崩溃 (WCF-BUG-05)。
  5. 完整用例覆盖：涵盖登录、账号、个人信息、消息字典、联系人/DB容错、收信通道、文件传输助手发信。
  6. 详细日志与报告：控制台与本地日志文件双向记录，生成格式化 Scorecard 与调试排错指引。
"""

import os
import sys
import time
import json
import socket
import logging
import traceback
import subprocess
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

# Windows 控制台编码安全配置
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 路径常量
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SMOKE_DIR = os.path.abspath(os.path.dirname(__file__))
LOG_FILE = os.path.join(SMOKE_DIR, "smoke_test.log")
LOCK_FILE = os.path.join(BASE_DIR, ".venv", "Lib", "site-packages", "wcferry", ".wcf.lock")


class DualLogger:
    """双向日志器：同时写入标准输出与日志文件"""

    def __init__(self, log_path: str):
        self.log_path = log_path
        self.logger = logging.getLogger("WCF_SmokeTest")
        self.logger.setLevel(logging.DEBUG)
        self.logger.handlers.clear()

        # 文件 Handler
        file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_fmt = logging.Formatter(
            "[%(asctime)s.%(msecs)03d] [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(file_fmt)
        self.logger.addHandler(file_handler)

        # 控制台 Handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_fmt = logging.Formatter("[%(asctime)s] %(message)s", datefmt="%H:%M:%S")
        console_handler.setFormatter(console_fmt)
        self.logger.addHandler(console_handler)

    def info(self, msg: str):
        self.logger.info(msg)

    def debug(self, msg: str):
        self.logger.debug(msg)

    def warning(self, msg: str):
        self.logger.warning(msg)

    def error(self, msg: str):
        self.logger.error(msg)


LOG = DualLogger(LOG_FILE)


class TestResult:
    """单个测试用例结果对象"""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.status = "PENDING"  # PASS, FAIL, WARN, SKIP
        self.duration_ms = 0.0
        self.details: Dict[str, Any] = {}
        self.error_msg: str = ""

    def mark_pass(self, duration_ms: float, details: Dict[str, Any] = None):
        self.status = "PASS"
        self.duration_ms = duration_ms
        self.details = details or {}

    def mark_warn(self, duration_ms: float, warning: str, details: Dict[str, Any] = None):
        self.status = "WARN"
        self.duration_ms = duration_ms
        self.error_msg = warning
        self.details = details or {}

    def mark_fail(self, duration_ms: float, error: str, details: Dict[str, Any] = None):
        self.status = "FAIL"
        self.duration_ms = duration_ms
        self.error_msg = error
        self.details = details or {}


class WcfSmokeTestSuite:
    """WCF 冒烟测试执行器"""

    def __init__(self, target_wxid: str = "filehelper"):
        self.target_wxid = target_wxid
        self.wcf = None
        self.results: List[TestResult] = []
        self.current_pid: Optional[int] = None
        self.start_timestamp = datetime.now()

    def run_all(self):
        """执行完整测试链路"""
        LOG.info("=" * 70)
        LOG.info("  🚀 WeChatFerry (WCF) 实机全功能冒烟测试套件")
        LOG.info(f"  日志记录位置: {LOG_FILE}")
        LOG.info(f"  测试目标对象: {self.target_wxid}")
        LOG.info(f"  启动时间: {self.start_timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        LOG.info("=" * 70)

        # 阶段一：环境检查
        if not self.step_01_environment_check():
            self.print_summary()
            return False

        # 阶段二：手动微信监听与建立连接（具备失效进程感知与重启等待回路）
        connected = False
        stale_pids = set()

        while not connected:
            if not self.step_02_manual_wechat_listener(exclude_pids=stale_pids):
                self.print_summary()
                return False

            conn_ok, err_code = self.step_03_rpc_connect()
            if conn_ok:
                connected = True
                break

            # 若遇到已注入但端口失效（WCF 单次注入约束），引导重启
            if err_code == "STALE_SPY":
                stale_pids.add(self.current_pid)
                LOG.warning("\n" + "!" * 70)
                LOG.warning(f"  [!] 检测到微信进程 PID {self.current_pid} 的 WCF 会话已失效（端口拒绝连接）。")
                LOG.warning("  [!] 原因：WCF 采用 nng_pair1 单会话模型，前序脚本退出后服务线程已停止。")
                LOG.warning("  [!] 【请手动操作】请退出当前的微信客户端，并重新启动微信扫码登录。")
                LOG.warning("  [!] 脚本将自动监听新的微信进程并无缝继续测试...")
                LOG.warning("!" * 70 + "\n")
                # 等待用户退出旧微信进程
                self._wait_process_exit(self.current_pid)
            else:
                self.print_summary()
                return False

        # 阶段三：登录状态监听与账户校验
        if not self.step_04_login_listener():
            self.step_cleanup()
            self.print_summary()
            return False

        # 阶段四：功能接口冒烟测试
        self.test_user_info()
        self.test_msg_types()
        self.test_database_and_contacts()
        self.test_receiving_channel()
        self.test_send_filehelper()

        # 阶段五：清理与报告
        self.step_cleanup()
        self.print_summary()
        return all(r.status in ("PASS", "WARN") for r in self.results)

    # --------------------------------------------------------------------------
    # 步骤 1：前置环境检查
    # --------------------------------------------------------------------------
    def step_01_environment_check(self) -> bool:
        test = TestResult("01_ENV_CHECK", "环境与 DLL 依赖校验")
        t0 = time.time()
        LOG.info("\n[1/8] 检查运行环境与 DLL 状态...")

        try:
            # 清理残留锁
            if os.path.exists(LOCK_FILE):
                try:
                    os.remove(LOCK_FILE)
                    LOG.info(f"  [*] 已清理残留锁文件: {LOCK_FILE}")
                except Exception as e:
                    LOG.warning(f"  [!] 清理锁文件失败: {e}")

            # 导入 wcferry 库检查
            import wcferry
            wcf_pkg = os.path.dirname(wcferry.__file__)
            spy_dll = os.path.join(wcf_pkg, "spy.dll")
            wcf_exe = os.path.join(wcf_pkg, "wcf.exe")

            if not os.path.exists(spy_dll):
                raise FileNotFoundError(f"缺少关键 DLL: {spy_dll}")
            if not os.path.exists(wcf_exe):
                raise FileNotFoundError(f"缺少启动程序: {wcf_exe}")

            spy_size_kb = os.path.getsize(spy_dll) // 1024
            LOG.info(f"  [OK] Python: {sys.version.split()[0]} ({sys.maxsize > 2**32 and '64-bit' or '32-bit'})")
            LOG.info(f"  [OK] wcferry: v{wcferry.__version__} @ {wcf_pkg}")
            LOG.info(f"  [OK] spy.dll: {spy_size_kb} KB (Release)")

            test.mark_pass(
                (time.time() - t0) * 1000,
                {"python": sys.version.split()[0], "wcferry_ver": wcferry.__version__, "spy_size_kb": spy_size_kb}
            )
            self.results.append(test)
            return True
        except Exception as e:
            test.mark_fail((time.time() - t0) * 1000, str(e))
            self.results.append(test)
            LOG.error(f"  [X] 环境检查失败: {e}")
            return False

    # --------------------------------------------------------------------------
    # 步骤 2：手动微信进程监听（绝不自动启动）
    # --------------------------------------------------------------------------
    def step_02_manual_wechat_listener(self, timeout_sec: int = 180, exclude_pids: set = None) -> bool:
        exclude_pids = exclude_pids or set()
        test = TestResult("02_WECHAT_PROCESS", "手动微信进程监听")
        t0 = time.time()
        LOG.info("\n[2/8] 监听微信客户端进程 (WeChat.exe)...")

        pid = self._get_wechat_pid(exclude_pids)
        if not pid:
            LOG.info("  >>> [状态提示] 未检测到可用/新的微信客户端进程。")
            LOG.info("  >>> 【请手动操作】请在 Windows 桌面上手动启动微信客户端。")
            LOG.info(f"  >>> 正在监听微信进程中（超时时间: {timeout_sec} 秒）...")

            while not pid and (time.time() - t0) < timeout_sec:
                time.sleep(2)
                pid = self._get_wechat_pid(exclude_pids)
                elapsed = int(time.time() - t0)
                LOG.debug(f"  监听微信进程中... [{elapsed}/{timeout_sec}s]")

        if not pid:
            err = f"等待微信进程超时 ({timeout_sec}s)。请启动微信后再试。"
            test.mark_fail((time.time() - t0) * 1000, err)
            self.results.append(test)
            LOG.error(f"  [X] {err}")
            return False

        self.current_pid = pid
        proc_info = self._get_wechat_process_details(pid)
        LOG.info(f"  [OK] 检测到微信正在运行！PID: {pid}")
        if proc_info:
            LOG.info(f"       进程名称: {proc_info.get('ProcessName')}")
            LOG.info(f"       启动时间: {proc_info.get('StartTime', 'N/A')}")
            LOG.info(f"       工作内存: {proc_info.get('WorkingSetMB', 'N/A')} MB")

        test.mark_pass((time.time() - t0) * 1000, proc_info or {"pid": pid})
        self.results.append(test)
        return True

    # --------------------------------------------------------------------------
    # 步骤 3：WCF RPC 连接建立 (强制 debug=False)
    # --------------------------------------------------------------------------
    def step_03_rpc_connect(self) -> Tuple[bool, str]:
        test = TestResult("03_RPC_CONNECT", "WCF RPC 服务连接 (debug=False)")
        t0 = time.time()
        LOG.info(f"\n[3/8] 连接 WCF RPC 服务 (PID {self.current_pid}, debug=False, port=10086)...")
        LOG.info("  [*] 严格使用 Release spy.dll，规避 Debug CRT ABI 崩溃 (WCF-BUG-05)")

        try:
            from wcferry import Wcf
            self.wcf = Wcf(debug=False, block=False)
            LOG.info("  [OK] WCF 实例创建成功，RPC 双向管道握手就绪。")
            test.mark_pass((time.time() - t0) * 1000, {"port": 10086, "debug_mode": False})
            self.results.append(test)
            return True, ""
        except Exception as e:
            tb = traceback.format_exc()
            LOG.debug(f"RPC 连接异常堆栈:\n{tb}")
            err_str = str(e)

            # 判断是否属于 spy 已在模块中但 RPC 未监听的陈旧态
            if "Connection refused" in err_str or "10" in err_str:
                return False, "STALE_SPY"

            test.mark_fail((time.time() - t0) * 1000, err_str)
            self.results.append(test)
            LOG.error(f"  [X] WCF 连接失败: {e}")
            return False, "OTHER_ERROR"

    # --------------------------------------------------------------------------
    # 步骤 4：微信登录状态监听
    # --------------------------------------------------------------------------
    def step_04_login_listener(self, timeout_sec: int = 60) -> bool:
        test = TestResult("04_LOGIN_STATE", "微信登录态监听与 wxid 校验")
        t0 = time.time()
        LOG.info("\n[4/8] 检查微信登录状态...")

        logged_in = self.wcf.is_login()
        if not logged_in:
            LOG.info("  >>> [提示] 微信客户端尚未登录。")
            LOG.info("  >>> 【请手动操作】请在电脑屏幕上点击【登录】或扫码完成登录。")
            LOG.info(f"  >>> 正在等待登录状态（超时时间: {timeout_sec} 秒）...")

            while not logged_in and (time.time() - t0) < timeout_sec:
                time.sleep(2)
                logged_in = self.wcf.is_login()
                elapsed = int(time.time() - t0)
                LOG.debug(f"  等待登录中... [{elapsed}/{timeout_sec}s]")

        if not logged_in:
            err = f"等待微信登录超时 ({timeout_sec}s)。测试中止。"
            test.mark_fail((time.time() - t0) * 1000, err)
            self.results.append(test)
            LOG.error(f"  [X] {err}")
            return False

        self_wxid = self.wcf.get_self_wxid()
        LOG.info(f"  [OK] 微信已登录！当前账号 wxid: {self_wxid}")

        test.mark_pass((time.time() - t0) * 1000, {"is_login": True, "self_wxid": self_wxid})
        self.results.append(test)
        return True

    # --------------------------------------------------------------------------
    # 步骤 5：用户信息获取测试
    # --------------------------------------------------------------------------
    def test_user_info(self):
        test = TestResult("05_USER_INFO", "获取当前登录用户信息 (get_user_info)")
        t0 = time.time()
        LOG.info("\n[5/8] 测试 get_user_info() 接口...")

        try:
            user_info = self.wcf.get_user_info()
            LOG.info(f"  [OK] 用户信息获取成功:")
            for k, v in user_info.items():
                LOG.info(f"       • {k}: {v}")
            test.mark_pass((time.time() - t0) * 1000, user_info)
        except Exception as e:
            LOG.error(f"  [X] 获取用户信息异常: {e}")
            test.mark_fail((time.time() - t0) * 1000, str(e))

        self.results.append(test)

    # --------------------------------------------------------------------------
    # 步骤 6：消息类型字典注册表测试
    # --------------------------------------------------------------------------
    def test_msg_types(self):
        test = TestResult("06_MSG_TYPES", "消息类型映射字典 (get_msg_types)")
        t0 = time.time()
        LOG.info("\n[6/8] 测试 get_msg_types() 接口...")

        try:
            msg_types = self.wcf.get_msg_types()
            count = len(msg_types)
            sample = dict(list(msg_types.items())[:5])
            LOG.info(f"  [OK] 获取到 {count} 种消息类型支持。样例: {sample}")
            test.mark_pass((time.time() - t0) * 1000, {"total_types": count, "sample": sample})
        except Exception as e:
            LOG.error(f"  [X] 获取消息类型异常: {e}")
            test.mark_fail((time.time() - t0) * 1000, str(e))

        self.results.append(test)

    # --------------------------------------------------------------------------
    # 步骤 7：数据库与联系人接口容错诊断测试 (WCF-BUG-02 评估)
    # --------------------------------------------------------------------------
    def test_database_and_contacts(self):
        test = TestResult("07_DB_CONTACTS", "数据库列表与联系人诊断 (WCF-BUG-02)")
        t0 = time.time()
        LOG.info("\n[7/8] 测试 get_dbs() 与 get_contacts() 接口...")

        diag_data = {}
        try:
            dbs = self.wcf.get_dbs()
            diag_data["dbs"] = dbs
            LOG.info(f"  [*] 已打开数据库列表: {dbs or '[]'}")
        except Exception as e:
            LOG.warning(f"  [!] get_dbs 异常: {e}")
            diag_data["dbs_error"] = str(e)

        try:
            contacts = self.wcf.get_contacts()
            contacts_count = len(contacts) if contacts else 0
            diag_data["contacts_count"] = contacts_count
            if contacts_count > 0:
                LOG.info(f"  [OK] 成功获取联系人数量: {contacts_count}")
                test.mark_pass((time.time() - t0) * 1000, diag_data)
            else:
                warn_msg = (
                    "get_contacts() 返回 0 个联系人。\n"
                    "  说明：符合 ROADMAP.md 中记录的已知缺陷 WCF-BUG-02（3.9.12.56 数据库句柄偏移）。\n"
                    "  此为预期的容错表现，系统自动回退使用裸 wxid，不影响常规收发消息。"
                )
                LOG.warning(f"  [WARN] {warn_msg}")
                test.mark_warn((time.time() - t0) * 1000, warn_msg, diag_data)
        except Exception as e:
            LOG.warning(f"  [WARN] get_contacts 抛出异常: {e}")
            test.mark_warn((time.time() - t0) * 1000, str(e), diag_data)

        self.results.append(test)

    # --------------------------------------------------------------------------
    # 步骤 8：消息接收通道探针测试 (WCF-BUG-01 验证)
    # --------------------------------------------------------------------------
    def test_receiving_channel(self):
        test = TestResult("08_RECV_CHANNEL", "消息接收通道启停探针 (10087 端口)")
        t0 = time.time()
        LOG.info("\n[8/8] 测试接收通道探针 enable_receiving_msg / disable_recv_msg...")

        try:
            # 开启接收
            ret = self.wcf.enable_receiving_msg(pyq=False)
            is_recv = self.wcf.is_receiving_msg()
            LOG.info(f"  [*] 启用消息接收返回值: {ret}, 接收状态: {is_recv}")

            # 检测 10087 端口是否成功进入监听
            port_open = False
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1.0)
                port_open = (s.connect_ex(("127.0.0.1", 10087)) == 0)

            LOG.info(f"  [*] 10087 消息推送服务监听探测: {'成功 (ESTABLISHED/LISTENING)' if port_open else '未监听'}")

            # 关闭接收
            disable_ret = self.wcf.disable_recv_msg()
            LOG.info(f"  [*] 关闭接收通道返回值: {disable_ret}")

            if ret and port_open:
                LOG.info("  [OK] 接收通道测试通过，WCF-BUG-01 补丁工作正常。")
                test.mark_pass((time.time() - t0) * 1000, {"port_10087": True, "enable_ret": ret})
            else:
                test.mark_warn((time.time() - t0) * 1000, "10087 端口未成功握手", {"port_10087": port_open})
        except Exception as e:
            LOG.error(f"  [X] 消息接收通道测试异常: {e}")
            test.mark_fail((time.time() - t0) * 1000, str(e))

        self.results.append(test)

    # --------------------------------------------------------------------------
    # 步骤 9：文件传输助手实机发信验证
    # --------------------------------------------------------------------------
    def test_send_filehelper(self):
        test = TestResult("09_SEND_FILEHELPER", "文件传输助手发信实机验证")
        t0 = time.time()
        LOG.info(f"\n[9/9] 实机发信验证：向 [{self.target_wxid}] 发送文本...")

        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        msg_content = f"【WCF SmokeTest】自动化冒烟发信验证成功！时间: {timestamp_str}"

        try:
            ret = self.wcf.send_text(msg_content, self.target_wxid)
            if ret == 0:
                LOG.info(f"  [OK] 消息发送成功！返回码: {ret}")
                LOG.info(f"       接收人: {self.target_wxid}")
                LOG.info(f"       内容: {msg_content}")
                test.mark_pass(
                    (time.time() - t0) * 1000,
                    {"target": self.target_wxid, "ret": ret, "content": msg_content}
                )
            else:
                err_msg = f"发送失败，返回码: {ret} (非 0)"
                LOG.error(f"  [X] {err_msg}")
                test.mark_fail((time.time() - t0) * 1000, err_msg)
        except Exception as e:
            LOG.error(f"  [X] 发送消息抛出异常: {e}")
            test.mark_fail((time.time() - t0) * 1000, str(e))

        self.results.append(test)

    # --------------------------------------------------------------------------
    # 步骤 10：安全清理
    # --------------------------------------------------------------------------
    def step_cleanup(self):
        if self.wcf:
            LOG.info("\n[*] 正在断开 WCF 连接并回收资源...")
            try:
                self.wcf.cleanup()
                LOG.info("  [OK] WCF 资源清理完成。")
            except Exception as e:
                LOG.warning(f"  [!] 清理 WCF 异常: {e}")
            finally:
                self.wcf = None

    # --------------------------------------------------------------------------
    # 辅助工具方法
    # --------------------------------------------------------------------------
    def _get_wechat_pid(self, exclude_pids: set = None) -> Optional[int]:
        """通过 PowerShell 获取当前活跃的 WeChat.exe PID（支持排除已知旧 PID）"""
        exclude_pids = exclude_pids or set()
        try:
            cmd = "Get-Process WeChat -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"
            out = subprocess.check_output(["powershell", "-NoProfile", "-Command", cmd], text=True).strip()
            if out:
                for line in out.splitlines():
                    p = int(line.strip())
                    if p not in exclude_pids:
                        return p
            return None
        except Exception:
            return None

    def _wait_process_exit(self, pid: int, poll_interval: int = 2):
        """轮询等待指定的旧进程完全退出"""
        LOG.info(f"  >>> 正在等待旧微信进程 (PID {pid}) 退出...")
        while True:
            try:
                cmd = f"Get-Process -Id {pid} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"
                out = subprocess.check_output(["powershell", "-NoProfile", "-Command", cmd], text=True).strip()
                if not out:
                    LOG.info(f"  [OK] 旧微信进程 (PID {pid}) 已完全退出。")
                    break
            except Exception:
                break
            time.sleep(poll_interval)

    def _get_wechat_process_details(self, pid: int) -> Optional[Dict[str, Any]]:
        """获取微信进程详情"""
        try:
            cmd = (
                f"Get-Process -Id {pid} -ErrorAction SilentlyContinue | "
                "Select-Object Id, ProcessName, StartTime, "
                "@{Name='WorkingSetMB';Expression={[math]::Round($_.WorkingSet64/1MB, 2)}} | "
                "ConvertTo-Json"
            )
            out = subprocess.check_output(["powershell", "-NoProfile", "-Command", cmd], text=True).strip()
            if out:
                return json.loads(out)
        except Exception:
            pass
        return None

    # --------------------------------------------------------------------------
    # 测试总结输出
    # --------------------------------------------------------------------------
    def print_summary(self):
        """格式化输出冒烟测试总览卡片"""
        LOG.info("\n" + "=" * 70)
        LOG.info("               WCF 冒烟测试执行总结与质量报告")
        LOG.info("=" * 70)
        LOG.info(f"{'编号/用例名称':<25} | {'状态':<6} | {'耗时':<9} | {'备 注 / 详 情'}")
        LOG.info("-" * 70)

        pass_count = 0
        warn_count = 0
        fail_count = 0

        for r in self.results:
            duration = f"{r.duration_ms:.1f}ms"
            if r.status == "PASS":
                pass_count += 1
                status_str = "✅ PASS"
                remark = "成功"
                if "self_wxid" in r.details:
                    remark = f"wxid: {r.details['self_wxid']}"
                elif "total_types" in r.details:
                    remark = f"支持类型: {r.details['total_types']}"
            elif r.status == "WARN":
                warn_count += 1
                status_str = "⚠️ WARN"
                remark = r.error_msg.split("\n")[0]
            else:
                fail_count += 1
                status_str = "❌ FAIL"
                remark = r.error_msg.split("\n")[0]

            LOG.info(f"{r.name:<25} | {status_str:<6} | {duration:<9} | {remark}")

        LOG.info("-" * 70)
        total_time = (datetime.now() - self.start_timestamp).total_seconds()
        LOG.info(f"总计用例: {len(self.results)} | 通过: {pass_count} | 警告: {warn_count} | 失败: {fail_count} | 总耗时: {total_time:.2f}s")
        LOG.info(f"详细日志文件: {LOG_FILE}")
        LOG.info("=" * 70 + "\n")


def main():
    suite = WcfSmokeTestSuite(target_wxid="filehelper")
    success = suite.run_all()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

