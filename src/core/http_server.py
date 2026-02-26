"""
HTTP / WebSocket 服务端

负责:
    - /ws:          WebSocket 端点，承载消息推送、回复返回和心跳保活
    - /api/send:    供外部服务主动向 QQ 发送消息
    - /api/health:  健康检查接口
"""

import asyncio
import json
import logging
from typing import Optional

import aiohttp
from aiohttp import web

from qq_adapter_protocol import MessageRequest, MessageResponse, MessageSource
from .qq_bot import QQBot

logger = logging.getLogger("qq-adapter")

# 等待客户端回复的超时秒数
WS_REPLY_TIMEOUT = 60


class HttpServer:
    """对外 HTTP + WebSocket 服务端，搭配 QQBot 使用"""

    def __init__(
        self,
        qq_bot: QQBot,
        *,
        host: str = "0.0.0.0",
        port: int = 8080,
    ):
        self.qq_bot = qq_bot
        self.host = host
        self.port = port
        self._runner: Optional[web.AppRunner] = None

        self._clients: set[web.WebSocketResponse] = set()
        self._pending: dict[str, asyncio.Future[MessageResponse]] = {}

        self.qq_bot.on_message = self._ws_broadcast

    # -------- WebSocket 端点 --------

    async def _handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        """GET /ws — WebSocket 连接入口"""
        ws = web.WebSocketResponse(heartbeat=120)
        await ws.prepare(request)

        self._clients.add(ws)
        peer = request.remote
        logger.info("WebSocket 客户端已连接: %s (当前 %d 个)", peer, len(self._clients))

        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        continue
                    msg_id = data.get("msg_id", "")
                    fut = self._pending.get(msg_id)
                    if fut and not fut.done():
                        content = data.get("content")
                        logger.info("收到客户端回复 [%s]: %s", msg_id, content)
                        fut.set_result(MessageResponse(content=content))
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.warning("WebSocket 错误: %s", ws.exception())
        finally:
            self._clients.discard(ws)
            logger.info("WebSocket 客户端已断开: %s (剩余 %d 个)", peer, len(self._clients))

        return ws

    # -------- 广播回调 --------

    async def _ws_broadcast(self, request: MessageRequest) -> MessageResponse:
        """
        将 QQ 消息广播给所有 WebSocket 客户端，等待第一个回复。

        发送 JSON (与原 webhook 格式一致):
            {"source", "content", "msg_id", "event_type", "source_id", "sender_id"}

        期望客户端回复 JSON:
            {"msg_id": "对应的消息ID", "content": "回复内容"}
        """
        if not self._clients:
            logger.warning("没有已连接的 WebSocket 客户端，无法转发消息")
            return MessageResponse(content=None)

        payload = json.dumps({
            "source": request.source.value,
            "content": request.content,
            "msg_id": request.msg_id,
            "event_type": request.event_type,
            "source_id": request.source_id,
            "sender_id": request.sender_id,
        }, ensure_ascii=False)

        fut: asyncio.Future[MessageResponse] = asyncio.get_running_loop().create_future()
        self._pending[request.msg_id] = fut

        dead: set[web.WebSocketResponse] = set()
        for ws in self._clients:
            try:
                await ws.send_str(payload)
            except Exception:
                dead.add(ws)
        self._clients -= dead

        try:
            return await asyncio.wait_for(fut, timeout=WS_REPLY_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("等待客户端回复超时: %s", request.msg_id)
            return MessageResponse(content=None)
        finally:
            self._pending.pop(request.msg_id, None)

    # -------- HTTP 路由 --------

    def _create_app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/ws", self._handle_ws)
        app.router.add_post("/api/send", self._handle_send)
        app.router.add_get("/api/health", self._handle_health)
        return app

    async def _handle_health(self, request: web.Request) -> web.Response:
        """GET /api/health — 返回服务运行状态"""
        return web.json_response({
            "ok": True,
            "running": self.qq_bot._running,
            "ws_clients": len(self._clients),
        })

    async def _handle_send(self, request: web.Request) -> web.Response:
        """
        POST /api/send — 主动发送消息到 QQ

        请求体 JSON:
            {
                "source": "group",       # guild / group / c2c
                "source_id": "xxx",      # 目标标识
                "content": "消息内容",
                "msg_id": ""             # 可选，关联的消息 ID
            }
        """
        try:
            data = await request.json()
        except Exception:
            return web.json_response(
                {"ok": False, "error": "invalid json"}, status=400
            )

        source_str = data.get("source", "")
        try:
            source = MessageSource(source_str)
        except ValueError:
            return web.json_response(
                {"ok": False, "error": f"invalid source: {source_str}"}, status=400
            )

        source_id = data.get("source_id", "")
        content = data.get("content", "")
        msg_id = data.get("msg_id", "")

        if not source_id or not content:
            return web.json_response(
                {"ok": False, "error": "source_id and content required"}, status=400
            )

        try:
            await self.qq_bot.send_message(source, source_id, content, msg_id)
            return web.json_response({"ok": True})
        except Exception as e:
            logger.exception("API send 失败")
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    # -------- 启停 --------

    async def start(self):
        """启动 HTTP + WebSocket 服务"""
        app = self._create_app()
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        logger.info("HTTP 服务端已启动: http://%s:%d (WebSocket: /ws)", self.host, self.port)

    async def stop(self):
        """停止服务，关闭所有 WebSocket 连接"""
        for ws in list(self._clients):
            await ws.close()
        self._clients.clear()

        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()

        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            logger.info("HTTP 服务端已停止")
