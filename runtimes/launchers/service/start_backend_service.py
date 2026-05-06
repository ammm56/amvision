"""backend-service Python launcher。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


LAUNCHERS_ROOT = Path(__file__).resolve().parents[1]
if str(LAUNCHERS_ROOT) not in sys.path:
    sys.path.insert(0, str(LAUNCHERS_ROOT))

from common import resolve_app_root, run_python_module


def build_argument_parser() -> argparse.ArgumentParser:
    """构造 backend-service launcher 参数解析器。"""

    parser = argparse.ArgumentParser(description="amvision backend-service launcher")
    parser.add_argument("--app-root", help="应用根目录；未传入时按 launcher 相对位置自动解析")
    parser.add_argument("--python-executable", help="用于启动 backend-service 的 Python 解释器路径")
    parser.add_argument("--host", default="0.0.0.0", help="uvicorn 监听地址")
    parser.add_argument("--port", type=int, default=8000, help="uvicorn 监听端口")
    parser.add_argument("--log-level", default="info", help="uvicorn 日志级别")
    parser.add_argument("--reload", action="store_true", help="是否启用 uvicorn reload")
    parser.add_argument(
        "extra_args",
        nargs=argparse.REMAINDER,
        help="附加传给 uvicorn 的参数；如需显式传递 --，请放在命令末尾",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """执行 backend-service launcher 主入口。"""

    parser = build_argument_parser()
    args = parser.parse_args(argv)
    app_root = resolve_app_root(script_file=Path(__file__), explicit_app_root=args.app_root)
    extra_args = args.extra_args[1:] if args.extra_args[:1] == ["--"] else args.extra_args
    module_args = [
        "backend.service.api.app:app",
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--log-level",
        args.log_level,
    ]
    if args.reload:
        module_args.append("--reload")
    module_args.extend(extra_args)
    return run_python_module(
        app_root=app_root,
        module_name="uvicorn",
        module_args=module_args,
        python_executable=args.python_executable,
    )


if __name__ == "__main__":
    raise SystemExit(main())