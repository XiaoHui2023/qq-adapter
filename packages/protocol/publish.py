"""
PyPI 一键发布脚本
自动递增补丁版本号并发布到 PyPI
用法: python publish.py
"""

import re
import subprocess
import sys
import shutil
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PYPROJECT = SCRIPT_DIR / "pyproject.toml"
DIST_DIR = SCRIPT_DIR / "dist"


def run(cmd: str):
    print(f"\n>>> {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=SCRIPT_DIR)
    if result.returncode != 0:
        print(f"\n命令失败 (exit code: {result.returncode})")
        sys.exit(result.returncode)


def bump_version() -> str:
    content = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"(\d+)\.(\d+)\.(\d+)"', content, re.MULTILINE)
    if not match:
        print("无法在 pyproject.toml 中找到版本号")
        sys.exit(1)

    major, minor, patch = int(match.group(1)), int(match.group(2)), int(match.group(3))
    old_version = f"{major}.{minor}.{patch}"
    new_version = f"{major}.{minor}.{patch + 1}"

    new_content = content.replace(f'version = "{old_version}"', f'version = "{new_version}"')
    PYPROJECT.write_text(new_content, encoding="utf-8")
    return new_version


def main():
    new_version = bump_version()
    print(f"版本号已更新为: {new_version}")

    if DIST_DIR.exists():
        print(f"清理 {DIST_DIR} ...")
        shutil.rmtree(DIST_DIR)

    print("开始构建...")
    run("python -m build")

    print("上传到 PyPI...")
    run("python -m twine upload dist/*")

    print("\n发布完成！")


if __name__ == "__main__":
    main()
