import argparse
import asyncio
import os

from config import load_env, setup_logging
from core import QQClient, HttpServer


def parse_args():
    p = argparse.ArgumentParser(description="QQ Adapter Bot")

    p.add_argument("--env", default=None, help=".env 文件路径 (默认: 项目根目录 .env)")
    p.add_argument("--log-file", default=None, help="日志输出文件路径 (不指定则仅控制台)")
    p.add_argument("--host", default=None, help="HTTP 服务监听地址 (默认: 0.0.0.0)")
    p.add_argument("--port", type=int, default=None, help="HTTP 服务监听端口 (默认: 8080)")

    return p.parse_args()


async def main():
    args = parse_args()

    load_env(args.env)
    setup_logging(log_file=args.log_file)

    host = args.host or os.environ.get("HTTP_HOST", "0.0.0.0")
    port = args.port or int(os.environ.get("HTTP_PORT", "8080"))

    client = QQClient(
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
