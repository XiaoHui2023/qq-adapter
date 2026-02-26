"""
QQ Adapter 入口脚本

用法:
    python src/                            # 使用默认配置启动
    python src/ --config config.yaml       # 指定配置文件路径

启动流程:
    1. 解析命令行参数
    2. 加载 config.yaml 配置
    3. 加载 .env 环境变量
    4. 初始化日志
    5. 创建 QQBot（QQ WebSocket 客户端）
    6. 创建 HttpServer（对外 HTTP 接口）
    7. 并行运行两者，Ctrl+C 优雅退出
"""

import argparse
import asyncio
import os

from config import load_env, setup_logging
from core import QQBot, HttpServer
from models import AppConfig


def parse_args():
    p = argparse.ArgumentParser(
        description="QQ Adapter — 轻量级 QQ 开放平台 Bot 适配器",
    )
    p.add_argument(
        "--config", default="config.yaml",
        help="配置文件路径 (默认: config.yaml)",
    )
    return p.parse_args()


async def main():
    args = parse_args()

    cfg = AppConfig.from_yaml(args.config)

    load_env()
    setup_logging(log_dir=cfg.log.dir, level=cfg.log.level)

    client = QQBot(
        app_id=os.environ["APP_ID"],
        app_secret=os.environ["APP_SECRET"],
        proxy=os.environ.get("PROXY"),
    )

    server = HttpServer(
        client,
        host=cfg.server.host,
        port=cfg.server.port,
    )

    try:
        await server.start()
        await client.run()
    except KeyboardInterrupt:
        pass
    finally:
        await client.stop()
        await server.stop()


if __name__ == "__main__":
    asyncio.run(main())
