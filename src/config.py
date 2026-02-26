"""
环境变量加载与日志配置

提供两个工具函数:
    load_env()      — 从 .env 文件加载环境变量
    setup_logging() — 配置全局日志格式，可选同时输出到目录
"""

import logging
import os
from datetime import datetime
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


def setup_logging(log_dir: Optional[str] = None, level: int = logging.INFO):
    """
    配置全局日志。

    日志始终输出到控制台，如果指定了 log_dir 则同时写入该目录下
    以启动时间命名的日志文件（格式: YYYYMMDD_HHMMSS.log）。

    Args:
        log_dir: 日志输出目录，None 表示仅控制台输出
        level:   日志级别，默认 INFO
    """
    fmt = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handlers: list[logging.Handler] = [logging.StreamHandler()]

    if log_dir:
        dir_path = Path(log_dir)
        dir_path.mkdir(parents=True, exist_ok=True)
        filename = datetime.now().strftime("%Y%m%d_%H%M%S") + ".log"
        file_handler = logging.FileHandler(dir_path / filename, encoding="utf-8")
        handlers.append(file_handler)

    logging.basicConfig(level=level, format=fmt, datefmt=datefmt, handlers=handlers)
