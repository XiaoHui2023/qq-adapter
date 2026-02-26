"""
QQ 开放平台 WebSocket 客户端

负责:
    - 鉴权: 获取并自动刷新 access_token
    - 网关: 通过 WebSocket 连接 QQ 开放平台
    - 心跳: 按服务端要求的间隔发送心跳包
    - 收发: 接收频道/群/私聊消息，通过回调处理后自动回复
    - 去重: 同一条消息仅处理一次，防止重复回复

WebSocket 协议流程:
    首次连接: Hello(op=10) → Identify(op=2) → Ready(op=0) → 心跳 + 事件循环
    断线重连: Hello(op=10) → Resume(op=6) → 恢复会话 / Invalid Session → 全新连接
"""

import asyncio
import json
import logging
import sys
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Callable, Awaitable, Optional

import aiohttp

from qq_adapter_protocol import MessageRequest, MessageResponse, MessageSource

logger = logging.getLogger("qq-adapter")

# 默认订阅的事件意图:
#   bit 0  — GUILDS (频道事件)
#   bit 1  — GUILD_MEMBERS (频道成员事件)
#   bit 25 — GROUP_AND_C2C_EVENT (群聊和私聊事件)
#   bit 30 — PUBLIC_GUILD_MESSAGES (公域频道消息)
DEFAULT_INTENTS = (1 << 0) | (1 << 1) | (1 << 25) | (1 << 30)

# 消息去重缓存容量，超出后按 FIFO 淘汰
MSG_DEDUP_CACHE_SIZE = 1000

# 消息回调签名: 接收 MessageRequest，返回 MessageResponse
MessageCallback = Callable[[MessageRequest], Awaitable[MessageResponse]]


async def _default_callback(request: MessageRequest) -> MessageResponse:
    """默认回调：原样回显消息内容"""
    return MessageResponse(content=request.content)


