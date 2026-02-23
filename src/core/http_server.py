"""HTTP 服务端：对外暴露 API 接口、转发 webhook"""

import logging
from typing import Optional

import aiohttp
from aiohttp import web

from qq_adapter_protocol import MessageRequest, MessageResponse, MessageSource
from .qq_client import QQClient

logger = logging.getLogger("qq-adapter")


class HttpServer:
    def __init__(
        self,
        qq_client: QQClient,
        *,
        webhook_url: Optional[str] = None,
        host: str = "0.0.0.0",
        port: int = 8080,
    ):
        self.qq_client = qq_client
        self.webhook_url = webhook_url
        self.host = host
        self.port = port
        self._runner: Optional[web.AppRunner] = None

        if webhook_url:
            self.qq_client.on_message = self._webhook_callback

    # -------- webhook 回调 --------

    async def _webhook_callback(self, request: MessageRequest) -> MessageResponse:
        payload = {
            "source": request.source.value,
            "content": request.content,
            "msg_id": request.msg_id,
            "event_type": request.event_type,
            "source_id": request.source_id,
            "sender_id": request.sender_id,
        }
        try:
            async with self.qq_client._http.post(
                self.webhook_url, json=payload, proxy=self.qq_client.proxy
            ) as resp:
                data = await resp.json()
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
        return web.json_response({
            "ok": True,
            "running": self.qq_client._running,
        })

    async def _handle_send(self, request: web.Request) -> web.Response:
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
            await self.qq_client.send_message(source, source_id, content, msg_id)
            return web.json_response({"ok": True})
        except Exception as e:
            logger.exception("API send 失败")
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    # -------- 启停 --------

    async def start(self):
        app = self._create_app()
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        logger.info("HTTP 服务端已启动: http://%s:%d", self.host, self.port)

    async def stop(self):
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            logger.info("HTTP 服务端已停止")
