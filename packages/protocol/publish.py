"""
PyPI 一键发布脚本
用法:
    python publish.py          # 发布到 PyPI
    python publish.py --test   # 发布到 TestPyPI
"""

import subprocess
import sys
import shutil
from pathlib import Path

DIST_DIR = Path(__file__).parent / "dist"


def run(cmd: str):
    print(f"\n>>> {cmd}")
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        print(f"\n命令失败 (exit code: {result.returncode})")
        sys.exit(result.returncode)


def main():
    is_test = "--test" in sys.argv

    if DIST_DIR.exists():
        print(f"清理 {DIST_DIR} ...")
        shutil.rmtree(DIST_DIR)

    print("开始构建...")
    run("python -m build")

    if is_test:
        print("上传到 TestPyPI...")
        run("python -m twine upload --repository testpypi dist/*")
    else:
        print("上传到 PyPI...")
        run("python -m twine upload dist/*")

    print("\n发布完成！")


if __name__ == "__main__":
    main()
