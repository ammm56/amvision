"""独立 inference daemon Python launcher。"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


LAUNCHERS_ROOT = Path(__file__).resolve().parents[1]
if str(LAUNCHERS_ROOT) not in sys.path:
    sys.path.insert(0, str(LAUNCHERS_ROOT))

from common import (  # noqa: E402
    build_python_module_environment,
    resolve_app_root,
    resolve_code_root,
    run_python_module,
)


def build_argument_parser() -> argparse.ArgumentParser:
    """构造 inference daemon launcher 参数。"""

    parser = argparse.ArgumentParser(description="amvision inference daemon launcher")
    parser.add_argument("--app-root", help="应用根目录；未传入时按 launcher 相对位置解析")
    parser.add_argument("--python-executable", help="用于启动 daemon 的 Python 解释器路径")
    parser.add_argument("--check", action="store_true", help="只校验 daemon 运行配置")
    parser.add_argument("--probe", action="store_true", help="探测已经运行的 daemon")
    return parser


def main(argv: list[str] | None = None) -> int:
    """通过统一代码根和本地 runtime 环境启动 daemon。"""

    args = build_argument_parser().parse_args(argv)
    app_root = resolve_app_root(script_file=Path(__file__), explicit_app_root=args.app_root)
    module_args: list[str] = []
    if args.check:
        module_args.append("--check")
    if args.probe:
        # probe 必须在当前 launcher 进程内执行。若再派生一层 Python，Windows
        # 超时终止只能杀掉外层 wrapper，容易留下孤儿探针进程并误判 daemon 就绪。
        runtime_env = build_python_module_environment(app_root)
        os.environ.update(runtime_env)
        code_root = resolve_code_root(app_root)
        if str(code_root) not in sys.path:
            sys.path.insert(0, str(code_root))
        from backend.inference_daemon.main import main as daemon_main

        return daemon_main(["--probe"])
    return run_python_module(
        app_root=app_root,
        module_name="backend.inference_daemon.main",
        module_args=module_args,
        python_executable=args.python_executable,
    )


if __name__ == "__main__":
    raise SystemExit(main())
