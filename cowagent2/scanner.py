# -*- coding: utf-8 -*-
"""
CowAgent 2 联系人与群聊扫描绑定器 (ContactScanner)
===================================================
特性:
  1. 多源发现：通过种子库、WCF 接口、本地已打开数据库以及实时消息流动态搜集可用会话；
  2. 智能绑定：将微信好友昵称/备注名、群聊名称与真实的 wxid / roomid 进行关联绑定；
  3. 持久化缓存：自动保存到 cowagent2/data/contacts_cache.json；
  4. 白名单状态同步：自动与 whitelist.json 状态合并供 Web 控制台展示和切换。
"""

import os
import json
import time
import re
import logging
from typing import Dict, List, Any, Optional
from cowagent2.config import cfg, CONTACTS_CACHE_PATH

logger = logging.getLogger("CowAgent2.Scanner")


class ContactScanner:
    def __init__(self, wcf_client: Optional[Any] = None):
        self.wcf_client = wcf_client
        # target_id -> dict
        self.catalog: Dict[str, Dict[str, Any]] = {}
        self._init_defaults()
        self.load_cache()

    def _init_defaults(self):
        """初始化内置已知联系人"""
        self.register_or_update(
            target_id="filehelper",
            name="文件传输助手",
            remark="微信官方文件传输助手",
            is_group=False,
            source="system"
        )

    def load_cache(self):
        """从 contacts_cache.json 加载已发现的会话清单"""
        if os.path.exists(CONTACTS_CACHE_PATH):
            try:
                with open(CONTACTS_CACHE_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for item in data:
                    self.catalog[item["id"]] = item
                logger.info(f"已从缓存加载 {len(self.catalog)} 个联系人/群聊")
            except Exception as e:
                logger.warning(f"加载联系人缓存失败: {e}")

    def save_cache(self):
        """保存联系人缓存到磁盘"""
        try:
            items = list(self.catalog.values())
            with open(CONTACTS_CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(items, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存联系人缓存失败: {e}")

    def register_or_update(
        self,
        target_id: str,
        name: str = "",
        remark: str = "",
        is_group: bool = False,
        source: str = "runtime",
        alias: str = ""
    ) -> Dict[str, Any]:
        """登记或更新联系人/群聊信息"""
        if not target_id:
            return {}

        now = time.time()
        is_chatroom = is_group or target_id.endswith("@chatroom")

        if target_id not in self.catalog:
            display_name = remark or name or ("群聊" if is_chatroom else "联系人") + f"_{target_id[:6]}"
            self.catalog[target_id] = {
                "id": target_id,
                "name": name or display_name,
                "remark": remark,
                "alias": alias,
                "type": "chatroom" if is_chatroom else "contact",
                "source": source,
                "first_seen": now,
                "last_seen": now
            }
            logger.info(f"扫描发现新会话 [{self.catalog[target_id]['type']}]: {display_name} ({target_id})")
        else:
            item = self.catalog[target_id]
            is_placeholder = not item.get("name") or item.get("name").startswith("联系人_") or item.get("name").startswith("群聊_")
            if name and (is_placeholder or source == "manual"):
                item["name"] = name
            if remark:
                item["remark"] = remark
            if alias:
                item["alias"] = alias
            item["last_seen"] = now

        self.save_cache()
        return self.catalog[target_id]

    def scan_from_wcf(self, wcf) -> int:
        """从运行中的 WCF 实例全面扫描可用联系人与群聊"""
        count_before = len(self.catalog)
        try:
            # 1. 扫描自身账号
            self_wxid = wcf.get_self_wxid()
            if self_wxid:
                user_info = wcf.get_user_info() or {}
                self.register_or_update(
                    target_id=self_wxid,
                    name=user_info.get("name", "我"),
                    remark="本机当前登录账号",
                    is_group=False,
                    source="self"
                )

            # 2. 尝试从 WCF 原生 get_contacts 获取
            contacts = wcf.get_contacts() or []
            for c in contacts:
                wxid = c.get("wxid")
                if wxid:
                    self.register_or_update(
                        target_id=wxid,
                        name=c.get("name", ""),
                        remark=c.get("remark", ""),
                        is_group=wxid.endswith("@chatroom"),
                        source="wcf_api"
                    )

            # 3. 尝试从已打开数据库中的活跃 Talker 提取
            dbs = wcf.get_dbs() or []
            if "MSG0.db" in dbs:
                # 方案 3.1: 从 MSG 消息记录表直接提取最近对话的所有联系人与群聊 (包括自己发消息的好友)
                try:
                    rows = wcf.query_sql("MSG0.db", "SELECT DISTINCT StrTalker FROM MSG ORDER BY CreateTime DESC LIMIT 200;") or []
                    for r in rows:
                        talker = r.get("StrTalker")
                        if talker and len(talker) > 3 and talker != "filehelper":
                            self.register_or_update(
                                target_id=talker,
                                name="",
                                is_group=talker.endswith("@chatroom"),
                                source="db_history"
                            )
                except Exception as e:
                    logger.debug(f"从 MSG 表查询 Talker 失败: {e}")

                # 方案 3.2: 从 Name2ID 映射表拉取所有活跃 Talker
                try:
                    rows = wcf.query_sql("MSG0.db", "SELECT DISTINCT UsrName FROM Name2ID LIMIT 200;") or []
                    for r in rows:
                        talker = r.get("UsrName")
                        if talker and len(talker) > 3 and talker != "filehelper":
                            self.register_or_update(
                                target_id=talker,
                                name="",
                                is_group=talker.endswith("@chatroom"),
                                source="db_name2id"
                            )
                except Exception as e:
                    logger.debug(f"从 Name2ID 查询 UsrName 失败: {e}")

        except Exception as e:
            logger.warning(f"扫描 WCF 联系人过程异常: {e}")

        added = len(self.catalog) - count_before
        logger.info(f"扫描完成，新增发现 {added} 个会话，当前目录总计 {len(self.catalog)} 个")
        return len(self.catalog)

    def _get_latest_talker_from_db(self) -> str:
        """从 MSG0.db 查询本机最近发出的私聊消息的目标 wxid"""
        if not self.wcf_client:
            return ""
        try:
            sql = "SELECT StrTalker FROM MSG WHERE IsSender = 1 ORDER BY CreateTime DESC LIMIT 1;"
            rows = self.wcf_client.query_sql("MSG0.db", sql)
            if rows and len(rows) > 0:
                talker = rows[0].get("StrTalker", "")
                if talker and not talker.endswith("@chatroom") and talker != "filehelper":
                    return talker
        except Exception as e:
            logger.debug(f"从 MSG0.db 提取最近发出的私聊联系人失败: {e}")
        return ""

    def update_from_message(self, msg) -> Dict[str, Any]:
        """从实时接收到的微信消息动态抽取会话名并注册（涵盖收消息与自己发消息）"""
        is_group = bool(getattr(msg, "from_group", lambda: False)())
        is_self = bool(getattr(msg, "from_self", lambda: False)())

        if is_group:
            target_id = getattr(msg, "roomid", "")
        elif is_self:
            # 关键：自己发出的私聊消息，底层 sender 是自己，真正的好友 wxid 在 MSG0.db 最新记录中
            target_id = self._get_latest_talker_from_db() or getattr(msg, "sender", "")
        else:
            target_id = getattr(msg, "sender", "")

        if not target_id or target_id == "filehelper":
            return {}

        name_candidate = ""
        # 尝试从 xml 中粗提取群名/昵称
        xml_str = getattr(msg, "xml", "")
        if xml_str:
            m = re.search(r"<displayname><!\[CDATA\[(.*?)\]\]></displayname>", xml_str)
            if m:
                name_candidate = m.group(1)

        return self.register_or_update(
            target_id=target_id,
            name=name_candidate,
            is_group=is_group,
            source="message_stream"
        )

    def get_contact(self, target_id: str) -> Optional[Dict[str, Any]]:
        """获取指定 ID 的联系人或群聊信息"""
        return self.catalog.get(target_id)

    def scan(self) -> List[Dict[str, Any]]:
        """执行主动扫描"""
        if self.wcf_client:
            self.scan_from_wcf(self.wcf_client)
        return list(self.catalog.values())

    def on_wcf_message(self, msg) -> None:
        """接收 WCF 消息并动态提取联系人"""
        try:
            self.update_from_message(msg)
        except Exception as e:
            logger.debug(f"on_wcf_message scan error: {e}")

    def add_talker(self, target_id: str, is_group: bool = False) -> Dict[str, Any]:
        """动态添加活跃对话方"""
        return self.register_or_update(target_id=target_id, is_group=is_group, source="talker")

    def get_all_with_whitelist_status(self, config_obj = None) -> List[Dict[str, Any]]:
        """获取所有已扫描到的会话列表，附带实时白名单勾选状态（供 Web UI 渲染）"""
        c = config_obj or cfg
        results = []
        for target_id, item in self.catalog.items():
            is_group = item["type"] == "chatroom"
            is_whitelisted = c.is_allowed(target_id, target_id if is_group else "")
            auto_reply = c.get_session_auto_reply(target_id)
            results.append({
                "wxid": target_id,
                "name": item.get("name") or target_id,
                "nickname": item.get("remark") or item.get("name") or target_id,
                "remark": item.get("remark", ""),
                "alias": item.get("alias", ""),
                "is_group": is_group,
                "is_whitelisted": is_whitelisted,
                "auto_reply": auto_reply,
                "last_seen": item.get("last_seen", 0)
            })

        # 排序：优先白名单，其次按最后活跃时间倒序
        results.sort(key=lambda x: (not x["is_whitelisted"], -x["last_seen"]))
        return results

    def get_contacts_with_whitelist(self, config_obj = None) -> List[Dict[str, Any]]:
        """别名方法，供 Web 控制台调用"""
        return self.get_all_with_whitelist_status(config_obj)


scanner = ContactScanner()
