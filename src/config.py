"""
环境变量加载与日志配置

提供两个工具函数:
    load_env()      — 从 .env 文件加载环境变量
    setup_logging() — 配置全局日志格式，可选同时输出到文件
"""

import logging
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


def load_env(env_path: Optional[str] = None):
    """
    加载 .env 文件到 os.environ。

    Args:
        env_path: .env 文件路径。未指定时默认使用 src/.env
    """
    path = Path(env_path) if env_path else Path(__file__).parent / ".env"
    load_dotenv(path)


def setup_logging(log_file: Optional[str] = None, level: int = logging.INFO):
    """
    配置全局日志。

    日志始终输出到控制台，如果指定了 log_file 则同时写入文件。

    Args:
        log_file: 日志文件路径，None 表示仅控制台输出
        level:    日志级别，默认 INFO
    """
    fmt = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handlers: list[logging.Handler] = [logging.StreamHandler()]

    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        handlers.append(file_handler)

    logging.basicConfig(level=level, format=fmt, datefmt=datefmt, handlers=handlers)
