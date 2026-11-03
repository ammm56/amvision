"""同机点云调用与工件配方导出入口，复用已有跨平台 launcher。"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


LAUNCHERS_ROOT = Path(__file__).resolve().parents[1]
if str(LAUNCHERS_ROOT) not in sys.path:
    sys.path.insert(0, str(LAUNCHERS_ROOT))

from common import resolve_app_root, run_python_module  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    """仅转发两个正式工具；运行目录与服务一致，不启动服务或猜测 Trigger。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", help="服务应用根目录；默认按启动器位置解析")
    parser.add_argument(
        "--python-executable", help="显式解释器；发行默认使用同目录 Python"
    )
    parser.add_argument("tool", choices=("invoke", "recipe"))
    parser.add_argument("tool_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    tool_args = args.tool_args[1:] if args.tool_args[:1] == ["--"] else args.tool_args
    return run_python_module(
        app_root=resolve_app_root(
            script_file=Path(__file__), explicit_app_root=args.app_root
        ),
        module_name={
            "invoke": "runtimes.clients.point_cloud",
            "recipe": "scripts.metrology_workpiece",
        }[args.tool],
        module_args=tool_args,
        python_executable=args.python_executable,
    )


if __name__ == "__main__":
    raise SystemExit(main())
