"""
qq-adapter-protocol — QQ Adapter 通信协议包

定义 QQ Adapter 服务端与客户端之间的公共数据结构，
双方共用同一套协议，确保消息格式一致。

安装:
    pip install qq-adapter-protocol

使用:
    from qq_adapter_protocol import MessageSource, MessageRequest, MessageResponse

    # 构建一条消息
    req = MessageRequest(
        source=MessageSource.GROUP,
        content="你好",
        source_id="group_openid_xxx",
    )

    # 构建一条回复
    resp = MessageResponse(content="收到")
"""

from .models import MessageSource, MessageRequest, MessageResponse

__all__ = ["MessageSource", "MessageRequest", "MessageResponse", "QQAdapterClient", "run_all"]


def __getattr__(name: str):
    if name == "QQAdapterClient":
        from .client import QQAdapterClient
        return QQAdapterClient
    if name == "run_all":
        from .client import run_all
        return run_all
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
