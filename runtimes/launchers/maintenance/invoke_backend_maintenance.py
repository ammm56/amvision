"""backend-maintenance Python launcher。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


LAUNCHERS_ROOT = Path(__file__).resolve().parents[1]
if str(LAUNCHERS_ROOT) not in sys.path:
    sys.path.insert(0, str(LAUNCHERS_ROOT))

from common import resolve_app_root, run_python_module


def build_argument_parser() -> argparse.ArgumentParser:
    """构造 backend-maintenance launcher 参数解析器。"""

    parser = argparse.ArgumentParser(description="amvision backend-maintenance launcher")
    parser.add_argument("--app-root", help="应用根目录；未传入时按 launcher 相对位置自动解析")
    parser.add_argument("--python-executable", help="用于启动 backend-maintenance 的 Python 解释器路径")
    parser.add_argument(
        "maintenance_args",
        nargs=argparse.REMAINDER,
        help="传递给 backend-maintenance 的原始参数",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """执行 backend-maintenance launcher 主入口。"""

    parser = build_argument_parser()
    args = parser.parse_args(argv)
    app_root = resolve_app_root(script_file=Path(__file__), explicit_app_root=args.app_root)
    maintenance_args = (
        args.maintenance_args[1:]
        if args.maintenance_args[:1] == ["--"]
        else args.maintenance_args
    )
    return run_python_module(
        app_root=app_root,
        module_name="backend.maintenance.main",
        module_args=maintenance_args,
        python_executable=args.python_executable,
    )


if __name__ == "__main__":
    raise SystemExit(main())