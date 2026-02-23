"""
客户端示例：Webhook 接收端

演示如何编写一个业务服务，接收 QQ Adapter 推送的消息并返回回复。

工作流:
    1. QQ 用户发消息 → QQ Adapter 收到
    2. QQ Adapter POST 到本服务的 /webhook
    3. 本服务处理消息，返回 {"content": "回复内容"}
    4. QQ Adapter 将回复发回给 QQ 用户

使用方法:
    1. 启动本客户端:    python test.py
    2. 启动 QQ Adapter: python src/
    3. 确保 QQ Adapter 的 WEBHOOK_URL 指向 http://127.0.0.1:5000/webhook

依赖:
    pip install aiohttp qq-adapter-protocol
"""

from dataclasses import asdict

from aiohttp import web
from qq_adapter_protocol import MessageRequest, MessageResponse, MessageSource


async def handle_webhook(request: web.Request) -> web.Response:
    """
    处理 QQ Adapter 推送的 Webhook 请求。

    收到的 JSON 格式:
        {
            "source": "c2c",           # 消息来源: guild / group / c2c
            "content": "用户消息",      # 消息内容
            "msg_id": "abc123",        # 消息 ID
            "event_type": "C2C_...",   # QQ 事件类型
            "source_id": "openid",     # 来源标识
            "sender_id": "openid"      # 发送者标识
        }

    返回的 JSON 格式:
        {"content": "回复内容"}        # content 为 null 时不回复
    """
    data = await request.json()

    # 使用协议包解析为结构化对象
    msg = MessageRequest(
        source=MessageSource(data["source"]),
        content=data.get("content", ""),
        source_id=data.get("source_id", ""),
        msg_id=data.get("msg_id", ""),
        event_type=data.get("event_type", ""),
        sender_id=data.get("sender_id", ""),
    )

    # 业务逻辑：在原消息后追加"（已处理）"
    reply = MessageResponse(content=msg.content + "（已处理）")
    print(f"[{msg.source.value}] {msg.sender_id}: {msg.content} → {reply.content}")

    return web.json_response(asdict(reply))


app = web.Application()
app.router.add_post("/webhook", handle_webhook)

if __name__ == "__main__":
    web.run_app(app, host="127.0.0.1", port=5000)
