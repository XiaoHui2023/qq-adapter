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
