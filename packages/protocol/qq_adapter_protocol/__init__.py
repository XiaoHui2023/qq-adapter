"""
qq-adapter-protocol — QQ Adapter 通信协议包

定义 QQ Adapter 服务端与客户端之间的公共数据结构，
双方共用同一套协议，确保消息格式一致。

客户端通过 WebSocket 连接服务端的 /ws 端点收发消息。


使用:
    from qq_adapter_protocol import QQAdapterClient, MessageResponse

    def handler(req):
        return MessageResponse(content="收到: " + req.content)

    client = QQAdapterClient("http://127.0.0.1:8080")
    client.run(handler)
"""

from .models import MessageSource, MessageRequest, MessageResponse
from .client import QQAdapterClient, run_all

__all__ = ["MessageSource", "MessageRequest", "MessageResponse", "QQAdapterClient", "run_all"]
