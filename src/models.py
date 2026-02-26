"""
Pydantic 配置模型

通过 config.yaml 管理除 QQ 凭据以外的所有配置项。
QQ 凭据（APP_ID / APP_SECRET / PROXY）仍由 .env 环境变量提供。
"""

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field
import yaml


class ServerConfig(BaseModel):
    host: str = Field("0.0.0.0", description="HTTP 监听地址")
    port: int = Field(8080, description="HTTP 监听端口")


class LogConfig(BaseModel):
    level: str = Field("INFO", description="日志级别")
    dir: Optional[str] = Field(None, description="日志输出目录，不指定则仅控制台")


class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    log: LogConfig = Field(default_factory=LogConfig)

    @classmethod
    def from_yaml(cls, path: str | Path = "config.yaml") -> "AppConfig":
        p = Path(path)
        if not p.exists():
            return cls()
        with open(p, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls.model_validate(data)
