"""
客户端测试：启动 HTTP 服务接收 qq_adapter 的 webhook 推送，
收到消息后在原文追加"（已处理）"返回。

使用前确保 qq_adapter 服务端的 WEBHOOK_URL 指向本客户端地址，
例如 WEBHOOK_URL=http://127.0.0.1:5000/webhook
"""

from dataclasses import asdict

from aiohttp import web
from qq_adapter_protocol import MessageRequest, MessageResponse, MessageSource


async def handle_webhook(request: web.Request) -> web.Response:
    data = await request.json()

    msg = MessageRequest(
        source=MessageSource(data["source"]),
        content=data.get("content", ""),
        source_id=data.get("source_id", ""),
        msg_id=data.get("msg_id", ""),
        event_type=data.get("event_type", ""),
        sender_id=data.get("sender_id", ""),
    )

    reply = MessageResponse(content=msg.content + "（已处理）")
    print(f"[{msg.source.value}] {msg.sender_id}: {msg.content} → {reply.content}")

    return web.json_response(asdict(reply))


app = web.Application()
app.router.add_post("/webhook", handle_webhook)

if __name__ == "__main__":
    web.run_app(app, host="127.0.0.1", port=5000)
