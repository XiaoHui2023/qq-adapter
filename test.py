"""
客户端示例：使用 QQAdapterClient 接收 QQ Adapter 推送的消息

使用方法:
    1. pip install qq-adapter-protocol[client]
    2. 启动本客户端:    python test.py
    3. 启动 QQ Adapter: python src/
    4. 确保 QQ Adapter 的 WEBHOOK_URL 指向 http://127.0.0.1:<port>/webhook
"""

from qq_adapter_protocol import QQAdapterClient, MessageRequest, MessageResponse


async def handle(msg: MessageRequest) -> MessageResponse:
    reply = msg.content + "（已处理）"
    print(f"[{msg.source.value}] {msg.sender_id}: {msg.content} → {reply}")
    return MessageResponse(content=reply)


if __name__ == "__main__":
    QQAdapterClient(5000).run(handle)
