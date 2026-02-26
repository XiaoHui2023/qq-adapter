"""
QQ Adapter Webhook 客户端

封装 HTTP 服务器样板代码，用户只需提供回调函数即可处理消息。
支持服务端健康检查、心跳检测、自动重连和生命周期事件。

依赖:
    pip install qq-adapter-protocol[client]
"""

import asyncio
import inspect
import logging
from dataclasses import asdict
from typing import Callable, Union, Awaitable, Optional

try:
    from aiohttp import web, ClientSession, ClientError
except ImportError:
    raise ImportError(
        "客户端功能需要 aiohttp，请执行: pip install qq-adapter-protocol[client]"
    ) from None

from .models import MessageRequest, MessageResponse, MessageSource

logger = logging.getLogger("qq-adapter-client")

MessageHandler = Callable[
    [MessageRequest], Union[MessageResponse, Awaitable[MessageResponse]]
]
LifecycleHook = Callable[[], Union[None, Awaitable[None]]]


class QQAdapterClient:
    """
    QQ Adapter Webhook 客户端

    接收 QQ Adapter 服务端推送的消息，交给回调函数处理后返回回复。
    可选连接服务端进行健康检查、心跳检测和断连感知。

    用法（单客户端）:
        client = QQAdapterClient("127.0.0.1", 5000, server_url="http://127.0.0.1:8080")

        @client.on_connect
        async def connected():
            print("已连接到服务端")

        @client.on_disconnect
        async def disconnected():
            print("服务端断连")

        client.run(handler)

    用法（多客户端）:
        from qq_adapter_protocol import run_all
        run_all(
            ("127.0.0.1", 5000, handler_a),
            ("127.0.0.1", 5001, handler_b),
        )
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 5000,
        path: str = "/webhook",
        server_url: Optional[str] = None,
    ):
        self.host = host
        self.port = port
        self.path = path
        self.server_url = server_url.rstrip("/") if server_url else None

        self._handler: Optional[MessageHandler] = None
        self._runner: Optional[web.AppRunner] = None
        self._heartbeat_task: Optional[asyncio.Task] = None

        self._connected = False
        self._on_connect: Optional[LifecycleHook] = None
        self._on_disconnect: Optional[LifecycleHook] = None

    # -------- 连接状态 --------

    @property
    def connected(self) -> bool:
        """服务端是否在线"""
        return self._connected

    # -------- 生命周期装饰器 --------

    def on_connect(self, fn: LifecycleHook) -> LifecycleHook:
        """注册服务端连接成功回调（装饰器）"""
        self._on_connect = fn
        return fn

    def on_disconnect(self, fn: LifecycleHook) -> LifecycleHook:
        """注册服务端断连回调（装饰器）"""
        self._on_disconnect = fn
        return fn

    async def _fire(self, hook: Optional[LifecycleHook]):
        if hook is None:
            return
        try:
            result = hook()
            if inspect.isawaitable(result):
                await result
        except Exception:
            logger.exception("生命周期回调异常")

    # -------- 服务端探测 --------

    async def _check_server(self, session: ClientSession) -> bool:
        """单次健康检查，返回是否成功"""
        try:
            async with session.get(
                f"{self.server_url}/api/health", timeout=asyncio.timeout(5)
            ) as resp:
                return resp.status == 200
        except Exception:
            return False

    async def _wait_for_server(self, timeout: float = 60, interval: float = 2):
        """轮询服务端健康检查，直到连接成功或超时"""
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        async with ClientSession() as session:
            while loop.time() < deadline:
                if await self._check_server(session):
                    self._connected = True
                    logger.info("已连接到服务端: %s", self.server_url)
                    await self._fire(self._on_connect)
                    return
                remaining = deadline - loop.time()
                logger.info(
                    "等待服务端就绪... (%s) 剩余 %.0fs",
                    self.server_url, remaining,
                )
                await asyncio.sleep(interval)
        raise TimeoutError(f"无法连接到服务端 {self.server_url}，超时 {timeout}s")

    async def _heartbeat_loop(self, interval: float = 10):
        """后台心跳，检测服务端是否断连，断连后持续探测直到恢复"""
        async with ClientSession() as session:
            while True:
                await asyncio.sleep(interval)
                alive = await self._check_server(session)

                if alive and not self._connected:
                    self._connected = True
                    logger.info("服务端已重新连接: %s", self.server_url)
                    await self._fire(self._on_connect)
                elif not alive and self._connected:
                    self._connected = False
                    logger.warning("服务端连接已断开，等待重连... (%s)", self.server_url)
                    await self._fire(self._on_disconnect)

    # -------- Webhook 处理 --------

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

    # -------- 启停 --------

    async def start(self, handler: MessageHandler):
        """
        非阻塞启动客户端。

        1. 启动 HTTP 服务器接收 webhook 推送
        2. 如果配置了 server_url，等待服务端就绪
        3. 启动后台心跳任务持续监测连接状态
        """
        self._handler = handler

        app = self._create_app()
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        logger.info("客户端已启动: http://%s:%s%s", self.host, self.port, self.path)

        if self.server_url:
            await self._wait_for_server()
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def stop(self):
        """停止客户端，清理所有资源"""
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None

        if self._connected:
            self._connected = False
            await self._fire(self._on_disconnect)

        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            logger.info("客户端已停止: %s:%s", self.host, self.port)

    def run(self, handler: MessageHandler):
        """
        阻塞运行客户端（单客户端便捷方法）。

        如果配置了 server_url，会先等待服务端就绪，再进入消息接收循环。
        """

        async def _main():
            await self.start(handler)
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                pass
            finally:
                await self.stop()

        asyncio.run(_main())


async def _run_all_main(groups):
    clients = []
    for group in groups:
        if len(group) == 3:
            host, port, handler = group
            server_url = None
        else:
            host, port, handler, server_url = group
        client = QQAdapterClient(host, port, server_url=server_url)
        await client.start(handler)
        clients.append(client)
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass
    finally:
        for client in clients:
            await client.stop()


def run_all(*groups):
    """
    一次性阻塞启动多个客户端。

    用法:
        run_all(
            ("127.0.0.1", 5000, handler_a),
            ("127.0.0.1", 5001, handler_b, "http://127.0.0.1:8080"),
        )
    """
    asyncio.run(_run_all_main(groups))
