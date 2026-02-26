"""
QQ Adapter WebSocket 客户端

通过 WebSocket 连接 QQ Adapter 服务端，接收消息推送并返回回复。
支持自动重连和生命周期事件。

依赖:
    pip install qq-adapter-protocol[client]
"""

import asyncio
import inspect
import json
import logging
from dataclasses import asdict
from typing import Callable, Union, Awaitable, Optional
from urllib.parse import urlparse

try:
    import aiohttp
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
    QQ Adapter WebSocket 客户端

    通过 WebSocket 连接 QQ Adapter 服务端，接收消息推送，
    交给回调函数处理后将回复通过同一连接发回。

    用法（单客户端）:
        client = QQAdapterClient("http://127.0.0.1:8080")

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
            {"handler": handler_a, "server_url": "http://127.0.0.1:8080"},
            {"handler": handler_b, "server_url": "http://10.0.0.1:8080"},
        )
    """

    def __init__(self, server_url: str):
        server_url = server_url.strip().rstrip("/")
        # 无 scheme 时自动补全（如 "127.0.0.1:8080" -> "http://127.0.0.1:8080"）
        if server_url and not server_url.startswith(("http://", "https://")):
            server_url = "http://" + server_url
        parsed = urlparse(server_url)
        if parsed.hostname is None:
            raise ValueError(
                f"无效的 server_url: {server_url!r}，"
                "请使用完整 URL（如 http://127.0.0.1:8080）或 host:port 格式"
            )
        self.server_url = server_url

        self._handler: Optional[MessageHandler] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._ws_task: Optional[asyncio.Task] = None
        self._running = False

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
        parsed = urlparse(self.server_url)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=5
            )
            writer.close()
            await writer.wait_closed()
            return True
        except Exception:
            return False

    async def _wait_for_server(self, interval: float = 2):
        """轮询服务端，直到 TCP 可达（无限重试）"""
        logged = False
        while self._running:
            if await self._check_server():
                return
            if not logged:
                logger.info("等待服务端就绪... (%s)", self.server_url)
                logged = True
            else:
                logger.debug("等待服务端就绪... (%s)", self.server_url)
            await asyncio.sleep(interval)

    # -------- WebSocket 消息循环 --------

    async def _ws_loop(self):
        """WebSocket 连接循环：连接 → 收消息 → 断线重连"""
        ws_url = self.server_url + "/ws"
        while self._running:
            await self._wait_for_server()
            if not self._running:
                break

            try:
                self._ws = await self._session.ws_connect(ws_url)
            except Exception:
                logger.warning("WebSocket 连接失败，将在 2 秒后重试...")
                await asyncio.sleep(2)
                continue

            self._connected = True
            logger.info("已连接到服务端: %s", ws_url)
            await self._fire(self._on_connect)

            try:
                async for msg in self._ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        asyncio.create_task(self._handle_message(msg.data))
                    elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        break
            except Exception:
                logger.exception("WebSocket 消息循环异常")
            finally:
                self._connected = False
                if self._ws and not self._ws.closed:
                    await self._ws.close()
                self._ws = None

            logger.warning("服务端连接已断开，等待重连... (%s)", self.server_url)
            await self._fire(self._on_disconnect)

            if self._running:
                await asyncio.sleep(2)

    async def _handle_message(self, raw: str):
        """解析服务端推送的消息，调用回调，发回回复"""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return

        request = MessageRequest(
            source=MessageSource(data["source"]),
            content=data.get("content", ""),
            source_id=data.get("source_id", ""),
            msg_id=data.get("msg_id", ""),
            event_type=data.get("event_type", ""),
            sender_id=data.get("sender_id", ""),
        )

        try:
            result = self._handler(request)
            if inspect.isawaitable(result):
                result = await result
            if result is None:
                result = MessageResponse(content=None)
        except Exception:
            logger.exception("消息处理回调异常")
            result = MessageResponse(content=None)

        content = result.content
        if not isinstance(content, str):
            content = str(content)
        if content is None:
            return
        response = {
            "msg_id": request.msg_id,
            "content": content,
        }

        if self._ws and not self._ws.closed:
            try:
                await self._ws.send_json(response)
            except Exception:
                logger.exception("发送回复失败")

    # -------- 启停 --------

    async def start(self, handler: MessageHandler):
        """
        非阻塞启动客户端。

        1. 等待服务端 TCP 可达
        2. 建立 WebSocket 连接
        3. 在后台任务中持续接收消息并自动重连
        """
        self._handler = handler
        self._running = True
        self._session = aiohttp.ClientSession()
        self._ws_task = asyncio.create_task(self._ws_loop())

    async def stop(self):
        """停止客户端，清理所有资源"""
        self._running = False

        if self._ws and not self._ws.closed:
            await self._ws.close()

        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
            self._ws_task = None

        if self._connected:
            self._connected = False
            await self._fire(self._on_disconnect)

        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

        logger.info("客户端已停止")

    def run(self, handler: MessageHandler):
        """阻塞运行客户端（单客户端便捷方法）。"""

        async def _main():
            await self.start(handler)
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                pass
            finally:
                await self.stop()

        asyncio.run(_main())


_RUN_ALL_VALID_KEYS = {"handler", "server_url"}


async def _run_all_main(groups):
    clients = []
    for group in groups:
        handler = group["handler"]
        client = QQAdapterClient(server_url=group["server_url"])
        await client.start(handler)
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
    - handler:    必传，消息处理回调
    - server_url: 必传，服务端地址

    用法:
        run_all(
            {"handler": handler_a, "server_url": "http://127.0.0.1:8080"},
            {"handler": handler_b, "server_url": "http://10.0.0.1:8080"},
        )
    """
    if not groups:
        raise ValueError("run_all 至少需要一个客户端配置")

    for i, group in enumerate(groups):
        if not isinstance(group, dict):
            raise TypeError(f"第 {i + 1} 个参数应为字典，实际类型: {type(group).__name__}")
        if "handler" not in group:
            raise ValueError(f"第 {i + 1} 个配置缺少必需的 'handler' 键")
        if "server_url" not in group:
            raise ValueError(f"第 {i + 1} 个配置缺少必需的 'server_url' 键")
        unknown = set(group.keys()) - _RUN_ALL_VALID_KEYS
        if unknown:
            raise ValueError(f"第 {i + 1} 个配置包含未知键: {unknown}")

    asyncio.run(_run_all_main(groups))
