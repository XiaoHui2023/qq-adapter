# QQ Adapter

轻量级 QQ 开放平台 Bot 适配器。通过 WebSocket 对接 QQ 开放平台，同时对外暴露 HTTP 接口，让任意语言/框架的业务服务都能轻松收发 QQ 消息。

## 架构

```
┌──────────┐  WebSocket   ┌──────────────┐  Webhook POST  ┌──────────────┐
│ QQ 开放  │◄────────────►│  QQ Adapter   │───────────────►│  你的业务    │
│ 平台     │              │  (本项目)     │◄───────────────│  服务        │
└──────────┘              │               │  JSON Response │              │
                          │  HTTP Server  │◄───────────────│              │
                          │  /api/send    │  主动发消息    │              │
                          │  /api/health  │                └──────────────┘
                          └──────────────┘
```

**QQBot** — 负责 QQ 开放平台的鉴权、WebSocket 连接、心跳维持、消息收发。

**HttpServer** — 对外提供 HTTP 接口：将收到的 QQ 消息通过 Webhook 推送给业务服务，并暴露 `/api/send` 让业务服务主动发消息。

**qq-adapter-protocol** — 独立发布的通信协议包，定义 `MessageRequest` / `MessageResponse` 等公共数据结构，服务端和客户端共用。

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

安装通信协议包（开发模式）：

```bash
cd packages/protocol
pip install -e .
```

### 2. 配置环境变量

复制 `.env.example` 并填写：

```bash
cp src/.env.example src/.env
```

```env
# QQ 开放平台应用凭据（必填）
APP_ID=你的AppID
APP_SECRET=你的AppSecret

# 出站代理（选填，用于 IP 白名单场景）
PROXY=http://user:pass@server:port

# Webhook 地址（选填，收到消息后 POST 到此地址）
WEBHOOK_URL=http://127.0.0.1:5000/webhook
```

### 3. 启动服务端

```bash
# 最简启动
python src/

# 指定 HTTP 监听地址和端口
python src/ --host 0.0.0.0 --port 9090

# 日志输出到文件
python src/ --log-file bot.log

# 指定 .env 路径
python src/ --env /path/to/.env
```

### 4. 编写客户端

客户端只需实现一个 HTTP 接口接收 Webhook 推送，用 `qq-adapter-protocol` 解析数据：

```python
from dataclasses import asdict
from aiohttp import web
from qq_adapter_protocol import MessageRequest, MessageResponse, MessageSource

async def handle_webhook(request: web.Request) -> web.Response:
    data = await request.json()

    # 用协议包解析消息
    msg = MessageRequest(
        source=MessageSource(data["source"]),
        content=data.get("content", ""),
        source_id=data.get("source_id", ""),
        msg_id=data.get("msg_id", ""),
        sender_id=data.get("sender_id", ""),
    )

    # 处理消息，返回回复内容
    reply = MessageResponse(content=f"收到: {msg.content}")
    return web.json_response(asdict(reply))

app = web.Application()
app.router.add_post("/webhook", handle_webhook)

if __name__ == "__main__":
    web.run_app(app, host="127.0.0.1", port=5000)
```

## 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--env` | `.env` 文件路径 | `src/.env` |
| `--log-file` | 日志输出文件路径 | 不输出到文件 |
| `--host` | HTTP 服务监听地址 | `0.0.0.0` |
| `--port` | HTTP 服务监听端口 | `8080` |

## HTTP API

### POST /api/send — 主动发送消息

业务服务可通过此接口主动向 QQ 发送消息。

**请求体：**

```json
{
    "source": "group",
    "source_id": "group_openid_xxx",
    "content": "你好！",
    "msg_id": ""
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `source` | `string` | 消息类型：`guild` / `group` / `c2c` |
| `source_id` | `string` | 目标标识（channel_id / group_openid / user_openid） |
| `content` | `string` | 消息内容 |
| `msg_id` | `string` | 关联的消息 ID（可选，用于被动回复） |

**响应：**

```json
{"ok": true}
```

### GET /api/health — 健康检查

```json
{"ok": true, "running": true}
```

## Webhook 协议

服务端收到 QQ 消息后会 POST 到 `WEBHOOK_URL`，请求体：

```json
{
    "source": "c2c",
    "content": "你好",
    "msg_id": "abc123",
    "event_type": "C2C_MESSAGE_CREATE",
    "source_id": "user_openid_xxx",
    "sender_id": "user_openid_xxx"
}
```

客户端返回 JSON，`content` 字段为回复内容，为 `null` 时不回复：

```json
{"content": "收到你的消息！"}
```

## 项目结构

```
qq_adapter/
├── src/                            # 服务端源码
│   ├── __main__.py                 # 入口：参数解析、启动服务
│   ├── config.py                   # 环境变量加载、日志配置
│   ├── .env.example                # 环境变量模板
│   └── core/
│       ├── qq_bot.py            # QQBot：QQ 开放平台 WebSocket 对接
│       └── http_server.py          # HttpServer：HTTP API + Webhook 转发
├── packages/
│   └── protocol/                   # 独立发布的通信协议包
│       ├── pyproject.toml
│       └── qq_adapter_protocol/
│           └── models.py           # MessageSource, MessageRequest, MessageResponse
├── test.py                         # 客户端测试示例
├── requirements.txt                # 服务端依赖
├── update.bat                      # Windows 一键更新脚本
└── README.md
```

## 通信协议包

`qq-adapter-protocol` 是独立发布的 pip 包，服务端和客户端共用。

### 安装

```bash
# 从 PyPI 安装
pip install qq-adapter-protocol

# 从源码安装（开发模式）
cd packages/protocol
pip install -e .
```

### 数据结构

**MessageSource** — 消息来源枚举

| 值 | 说明 |
|----|------|
| `guild` | 频道消息 |
| `group` | 群消息 |
| `c2c` | 私聊消息 |

**MessageRequest** — 消息载体

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `source` | `MessageSource` | 必填 | 消息来源 |
| `content` | `str` | 必填 | 消息内容 |
| `source_id` | `str` | 必填 | 来源标识 |
| `msg_id` | `str` | `""` | 消息 ID |
| `event_type` | `str` | `""` | 事件类型 |
| `sender_id` | `str` | `""` | 发送者 ID |
| `raw` | `dict` | `{}` | 原始事件数据 |

**MessageResponse** — 回复载体

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `content` | `str \| None` | `None` | 回复内容，为 None 时不回复 |

## 代理配置

QQ 开放平台要求 API 请求源 IP 在白名单内。如果本机 IP 不在白名单，可通过 HTTP 代理转发：

1. 在白名单内的服务器上搭建 Squid 代理
2. 在 `.env` 中配置 `PROXY=http://user:pass@server:port`

代理仅用于 QQ API 请求，Webhook 回调不走代理。

## License

MIT
