"""
QQ Adapter Webhook 客户端

封装 HTTP 服务器样板代码，用户只需提供回调函数即可处理消息。
支持 TCP 连通性检测、心跳检测、自动重连和生命周期事件。

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
LifecycleHook = Callable[[], Union[None, Awaitable[None]]]


class QQAdapterClient:
    """
    QQ Adapter Webhook 客户端

    接收 QQ Adapter 服务端推送的消息，交给回调函数处理后返回回复。
    可选连接服务端进行 TCP 连通性检测、心跳检测和断连感知。

    用法（单客户端）:
        client = QQAdapterClient(5000, server_url="http://127.0.0.1:8080")

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
            {"handler": handler_a, "port": 5000},
            {"handler": handler_b, "server_url": "http://127.0.0.1:8080"},
        )

    port 为 None 时，操作系统会自动分配一个可用端口。
    """

    def __init__(
        self,
        port: Optional[int] = None,
        path: str = "/webhook",
        server_url: Optional[str] = None,
        host: str = "127.0.0.1",
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

    async def _check_server(self) -> bool:
        """纯 TCP 连通性检测：只检查服务端 IP:端口是否可达"""
        from urllib.parse import urlparse

        parsed = urlparse(self.server_url)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=5
            )
            writer.close()
            await writer.wait_closed()
            return True
        except Exception:
            return False

    async def _wait_for_server(self, interval: float = 2):
        """轮询服务端，直到连接成功（无限重试）"""
        while True:
            if await self._check_server():
                self._connected = True
                logger.info("已连接到服务端: %s", self.server_url)
                await self._fire(self._on_connect)
                return
            logger.info("等待服务端就绪... (%s)", self.server_url)
            await asyncio.sleep(interval)

    async def _heartbeat_loop(self, interval: float = 10):
        """后台心跳，检测服务端是否断连，断连后持续探测直到恢复"""
        while True:
            await asyncio.sleep(interval)
            alive = await self._check_server()

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

        当 port 为 None 时，绑定 0 端口让 OS 自动分配，启动后回填实际端口。
        """
        self._handler = handler

        app = self._create_app()
        self._runner = web.AppRunner(app)
        await self._runner.setup()

        bind_port = self.port if self.port is not None else 0
        site = web.TCPSite(self._runner, self.host, bind_port)
        await site.start()

        if self.port is None:
            sock = site._server.sockets[0]  # type: ignore[union-attr]
            self.port = sock.getsockname()[1]

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
            if not self.server_url:
                logger.info("未配置 server_url，跳过服务端连接检测，仅监听 webhook")
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                pass
            finally:
                await self.stop()

        asyncio.run(_main())


_RUN_ALL_VALID_KEYS = {"handler", "port", "server_url", "host", "path"}


async def _run_all_main(groups):
    clients = []
    for group in groups:
        handler = group["handler"]
        client = QQAdapterClient(
            port=group.get("port"),
            server_url=group.get("server_url"),
            host=group.get("host", "127.0.0.1"),
            path=group.get("path", "/webhook"),
        )
        await client.start(handler)
        if not client.server_url:
            logger.info("未配置 server_url，跳过服务端连接检测，仅监听 webhook")
        clients.append(client)
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass
    finally:
        for client in clients:
            await client.stop()


def run_all(*groups: dict):
    """
    一次性阻塞启动多个客户端。

    每个 group 是一个字典，支持以下键:
    - handler: 必传，消息处理回调
    - port: 可选，监听端口，None 时自动分配
    - server_url: 可选，服务端地址
    - host: 可选，监听地址，默认 "127.0.0.1"
    - path: 可选，webhook 路径，默认 "/webhook"

    用法:
        run_all(
            {"handler": handler_a, "port": 5000},
            {"handler": handler_b, "server_url": "http://127.0.0.1:8080"},
        )
    """
    if not groups:
        raise ValueError("run_all 至少需要一个客户端配置")

    for i, group in enumerate(groups):
        if not isinstance(group, dict):
            raise TypeError(f"第 {i + 1} 个参数应为字典，实际类型: {type(group).__name__}")
        if "handler" not in group:
            raise ValueError(f"第 {i + 1} 个配置缺少必需的 'handler' 键")
        unknown = set(group.keys()) - _RUN_ALL_VALID_KEYS
        if unknown:
            raise ValueError(f"第 {i + 1} 个配置包含未知键: {unknown}")

    asyncio.run(_run_all_main(groups))
