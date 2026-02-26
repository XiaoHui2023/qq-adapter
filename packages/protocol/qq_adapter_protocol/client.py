"""
QQ Adapter Webhook 客户端

封装 HTTP 服务器样板代码，用户只需提供回调函数即可处理消息。

依赖:
    pip install qq-adapter-protocol[client]
"""

import asyncio
import inspect
import logging
from dataclasses import asdict
from typing import Callable, Union, Awaitable, Optional

try:
    from aiohttp import web
except ImportError:
    raise ImportError(
        "客户端功能需要 aiohttp，请执行: pip install qq-adapter-protocol[client]"
    ) from None

from .models import MessageRequest, MessageResponse, MessageSource

logger = logging.getLogger("qq-adapter-client")

MessageHandler = Callable[
    [MessageRequest], Union[MessageResponse, Awaitable[MessageResponse]]
]


class QQAdapterClient:
    """
    QQ Adapter Webhook 客户端

    接收 QQ Adapter 服务端推送的消息，交给回调函数处理后返回回复。

    用法（单客户端）:
        client = QQAdapterClient("127.0.0.1", 5000)
        client.run(handler)

    用法（多客户端）:
        await client_a.start(handler_a)
        await client_b.start(handler_b)
        await asyncio.Event().wait()
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 5000,
        path: str = "/webhook",
    ):
        self.host = host
        self.port = port
        self.path = path
        self._handler: Optional[MessageHandler] = None
        self._runner: Optional[web.AppRunner] = None

    async def _handle_webhook(self, request: web.Request) -> web.Response:
        """接收 Webhook POST，解析为 MessageRequest，调用回调，返回 MessageResponse"""
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"content": None}, status=400)

        msg = MessageRequest(
            source=MessageSource(data["source"]),
            content=data.get("content", ""),
            source_id=data.get("source_id", ""),
            msg_id=data.get("msg_id", ""),
            event_type=data.get("event_type", ""),
            sender_id=data.get("sender_id", ""),
        )

        try:
            result = self._handler(msg)
            if inspect.isawaitable(result):
                result = await result
        except Exception:
            logger.exception("消息处理回调异常")
            result = MessageResponse(content=None)

        return web.json_response(asdict(result))

    def _create_app(self) -> web.Application:
        app = web.Application()
        app.router.add_post(self.path, self._handle_webhook)
        return app

    async def start(self, handler: MessageHandler):
        """
        非阻塞启动客户端。

        适用于需要同时运行多个客户端，或嵌入已有 asyncio 应用的场景。
        调用后立即返回，服务在后台监听。
        """
        self._handler = handler
        app = self._create_app()
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        logger.info("客户端已启动: http://%s:%s%s", self.host, self.port, self.path)

    async def stop(self):
        """停止客户端"""
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            logger.info("客户端已停止: %s:%s", self.host, self.port)

    def run(self, handler: MessageHandler):
        """
        阻塞运行客户端。

        单客户端场景的便捷方法，内部调用 asyncio.run()。
        """
        self._handler = handler
        app = self._create_app()
        web.run_app(app, host=self.host, port=self.port)

    @staticmethod
    def run_all(*pairs: tuple["QQAdapterClient", MessageHandler]):
        """
        一次性阻塞启动多个客户端。

        用法:
            QQAdapterClient.run_all(
                (client_a, handler_a),
                (client_b, handler_b),
            )
        """
        async def _main():
            for client, handler in pairs:
                await client.start(handler)
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                pass
            finally:
                for client, _ in pairs:
                    await client.stop()

        asyncio.run(_main())
