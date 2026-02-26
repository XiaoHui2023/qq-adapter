# qq-adapter-protocol

QQ Adapter 通信协议包，定义主脚本与客户端之间的公共数据结构。

## 安装

```bash
pip install qq-adapter-protocol
```

从源码安装（开发模式）：

```bash
cd packages/qq_adapter_protocol
pip install -e .
```

## 使用

```python
from qq_adapter_protocol import MessageSource, MessageRequest, MessageResponse

# 构建一条消息请求
req = MessageRequest(
    source=MessageSource.GROUP,
    content="你好",
    source_id="group_openid_xxx",
)

# 构建一条回复
resp = MessageResponse(content="收到")
```

## 数据结构

### MessageSource

消息来源枚举：

| 值 | 说明 |
|----|------|
| `guild` | 频道消息 |
| `group` | 群消息 |
| `c2c` | 私聊消息 |

### MessageRequest

消息请求载体，用于 webhook 推送和 API 发送。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `source` | `MessageSource` | *必填* | 消息来源类型 |
| `content` | `str` | *必填* | 消息内容 |
| `source_id` | `str` | *必填* | 来源标识（channel_id / group_openid / user_openid） |
| `msg_id` | `str` | `""` | 消息 ID |
| `event_type` | `str` | `""` | 事件类型 |
| `sender_id` | `str` | `""` | 发送者 ID |
| `raw` | `dict` | `{}` | 原始事件数据 |

### MessageResponse

消息回复载体。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `content` | `str \| None` | `None` | 回复内容，为 None 时不回复 |

## 客户端

协议包内置了 Webhook 客户端，用于接收 QQ Adapter 推送的消息。

安装（需要 aiohttp）：

```bash
pip install qq-adapter-protocol[client]
```

### 单客户端

```python
from qq_adapter_protocol import QQAdapterClient, MessageRequest, MessageResponse

async def handle(msg: MessageRequest) -> MessageResponse:
    return MessageResponse(content=msg.content + "（已处理）")

QQAdapterClient("127.0.0.1", 5000).run(handle)
```

### 多客户端并发

```python
import asyncio
from qq_adapter_protocol import QQAdapterClient, MessageRequest, MessageResponse

async def handler_a(msg: MessageRequest) -> MessageResponse:
    return MessageResponse(content=f"Bot A: {msg.content}")

async def handler_b(msg: MessageRequest) -> MessageResponse:
    return MessageResponse(content=f"Bot B: {msg.content}")

async def main():
    client_a = QQAdapterClient("127.0.0.1", 5001)
    client_b = QQAdapterClient("127.0.0.1", 5002)
    await client_a.start(handler_a)
    await client_b.start(handler_b)
    try:
        await asyncio.Event().wait()
    finally:
        await client_a.stop()
        await client_b.stop()

asyncio.run(main())
```

### 批量启动（便捷方式）

```python
QQAdapterClient.run_all(
    (QQAdapterClient("127.0.0.1", 5001), handler_a),
    (QQAdapterClient("127.0.0.1", 5002), handler_b),
)
```

### QQAdapterClient

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `host` | `str` | `"127.0.0.1"` | 监听地址 |
| `port` | `int` | `5000` | 监听端口 |
| `path` | `str` | `"/webhook"` | Webhook 路径 |

| 方法 | 说明 |
|------|------|
| `run(handler)` | 阻塞运行，适合单客户端 |
| `await start(handler)` | 非阻塞启动，适合多客户端或嵌入 asyncio 应用 |
| `await stop()` | 停止客户端 |
| `run_all(*pairs)` | 静态方法，批量阻塞启动多个客户端 |