class QQBot:
    """QQ 开放平台 Bot 客户端"""

    API_BASE = "https://api.sgroup.qq.com"
    AUTH_URL = "https://bots.qq.com/app/getAppAccessToken"

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        *,
        intents: int = DEFAULT_INTENTS,
        on_message: Optional[MessageCallback] = None,
        proxy: Optional[str] = None,
    ):
        """
        Args:
            app_id:     QQ 开放平台 AppID
            app_secret: QQ 开放平台 AppSecret
            intents:    事件订阅意图位掩码
            on_message: 消息回调函数，不传则使用默认回显
            proxy:      出站 HTTP 代理地址（用于 IP 白名单场景）
        """
        self.app_id = app_id
        self.app_secret = app_secret
        self.intents = intents
        self.on_message: MessageCallback = on_message or _default_callback
        self.proxy = proxy

        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._hb_task: Optional[asyncio.Task] = None
        self._tasks: set[asyncio.Task] = set()
        self._running = False
        self._seq: Optional[int] = None
        self._session_id: Optional[str] = None
        self._msg_seq: dict[str, int] = {}
        self._replied_msgs: OrderedDict[str, None] = OrderedDict()

    # -------- access token --------

    async def _get_access_token(self) -> str:
        """获取 access_token，过期前自动刷新"""
        now = datetime.now(timezone.utc)
        if (
            self._access_token
            and self._token_expires_at
            and now < self._token_expires_at
        ):
            return self._access_token

        async with self._http.post(self.AUTH_URL, json={
            "appId": self.app_id,
            "clientSecret": self.app_secret,
        }, proxy=self.proxy) as resp:
            data = await resp.json()

        if "access_token" not in data:
            raise RuntimeError(f"鉴权失败: {data}")

        self._access_token = data["access_token"]
        # 提前 30 秒过期，留出刷新余量
        self._token_expires_at = now + timedelta(
            seconds=int(data["expires_in"]) - 30
        )
        logger.info("获取 access_token 成功, 有效期至 %s", self._token_expires_at)
        return self._access_token

    async def _auth_headers(self) -> dict[str, str]:
        """构建 QQ API 鉴权请求头"""
        token = await self._get_access_token()
        return {
            "Authorization": f"QQBot {token}",
            "X-Union-Appid": self.app_id,
        }

    # -------- HTTP 客户端 --------

    @property
    def _http(self) -> aiohttp.ClientSession:
        """获取 HTTP 会话，未启动时抛出异常"""
        if self._session is None or self._session.closed:
            raise RuntimeError("QQBot 尚未启动, 请先调用 run()")
        return self._session

    async def api_get(self, path: str) -> dict:
        """调用 QQ 开放平台 GET 接口"""
        headers = await self._auth_headers()
        async with self._http.get(
            f"{self.API_BASE}{path}", headers=headers, proxy=self.proxy
        ) as resp:
            return await resp.json()

    async def api_post(self, path: str, body: dict) -> dict:
        """调用 QQ 开放平台 POST 接口"""
        headers = await self._auth_headers()
        async with self._http.post(
            f"{self.API_BASE}{path}", headers=headers, json=body, proxy=self.proxy
        ) as resp:
            text = await resp.text()
            logger.debug("POST %s → %s %s", path, resp.status, text[:200])
            return json.loads(text) if text else {}

    # -------- 发送消息 --------

    async def reply_guild(self, channel_id: str, msg_id: str, content: str):
        """回复频道消息"""
        await self.api_post(f"/channels/{channel_id}/messages", {
            "content": content,
            "msg_id": msg_id,
        })

    async def reply_group(self, group_openid: str, msg_id: str,
                          content: str, msg_seq: int = 1):
        """回复群消息"""
        await self.api_post(f"/v2/groups/{group_openid}/messages", {
            "msg_type": 0,
            "content": content,
            "msg_id": msg_id,
            "msg_seq": msg_seq,
            "timestamp": int(time.time()),
        })

    async def reply_c2c(self, openid: str, msg_id: str,
                        content: str, msg_seq: int = 1):
        """回复私聊消息"""
        await self.api_post(f"/v2/users/{openid}/messages", {
            "msg_type": 0,
            "content": content,
            "msg_id": msg_id,
            "msg_seq": msg_seq,
            "timestamp": int(time.time()),
        })

    def next_seq(self, key: str) -> int:
        """生成递增的消息序列号（群/私聊发送需要）"""
        self._msg_seq[key] = self._msg_seq.get(key, 0) + 1
        return self._msg_seq[key]

    async def send_message(self, source: MessageSource, source_id: str,
                           content: str, msg_id: str = ""):
        """统一发送接口，根据消息来源类型自动路由"""
        if source == MessageSource.GUILD:
            await self.reply_guild(source_id, msg_id, content)
        elif source == MessageSource.GROUP:
            seq = self.next_seq(source_id)
            await self.reply_group(source_id, msg_id, content, seq)
        else:
            seq = self.next_seq(source_id)
            await self.reply_c2c(source_id, msg_id, content, seq)

    # -------- 事件分发 --------

    # QQ 事件类型 → 消息来源枚举的映射
    _EVENT_SOURCE_MAP: dict[str, MessageSource] = {
        "AT_MESSAGE_CREATE": MessageSource.GUILD,
        "GROUP_AT_MESSAGE_CREATE": MessageSource.GROUP,
        "C2C_MESSAGE_CREATE": MessageSource.C2C,
    }

    def _build_request(self, event_type: str, data: dict) -> Optional[MessageRequest]:
        """将 QQ 原始事件数据解析为 MessageRequest，非消息事件返回 None"""
        source = self._EVENT_SOURCE_MAP.get(event_type)
        if source is None:
            return None

        content = data.get("content", "").strip()
        msg_id = data.get("id", "")

        if source == MessageSource.GUILD:
            source_id = data.get("channel_id", "")
            sender_id = data.get("author", {}).get("id", "")
        elif source == MessageSource.GROUP:
            source_id = data.get("group_openid", "")
            sender_id = data.get("author", {}).get("member_openid", "")
        else:
            source_id = data.get("author", {}).get("user_openid", "")
            sender_id = source_id

        return MessageRequest(
            source=source,
            content=content,
            msg_id=msg_id,
            event_type=event_type,
            source_id=source_id,
            sender_id=sender_id,
            raw=data,
        )

    def _mark_replied(self, msg_id: str) -> bool:
        """标记消息已处理。返回 True 表示首次处理，False 表示重复消息"""
        if msg_id in self._replied_msgs:
            return False
        self._replied_msgs[msg_id] = None
        while len(self._replied_msgs) > MSG_DEDUP_CACHE_SIZE:
            self._replied_msgs.popitem(last=False)
        return True

    def _spawn_task(self, coro) -> asyncio.Task:
        """创建后台任务并自动管理生命周期"""
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _dispatch_message(self, event_type: str, data: dict):
        """事件分发：解析消息 → 去重 → 异步处理"""
        request = self._build_request(event_type, data)
        if request is None:
            logger.debug("非消息事件 %s, 跳过回调", event_type)
            return

        if not self._mark_replied(request.msg_id):
            logger.debug("消息 %s 已处理过, 跳过", request.msg_id)
            return

        logger.info("收到消息 [%s] %s: %s", request.source.value,
                     request.sender_id, request.content[:100])

        # 在后台任务中处理，不阻塞 WebSocket 事件循环
        self._spawn_task(self._handle_and_reply(request))

    async def _handle_and_reply(self, request: MessageRequest):
        """调用回调处理消息并发送回复"""
        try:
            response = await self.on_message(request)
        except Exception:
            logger.exception("处理消息 %s 时出错", request.msg_id)
            return

        if response.content is None:
            return

        try:
            await self.send_message(request.source, request.source_id,
                                    response.content, request.msg_id)
        except Exception:
            logger.exception("回复消息 %s 时出错", request.msg_id)

    # -------- 心跳 --------

    async def _heartbeat_loop(self, ws: aiohttp.ClientWebSocketResponse,
                              interval: float):
        """按固定间隔发送心跳包，维持 WebSocket 连接"""
        while True:
            await asyncio.sleep(interval)
            await ws.send_json({"op": 1, "d": self._seq})
            logger.debug("心跳 seq=%s", self._seq)

    # -------- 主循环 --------

    async def run(self):
        """启动 Bot：建立 HTTP 会话 → 连接/重连 WebSocket → 进入事件循环"""
        self._running = True
        self._session = aiohttp.ClientSession()
        try:
            while self._running:
                reason = await self._try_connect()
                if not self._running or reason == "stopped":
                    break
                if reason == "invalid_session":
                    self._session_id = None
                    self._seq = None
                wait = 5
                logger.info("将在 %d 秒后重连...", wait)
                await asyncio.sleep(wait)
        finally:
            await self._cleanup()

    async def _try_connect(self) -> str:
        """尝试连接: 优先 Resume 恢复会话, 失败则全新 Identify。返回退出原因"""
        if self._session_id and self._seq is not None:
            try:
                reason = await self._resume()
                if reason != "invalid_session":
                    return reason
                logger.info("Resume 被拒绝, 将全新连接")
            except Exception:
                logger.exception("Resume 失败, 将全新连接")
            self._session_id = None
            self._seq = None
        try:
            return await self._connect()
        except Exception:
            logger.exception("连接异常")
            return "error"

    async def _connect(self) -> str:
        """完整的 WebSocket 连接流程：鉴权 → 获取网关 → Hello → Identify → Ready → 事件循环"""
        token = await self._get_access_token()

        gw = await self.api_get("/gateway/bot")
        if "url" not in gw:
            raise RuntimeError(f"获取网关失败, 请检查 APP_ID/APP_SECRET: {gw}")
        ws_url = gw["url"]
        logger.info("网关地址: %s", ws_url)

        self._ws = await self._http.ws_connect(ws_url, proxy=self.proxy)
        try:
            # 1. 接收 Hello，获取心跳间隔
            hello = await self._ws.receive_json()
            if hello.get("op") != 10:
                raise RuntimeError(f"期望 Hello(op=10), 收到 {hello}")
            heartbeat_interval = hello["d"]["heartbeat_interval"] / 1000
            logger.info("心跳间隔: %.1fs", heartbeat_interval)

            # 2. 发送 Identify 进行鉴权
            await self._ws.send_json({
                "op": 2,
                "d": {
                    "token": f"QQBot {token}",
                    "intents": self.intents,
                    "shard": [0, 1],
                    "properties": {
                        "$os": sys.platform,
                        "$language": f"python {sys.version}",
                        "$sdk": "qq-adapter",
                    },
                },
            })
            logger.info("已发送鉴权 Identify")

            # 3. 接收 Ready，确认上线
            ready = await self._ws.receive_json()
            if ready.get("op") == 9:
                raise RuntimeError(f"鉴权失败 (Invalid Session): {ready}")
            if ready.get("op") != 0 or ready.get("t") != "READY":
                raise RuntimeError(f"期望 Ready 事件, 收到 {ready}")

            self._session_id = ready["d"]["session_id"]
            self._seq = ready.get("s")
            bot_name = ready["d"]["user"].get("username", "?")
            logger.info("Bot [%s] 已上线, session=%s", bot_name, self._session_id)

            # 4. 启动心跳循环
            self._hb_task = asyncio.create_task(
                self._heartbeat_loop(self._ws, heartbeat_interval)
            )

            # 5. 进入事件循环
            return await self._event_loop(self._ws)
        finally:
            if self._hb_task:
                self._hb_task.cancel()
                self._hb_task = None
            if not self._ws.closed:
                await self._ws.close()

    async def _resume(self) -> str:
        """断线恢复：用 Resume(op=6) 携带 session_id 和 seq 恢复之前的会话"""
        token = await self._get_access_token()

        gw = await self.api_get("/gateway/bot")
        if "url" not in gw:
            raise RuntimeError(f"获取网关失败: {gw}")
        ws_url = gw["url"]

        self._ws = await self._http.ws_connect(ws_url, proxy=self.proxy)
        try:
            hello = await self._ws.receive_json()
            if hello.get("op") != 10:
                raise RuntimeError(f"期望 Hello(op=10), 收到 {hello}")
            heartbeat_interval = hello["d"]["heartbeat_interval"] / 1000

            await self._ws.send_json({
                "op": 6,
                "d": {
                    "token": f"QQBot {token}",
                    "session_id": self._session_id,
                    "seq": self._seq,
                },
            })
            logger.info("已发送 Resume, session=%s, seq=%s",
                        self._session_id, self._seq)

            self._hb_task = asyncio.create_task(
                self._heartbeat_loop(self._ws, heartbeat_interval)
            )
            return await self._event_loop(self._ws)
        finally:
            if self._hb_task:
                self._hb_task.cancel()
                self._hb_task = None
            if not self._ws.closed:
                await self._ws.close()

    async def _event_loop(self, ws: aiohttp.ClientWebSocketResponse) -> str:
        """WebSocket 事件循环，返回退出原因: reconnect / invalid_session / closed / stopped"""
        async for msg in ws:
            if not self._running:
                return "stopped"

            if msg.type == aiohttp.WSMsgType.TEXT:
                payload = json.loads(msg.data)
                op = payload.get("op")

                if payload.get("s") is not None:
                    self._seq = payload["s"]

                if op == 0:       # Dispatch: 业务事件
                    event_type = payload.get("t", "")
                    await self._dispatch_message(event_type, payload.get("d", {}))
                elif op == 11:    # Heartbeat ACK
                    logger.debug("心跳 ACK")
                elif op == 7:     # Reconnect: 服务端要求重连
                    logger.warning("服务器要求重连")
                    return "reconnect"
                elif op == 9:     # Invalid Session
                    logger.error("Invalid Session, 需重新鉴权")
                    return "invalid_session"
                else:
                    logger.warning("未知 op=%s: %s", op, payload)

            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                logger.warning("WebSocket 连接关闭: %s", msg)
                return "closed"
        return "closed"

    # -------- 停止 --------

    async def stop(self):
        """优雅停止 Bot：取消心跳和所有后台任务，关闭 WebSocket"""
        logger.info("正在停止 QQBot...")
        self._running = False
        if self._hb_task:
            self._hb_task.cancel()
            self._hb_task = None
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        if self._ws and not self._ws.closed:
            await self._ws.close()

    async def _cleanup(self):
        """清理 HTTP 会话"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
        logger.info("QQBot 已停止")
