"""
QQ Adapter 入口脚本

用法:
    python src/                          # 使用默认配置启动
    python src/ --host 0.0.0.0 --port 9090  # 指定 HTTP 监听地址
    python src/ --log-file bot.log       # 日志同时输出到文件
    python src/ --env /path/to/.env      # 指定环境变量文件

启动流程:
    1. 解析命令行参数
    2. 加载 .env 环境变量
    3. 初始化日志
    4. 创建 QQBot（QQ WebSocket 客户端）
    5. 创建 HttpServer（对外 HTTP 接口）
    6. 并行运行两者，Ctrl+C 优雅退出
"""

import argparse
import asyncio
import os

from config import load_env, setup_logging
from core import QQBot, HttpServer


def parse_args():
    p = argparse.ArgumentParser(
        description="QQ Adapter — 轻量级 QQ 开放平台 Bot 适配器",
    )
    p.add_argument(
        "--env", default=None,
        help=".env 文件路径 (默认: src/.env)",
    )
    p.add_argument(
        "--log-file", default=None,
        help="日志输出文件路径，不指定则仅输出到控制台",
    )
    p.add_argument(
        "--host", default=None,
        help="HTTP 服务监听地址 (默认: 0.0.0.0，可通过环境变量 HTTP_HOST 覆盖)",
    )
    p.add_argument(
        "--port", type=int, default=None,
        help="HTTP 服务监听端口 (默认: 8080，可通过环境变量 HTTP_PORT 覆盖)",
    )
    return p.parse_args()


async def main():
    args = parse_args()

    load_env(args.env)
    setup_logging(log_file=args.log_file)

    # 命令行参数优先，其次环境变量，最后使用默认值
    host = args.host or os.environ.get("HTTP_HOST", "0.0.0.0")
    port = args.port or int(os.environ.get("HTTP_PORT", "8080"))

    client = QQBot(
        app_id=os.environ["APP_ID"],
        app_secret=os.environ["APP_SECRET"],
        proxy=os.environ.get("PROXY"),
    )

    server = HttpServer(
        client,
        webhook_url=os.environ.get("WEBHOOK_URL"),
        host=host,
        port=port,
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
