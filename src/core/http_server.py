"""
HTTP 服务端

负责:
    - Webhook 转发: 收到 QQ 消息后 POST 到外部业务服务，用响应内容回复
    - /api/send:    供外部服务主动向 QQ 发送消息
    - /api/health:  健康检查接口
"""

import json
import logging
from typing import Optional

import aiohttp
from aiohttp import web

from qq_adapter_protocol import MessageRequest, MessageResponse, MessageSource
from .qq_bot import QQBot

logger = logging.getLogger("qq-adapter")


class HttpServer:
    """对外 HTTP 服务端，搭配 QQBot 使用"""

    def __init__(
        self,
        qq_bot: QQBot,
        *,
        webhook_url: Optional[str] = None,
        host: str = "0.0.0.0",
        port: int = 8080,
    ):
        """
        Args:
            qq_bot:   QQBot 实例，用于发送消息和复用 HTTP 会话
            webhook_url: Webhook 推送地址，配置后自动接管 QQBot 的消息回调
            host:        HTTP 监听地址
            port:        HTTP 监听端口
        """
        self.qq_bot = qq_bot
        self.webhook_url = webhook_url
        self.host = host
        self.port = port
        self._runner: Optional[web.AppRunner] = None

        # 配置了 webhook 时，自动将 QQBot 的消息回调替换为 webhook 转发
        if webhook_url:
            self.qq_bot.on_message = self._webhook_callback

    # -------- webhook 回调 --------

    async def _webhook_callback(self, request: MessageRequest) -> MessageResponse:
        """
        将收到的 QQ 消息转发到 webhook_url。

        发送 JSON:
            {"source", "content", "msg_id", "event_type", "source_id", "sender_id"}

        期望响应 JSON:
            {"content": "回复内容"}  # content 为 null 时不回复
        """
        payload = {
            "source": request.source.value,
            "content": request.content,
            "msg_id": request.msg_id,
            "event_type": request.event_type,
            "source_id": request.source_id,
            "sender_id": request.sender_id,
        }
        try:
            async with self.qq_bot._http.post(
                self.webhook_url, json=payload
            ) as resp:
                body = await resp.text()
                if resp.status != 200:
                    logger.error("Webhook 返回 %d: %s", resp.status, body[:200])
                    return MessageResponse(content=None)
                data = json.loads(body)
                return MessageResponse(content=data.get("content"))
        except Exception:
            logger.exception("Webhook 请求失败: %s", self.webhook_url)
            return MessageResponse(content=None)

    # -------- HTTP 路由 --------

    def _create_app(self) -> web.Application:
        app = web.Application()
        app.router.add_post("/api/send", self._handle_send)
        app.router.add_get("/api/health", self._handle_health)
        return app

    async def _handle_health(self, request: web.Request) -> web.Response:
        """GET /api/health — 返回服务运行状态"""
        return web.json_response({
            "ok": True,
            "running": self.qq_bot._running,
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
        """启动 HTTP 服务"""
        app = self._create_app()
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        logger.info("HTTP 服务端已启动: http://%s:%d", self.host, self.port)

    async def stop(self):
        """停止 HTTP 服务"""
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            logger.info("HTTP 服务端已停止")
