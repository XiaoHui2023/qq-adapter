"""
QQ Adapter 通信协议数据结构

所有模型基于标准库 dataclass，零外部依赖。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class MessageSource(str, Enum):
    """消息来源类型"""

    GUILD = "guild"   # 频道消息（通过 @Bot 触发）
    GROUP = "group"   # 群消息（通过 @Bot 触发）
    C2C = "c2c"       # 私聊消息


@dataclass
class MessageRequest:
    """
    消息请求载体

    用途:
        - Webhook 推送: QQ Adapter 将收到的消息封装为此结构推送给业务服务
        - API 发送:     业务服务通过 /api/send 接口发送消息时也使用此结构

    Attributes:
        source:     消息来源类型
        content:    消息文本内容
        source_id:  来源标识，根据 source 类型分别为:
                    - guild: channel_id (频道子频道 ID)
                    - group: group_openid (群 openid)
                    - c2c:   user_openid (用户 openid)
        msg_id:     消息 ID（被动回复时必填）
        event_type: QQ 事件类型（如 C2C_MESSAGE_CREATE）
        sender_id:  发送者标识
        raw:        原始事件数据（仅服务端内部使用）
    """
    source: MessageSource
    content: str
    source_id: str
    msg_id: str = ""
    event_type: str = ""
    sender_id: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class MessageResponse:
    """
    消息回复载体

    Webhook 客户端返回此结构告诉 QQ Adapter 如何回复。

    Attributes:
        content: 回复内容，为 None 时表示不回复
    """
    content: Optional[str] = None
