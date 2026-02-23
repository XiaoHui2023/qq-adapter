"""环境变量加载与日志配置"""

import logging
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


def load_env(env_path: Optional[str] = None):
    """加载 .env 文件。未指定路径时使用项目根目录的 .env"""
    path = Path(env_path) if env_path else Path(__file__).parent / ".env"
    load_dotenv(path)


def setup_logging(log_file: Optional[str] = None, level: int = logging.INFO):
    """配置日志。可选输出到文件。"""
    fmt = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handlers: list[logging.Handler] = [logging.StreamHandler()]

    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        handlers.append(file_handler)

    logging.basicConfig(level=level, format=fmt, datefmt=datefmt, handlers=handlers)
