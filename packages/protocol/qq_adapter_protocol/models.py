from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class MessageSource(str, Enum):
    GUILD = "guild"
    GROUP = "group"
    C2C = "c2c"


@dataclass
class MessageRequest:
    source: MessageSource
    content: str
    # 来源标识，根据 source 类型分别为 channel_id / group_openid / user_openid
    source_id: str
    msg_id: str = ""
    event_type: str = ""
    sender_id: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class MessageResponse:
    content: Optional[str] = None
    """回复内容，为 None 时不回复"""
